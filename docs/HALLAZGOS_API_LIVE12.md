# Hallazgos de la API de Live 12 (verificados)

Entorno: **Ableton Live 12.2.7 Intro**, Windows 11, Python embebido de Live (3.11), Remote Script en `Documents\Ableton\User Library\Remote Scripts`. Todo lo de esta lista se probó en vivo; lo no verificado está marcado.

## Funciona

| Capacidad | API | Notas |
|---|---|---|
| Remote Scripts de usuario en Intro | `User Library/Remote Scripts/<Nombre>/__init__.py` con `create_instance(c_instance)` | Sin Max for Live |
| Ejecutar comandos de forma segura | encolar desde el hilo del socket y vaciar la cola en `update_display()` (~10 Hz) | Latencia ~0.3 s por llamada ida y vuelta |
| Notas MIDI modernas | `Clip.add_new_notes(MidiNoteSpecification…)`, `get_notes_extended`, `remove_notes_extended` | `probability` y `velocity_deviation` funcionan |
| Envolventes de clip | `clip.create_automation_envelope(param)`, `envelope.insert_step(t, dur, value)`, `clip.clear_envelope` | Probado con Auto Filter, Utility y macros de rack |
| Cuantizar | `clip.quantize(grid, amount)` | grid: 1=1/4 … 5=1/16 … 8=1/32 |
| Navegador | `Application.browser` + `.sounds/.drums/.instruments/.audio_effects…` y `browser.load_item(item)` | Carga en la pista seleccionada |
| Instrumento en la posición correcta | `load_item` con pista MIDI | Live coloca el instrumento antes de los efectos aunque ya haya efectos |
| Arrangement | `track.duplicate_clip_to_arrangement(clip, time)`, `track.arrangement_clips`, `track.delete_clip(clip)` | También existe `track.create_midi_clip` (no probado) |
| Volver al Arrangement | `song.back_to_arranger = False` | Necesario después de lanzar escenas |
| Marcador de inicio | `song.start_time` | **Sí** funciona con el transporte detenido |
| Ruteo | `track.available_input_routing_types` / `input_routing_type` | **"Resampling" disponible en Intro**. Desde otra pista: canales `Pre FX` / `Post FX` / `Post Mixer`, y también **por pad y por dispositivo interno** de un Drum Rack |
| Grabar varias pistas a la vez | armar N pistas de audio + `record_mode` | Base de los stems en una pasada |
| Grabación | `song.record_mode = True` + `start_playing()` | Graba en el Arrangement desde `start_time` |
| Monitoreo | `track.current_monitoring_state` (0 In, 1 Auto, 2 Off) | Off para resampling |
| Medidores | `track.output_meter_left/right` | Escala no lineal (ver "Calibraciones medidas" abajo) |
| Racks visibles | `device.chains[i].devices[j]`, `chain.mixer_device.volume` | Kits de batería y "Synthetic Flute": sí |
| **Sidechain real** | `CompressorDevice.available_input_routing_types` / `input_routing_type` / `input_routing_channel` (no son parámetros: se ven con `dir(device)`) | Fuente = cualquier pista (Pre FX / Post FX / Post Mixer) |
| Mostrar un valor sin cambiarlo | `DeviceParameter.str_for_value(v)` | Base de `set_parameter_real` (bisección) |
| Clips de audio desde archivo | `ClipSlot.create_audio_clip(path)` (Live 12) | Ruta absoluta; WAV/AIFF/FLAC/MP3 |
| Reproducción de clips de audio | `clip.warping`, `clip.warp_mode` (0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch, 4 Complex, 6 Complex Pro), `pitch_coarse`, `pitch_fine`, `gain` + `gain_display_string` | Tono "tipo cinta": `warping=False` + `pitch_coarse`. Comprobar qué modos trae tu edición |
| Reordenar dispositivos | `song.move_device(device, track, index)` | |
| Propiedades de Simpler | `SimplerDevice.voices`, `.retrigger`, `.playback_mode` | `voices` no aparece como parámetro |
| Recarga en caliente | `importlib.reload(sys.modules[cls.__module__])` y luego `self.__class__ = module.AbletonMCP` | El hilo del socket sigue vivo; los métodos nuevos entran al instante |
| Ruta del clip grabado | `clip.file_path`, `clip.start_marker`, `clip.beat_to_sample_time()`, `clip.sample_rate` | Ver "Gotchas" sobre codificación |
| Otras cosas presentes | `song.song_length`, `root_note`, `scale_name`, `capture_midi`, `begin_undo_step`/`end_undo_step`, `punch_in/out`, `cue_points` | Listadas con `inspect`; no todas probadas |

