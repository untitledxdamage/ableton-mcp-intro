# Validación: en qué pruebas se sostiene este puente

Este MCP no es oficial ni tiene una suite de pruebas contra muchas configuraciones. Lo que tiene es **uso real y verificado** en un Ableton Live 12.2.7 **Intro** (Windows 11), en proyectos completos, con cada resultado comprobado por medición y no por lo que "dice" la herramienta. Este documento resume esa evidencia.

## Entorno probado
- Ableton Live **12.2.7 Intro** · Windows 11 Pro · Python 3.13 · SDK `mcp` 2.x.
- Cliente: **Claude Code** (app de escritorio).
- Sesiones reales del 28 y 29 de septiembre de 2026.

## Uso real (no son demos)

| Proyecto | Qué exigió del puente |
|---|---|
| **Beat Plugg / Cloud Trap completo**: 6 pistas, 64 compases, 3 versiones de mezcla | Crear pistas, cargar presets de Intro, escribir cientos de notas MIDI, escenas y Arrangement, automatización en clips, sidechain real, EQ, saturación, master, render a WAV y **stems** en una pasada |
| **Procesamiento de grabaciones de foley y ambiente** para un canal de video (chimenea) | Cargar archivos de audio en clips, tono "tipo cinta", ruteo, stems; análisis de textura (contraste, crepitar, zumbido) |
| **Beat lo-fi desde un set vacío, grabado en video** (`examples/video/`) | Solo herramientas MCP: pistas, kit, MIDI, arreglo, medición y corrección de la mezcla, limitador, render y verificación; detectó un kit con pads ocultos y un master saturando |
| **Reconstrucción por scripts**: el mismo puente controlado sin MCP, por socket | El protocolo JSON funciona para cualquier programa, no solo para Claude |

## Capacidades verificadas

Cada fila se comprobó **midiendo el resultado**: releyendo el estado de Live, con medidores o analizando el audio renderizado.

| Capacidad | Cómo se verificó | Resultado |
|---|---|---|
| Conexión, pistas, clips, notas, escenas, navegador | Prueba de integración `tests/test_bridge.py` | 21/21 operaciones OK; los errores devuelven un mensaje claro |
| Escribir y leer MIDI (probabilidad, velocity) | Leer de vuelta con `get_notes` | Idéntico a lo escrito |
| Buscar y cargar presets | Búsqueda "808" → primero el kit, no samples sueltos | Corregido con búsqueda por niveles y ranking |
| Parámetros en unidades reales | `set_parameter_real` a 30 / 150 / 5000 / 12000 Hz, -20 dB, 160 ms, 45 % | Display de Live = objetivo (±1 %) |
| Racks y pads de batería | Volumen por pad, lectura de chains | OK; los racks con contenido oculto se reportan (`chains: []`) |
| Sidechain real (Compressor) | Stems + medición de caída en cada golpe | Pad -9.5 dB, campanas -8.8, flauta -5.5, reverb -5.7 |
| Arrangement | Salto a los compases 9 / 25 / 33 / 57 mientras suena + medidores | Cada sección suena con sus pistas |
| Render a WAV | Detección de ataques en el archivo | Golpes en 0.00 / 1.75 / 3.00 / 4.02 / 5.75 beats, igual que el MIDI |
| Stems en una pasada | Suma de stems contra el render del master | Correlación **0.97** (la diferencia es la cadena de master) |
| Análisis de loudness | Comparación con pyloudnorm / BS.1770 | Idéntico (±0.02 LU), 92 MB de RAM para cualquier duración |
| Afinación | FFT del bajo renderizado | Detectó un preset +23.7 cents desafinado; corregido a +0.9 |
| Textura de foley | Archivos con veredicto humano previo | Reprodujo 21.0 dB de una cama aprobada y el zumbido (234 Hz) de un audio generado que había sido rechazado |
| Automatización (envolventes de clip) | Envolvente de 16 pasos en `test_bridge.py`; en el beat, un filtro que se abre de 700 Hz a 12 kHz en 8 compases (intro), un pad que se cierra y se abre, y una caída de volumen en cada golpe del 808 | El efecto se midió en el audio: el intro quedó -15.3 LUFS frente a -13.0 sin la apertura; la caída midió -8 dB |
| Recarga en caliente | Cambios de código sin reiniciar Live | Más de 10 recargas en uso real |
| Audio directo en el Arrangement | `arrangement_audio_clip` coloca un archivo de 60 s en el compás 5 de un set vacío; se reproduce leyendo posición y medidor a la vez | Clip de beat 16 a 136 (60 s a 120 BPM); silencio antes del beat 16 (6 lecturas en 0.0), señal desde el beat 16.3 |
| Clips de audio desde archivo | Grabaciones reales de foley cargadas, con cambio de tono tipo cinta (`warping=False` + `pitch_coarse`), procesadas y exportadas como stems | OK (Live 12: `ClipSlot.create_audio_clip`) |

