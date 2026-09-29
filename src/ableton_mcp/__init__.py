"""MCP server that drives Ableton Live through the AbletonMCP_Intro Remote Script.

The Remote Script (remote_script/AbletonMCP_Intro) listens on 127.0.0.1:9880 inside
Live and speaks newline-delimited JSON: {"id", "cmd", "params"} ->
{"id", "ok", "result" | "error"}.
"""
import itertools
import json
import socket
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .audio import Renderer, analyze

HOST, PORT = "127.0.0.1", 9880

INSTRUCTIONS = """Controls a running Ableton Live 12 (Intro edition on this rig).
Conventions:
- Indexes are 0-based (track 0 = first track, slot 0 = first scene row).
- Time is in beats (quarter notes). In 4/4 one bar = 4 beats; a 16th = 0.25.
- MIDI pitch 60 is middle C, which Ableton labels C3. Drum Racks usually map
  kick=36 (C1), snare=38, clap=39, closed hat=42, open hat=46; always call
  get_drum_pads to read the real kit.
- Live Intro limits: 16 tracks, 16 scenes, no Max for Live, only Intro devices.
- Call get_session_info first. You cannot hear: verify with measure_levels
  (live meters) and render_to_wav + analyze_audio (LUFS, true peak, band balance).
Measured on this rig:
- Meter scale: 0.917 = -0.3 dBFS; about 0.0125-0.015 meter units per dB near the top.
- Fader: 0.85 = 0 dB, ~0.025 per dB near unity. Utility Gain raw -1..1 = -35..+35 dB.
- Real sidechain works: Compressor input routing via set_sidechain (use a silent
  ghost-trigger track keyed to the 808 notes, 'Sends Only' output).
- Use set_parameter_real for filters/EQ/compressors (units, not raw values).
  Auto Filter at Resonance 0 has a soft knee: an HP 'at 30 Hz' 24 dB still
  cuts ~3 dB an octave above. Sends: dB = 40*(value-1) above 0.5 (0.45 = -22 dB).
- Always compare processing at matched loudness (drive adds level; MS2 drive +6.6 dB).
- Many Intro presets are racks whose inner devices are hidden (get_rack returns
  no chains): only their macros are reachable. Prefer plain devices (.adv) when
  you need deep control (e.g. Simpler 808 for glide).
- Presets can be detuned or carry vibrato: tune basses by rendering solo and
  measuring the fundamental before trusting them.
- song_time only moves while playing; set start_time while stopped.
- Group edits you may want to revert; transport(action="undo") uses Live's history.
"""

mcp = MCPServer("ableton", instructions=INSTRUCTIONS)