## No funciona o está limitado

| Qué | Detalle | Alternativa |
|---|---|---|
| Exportar audio | No hay función de render/export en la API | Resampling en tiempo real (`render_to_wav`) |
| Guardar el set | No hay `save` en la API | `Ctrl+S` a la ventana de Live (WScript `AppActivate` + `SendKeys`) |
| Crear un set nuevo | No hay API | Hacerlo a mano |
| Racks de presets de Intro con contenido oculto | "808 Drifter", "VHS Dreams": `device.chains` devuelve `[]` | Usar dispositivos simples (`.adv`) o solo los macros |
| Modo de voz de Drift | No expuesto como parámetro | Simpler con `voices = 1` para bajos mono |
| Mover el cabezal con el transporte detenido | `current_song_time = x` se ignora (vuelve a 0) | `start_time` detenido, o `current_song_time` mientras suena |
| Recargar código cambiando el Control Surface | Live reutiliza el módulo cacheado en `sys.modules` | Reiniciar Live una vez; después, `reload` |

## Gotchas (costaron tiempo)

1. **La grabación queda bloqueada hasta guardar.** El WAV recién grabado figura con 0 bytes y con bloqueo de lectura mientras el set no se guarde, aunque ya se haya borrado la pista. Al guardar, Live lo cierra y lo escribe (4.3 MB para 7.5 s a 96 kHz / 24 bits).
2. **Pre-roll de latencia en las grabaciones.** El archivo empieza **0.32 s (0.75 beats a 140 BPM) antes** del punto de grabación; el `start_marker` del clip lo compensa. Si copias el WAV crudo, queda desfasado. Recorta `beat_to_sample_time(start_marker) / sample_rate` segundos.
3. **Rutas con caracteres no ASCII.** `clip.file_path` y `song.file_path` devuelven `U+FFFD` en lugar de `í` ("Sin t�tulo"). Hay que resolverlas con `glob`, reemplazando `U+FFFD` por `?` y escapando los corchetes del nombre (`[2026-09-28 051747]`).
4. **libsndfile no abre rutas no ASCII en Windows.** Lee los bytes con `open()` y pásale `io.BytesIO` a `soundfile`.
5. **El SDK de MCP 2.x** renombró `FastMCP` a `MCPServer` (`mcp.server.mcpserver`). Las excepciones genéricas se ocultan como "Error executing tool"; lanza `ToolError` para que Claude vea el mensaje.
6. **Tipos numpy en respuestas MCP.** Convierte a `float` antes de devolver.
7. **La búsqueda en el navegador debe ser por niveles (BFS).** Con búsqueda en profundidad, "808" encuentra primero samples sueltos dentro de `Drum Hits/` antes que el `808 Core Kit.adg`. Hay que ordenar por coincidencia exacta, luego dispositivo o preset antes que audio, luego profundidad.
8. **`load_device` agrega al final de la cadena.** Un EQ cargado en el master queda **después** del limitador; hay que moverlo con `move_device`.
9. **Los presets pueden estar desafinados.** "Sub 808 Bass" venía +23.7 cents alto y con vibrato de ±50 cents.
10. **La tecla S pone en solo la pista seleccionada.** Al automatizar Ctrl+S con `WScript.Shell.SendKeys`, una "S" llegó sola y puso la flauta en solo; los stems siguientes salieron en silencio salvo la flauta. Arreglo: `SendInput` atómico, verificar la ventana en primer plano, seleccionar el master antes de guardar y comparar solo y mute antes y después. Cambiar solo **no** marca el set como modificado (no aparece `*`).
11. **Los envíos no usan la curva del fader.** 0.45 = -22 dB (el fader en 0.45 sería unos -16 dB). Lee siempre `sends_display`.
12. **Nombres automáticos de los returns.** Un return con nombre por defecto se renombra solo al agregarle dispositivos ("A-Reverb" pasó a "A-Reverb | Compressor"). Live antepone la letra: para fijarlo, nómbralo "Reverb" (queda "A-Reverb"). Nombrarlo "A-Reverb" da "A-A-Reverb".
13. **Auto Filter con Resonance 0 % tiene un knee suave** (Q ≈ 0.5): un pasa-altos de 24 dB "a 30 Hz" resta ~3 dB a 60 Hz.
14. **El drive del circuito MS2 del Auto Filter suma ~+6.6 dB** de nivel: compensar con su Output.
15. **Foco de ventana con un usuario activo.** `SetForegroundWindow` falla aunque se use `AttachThreadInput` si el usuario está interactuando con otra app. No insistir: esperar a que el usuario guarde.
16. **Intro no tiene EQ Eight.** Para cortes y ecualización: Auto Filter (tipos, circuitos y pendientes) y Channel EQ (pasa-altos fijo, graves, medios sweepable y agudos).
17. **Prueba en un set limpio.** El set por defecto puede tener trabajo del usuario; las pruebas no deben dejar tempo ni nombres de escena cambiados.

