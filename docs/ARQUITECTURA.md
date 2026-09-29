# Arquitectura

## Componentes

```
┌─────────────┐   stdio (JSON-RPC MCP)   ┌──────────────────────────┐  TCP 127.0.0.1:9880   ┌──────────────────────────────┐
│ Claude Code │ ───────────────────────▶ │ servidor MCP (Python 3.13)│ ───────────────────▶ │ Remote Script (Python de Live)│
│ / Desktop   │ ◀─────────────────────── │ src/ableton_mcp           │ ◀─────────────────── │ remote_script/AbletonMCP_Intro      │
└─────────────┘                          │  ├ __init__.py  herramientas│  JSON por líneas      │  ├ hilo socket → cola         │
                                         │  └ audio.py     render/análisis                     │  └ update_display() → API Live │
                                         └──────────────────────────┘                        └──────────────────────────────┘
```

### Remote Script (`remote_script/AbletonMCP_Intro/__init__.py`)
- Es una subclase de `_Framework.ControlSurface`. Live la crea con `create_instance(c_instance)` cuando el usuario elige "AbletonMCP_Intro" como Control Surface.
- **Hilo del socket:** acepta conexiones en `127.0.0.1:9880`, lee JSON línea por línea y mete `(cmd, params, cola_respuesta)` en una `queue.Queue`. Espera la respuesta hasta 20 s.
- **Hilo principal de Live:** `update_display()` (~10 veces por segundo) vacía hasta 32 comandos por ciclo y ejecuta `cmd_<nombre>(**params)`. La API de Live solo es segura desde aquí.
- **Despacho:** cada método `cmd_*` es un comando; el nombre del comando es el del método sin el prefijo. `CommandError` produce un error legible; cualquier otra excepción se registra en `Log.txt` de Live y se devuelve con su tipo.
- **Recarga en caliente (`reload`):** `importlib.reload` del módulo y `self.__class__ = module.AbletonMCP`. La instancia viva (socket, cola) adopta los métodos nuevos sin reiniciar Live.

### Protocolo
```
→ {"id": 7, "cmd": "set_tempo", "params": {"bpm": 140}}\n
← {"id": 7, "ok": true, "result": {"tempo": 140.0}}\n
← {"id": 8, "ok": false, "error": "Slot 7 out of range (0-7)"}\n
```

### Servidor MCP (`src/ableton_mcp/`)
- `MCPServer` del SDK `mcp` 2.x. Cada herramienta es un envoltorio fino sobre `live.send(cmd, **params)`, con tipos (pydantic) y descripciones pensadas para Claude.
- `LiveConnection`: un solo socket persistente con reconexión automática y un lock (las llamadas se serializan).
- `INSTRUCTIONS`: convenciones y reglas medidas que el cliente recibe al conectarse.
- `audio.py`:
  - `Renderer`: render en un hilo de fondo; `render_status` consulta el progreso.
  - `analyze()`: LUFS (pyloudnorm, BS.1770), true peak (sobremuestreo ×4), crest, bandas (Welch), correlación estéreo y de graves, loudness por sección.
  - `trim_copy()`: recorta el pre-roll y copia en el mismo formato.
  - `save_live_set()`: Ctrl+S a la ventana de Live (Windows).

## Flujo de render

```
render_to_wav(start_bar, end_bar, tail_bars)
 1. get_session_info → tempo, ruta del set (si no está guardado, error)
 2. fin = end_bar o el final del último clip del Arrangement
 3. desarmar pistas armadas; crear pista "Render" (input Resampling, monitoring off, arm)
 4. stop → back_to_arranger → start_time = inicio → record_mode on → play
 5. esperar (compases × 4 × 60 / tempo) + 0.3 s   [hilo de fondo]
 6. stop → record_mode off → leer file_path y start_marker del clip grabado
 7. borrar la pista "Render" → restaurar armado → Ctrl+S (Live suelta el WAV)
 8. esperar a que el archivo se pueda leer → recortar el pre-roll → copiar al destino
 9. analyze() → resultado en render_status
```

## Agregar un comando nuevo

1. En el Remote Script, agrega un método `cmd_mi_comando(self, arg1, arg2=None)` que devuelva algo serializable a JSON. Usa `self._track()`, `self._clip()`, `self._device()` y `self._param()` para resolver índices con errores claros.
2. Instala y recarga: `install_remote_script.ps1 -Reload`.
3. Pruébalo por el socket: `uv run python -c "from ableton_mcp import live; print(live.send('mi_comando', arg1=1))"`.
4. Expónlo en `src/ableton_mcp/__init__.py` con `@mcp.tool()`. La descripción es lo que Claude lee: incluye unidades, rangos y cuándo usarlo.
5. Agrégalo a `tests/mcp_smoke.py` si es de solo lectura.
6. El cliente MCP (Claude Code) necesita una sesión nueva para ver herramientas nuevas.

## Referencia de comandos del socket

