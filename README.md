# Ableton MCP for Live Intro

> **English** · [Español](README.es.md)

An **unofficial** [MCP](https://modelcontextprotocol.io) server that lets **Claude, or any AI agent**, operate **Ableton Live 12**. It is built and tested on the entry-level **Live Intro** edition: no Max for Live, only stock Intro devices, and within Intro's limits (16 tracks, 16 scenes).

Its robustness doesn't come from theory. It comes from **real projects** controlled end to end through this bridge, where every result was checked by measurement and every bug found along the way was fixed and documented. See [docs/VALIDACION.md](docs/VALIDACION.md).

> Not affiliated with or endorsed by Ableton AG. "Ableton" and "Live" are trademarks of Ableton AG.

## What it's for

It gives an agent hands and ears inside Live:

- **Build sessions:** create MIDI, audio and return tracks; load instruments, effects, kits and presets from the browser.
- **Write music:** MIDI clips with notes, probability and velocity variation; quantize; read back what you played.
- **Arrange:** scenes, and placing clips in the Arrangement to lay out a full song.
- **Shape sound:** set any device parameter, **in real units** (Hz, dB, ms, %); reach inside racks and Drum Rack pads; reorder effects.
- **Mix:** volume, pan, sends, routing, **real Compressor sidechain**, audio clips (warp, tape-style pitch, gain).
- **Check its own work**, since an agent can't hear: live meters, **render to WAV or stems**, and audio analysis (LUFS, true peak, spectral balance, stereo, texture).

## What it does well (tested)

- **Fine-grained control on Intro.** 55 tools that cover the everyday Live workflow without Max for Live.
- **Real units instead of raw values.** "150 Hz" or "-18 dB" land exactly: the bridge bisects Live's own display values.
- **Honest rendering.** Live's API can't export, so the bridge records in real time and trims Live's hidden latency pre-roll, so files start on the downbeat (verified to the transient). All stems come out in one pass, and they sum back to the master (correlation 0.97).
- **Measurement you can trust.** Loudness matches BS.1770 references within ±0.02 LU, streamed in about 90 MB of RAM.
- **Safe around a human.** It never steals focus while you're using the computer, guards against Live's "S = solo" hotkey, restores solo/mute states, and returns clear errors.
- **Hot reload.** Update the script without restarting Live.

## What it doesn't do

- **It doesn't export through Live's dialog.** Renders are real-time recordings, so a 2-minute song takes 2 minutes.
- **It can't save or create sets by itself.** Saving after a render is done with Ctrl+S on Windows; on other systems you save by hand.
- **It can't reach inside many Intro presets.** Some racks hide their internals; only their macros are reachable.
- **It can't judge taste.** It measures; you listen and decide.

## Works with any agent

- **Any MCP client** (Claude Code and Claude Desktop tested; others should work because MCP is a standard).
- **Any program, without MCP**, through the local socket. Send one JSON line per command:
  ```
  → {"id": 1, "cmd": "set_tempo", "params": {"bpm": 140}}
  ← {"id": 1, "ok": true, "result": {"tempo": 140.0}}
  ```
  Commands and parameters: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Install

**Requirements:** Ableton Live 12 (Intro or higher), Python 3.13, [uv](https://docs.astral.sh/uv/).

1. **Get the project:** `git clone https://github.com/untitledxdamage/ableton-mcp-intro`
2. **Install the script into Live:**
   ```bash
   powershell -ExecutionPolicy Bypass -File install_remote_script.ps1
   ```
3. **Enable it in Live** (once): *Settings → Link, Tempo & MIDI → Control Surface → **AbletonMCP_Intro*** (Input/Output: None). The status bar shows "AbletonMCP_Intro listo en el puerto 9880".
4. **Register the MCP server:**
   - Claude Code:
     ```bash
     claude mcp add ableton --scope user -- uv run --directory "PATH\TO\ableton-mcp-intro" ableton-mcp
     ```
   - Claude Desktop or any MCP client (JSON config):
     ```json
     { "mcpServers": { "ableton": { "command": "uv",
         "args": ["run", "--directory", "PATH\\TO\\ableton-mcp-intro", "ableton-mcp"] } } }
     ```
5. **Check** (with Live open; read-only):
   ```bash
   uv run python tests/mcp_smoke.py
   ```

**Updating the script:** `install_remote_script.ps1 -Reload` applies changes without restarting Live. Toggling the Control Surface does **not** reload code.

## Tools (55)

| Area | Tools |
|---|---|
| Session and transport | `get_session_info` `set_tempo` `set_time_signature` `transport` `set_song_options` `show_view` |
| Tracks and routing | `create_track` `delete_track` `duplicate_track` `set_track` `select_track` `get_track_info` `get_routing` `set_routing` |
| MIDI clips | `create_clip` `add_notes` `get_notes` `remove_notes` `quantize_clip` `set_clip` `duplicate_clip` `delete_clip` `fire_clip` `stop_track_clips` `select_clip` `set_clip_automation` |
| Audio clips | `load_audio_clip` `set_audio_clip` |
| Scenes | `create_scene` `rename_scene` `fire_scene` `duplicate_scene` `delete_scene` |
| Devices | `browse` `search_browser` `load_device` `delete_device` `move_device` `get_device_parameters` `set_device_parameters` `set_parameter_real` `set_sidechain` `device_property` `get_drum_pads` `get_rack` `set_chain` |
| Arrangement | `arrangement_place` `get_arrangement_clips` `clear_arrangement` |
| Verification | `measure_levels` `render_to_wav` `render_status` `analyze_audio` |
| Maintenance | `ping` `reload_script` |

## Documentation (Spanish)

- [VALIDACION.md](docs/VALIDACION.md): the evidence. What was tested, how, the results, the 16 bugs found and fixed, and what is **not** tested.
- [HALLAZGOS_API_LIVE12.md](docs/HALLAZGOS_API_LIVE12.md): what works and what doesn't in the Live 12 API, pitfalls, and raw-value → real-unit calibration tables.
- [ARQUITECTURA.md](docs/ARQUITECTURA.md): internals, socket protocol, render flow, and how to add commands.

## How it was made

Built with **Claude Code** running **Claude Opus 5.5**, through iterative working sessions (*vibecoding*). I set the goals, used the bridge in real projects and judged every result; Claude wrote the code, measured the results and documented each failure. The bridge counts as robust because it was used and broken for real, not because it looks complete.

## Credits

The overall architecture (a script inside Live + a local socket + an MCP server) is inspired by [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp). This is an independent implementation written from scratch, focused on Live Intro, units, rendering and verification. It uses a different script name and port, so both can be installed side by side.

## License

[MIT](LICENSE). Provided as is, without warranty. Back up your sets.
