# Ableton MCP para Live Intro

> [English](README.md) · **Español**

Un servidor [MCP](https://modelcontextprotocol.io) **no oficial** para que **Claude, o cualquier agente de IA**, maneje **Ableton Live 12**. Está hecho y probado sobre **Live Intro**, la edición básica: sin Max for Live, solo con los dispositivos que trae Intro y dentro de sus límites (16 pistas, 16 escenas).

Su robustez no viene de la teoría. Viene de **proyectos reales** controlados de punta a punta con este puente, donde cada resultado se comprobó midiendo, y cada error que apareció se corrigió y quedó documentado. Ver [docs/VALIDACION.md](docs/VALIDACION.md).

> No está afiliado ni respaldado por Ableton AG. "Ableton" y "Live" son marcas de Ableton AG.

## Para qué sirve

Le da a un agente manos y oídos dentro de Live:

- **Armar sesiones:** crear pistas MIDI, de audio y de retorno; cargar instrumentos, efectos, kits y presets del navegador.
- **Escribir música:** clips MIDI con notas, probabilidad y variación de velocity; cuantizar; leer lo que tú tocaste.
- **Arreglar:** escenas, y colocar clips en el Arrangement para armar un tema completo.
- **Dar forma al sonido:** mover cualquier parámetro **en unidades reales** (Hz, dB, ms, %); entrar en racks y pads de batería; reordenar efectos.
- **Mezclar:** volumen, paneo, envíos, ruteo, **sidechain real con Compressor**, clips de audio (warp, tono tipo cinta, ganancia).
- **Revisar su propio trabajo**, porque un agente no oye: medidores en vivo, **render a WAV o stems** y análisis de audio (LUFS, true peak, balance espectral, estéreo, textura).

## Qué hace bien (probado)

- **Control fino en Intro.** 55 herramientas que cubren el trabajo diario en Live, sin Max for Live.
- **Unidades reales en vez de valores crudos.** Pedir "150 Hz" o "-18 dB" cae exacto: el puente busca el valor usando la propia pantalla de Live.
- **Render honesto.** La API de Live no exporta, así que el puente graba en tiempo real y recorta el desfase de latencia oculto que agrega Live. Los archivos empiezan en el primer tiempo (verificado en cada golpe). Todos los stems salen en una pasada, y su suma reproduce el master (correlación 0.97).
- **Medición confiable.** La loudness coincide con referencias BS.1770 (±0.02 LU) y el análisis usa unos 90 MB de RAM.
- **Seguro con una persona al lado.** No te quita el foco mientras usas la PC, se protege del atajo "S = solo" de Live, restaura solo y mute, y devuelve errores claros.
- **Recarga en caliente.** Actualiza el script sin reiniciar Live.

## Qué no hace

- **No exporta con el diálogo de Live.** El render graba en tiempo real, así que un tema de 2 minutos tarda 2 minutos.
- **No puede guardar ni crear sets por sí solo.** Tras un render guarda con Ctrl+S en Windows; en otros sistemas guardas tú.
- **No puede entrar en muchos presets de Intro.** Algunos racks esconden su interior; solo se ven sus macros.
- **No juzga el gusto.** Mide; tú escuchas y decides.

## Funciona con cualquier agente

- **Cualquier cliente MCP** (probado con Claude Code y Claude Desktop; los demás deberían funcionar porque MCP es un estándar).
- **Cualquier programa, sin MCP**, por el socket local. Se envía una línea JSON por comando:
  ```
  → {"id": 1, "cmd": "set_tempo", "params": {"bpm": 140}}
  ← {"id": 1, "ok": true, "result": {"tempo": 140.0}}
  ```
  Comandos y parámetros: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Instalación

**Necesitas:** Ableton Live 12 (Intro o superior), Python 3.13 y [uv](https://docs.astral.sh/uv/).

1. **Descarga el proyecto:** `git clone https://github.com/untitledxdamage/ableton-mcp-intro`
2. **Instala el script en Live:**
   ```bash
   powershell -ExecutionPolicy Bypass -File install_remote_script.ps1
   ```
3. **Actívalo en Live** (una sola vez): *Preferences → Link, Tempo & MIDI → Control Surface → **AbletonMCP_Intro*** (Input/Output: None). La barra de estado muestra "AbletonMCP_Intro listo en el puerto 9880".
4. **Registra el servidor MCP:**
   - Claude Code:
     ```bash
     claude mcp add ableton --scope user -- uv run --directory "RUTA\A\ableton-mcp-intro" ableton-mcp
     ```
   - Claude Desktop o cualquier cliente MCP (configuración JSON):
     ```json
     { "mcpServers": { "ableton": { "command": "uv",
         "args": ["run", "--directory", "RUTA\\A\\ableton-mcp-intro", "ableton-mcp"] } } }
     ```
5. **Comprueba la conexión** (con Live abierto; no modifica tu set):
   ```bash
   uv run python tests/mcp_smoke.py
   ```

**Para actualizar el script:** `install_remote_script.ps1 -Reload` aplica los cambios sin reiniciar Live. Cambiar el Control Surface **no** recarga el código.

## Herramientas (55)

| Área | Herramientas |
|---|---|
| Sesión y transporte | `get_session_info` `set_tempo` `set_time_signature` `transport` `set_song_options` `show_view` |
| Pistas y ruteo | `create_track` `delete_track` `duplicate_track` `set_track` `select_track` `get_track_info` `get_routing` `set_routing` |
| Clips MIDI | `create_clip` `add_notes` `get_notes` `remove_notes` `quantize_clip` `set_clip` `duplicate_clip` `delete_clip` `fire_clip` `stop_track_clips` `select_clip` `set_clip_automation` |
| Clips de audio | `load_audio_clip` `set_audio_clip` |
| Escenas | `create_scene` `rename_scene` `fire_scene` `duplicate_scene` `delete_scene` |
| Dispositivos | `browse` `search_browser` `load_device` `delete_device` `move_device` `get_device_parameters` `set_device_parameters` `set_parameter_real` `set_sidechain` `device_property` `get_drum_pads` `get_rack` `set_chain` |
| Arrangement | `arrangement_place` `get_arrangement_clips` `clear_arrangement` |
| Verificación | `measure_levels` `render_to_wav` `render_status` `analyze_audio` |
| Mantenimiento | `ping` `reload_script` |

## Documentación

- [VALIDACION.md](docs/VALIDACION.md): la evidencia. Qué se probó, cómo y con qué resultado, los 16 errores encontrados y corregidos, y lo que **no** está probado.
- [HALLAZGOS_API_LIVE12.md](docs/HALLAZGOS_API_LIVE12.md): qué funciona y qué no en la API de Live 12, sus trampas, y tablas de calibración de valores crudos a unidades reales.
- [ARQUITECTURA.md](docs/ARQUITECTURA.md): cómo está hecho por dentro, el protocolo del socket, el flujo de render y cómo agregar comandos.

## Cómo se hizo

Lo construí con **Claude Code** usando **Claude Opus 5.5**, en sesiones de trabajo iterativas (*vibecoding*). Yo definí los objetivos, usé el puente en proyectos reales y juzgué cada resultado; Claude escribió el código, midió los resultados y documentó cada falla. Es robusto porque se usó y se rompió de verdad, no porque parezca completo.

## Créditos

La arquitectura general (un script dentro de Live + un socket local + un servidor MCP) se inspira en [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp). Esta es una implementación independiente, escrita desde cero y enfocada en Live Intro, las unidades reales, el render y la verificación. Usa otro nombre de script y otro puerto, así que ambos pueden estar instalados a la vez.

## Licencia

[MIT](LICENSE). Se entrega tal cual, sin garantías. Respalda tus sets.