class LiveConnection:
    def __init__(self):
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def _connect(self):
        try:
            self._sock = socket.create_connection((HOST, PORT), timeout=5)
        except OSError as e:
            raise ToolError(
                "Cannot reach Ableton. Is Live open with the 'AbletonMCP_Intro' control "
                "surface selected in Settings > Link, Tempo & MIDI? (%s)" % e)
        self._sock.settimeout(30)
        self._buf = b""

    def _roundtrip(self, payload: bytes) -> dict:
        self._sock.sendall(payload)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Ableton closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line)

    def send(self, cmd: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        payload = (json.dumps({"id": next(self._ids), "cmd": cmd,
                               "params": params}) + "\n").encode()
        with self._lock:
            for attempt in (1, 2):
                if self._sock is None:
                    self._connect()
                try:
                    resp = self._roundtrip(payload)
                    break
                except (OSError, ConnectionError):
                    self._sock = None
                    if attempt == 2:
                        raise ToolError("Lost connection to Ableton (Live closed or script reloaded)")
        if not resp.get("ok"):
            raise ToolError(resp.get("error", "Unknown error from Live"))
        return resp.get("result")


live = LiveConnection()

TrackKind = Literal["track", "return", "master"]


class Note(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI note, 60 = C3 (middle C)")
    start: float = Field(ge=0, description="Start in beats from clip start")
    duration: float = Field(gt=0, description="Length in beats")
    velocity: float = Field(100, ge=1, le=127)
    mute: bool = False
    probability: float | None = Field(None, ge=0, le=1, description="Chance the note plays")
    velocity_deviation: float | None = Field(None, ge=-127, le=127, description="Random velocity range")


class AutomationPoint(BaseModel):
    time: float = Field(ge=0, description="Beat position inside the clip")
    value: float = Field(description="Raw parameter value (see get_device_parameters min/max)")
    duration: float = Field(0.0, ge=0, description="Hold length in beats; 0 = single point")


# ---------------------------------------------------------------- session

@mcp.tool()
def get_session_info() -> dict:
    """Snapshot of the Live set: tempo, signature, transport, every track with
    its devices and clips (by slot), return tracks, master, scenes, selection."""
    return live.send("get_session_info")


@mcp.tool()
def set_tempo(bpm: float) -> dict:
    """Set the song tempo in BPM (20-999)."""
    return live.send("set_tempo", bpm=bpm)


@mcp.tool()
def set_time_signature(numerator: int, denominator: int) -> dict:
    """Set the song time signature, e.g. 4/4, 3/4, 6/8."""
    return live.send("set_time_signature", numerator=numerator, denominator=denominator)


@mcp.tool()
def transport(action: Literal["play", "stop", "continue", "stop_all_clips", "back_to_arranger", "undo", "redo"]) -> dict:
    """Transport control. 'undo'/'redo' use Live's own history; 'back_to_arranger' makes
    every track follow the Arrangement again after Session clips were launched."""
    return live.send("transport", action=action)


@mcp.tool()
def set_song_options(metronome: bool | None = None, loop: bool | None = None,
                     loop_start: float | None = None, loop_length: float | None = None,
                     song_time: float | None = None, start_time: float | None = None,
                     record_mode: bool | None = None) -> dict:
    """Metronome, arrangement loop (start/length in beats), playhead and record mode.
    song_time only moves the playhead while playing; while stopped use start_time
    (the position 'play' starts from)."""
    return live.send("set_song_options", metronome=metronome, loop=loop,
                     loop_start=loop_start, loop_length=loop_length, song_time=song_time,
                     start_time=start_time, record_mode=record_mode)


# ----------------------------------------------------------------- tracks

@mcp.tool()
def get_track_info(track_index: int, kind: TrackKind = "track") -> dict:
    """Detailed info for one track (mixer, clips, device list with indexes)."""
    return live.send("get_track_info", track_index=track_index, kind=kind)


@mcp.tool()
def create_track(type: Literal["midi", "audio", "return"] = "midi", index: int = -1,
                 name: str | None = None) -> dict:
    """Create a MIDI, audio or return track. index=-1 appends at the end."""
    return live.send("create_track", type=type, index=index, name=name)


@mcp.tool()
def delete_track(track_index: int, kind: Literal["track", "return"] = "track") -> dict:
    """Delete a track or return track."""
    return live.send("delete_track", track_index=track_index, kind=kind)


@mcp.tool()
def duplicate_track(track_index: int) -> dict:
    """Duplicate a track (with devices and clips); the copy lands right after it."""
    return live.send("duplicate_track", track_index=track_index)


@mcp.tool()
def set_track(track_index: int, kind: TrackKind = "track", name: str | None = None,
              volume: float | None = None, pan: float | None = None,
              mute: bool | None = None, solo: bool | None = None, arm: bool | None = None,
              color_index: int | None = None, sends: list[float | None] | None = None,
              monitoring: Literal["in", "auto", "off"] | None = None) -> dict:
    """Change track properties. volume is 0.0-1.0 (0.85 = 0 dB, about 0.025 per dB
    near the top), pan -1 (L) to 1 (R), color_index 0-69 from Live's palette, sends
    is a list per return track (0.0-1.0, None leaves one unchanged)."""
    return live.send("set_track", track_index=track_index, kind=kind, name=name,
                     volume=volume, pan=pan, mute=mute, solo=solo, arm=arm,
                     color_index=color_index, sends=sends, monitoring=monitoring)


@mcp.tool()
def get_routing(track_index: int, kind: TrackKind = "track") -> dict:
    """Current and available input/output routings of a track (by display name)."""
    return live.send("get_routing", track_index=track_index, kind=kind)


@mcp.tool()
def set_routing(track_index: int, input_type: str | None = None, input_channel: str | None = None,
                output_type: str | None = None, kind: TrackKind = "track") -> dict:
    """Route a track by display name, e.g. input_type='Resampling' (records the master)
    or input_type='808' (records another track). See get_routing for options."""
    return live.send("set_routing", track_index=track_index, input_type=input_type,
                     input_channel=input_channel, output_type=output_type, kind=kind)


@mcp.tool()
def select_track(track_index: int, kind: TrackKind = "track") -> dict:
    """Select a track in Live's UI (shows its devices at the bottom)."""
    return live.send("select_track", track_index=track_index, kind=kind)


# ------------------------------------------------------------------ clips

@mcp.tool()
def create_clip(track_index: int, slot_index: int, length: float = 4.0,
                name: str | None = None) -> dict:
    """Create an empty MIDI clip in a Session View slot. length in beats (4 = one 4/4 bar)."""
    return live.send("create_clip", track_index=track_index, slot_index=slot_index,
                     length=length, name=name)


@mcp.tool()
def load_audio_clip(track_index: int, slot_index: int, file_path: str) -> dict:
    """Load an audio file (absolute path, WAV/AIFF/FLAC/MP3) into an empty Session View slot of an audio track."""
    return live.send("load_audio_clip", track_index=track_index, slot_index=slot_index,
                     file_path=file_path)


@mcp.tool()
def set_audio_clip(track_index: int, slot_index: int, warping: bool | None = None,
                   warp_mode: Literal[0, 1, 2, 3, 4, 6] | None = None,
                   pitch_coarse: int | None = None, pitch_fine: float | None = None,
                   gain: float | None = None) -> dict:
    """Audio clip playback. warp_mode: 0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch (tape-style: pitch and
    speed move together), 4 Complex, 6 Complex Pro (check which your edition has). pitch_coarse in
    semitones (-48..48), pitch_fine in cents (-50..50), gain raw 0..1 (read gain_display)."""
    return live.send("set_audio_clip", track_index=track_index, slot_index=slot_index,
                     warping=warping, warp_mode=warp_mode, pitch_coarse=pitch_coarse,
                     pitch_fine=pitch_fine, gain=gain)


@mcp.tool()
def add_notes(track_index: int, slot_index: int, notes: list[Note], replace: bool = False) -> dict:
    """Write MIDI notes into an existing clip. replace=True clears the clip first.
    Notes beyond the clip length are kept but won't play until the loop is extended."""
    return live.send("add_notes", track_index=track_index, slot_index=slot_index,
                     notes=[n.model_dump(exclude_none=True) for n in notes], replace=replace)


@mcp.tool()
def get_notes(track_index: int, slot_index: int) -> dict:
    """Read all notes of a MIDI clip (e.g. something the user played) plus clip info."""
    return live.send("get_notes", track_index=track_index, slot_index=slot_index)


@mcp.tool()
def remove_notes(track_index: int, slot_index: int, from_pitch: int = 0, pitch_span: int = 128,
                 from_time: float = 0.0, time_span: float | None = None) -> dict:
    """Delete notes inside a pitch/time window (defaults: the whole clip)."""
    return live.send("remove_notes", track_index=track_index, slot_index=slot_index,
                     from_pitch=from_pitch, pitch_span=pitch_span,
                     from_time=from_time, time_span=time_span)


@mcp.tool()
def quantize_clip(track_index: int, slot_index: int,
                  grid: Literal["1/4", "1/8", "1/8T", "1/8+1/8T", "1/16", "1/16T", "1/16+1/16T", "1/32"] = "1/16",
                  amount: float = 1.0) -> dict:
    """Quantize a clip's notes to a grid. amount 0-1 (1 = hard quantize)."""
    return live.send("quantize_clip", track_index=track_index, slot_index=slot_index,
                     grid=grid, amount=amount)


@mcp.tool()
def set_clip(track_index: int, slot_index: int, name: str | None = None,
             loop_start: float | None = None, loop_end: float | None = None,
             looping: bool | None = None, color_index: int | None = None) -> dict:
    """Rename a clip, change its loop region (beats), looping on/off or color."""
    return live.send("set_clip", track_index=track_index, slot_index=slot_index, name=name,
                     loop_start=loop_start, loop_end=loop_end, looping=looping,
                     color_index=color_index)


@mcp.tool()
def delete_clip(track_index: int, slot_index: int) -> dict:
    """Delete the clip in a slot."""
    return live.send("delete_clip", track_index=track_index, slot_index=slot_index)


@mcp.tool()
def duplicate_clip(track_index: int, slot_index: int, target_track: int, target_slot: int) -> dict:
    """Copy a clip to another slot (overwrites the target). Good for making variations."""
    return live.send("duplicate_clip", track_index=track_index, slot_index=slot_index,
                     target_track=target_track, target_slot=target_slot)


@mcp.tool()
def fire_clip(track_index: int, slot_index: int) -> dict:
    """Launch a clip (starts on the next launch-quantization boundary)."""
    return live.send("fire_clip", track_index=track_index, slot_index=slot_index)


@mcp.tool()
def stop_track_clips(track_index: int) -> dict:
    """Stop whatever clip is playing on one track."""
    return live.send("stop_track_clips", track_index=track_index)


@mcp.tool()
def select_clip(track_index: int, slot_index: int) -> dict:
    """Highlight a clip slot in Live's UI so the user sees it in the clip view."""
    return live.send("select_clip", track_index=track_index, slot_index=slot_index)


@mcp.tool()
def set_clip_automation(track_index: int, slot_index: int, device_index: int,
                        parameter: str | int, points: list[AutomationPoint],
                        clear: bool = True, kind: TrackKind = "track",
                        chain: int | None = None, chain_device: int | None = None) -> dict:
    """Draw a clip envelope for a device parameter (e.g. an Auto Filter sweep).
    Points are steps: each holds `value` from `time` for `duration` beats; use many
    short steps for a smooth ramp. Values use the parameter's raw range."""
    return live.send("set_clip_automation", track_index=track_index, slot_index=slot_index,
                     device_index=device_index, parameter=parameter,
                     points=[p.model_dump() for p in points], clear=clear, kind=kind,
                     chain=chain, chain_device=chain_device)


# ----------------------------------------------------------------- scenes

@mcp.tool()
def create_scene(index: int = -1, name: str | None = None) -> dict:
    """Add a scene (row). index=-1 appends at the bottom."""
    return live.send("create_scene", index=index, name=name)


@mcp.tool()
def rename_scene(scene_index: int, name: str) -> dict:
    """Rename a scene (e.g. 'Intro', 'Verso', 'Coro')."""
    return live.send("set_scene", scene_index=scene_index, name=name)


@mcp.tool()
def fire_scene(scene_index: int) -> dict:
    """Launch every clip in a scene row."""
    return live.send("fire_scene", scene_index=scene_index)


@mcp.tool()
def duplicate_scene(scene_index: int) -> dict:
    """Duplicate a scene with all its clips; the copy lands right below."""
    return live.send("duplicate_scene", scene_index=scene_index)


@mcp.tool()
def delete_scene(scene_index: int) -> dict:
    """Delete a scene row and its clips."""
    return live.send("delete_scene", scene_index=scene_index)


# ---------------------------------------------------------------- devices

@mcp.tool()
def get_device_parameters(track_index: int, device_index: int, kind: TrackKind = "track",
                          chain: int | None = None, chain_device: int | None = None) -> dict:
    """List every parameter of a device: index, name, raw value, min, max, the value
    as Live displays it (Hz, dB, ms...) and options for switch-type parameters.
    For a device nested inside a rack, pass chain + chain_device (see get_rack)."""
    return live.send("get_device_parameters", track_index=track_index,
                     device_index=device_index, kind=kind, chain=chain, chain_device=chain_device)


@mcp.tool()
def set_device_parameters(track_index: int, device_index: int, values: dict[str, float | str],
                          kind: TrackKind = "track", chain: int | None = None,
                          chain_device: int | None = None) -> dict:
    """Set several parameters at once: {"Frequency": 0.4, "Resonance": 0.3}.
    Keys are parameter names (or indexes as strings); values are raw numbers within
    min/max, or an option name for switch parameters. {"Device On": 0} bypasses it.
    Raw values are not always linear units: check the returned 'display' and adjust.
    Racks: pass chain + chain_device to reach a device inside a rack (see get_rack)."""
    return live.send("set_device_parameters", track_index=track_index,
                     device_index=device_index, values=values, kind=kind,
                     chain=chain, chain_device=chain_device)


@mcp.tool()
def set_parameter_real(track_index: int, device_index: int, parameter: str | int,
                       target: float, kind: TrackKind = "track", chain: int | None = None,
                       chain_device: int | None = None) -> dict:
    """Set a parameter in the units Live displays instead of raw values: Hz for
    frequencies (e.g. 150, 5000), dB for gains/thresholds, ms for times (seconds
    are converted), % for amounts. Finds the raw value by bisection without side
    effects. Prefer this over set_device_parameters for EQs, filters, compressors."""
    return live.send("set_parameter_display", track_index=track_index, device_index=device_index,
                     parameter=parameter, target=target, kind=kind, chain=chain,
                     chain_device=chain_device)


@mcp.tool()
def set_sidechain(track_index: int, device_index: int, source: str | None = None,
                  channel: str | None = "Post FX", kind: TrackKind = "track") -> dict:
    """Read or set the sidechain source of a Compressor (or any device with its own
    input routing). source = a track name, e.g. a silent 'ghost trigger' track that
    plays short hits on the 808 notes; then set_device_parameters {"S/C On": 1}.
    Omit source to list the available sources."""
    return live.send("device_routing", track_index=track_index, device_index=device_index,
                     input_type=source, input_channel=channel if source else None, kind=kind)


@mcp.tool()
def delete_device(track_index: int, device_index: int, kind: TrackKind = "track") -> dict:
    """Remove a device from a track's chain."""
    return live.send("delete_device", track_index=track_index, device_index=device_index, kind=kind)


@mcp.tool()
def get_drum_pads(track_index: int, device_index: int = 0, kind: TrackKind = "track") -> dict:
    """List the filled pads of a Drum Rack (MIDI note -> sample name)."""
    return live.send("get_drum_pads", track_index=track_index, device_index=device_index, kind=kind)


# ---------------------------------------------------------------- browser

BrowserCategory = Literal["sounds", "drums", "instruments", "audio_effects", "midi_effects",
                          "plugins", "clips", "samples", "packs", "user_library",
                          "current_project"]


@mcp.tool()
def browse(path: str = "instruments") -> dict:
    """List the contents of a browser folder, e.g. 'instruments', 'drums',
    'audio_effects/Delay & Loop', 'instruments/Drift'. First segment is the category."""
    return live.send("browse", path=path)


@mcp.tool()
def search_browser(query: str, category: BrowserCategory | None = None, max_results: int = 25) -> dict:
    """Find loadable items (devices, presets, kits, samples) whose name contains
    `query`. Without a category it searches instruments, drums, effects and sounds."""
    return live.send("search_browser", query=query, category=category, max_results=max_results)


@mcp.tool()
def load_device(track_index: int, path: str | None = None, query: str | None = None,
                category: BrowserCategory | None = None, kind: TrackKind = "track") -> dict:
    """Load an instrument, effect, kit or preset onto a track (appended to its chain).
    Give an exact browser `path` (from browse/search_browser) or a `query` name like
    'Reverb', 'Drift', 'EQ Eight', '808 Core Kit'. Call get_track_info afterwards to
    get the new device's index."""
    return live.send("load_device", track_index=track_index, path=path, query=query,
                     category=category, kind=kind)


@mcp.tool()
def device_property(track_index: int, device_index: int,
                    name: Literal["voices", "retrigger", "playback_mode", "multi_sample_mode",
                                  "slicing_playback_mode", "is_showing_chains"],
                    value: float | bool | None = None, kind: TrackKind = "track",
                    chain: int | None = None, chain_device: int | None = None) -> dict:
    """Read (value omitted) or set a device property that is not an automatable
    parameter, e.g. Simpler 'voices' (1 = mono, needed for 808 glide)."""
    return live.send("device_property", track_index=track_index, device_index=device_index,
                     name=name, value=value, kind=kind, chain=chain, chain_device=chain_device)


@mcp.tool()
def get_rack(track_index: int, device_index: int, kind: TrackKind = "track") -> dict:
    """Show the chains of a rack (Instrument/Drum/Audio Effect Rack; most presets
    are racks) and the devices inside each, to edit parameters the macros hide."""
    return live.send("get_rack", track_index=track_index, device_index=device_index, kind=kind)


@mcp.tool()
def set_chain(track_index: int, device_index: int, chain: int, volume: float | None = None,
              pan: float | None = None, mute: bool | None = None, solo: bool | None = None,
              kind: TrackKind = "track") -> dict:
    """Mix one chain of a rack, e.g. a single Drum Rack pad (get_rack lists them):
    volume 0-1 like a track fader (0.85 = 0 dB, 1.0 = +6 dB), pan -1..1."""
    return live.send("set_chain", track_index=track_index, device_index=device_index,
                     chain=chain, volume=volume, pan=pan, mute=mute, solo=solo, kind=kind)


@mcp.tool()
def move_device(track_index: int, device_index: int, new_index: int,
                kind: TrackKind = "track") -> dict:
    """Reorder a device in its chain (load_device always appends at the end, e.g.
    move an EQ in front of the master Limiter)."""
    return live.send("move_device", track_index=track_index, device_index=device_index,
                     new_index=new_index, kind=kind)


# ------------------------------------------------------------ arrangement

@mcp.tool()
def arrangement_place(track_index: int, slot_index: int, time: float) -> dict:
    """Copy a Session clip into the Arrangement timeline at `time` beats
    (bar N starts at (N-1)*4 in 4/4). Use it to lay out a full song from scenes."""
    return live.send("arrangement_place", track_index=track_index, slot_index=slot_index, time=time)


@mcp.tool()
def get_arrangement_clips(track_index: int) -> list:
    """List the clips already on a track's Arrangement timeline (start/end in beats)."""
    return live.send("get_arrangement_clips", track_index=track_index)


@mcp.tool()
def clear_arrangement(track_index: int) -> dict:
    """Remove every clip from a track's Arrangement timeline (Session clips stay)."""
    return live.send("clear_arrangement", track_index=track_index)


@mcp.tool()
def show_view(view: Literal["Arranger", "Session"] = "Arranger") -> dict:
    """Switch Live's main window between Arrangement and Session view."""
    return live.send("show_view", view=view)


# ----------------------------------------------------------------- meters

@mcp.tool()
def measure_levels(seconds: float = 8.0) -> dict:
    """Poll Live's output meters while the set plays and return the peak and
    average level per track, return and master (Live meter scale 0-1; 0.917 is
    -0.3 dBFS, ~0.0125-0.015 units per dB near the top). Start playback first.
    This is the closest thing to listening: use it to balance and catch clipping."""
    import time
    info = live.send("get_session_info")
    names = [t["name"] for t in info["tracks"]]
    rnames = [t["name"] for t in info["return_tracks"]]
    samples = []
    end = time.time() + max(1.0, min(seconds, 60.0))
    while time.time() < end:
        samples.append(live.send("get_meters"))
        time.sleep(0.1)

    def stats(values):
        peaks = [max(v) for v in values]
        return {"peak": round(max(peaks), 3), "avg": round(sum(peaks) / len(peaks), 3)}

    return {
        "was_playing": samples[-1]["is_playing"],
        "tracks": {n: stats([s["tracks"][i] for s in samples]) for i, n in enumerate(names)},
        "returns": {n: stats([s["returns"][i] for s in samples]) for i, n in enumerate(rnames)},
        "master": stats([s["master"] for s in samples]),
    }


# ------------------------------------------------------------------ debug

@mcp.tool()
def ping() -> dict:
    """Check the bridge is alive and report Live's version."""
    return live.send("ping")


# ---------------------------------------------------------- render/analyze

renderer = Renderer(live)


@mcp.tool()
def render_to_wav(start_bar: int = 1, end_bar: int | None = None, tail_bars: int = 2,
                  output_dir: str | None = None, filename: str | None = None,
                  section_bars: int | None = 8, stems: list[str] | None = None,
                  wait_seconds: float = 0) -> dict:
    """Render the Arrangement to WAV by recording in real time (Live has no export
    API). Default: the master mix to one file on the user's Desktop. With stems
    (track/return names, or ["all"]) it records one post-mixer file per track in a
    single pass into "<filename> - stems/" (mind Intro's 16-track limit: each stem
    adds a temporary track). end_bar=None renders to the last clip; tail_bars keeps
    reverb/delay tails. Files start exactly on the downbeat (latency pre-roll cut).
    The set must be saved once; the render saves it again (Live only releases new
    recordings on save). Takes as long as the music plays: returns immediately unless
    wait_seconds > 0; poll render_status until 'done'. Master renders include an
    analysis (LUFS, true peak, bands, per-section loudness); stems a level summary.
    Renders obey solo/mute: soloed tracks are reported in the result."""
    started = renderer.start(start_bar, end_bar, tail_bars, output_dir, filename, section_bars,
                             stems=stems)
    if wait_seconds > 0:
        return renderer.wait(wait_seconds)
    return started


@mcp.tool()
def render_status(wait_seconds: float = 0) -> dict:
    """Progress of the current render; with wait_seconds, block up to that long."""
    return renderer.wait(wait_seconds) if wait_seconds > 0 else renderer.status()


@mcp.tool()
def analyze_audio(path: str, section_seconds: float | None = None) -> dict:
    """Objective 'ears' for a WAV/AIFF/FLAC: integrated LUFS, sample and true peak,
    crest factor, clipping, spectral balance per band (dB relative to total),
    stereo and low-end (<150 Hz) correlation, loudness per section, and a
    'texture' block for Foley/ambiences: contrast_db (p95-p10 of 50 ms RMS; a real
    fireplace ~25-30 dB, below ~10 dB reads as a wash/"falling water"),
    crackle_ratio (p99/median 50 ms energy; >= 4 for crackly textures) and
    tonal_peak_hz/tonal_prominence (a line > 3x its local median in a noisy
    ambience is a hum; on music it is just a note, so ignore it there)."""
    return analyze(path, section_seconds)


@mcp.tool()
def reload_script() -> dict:
    """Hot-reload the Remote Script inside Live after its source file was updated."""
    return live.send("reload")


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