Generada desde el código (métodos `cmd_*` del Remote Script). Por el socket se usa el nombre de la primera columna. La herramienta MCP equivalente se llama igual, salvo donde se indica. `kind` es `"track"`, `"return"` o `"master"`; `chain` y `chain_device` llegan a dispositivos dentro de racks. Tiempos en beats; índices desde 0.

| Comando | Parámetros | Herramienta MCP |
|---|---|---|
| `add_notes` | `track_index, slot_index, notes, replace=False` | igual |
| `arrangement_place` | `track_index, slot_index, time` | igual |
| `browse` | `path='instruments'` | igual |
| `clear_arrangement` | `track_index` | igual |
| `create_clip` | `track_index, slot_index, length=4.0, name=None` | igual |
| `create_scene` | `index=-1, name=None` | igual |
| `create_track` | `type='midi', index=-1, name=None` | igual |
| `delete_clip` | `track_index, slot_index` | igual |
| `delete_device` | `track_index, device_index, kind='track'` | igual |
| `delete_scene` | `scene_index` | igual |
| `delete_track` | `track_index, kind='track'` | igual |
| `device_property` | `track_index, device_index, name, value=None, kind='track', chain=None, chain_device=None` | igual |
| `device_routing` | `track_index, device_index, input_type=None, input_channel=None, kind='track', chain=None, chain_device=None` | `set_sidechain` |
| `duplicate_clip` | `track_index, slot_index, target_track, target_slot` | igual |
| `duplicate_scene` | `scene_index` | igual |
| `duplicate_track` | `track_index` | igual |
| `fire_clip` | `track_index, slot_index` | igual |
| `fire_scene` | `scene_index` | igual |
| `get_arrangement_clips` | `track_index` | igual |
| `get_device_parameters` | `track_index, device_index, kind='track', chain=None, chain_device=None` | igual |
| `get_drum_pads` | `track_index, device_index, kind='track'` | igual |
| `get_meters` | — | (la usa `measure_levels`) |
| `get_notes` | `track_index, slot_index` | igual |
| `get_rack` | `track_index, device_index, kind='track'` | igual |
| `get_routing` | `track_index, kind='track'` | igual |
| `get_session_info` | — | igual |
| `get_track_info` | `track_index, kind='track'` | igual |
| `inspect` | `target='song', track_index=None, device_index=None, kind='track'` | (solo socket) |
| `load_audio_clip` | `track_index, slot_index, file_path` | igual |
| `load_device` | `track_index, path=None, query=None, category=None, kind='track'` | igual |
| `move_device` | `track_index, device_index, new_index, kind='track'` | igual |
| `ping` | — | igual |
| `quantize_clip` | `track_index, slot_index, grid='1/16', amount=1.0` | igual |
| `reload` | — | `reload_script` |
| `remove_notes` | `track_index, slot_index, from_pitch=0, pitch_span=128, from_time=0.0, time_span=None` | igual |
| `search_browser` | `query, category=None, max_results=25` | igual |
| `select_clip` | `track_index, slot_index` | igual |
| `select_track` | `track_index, kind='track'` | igual |
| `set_audio_clip` | `track_index, slot_index, warping=None, warp_mode=None, pitch_coarse=None, pitch_fine=None, gain=None` | igual |
| `set_chain` | `track_index, device_index, chain, volume=None, pan=None, mute=None, solo=None, kind='track'` | igual |
| `set_clip` | `track_index, slot_index, name=None, loop_start=None, loop_end=None, looping=None, color_index=None` | igual |
| `set_clip_automation` | `track_index, slot_index, device_index, parameter, points, clear=True, kind='track', chain=None, chain_device=None` | igual |
| `set_device_parameters` | `track_index, device_index, values, kind='track', chain=None, chain_device=None` | igual |
| `set_parameter_display` | `track_index, device_index, parameter, target, kind='track', chain=None, chain_device=None` | `set_parameter_real` |
| `set_routing` | `track_index, input_type=None, input_channel=None, output_type=None, kind='track'` | igual |
| `set_scene` | `scene_index, name=None` | `rename_scene` |
| `set_song_options` | `metronome=None, loop=None, loop_start=None, loop_length=None, song_time=None, record_mode=None, start_time=None` | igual |
| `set_tempo` | `bpm` | igual |
| `set_time_signature` | `numerator, denominator` | igual |
| `set_track` | `track_index, kind='track', name=None, volume=None, pan=None, mute=None, solo=None, arm=None, color_index=None, sends=None, monitoring=None` | igual |
| `show_view` | `view='Arranger'` | igual |
| `stop_track_clips` | `track_index` | igual |
| `transport` | `action` | igual |

## Explorar la API

El comando `inspect` (solo por socket, no expuesto a Claude) lista los atributos públicos de `song`, `view`, `track`, `application` o `browser`:

```bash
uv run python -c "from ableton_mcp import live; print(live.send('inspect', target='track'))"
```