## Calibraciones medidas (valores crudos → unidades reales)

| Qué | Valor crudo → valor real | Cómo se midió |
|---|---|---|
| Medidor de salida (`output_meter`) | **0.917 = -0.3 dBFS** (techo del limitador); 0.77 ≈ -10 dBFS; ~0.0125-0.015 por dB cerca del tope | Limitador empujado +12/+22 dB y render con pico conocido |
| Fader de pista o chain | 0.85 = 0 dB, 0.70 = -6, 0.55 = -12, 0.40 = -18 (~0.025 por dB cerca de 0 dB); 1.0 = +6 dB | `volume_display` |
| Utility Gain | -1..+1 lineal = -35..+35 dB (-0.4 = -14 dB) | display |
| Reverb Decay Time | 0.4428 = 2.5 s, 0.56 = 4.88 s | display |
| Simpler Glide Time | curva logarítmica: 0.3 = 3 ms, 0.4 = 10 ms, 0.5 = 31.6 ms, **0.58 = 79 ms** | display |
| Limiter Ceiling | 0.9701 = -0.3 dB, **0.90 = -1.0 dB** | display |
| Limiter Input Gain | 0.5 = 0 dB, 0.56 = +2.9 dB, 0.75 = +12 dB | display |
| Channel EQ High Gain | 0.5 = 0 dB, 0.567 = +2 dB, 0.6 = +3 dB | display |
| Drift LP Freq | 0.5 = 632 Hz, 0.6 = 1.26 kHz, 0.7 = 2.52 kHz (×1.41 cada 0.05) | display |
| Delay "L 16th" | valor 2 = 3 semicorcheas (corchea con puntillo) | display |
| Compressor Threshold / Ratio / Release | 0.3 = -24 dB, 0.5 = -14, 0.7 = -6 · 0.75 = 4:1, 0.9 = 10:1, 1.0 = inf · 0.3 = 127 ms, 0.34 = 172, 0.4 = 258, 0.5 = 459 | display |
| Auto Filter Frequency | 0.058 = 30 Hz, 0.291 = 150, 0.333 = 200, 0.515 = 700, 0.799 = 5 kHz, 0.925 = 12 kHz | `set_parameter_real` |
| **Envíos (sends)** | **no son como el fader**: 0.3 = -30 dB, 0.45 = -22 dB, 0.5 = -20 dB y desde ahí **dB = 40 × (valor − 1)** (0.75 = -10, 0.8 = -8, 1.0 = 0) | `sends_display` |

**Regla general:** usa `set_parameter_real` (Hz, dB, ms, %), que busca el valor crudo por bisección con `str_for_value` sin efectos secundarios. Si usas `set_device_parameters`, lee el `display` de la respuesta: los valores crudos casi nunca son lineales.