## Errores encontrados y corregidos

Esta es la razón de ser del proyecto: cada uno apareció en uso real, se diagnosticó con medición y quedó corregido o documentado.

1. **Los errores se ocultaban** ("Error executing tool") en el SDK `mcp` 2.x → ahora se usa `ToolError`.
2. **La búsqueda devolvía samples sueltos** antes que kits → búsqueda por niveles con ranking.
3. **Cambiar el Control Surface no recarga el código** (Live lo cachea) → comando `reload` que intercambia la clase en caliente.
4. **Mover el cabezal con el transporte detenido se ignora** → se usa `start_time`.
5. **Las grabaciones quedan bloqueadas (0 bytes) hasta guardar el set** → el render guarda, espera a que el archivo se libere y recién entonces copia.
6. **Pre-roll de latencia:** cada WAV empezaba 0.32 s antes → se recorta con el `start_marker` del clip.
7. **Rutas con acentos** devueltas corruptas por la API → resolución con glob.
8. **Una "S" suelta del guardado automático puso una pista en solo** (en Live, S = solo) → `SendInput` atómico, verificación de foco, master seleccionado antes de guardar, restauración de solo y mute.
9. **Robar el foco a un usuario activo** es peligroso y Windows lo bloquea → si hubo actividad en los últimos 30 s, espera a que el usuario guarde.
10. **El análisis usaba 678 MB de RAM** → streaming, 92 MB.
11. **`-inf` y NaN** (JSON inválido) en stems silenciosos → `null` y `silent: true`.
12. **Los envíos no usan la escala del fader** (0.45 = -22 dB) → medido y documentado; `sends_display` en las respuestas.
13. **Pasa-altos con knee suave** (Auto Filter a Resonance 0) → documentado con un A/B.
14. **Los returns se renombran solos** al agregarles dispositivos → documentado cómo fijar el nombre.
15. **El test de conexión fallaba** con el servidor abierto en otro cliente → lanza el servidor con el mismo intérprete.
16. **Choque de nombre y puerto** con otro proyecto similar → `AbletonMCP_Intro`, puerto 9880.

Detalle técnico de cada uno: [HALLAZGOS_API_LIVE12.md](HALLAZGOS_API_LIVE12.md).

## Pruebas incluidas

| Prueba | Qué hace | ¿Modifica tu set? |
|---|---|---|
| `tests/mcp_smoke.py [archivo.wav]` | Levanta el servidor MCP real, lista las herramientas y llama a las de lectura | No |
| `tests/test_bridge.py` | 21 operaciones de punta a punta por socket (crea una pista "MCP Test") | Sí; usar un set vacío |
| `tests/stems_check.py CARPETA` | Renderiza stems y master del mismo tramo y verifica que sumen | Guarda el set |
| `tests/texture_check.py ARCHIVOS` | Imprime las métricas de textura de archivos de audio | No |

## Lo que NO está probado
- Live **Standard/Suite** (debería funcionar: solo usa la API común), **Live 11** y **macOS**. En macOS el guardado automático tras un render no existe; hay que guardar a mano.
- Otros clientes MCP (Cursor, VS Code, etc.). El protocolo es estándar, pero no se probaron.
- Crear el set vacío en sí: la API no puede crear sets nuevos, así que la demo en video partió de una copia vaciada de un set existente.
- Sets grandes (más de 16 pistas no es posible en Intro).
