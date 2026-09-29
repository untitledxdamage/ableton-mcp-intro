# Changelog

All versions tested on Ableton Live 12.2.7 **Intro**, Windows 11. Evidence behind each release (Spanish): [docs/VALIDACION.md](docs/VALIDACION.md).

## [1.3.0] - 2026-09-29

### Added
- `examples/`: results made through the bridge, all generated from real renders by `examples/build_examples.py`: audio excerpts (the v3 beat, a v2/v3 A/B, the 808 before/after tuning), charts in light and dark (sidechain duck, loudness per section, 808 pitch, render alignment), `analyze_audio` JSON, a condensed real session, and a screenshot of the Arrangement taken through the bridge.
- `show_view` can hide panels (`hide=["Browser", "Detail"]`); new `navigate_view` zooms or scrolls a view (e.g. fit a whole song in the Arrangement).

## [1.2.0] - 2026-09-29

### Added
- `arrangement_audio_clip`: put an audio file directly on the Arrangement timeline at any beat (Live 12 `Track.create_audio_clip`), no Session slot needed. Verified by playing across the clip start with the meter: silence before, signal from the placed beat.

### Docs
- Audio clips and clip automation are now stated explicitly as capabilities, with evidence (a third-party AI review had concluded they were missing).

## [1.1.0] - 2026-09-29

### Added
- `load_audio_clip` and `set_audio_clip`: audio files into Session slots, warp modes, tape-style pitch (warping off + `pitch_coarse`), clip gain. Built during a Foley/ambience project on this same Live Intro.
- `analyze_audio` now returns a **`texture`** block for Foley and ambiences: `contrast_db` (p95-p10 of 50 ms RMS), `crackle_ratio` (p99/median 50 ms energy), `tonal_peak_hz` / `tonal_prominence` (hum detection). Validated against files with a prior human verdict: it reproduces the 21 dB of an approved fireplace bed and flags the 234 Hz hum of model-generated fire (`tests/texture_check.py`).
- `docs/VALIDACION.md`: what was tested, how and with what result, the bugs found and fixed, and what is not tested.
- Remote Script renamed to **`AbletonMCP_Intro`** on port **9880**, so it can live side by side with ahujasid/ableton-mcp.

## [1.0.0] - 2026-09-28

First public release. Developed with Claude Code (Claude Opus 5.5).

### Bridge
- Remote Script with a socket-and-queue design (commands run on Live's main thread in `update_display`), plus **hot reload** (`reload`).
- MCP server on the `mcp` 2.x SDK (`MCPServer`) with 53 tools: transport, tracks, routing, MIDI clips, scenes, Arrangement, browser (BFS search ranked kits/devices before samples), devices, racks, Drum Rack pads (`set_chain`), device order (`move_device`), device properties (Simpler `voices`).
- `set_parameter_real`: set parameters in Hz / dB / ms / % by bisecting `str_for_value`.
- `set_sidechain`: real Compressor sidechain routing (it isn't a device parameter in the API).

### Rendering and analysis
- `render_to_wav`: real-time recording of the master (Resampling) or **all stems in one pass** (Post Mixer), with the latency pre-roll trimmed via the clip start marker so files start on the downbeat.
- Auto-save with an atomic `SendInput` Ctrl+S, focus check, master selected first (a stray "S" solos the selected track), and solo/mute restored afterwards. If the user is active, it waits for a manual save instead of stealing focus.
- `analyze_audio`: streaming BS.1770 loudness, true peak, crest, band balance, stereo and low-end correlation, and per-section loudness, in about 90 MB of RAM at any length.
- `measure_levels`: live meter polling with a documented calibration.

### Fixed along the way
- Browser search returning loose samples before kits.
- Masked tool errors in `mcp` 2.x (now `ToolError`).
- Non-ASCII paths (Live returns U+FFFD; libsndfile can't open them on Windows).
- Recordings locked (0 bytes) until the set is saved.
- A stray keystroke soloing a track during auto-save.
- Analysis using 678 MB of RAM; now streamed.
- JSON-invalid `-inf`/NaN on silent stems.
