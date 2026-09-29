# AbletonMCP_Intro Remote Script (Live 12)
# Opens a local TCP socket (127.0.0.1:9880) and runs JSON commands against the
# Live Object Model. Commands are queued by the socket thread and executed on
# Live's main thread inside update_display(), which is the only safe place to
# touch the Live API.
from __future__ import absolute_import

import json
import queue
import socket
import threading
import traceback

import Live
from _Framework.ControlSurface import ControlSurface

HOST = "127.0.0.1"
PORT = 9880
RESPONSE_TIMEOUT = 20.0
MAX_BROWSER_NODES = 4000
AUDIO_EXTS = (".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg")

BROWSER_ROOTS = (
    "sounds", "drums", "instruments", "audio_effects", "midi_effects",
    "max_for_live", "plugins", "clips", "samples", "packs", "user_library",
    "current_project",
)


def create_instance(c_instance):
    return AbletonMCP(c_instance)


class CommandError(Exception):
    pass


class AbletonMCP(ControlSurface):

    def __init__(self, c_instance):
        self._commands = queue.Queue()
        self._running = True
        self._server = None
        ControlSurface.__init__(self, c_instance)
        self._handlers = self._build_handlers()
        self._thread = threading.Thread(target=self._serve, name="AbletonMCP_Intro")
        self._thread.daemon = True
        self._thread.start()
        self.log_message("AbletonMCP_Intro: listening on %s:%d" % (HOST, PORT))
        self.show_message("AbletonMCP_Intro listo en el puerto %d" % PORT)

    # ------------------------------------------------------------------ server

    def disconnect(self):
        self._running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass
        ControlSurface.disconnect(self)

    def _serve(self):
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((HOST, PORT))
            self._server.listen(4)
            self._server.settimeout(1.0)
        except Exception as e:
            self.log_message("AbletonMCP_Intro: could not bind: %s" % e)
            return
        while self._running:
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            t = threading.Thread(target=self._handle_client, args=(conn,))
            t.daemon = True
            t.start()

    def _handle_client(self, conn):
        conn.settimeout(None)
        buf = b""
        try:
            while self._running:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        conn.sendall(self._dispatch_line(line) + b"\n")
        except Exception as e:
            self.log_message("AbletonMCP_Intro: client error: %s" % e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _dispatch_line(self, line):
        req_id = None
        try:
            req = json.loads(line.decode("utf-8"))
            req_id = req.get("id")
            reply = queue.Queue()
            self._commands.put((req.get("cmd"), req.get("params") or {}, reply))
            try:
                ok, payload = reply.get(timeout=RESPONSE_TIMEOUT)
            except queue.Empty:
                ok, payload = False, "Timeout: Live did not process the command"
        except Exception as e:
            ok, payload = False, "Bad request: %s" % e
        resp = {"id": req_id, "ok": ok}
        resp["result" if ok else "error"] = payload
        return json.dumps(resp).encode("utf-8")

    def update_display(self):
        ControlSurface.update_display(self)
        # Drain on the main thread; cap per tick so the UI never stalls.
        for _ in range(32):
            try:
                cmd, params, reply = self._commands.get_nowait()
            except queue.Empty:
                break
            reply.put(self._execute(cmd, params))

    def _execute(self, cmd, params):
        handler = self._handlers.get(cmd)
        if handler is None:
            return False, "Unknown command: %s" % cmd
        try:
            return True, handler(**params)
        except CommandError as e:
            return False, str(e)
        except TypeError as e:
            return False, "Bad parameters for %s: %s" % (cmd, e)
        except Exception as e:
            self.log_message("AbletonMCP_Intro error in %s: %s" % (cmd, traceback.format_exc()))
            return False, "%s: %s" % (type(e).__name__, e)

    def _build_handlers(self):
        names = [n for n in dir(self) if n.startswith("cmd_")]
        return dict((n[4:], getattr(self, n)) for n in names)

    # ----------------------------------------------------------------- helpers

    @property
    def _song(self):
        return self.song()

    def _track(self, track_index, kind="track"):
        song = self._song
        if kind == "master":
            return song.master_track
        tracks = song.return_tracks if kind == "return" else song.tracks
        if not 0 <= track_index < len(tracks):
            raise CommandError("%s index %d out of range (0-%d)"
                               % (kind, track_index, len(tracks) - 1))
        return tracks[track_index]

    def _slot(self, track_index, slot_index):
        track = self._track(track_index)
        if not 0 <= slot_index < len(track.clip_slots):
            raise CommandError("Slot %d out of range (0-%d)"
                               % (slot_index, len(track.clip_slots) - 1))
        return track.clip_slots[slot_index]

    def _clip(self, track_index, slot_index):
        slot = self._slot(track_index, slot_index)
        if not slot.has_clip:
            raise CommandError("No clip in track %d slot %d" % (track_index, slot_index))
        return slot.clip

    def _device(self, track_index, device_index, kind="track", chain=None,
                chain_device=None):
        """A top-level device, or with chain/chain_device one nested in a rack."""
        track = self._track(track_index, kind)
        if not 0 <= device_index < len(track.devices):
            raise CommandError("Device %d out of range (%d devices)"
                               % (device_index, len(track.devices)))
        device = track.devices[device_index]
        if chain is None:
            return device
        if not device.can_have_chains or not 0 <= chain < len(device.chains):
            raise CommandError("%s has no chain %d" % (device.name, chain))
        inner = device.chains[chain].devices
        index = chain_device or 0
        if not 0 <= index < len(inner):
            raise CommandError("Chain %d has %d devices" % (chain, len(inner)))
        return inner[index]

    def _param(self, device, parameter):
        params = list(device.parameters)
        if isinstance(parameter, int):
            if not 0 <= parameter < len(params):
                raise CommandError("Parameter index %d out of range" % parameter)
            return params[parameter]
        wanted = str(parameter).strip().lower()
        for p in params:
            if p.name.lower() == wanted:
                return p
        matches = [p for p in params if wanted in p.name.lower()]
        if len(matches) == 1:
            return matches[0]
        raise CommandError("Parameter '%s' not found or ambiguous. Available: %s"
                           % (parameter, ", ".join(p.name for p in params)))

    @staticmethod
    def _param_info(i, p):
        info = {"index": i, "name": p.name, "value": round(p.value, 4),
                "min": p.min, "max": p.max, "display": p.str_for_value(p.value),
                "quantized": p.is_quantized}
        if p.is_quantized:
            info["options"] = list(p.value_items)
        return info

    @staticmethod
    def _device_info(i, d):
        info = {"index": i, "name": d.name, "class": d.class_name,
                "type": str(d.type), "can_have_chains": d.can_have_chains,
                "can_have_drum_pads": d.can_have_drum_pads}
        try:
            info["on"] = bool(d.parameters[0].value)
        except Exception:
            pass
        return info

    def _clip_info(self, clip):
        info = {"name": clip.name, "length": clip.length,
                "is_midi": clip.is_midi_clip, "looping": clip.looping,
                "loop_start": clip.loop_start, "loop_end": clip.loop_end,
                "is_playing": clip.is_playing, "color_index": clip.color_index}
        if clip.is_audio_clip:
            info["file_path"] = clip.file_path
        return info

    def _track_summary(self, i, t, kind="track"):
        mixer = t.mixer_device
        info = {"index": i, "name": t.name,
                "volume": round(mixer.volume.value, 3),
                "volume_display": mixer.volume.str_for_value(mixer.volume.value),
                "pan": round(mixer.panning.value, 3),
                "devices": [d.name for d in t.devices]}
        if kind != "master":
            info.update({"mute": t.mute, "solo": t.solo,
                         "color_index": t.color_index})
        if kind == "track":
            info["type"] = "midi" if t.has_midi_input else "audio"
            info["arm"] = t.arm if t.can_be_armed else None
            info["is_group"] = t.is_foldable
            info["sends"] = [round(s.value, 3) for s in mixer.sends]
            info["sends_display"] = [s.str_for_value(s.value) for s in mixer.sends]
            clips = {}
            for s_i, slot in enumerate(t.clip_slots):
                if slot.has_clip:
                    c = slot.clip
                    clips[str(s_i)] = "%s (%.1f beats%s)" % (
                        c.name or "sin nombre", c.length,
                        ", sonando" if c.is_playing else "")
            info["clips"] = clips
        return info

    # --------------------------------------------------------- session / song

    def cmd_ping(self):
        return {"pong": True, "live_version": "%d.%d.%d" % (
            Live.Application.get_application().get_major_version(),
            Live.Application.get_application().get_minor_version(),
            Live.Application.get_application().get_bugfix_version())}

    def cmd_get_session_info(self):
        song = self._song
        view = song.view
        sel_track = view.selected_track
        sel_scene = view.selected_scene
        return {
            "tempo": song.tempo,
            "signature": "%d/%d" % (song.signature_numerator, song.signature_denominator),
            "is_playing": song.is_playing,
            "metronome": song.metronome,
            "loop": {"on": song.loop, "start": song.loop_start, "length": song.loop_length},
            "song_time": song.current_song_time,
            "start_time": song.start_time,
            "song_length": song.song_length,
            "scale": {"root_note": song.root_note, "name": song.scale_name},
            "file_path": song.file_path,
            "tracks": [self._track_summary(i, t) for i, t in enumerate(song.tracks)],
            "return_tracks": [self._track_summary(i, t, "return")
                              for i, t in enumerate(song.return_tracks)],
            "master": self._track_summary(0, song.master_track, "master"),
            "scenes": [{"index": i, "name": s.name} for i, s in enumerate(song.scenes)],
            "selected_track": sel_track.name if sel_track else None,
            "selected_scene": list(song.scenes).index(sel_scene) if sel_scene in list(song.scenes) else None,
        }

    def cmd_set_tempo(self, bpm):
        self._song.tempo = float(bpm)
        return {"tempo": self._song.tempo}

    def cmd_set_time_signature(self, numerator, denominator):
        self._song.signature_numerator = int(numerator)
        self._song.signature_denominator = int(denominator)
        return {"signature": "%d/%d" % (numerator, denominator)}

    def cmd_transport(self, action):
        song = self._song
        if action == "play":
            song.start_playing()
        elif action == "stop":
            song.stop_playing()
        elif action == "continue":
            song.continue_playing()
        elif action == "stop_all_clips":
            song.stop_all_clips()
        elif action == "back_to_arranger":
            song.back_to_arranger = False
        elif action == "undo":
            if not song.can_undo:
                raise CommandError("Nothing to undo")
            song.undo()
        elif action == "redo":
            if not song.can_redo:
                raise CommandError("Nothing to redo")
            song.redo()
        else:
            raise CommandError("Unknown transport action: %s" % action)
        return {"done": action, "is_playing": song.is_playing}

    def cmd_set_song_options(self, metronome=None, loop=None, loop_start=None,
                             loop_length=None, song_time=None, record_mode=None,
                             start_time=None):
        song = self._song
        if start_time is not None:
            song.start_time = float(start_time)
        if record_mode is not None:
            song.record_mode = bool(record_mode)
        if metronome is not None:
            song.metronome = bool(metronome)
        if loop is not None:
            song.loop = bool(loop)
        if loop_start is not None:
            song.loop_start = float(loop_start)
        if loop_length is not None:
            song.loop_length = float(loop_length)
        if song_time is not None:
            song.current_song_time = float(song_time)
        return {"metronome": song.metronome, "loop": song.loop,
                "loop_start": song.loop_start, "loop_length": song.loop_length,
                "record_mode": song.record_mode, "song_time": song.current_song_time,
                "start_time": song.start_time}

    # ------------------------------------------------------------------ tracks

    def cmd_get_track_info(self, track_index, kind="track"):
        t = self._track(track_index, kind)
        info = self._track_summary(track_index, t, kind)
        info["devices"] = [self._device_info(i, d) for i, d in enumerate(t.devices)]
        return info

    def cmd_create_track(self, type="midi", index=-1, name=None):
        song = self._song
        if type == "midi":
            song.create_midi_track(index)
            tracks, new_index = song.tracks, (index if index >= 0 else len(song.tracks) - 1)
        elif type == "audio":
            song.create_audio_track(index)
            tracks, new_index = song.tracks, (index if index >= 0 else len(song.tracks) - 1)
        elif type == "return":
            song.create_return_track()
            tracks, new_index = song.return_tracks, len(song.return_tracks) - 1
        else:
            raise CommandError("type must be midi, audio or return")
        if name:
            tracks[new_index].name = name
        return {"index": new_index, "name": tracks[new_index].name, "type": type}

    def cmd_delete_track(self, track_index, kind="track"):
        name = self._track(track_index, kind).name
        if kind == "return":
            self._song.delete_return_track(track_index)
        else:
            self._song.delete_track(track_index)
        return {"deleted": name}

    def cmd_duplicate_track(self, track_index):
        self._song.duplicate_track(track_index)
        return {"new_index": track_index + 1}

    def cmd_set_track(self, track_index, kind="track", name=None, volume=None,
                      pan=None, mute=None, solo=None, arm=None, color_index=None,
                      sends=None, monitoring=None):
        t = self._track(track_index, kind)
        mixer = t.mixer_device
        if name is not None:
            t.name = name
        if volume is not None:
            mixer.volume.value = float(volume)
        if pan is not None:
            mixer.panning.value = float(pan)
        if mute is not None:
            t.mute = bool(mute)
        if solo is not None:
            t.solo = bool(solo)
        if arm is not None:
            if not t.can_be_armed:
                raise CommandError("Track cannot be armed")
            t.arm = bool(arm)
        if color_index is not None:
            t.color_index = int(color_index)
        if monitoring is not None:
            modes = {"in": 0, "auto": 1, "off": 2}
            t.current_monitoring_state = modes[str(monitoring).lower()]
        if sends:
            for i, v in enumerate(sends):
                if v is not None and i < len(mixer.sends):
                    mixer.sends[i].value = float(v)
        return self._track_summary(track_index, t, kind)

    def cmd_get_routing(self, track_index, kind="track"):
        t = self._track(track_index, kind)
        info = {"output": t.output_routing_type.display_name,
                "outputs": [r.display_name for r in t.available_output_routing_types]}
        if kind == "track":
            info.update({
                "input": t.input_routing_type.display_name,
                "input_channel": t.input_routing_channel.display_name,
                "inputs": [r.display_name for r in t.available_input_routing_types],
                "input_channels": [r.display_name for r in t.available_input_routing_channels],
                "monitoring": ["in", "auto", "off"][t.current_monitoring_state]})
        return info

    def cmd_set_routing(self, track_index, input_type=None, input_channel=None,
                        output_type=None, kind="track"):
        """Route by display name, e.g. input_type='Resampling' to record the master."""
        t = self._track(track_index, kind)

        def pick(options, name, what):
            for r in options:
                if r.display_name.lower() == str(name).lower():
                    return r
            raise CommandError("%s '%s' not available: %s" % (
                what, name, [r.display_name for r in options]))

        if input_type is not None:
            t.input_routing_type = pick(t.available_input_routing_types, input_type, "Input")
        if input_channel is not None:
            t.input_routing_channel = pick(t.available_input_routing_channels, input_channel,
                                           "Input channel")
        if output_type is not None:
            t.output_routing_type = pick(t.available_output_routing_types, output_type, "Output")
        return self.cmd_get_routing(track_index, kind)

    def cmd_select_track(self, track_index, kind="track"):
        self._song.view.selected_track = self._track(track_index, kind)
        return {"selected": self._song.view.selected_track.name}

    # ------------------------------------------------------------------- clips

    def cmd_create_clip(self, track_index, slot_index, length=4.0, name=None):
        slot = self._slot(track_index, slot_index)
        if slot.has_clip:
            raise CommandError("Slot already has a clip; delete it first")
        slot.create_clip(float(length))
        if name:
            slot.clip.name = name
        return self._clip_info(slot.clip)

    def cmd_delete_clip(self, track_index, slot_index):
        slot = self._slot(track_index, slot_index)
        if not slot.has_clip:
            raise CommandError("Slot is empty")
        slot.delete_clip()
        return {"deleted": True}

    def cmd_duplicate_clip(self, track_index, slot_index, target_track, target_slot):
        src = self._slot(track_index, slot_index)
        dst = self._slot(target_track, target_slot)
        if not src.has_clip:
            raise CommandError("Source slot is empty")
        src.duplicate_clip_to(dst)
        return {"copied_to": [target_track, target_slot]}

    def cmd_set_clip(self, track_index, slot_index, name=None, loop_start=None,
                     loop_end=None, looping=None, color_index=None):
        clip = self._clip(track_index, slot_index)
        if name is not None:
            clip.name = name
        if loop_end is not None:
            clip.loop_end = float(loop_end)
            clip.end_marker = float(loop_end)
        if loop_start is not None:
            clip.loop_start = float(loop_start)
            clip.start_marker = float(loop_start)
        if looping is not None:
            clip.looping = bool(looping)
        if color_index is not None:
            clip.color_index = int(color_index)
        return self._clip_info(clip)

    def cmd_load_audio_clip(self, track_index, slot_index, file_path):
        """Put an audio file (absolute path) into a Session View slot of an audio track (Live 12 API)."""
        slot = self._slot(track_index, slot_index)
        if slot.has_clip:
            raise CommandError("Slot already has a clip; delete it first")
        slot.create_audio_clip(file_path)
        return self._clip_info(slot.clip)

    def cmd_arrangement_audio_clip(self, track_index, file_path, time):
        """Put an audio file (absolute path) straight onto an audio track's Arrangement
        timeline at `time` beats (Live 12: Track.create_audio_clip), no Session slot."""
        track = self._track(track_index)
        if not hasattr(track, "create_audio_clip"):
            raise CommandError("This Live version has no Track.create_audio_clip")
        if track.has_midi_input:
            raise CommandError("Track %d is a MIDI track; use an audio track" % track_index)
        before = len(track.arrangement_clips)
        track.create_audio_clip(file_path, float(time))
        clips = sorted(track.arrangement_clips, key=lambda c: abs(c.start_time - float(time)))
        if len(track.arrangement_clips) <= before or not clips:
            raise CommandError("Live did not create the clip")
        c = clips[0]
        return {"name": c.name, "start": c.start_time, "end": c.end_time,
                "warping": c.warping, "file_path": c.file_path}

    def cmd_set_audio_clip(self, track_index, slot_index, warping=None, warp_mode=None,
                           pitch_coarse=None, pitch_fine=None, gain=None):
        """Audio clip playback: warp_mode 0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch, 4 Complex,
        6 Complex Pro; pitch_coarse in semitones, pitch_fine in cents, gain raw 0..1."""
        clip = self._clip(track_index, slot_index)
        if not clip.is_audio_clip:
            raise CommandError("Not an audio clip")
        if warping is not None:
            clip.warping = bool(warping)
        if warp_mode is not None:
            clip.warp_mode = int(warp_mode)
        if pitch_coarse is not None:
            clip.pitch_coarse = int(pitch_coarse)
        if pitch_fine is not None:
            clip.pitch_fine = float(pitch_fine)
        if gain is not None:
            clip.gain = float(gain)
        info = self._clip_info(clip)
        info.update({"warping": clip.warping, "warp_mode": clip.warp_mode,
                     "pitch_coarse": clip.pitch_coarse, "pitch_fine": clip.pitch_fine,
                     "gain": clip.gain, "gain_display": clip.gain_display_string})
        return info

    def cmd_add_notes(self, track_index, slot_index, notes, replace=False):
        clip = self._clip(track_index, slot_index)
        if not clip.is_midi_clip:
            raise CommandError("Not a MIDI clip")
        if replace:
            clip.remove_notes_extended(0, 128, 0.0, max(clip.length, clip.loop_end) + 1024)
        specs = []
        for n in notes:
            kwargs = dict(pitch=int(n["pitch"]),
                          start_time=float(n.get("start", n.get("start_time", 0.0))),
                          duration=float(n.get("duration", 0.25)),
                          velocity=float(n.get("velocity", 100)),
                          mute=bool(n.get("mute", False)))
            if "probability" in n:
                kwargs["probability"] = float(n["probability"])
            if "velocity_deviation" in n:
                kwargs["velocity_deviation"] = float(n["velocity_deviation"])
            specs.append(Live.Clip.MidiNoteSpecification(**kwargs))
        clip.add_new_notes(tuple(specs))
        return {"added": len(specs), "clip_length": clip.length}

    def cmd_get_notes(self, track_index, slot_index):
        clip = self._clip(track_index, slot_index)
        if not clip.is_midi_clip:
            raise CommandError("Not a MIDI clip")
        notes = clip.get_notes_extended(0, 128, 0.0, max(clip.length, clip.loop_end) + 1024)
        out = [{"pitch": n.pitch, "start": round(n.start_time, 4),
                "duration": round(n.duration, 4), "velocity": round(n.velocity, 1),
                "mute": n.mute, "probability": round(n.probability, 3)}
               for n in notes]
        out.sort(key=lambda n: (n["start"], n["pitch"]))
        return {"clip": self._clip_info(clip), "notes": out}

    def cmd_remove_notes(self, track_index, slot_index, from_pitch=0, pitch_span=128,
                         from_time=0.0, time_span=None):
        clip = self._clip(track_index, slot_index)
        if time_span is None:
            time_span = max(clip.length, clip.loop_end) + 1024
        clip.remove_notes_extended(int(from_pitch), int(pitch_span),
                                   float(from_time), float(time_span))
        return {"removed": True}

    def cmd_quantize_clip(self, track_index, slot_index, grid="1/16", amount=1.0):
        grids = {"1/4": 1, "1/8": 2, "1/8T": 3, "1/8+1/8T": 4, "1/16": 5,
                 "1/16T": 6, "1/16+1/16T": 7, "1/32": 8}
        if grid not in grids:
            raise CommandError("grid must be one of %s" % ", ".join(grids))
        clip = self._clip(track_index, slot_index)
        clip.quantize(grids[grid], float(amount))
        return {"quantized": grid, "amount": amount}

    def cmd_fire_clip(self, track_index, slot_index):
        self._slot(track_index, slot_index).fire()
        return {"fired": [track_index, slot_index]}

    def cmd_stop_track_clips(self, track_index):
        self._track(track_index).stop_all_clips()
        return {"stopped": track_index}

    def cmd_select_clip(self, track_index, slot_index):
        view = self._song.view
        view.selected_track = self._track(track_index)
        view.highlighted_clip_slot = self._slot(track_index, slot_index)
        return {"selected": [track_index, slot_index]}

    def cmd_set_clip_automation(self, track_index, slot_index, device_index,
                                parameter, points, clear=True, kind="track",
                                chain=None, chain_device=None):
        clip = self._clip(track_index, slot_index)
        param = self._param(self._device(track_index, device_index, kind, chain,
                                         chain_device), parameter)
        env = clip.automation_envelope(param)
        if env is not None and clear:
            clip.clear_envelope(param)
            env = None
        if env is None:
            env = clip.create_automation_envelope(param)
        if env is None:
            raise CommandError("Live refused to create an envelope for %s" % param.name)
        for pt in points:
            value = min(max(float(pt["value"]), param.min), param.max)
            env.insert_step(float(pt["time"]), float(pt.get("duration", 0.0)), value)
        return {"parameter": param.name, "points": len(points)}

    # ------------------------------------------------------------------ scenes

    def cmd_create_scene(self, index=-1, name=None):
        song = self._song
        song.create_scene(index)
        new_index = index if index >= 0 else len(song.scenes) - 1
        if name:
            song.scenes[new_index].name = name
        return {"index": new_index, "name": song.scenes[new_index].name}

    def cmd_set_scene(self, scene_index, name=None):
        scene = self._song.scenes[scene_index]
        if name is not None:
            scene.name = name
        return {"index": scene_index, "name": scene.name}

    def cmd_fire_scene(self, scene_index):
        self._song.scenes[scene_index].fire()
        return {"fired": scene_index}

    def cmd_duplicate_scene(self, scene_index):
        self._song.duplicate_scene(scene_index)
        return {"new_index": scene_index + 1}

    def cmd_delete_scene(self, scene_index):
        self._song.delete_scene(scene_index)
        return {"deleted": scene_index}

    # ----------------------------------------------------------------- devices

    def cmd_get_device_parameters(self, track_index, device_index, kind="track",
                                  chain=None, chain_device=None):
        d = self._device(track_index, device_index, kind, chain, chain_device)
        return {"device": self._device_info(device_index, d),
                "parameters": [self._param_info(i, p) for i, p in enumerate(d.parameters)]}

    def cmd_set_device_parameters(self, track_index, device_index, values, kind="track",
                                  chain=None, chain_device=None):
        d = self._device(track_index, device_index, kind, chain, chain_device)
        results = []
        for key, value in values.items():
            p = self._param(d, int(key) if str(key).isdigit() else key)
            if not p.is_enabled:
                raise CommandError("Parameter %s is disabled (automated or locked)" % p.name)
            if isinstance(value, str) and p.is_quantized:
                items = [str(v).lower() for v in p.value_items]
                if value.lower() not in items:
                    raise CommandError("%s options: %s" % (p.name, list(p.value_items)))
                value = items.index(value.lower())
            p.value = min(max(float(value), p.min), p.max)
            results.append({"name": p.name, "value": round(p.value, 4),
                            "display": p.str_for_value(p.value)})
        return {"device": d.name, "set": results}

    @staticmethod
    def _display_number(text):
        """'2.52 kHz' -> 2520.0, '-14.0 dB' -> -14.0, '172 ms' -> 172.0, '1.20 s' -> 1200.0."""
        import re
        m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", "."))
        if not m:
            return None
        v = float(m.group())
        low = text.lower()
        if "khz" in low:
            v *= 1000.0
        elif re.search(r"\d\s*s\b", low) and "ms" not in low:
            v *= 1000.0  # seconds -> ms, so time targets are always given in ms
        return v

    def cmd_set_parameter_display(self, track_index, device_index, parameter, target,
                                  kind="track", chain=None, chain_device=None):
        """Set a parameter by its displayed unit (Hz, dB, ms, %) instead of the raw
        value: bisects the raw range with str_for_value (no side effects) and
        assumes the display is monotonic. Frequencies in Hz, times in ms."""
        p = self._param(self._device(track_index, device_index, kind, chain, chain_device),
                        int(parameter) if str(parameter).isdigit() else parameter)
        lo, hi = p.min, p.max
        span = hi - lo
        f_lo = f_hi = None
        for step in (0, 1e-4, 1e-3, 1e-2):  # endpoints may read "-inf dB" / "inf : 1"
            if f_lo is None:
                f_lo = self._display_number(p.str_for_value(p.min + step * span))
                lo = p.min + step * span
            if f_hi is None:
                f_hi = self._display_number(p.str_for_value(p.max - step * span))
                hi = p.max - step * span
        if f_lo is None or f_hi is None:
            raise CommandError("%s has no numeric display" % p.name)
        rising = f_hi >= f_lo
        target = float(target)
        for _ in range(40):
            mid = (lo + hi) / 2.0
            v = self._display_number(p.str_for_value(mid))
            if v is None:
                break
            if (v < target) == rising:
                lo = mid
            else:
                hi = mid
        p.value = (lo + hi) / 2.0
        return {"name": p.name, "value": round(p.value, 5), "display": p.str_for_value(p.value)}

    def cmd_delete_device(self, track_index, device_index, kind="track"):
        t = self._track(track_index, kind)
        name = self._device(track_index, device_index, kind).name
        t.delete_device(device_index)
        return {"deleted": name}

    def cmd_get_drum_pads(self, track_index, device_index, kind="track"):
        d = self._device(track_index, device_index, kind)
        if not d.can_have_drum_pads:
            raise CommandError("%s is not a Drum Rack" % d.name)
        pads = [{"note": p.note, "name": p.name}
                for p in d.drum_pads if len(p.chains) > 0]
        return {"device": d.name, "pads": pads}

    # ----------------------------------------------------------------- browser

    def _browser(self):
        return Live.Application.get_application().browser

    def _browser_root(self, name):
        if name not in BROWSER_ROOTS:
            raise CommandError("Category must be one of: %s" % ", ".join(BROWSER_ROOTS))
        return getattr(self._browser(), name)

    def _browser_item(self, path):
        parts = [p for p in path.strip("/").split("/") if p]
        item = self._browser_root(parts[0])
        for part in parts[1:]:
            match = None
            for child in item.children:
                if child.name.lower() == part.lower():
                    match = child
                    break
            if match is None:
                raise CommandError("'%s' not found under '%s'. Children: %s" % (
                    part, item.name, ", ".join(c.name for c in item.children)[:1500]))
            item = match
        return item

    def cmd_browse(self, path="instruments"):
        item = self._browser_item(path)
        return {"path": path, "items": [
            {"name": c.name, "folder": c.is_folder, "loadable": c.is_loadable}
            for c in item.children]}

    def _search(self, query, categories, max_results):
        """Breadth-first, so top-level devices and kits beat deep sample folders;
        then ranked: exact name, devices/presets before raw audio files, shallow first."""
        query = query.lower()
        hits, visited = [], 0
        frontier = [(self._browser_root(cat), cat, 0) for cat in categories]
        while frontier and visited < MAX_BROWSER_NODES and len(hits) < max_results * 4:
            item, path, depth = frontier.pop(0)
            for child in item.children:
                visited += 1
                child_path = path + "/" + child.name
                name = child.name.lower()
                if child.is_loadable and query in name:
                    stem = name.rsplit(".", 1)[0] if "." in name else name
                    hits.append((stem != query, name.endswith(AUDIO_EXTS), depth,
                                 {"name": child.name, "path": child_path}))
                if depth < 6 and (child.is_folder or child.children):
                    frontier.append((child, child_path, depth + 1))
        hits.sort(key=lambda h: h[:3])
        return [h[3] for h in hits[:max_results]]

    def cmd_search_browser(self, query, category=None, max_results=25):
        cats = [category] if category else ["instruments", "drums", "audio_effects",
                                            "midi_effects", "sounds"]
        return {"results": self._search(query, cats, int(max_results))}

    def cmd_load_device(self, track_index, path=None, query=None, category=None,
                        kind="track"):
        if path:
            item = self._browser_item(path)
        elif query:
            cats = [category] if category else ["instruments", "audio_effects",
                                                "midi_effects", "drums", "sounds"]
            hits = self._search(query, cats, 25)
            if not hits:
                raise CommandError("Nothing loadable matches '%s'" % query)
            item = self._browser_item(hits[0]["path"])
        else:
            raise CommandError("Give path or query")
        if not item.is_loadable:
            raise CommandError("'%s' is a folder, not loadable" % item.name)
        track = self._track(track_index, kind)
        self._song.view.selected_track = track
        before = len(track.devices)
        self._browser().load_item(item)
        return {"loaded": item.name, "track": track.name,
                "devices_before": before, "note": "Device list refreshes on next call"}

    DEVICE_PROPERTIES = ("voices", "retrigger", "playback_mode", "multi_sample_mode",
                         "slicing_playback_mode", "is_showing_chains")

    def cmd_device_property(self, track_index, device_index, name, value=None,
                            kind="track", chain=None, chain_device=None):
        """Read or set a device property that is not a parameter (e.g. Simpler voices)."""
        if name not in self.DEVICE_PROPERTIES:
            raise CommandError("name must be one of %s" % ", ".join(self.DEVICE_PROPERTIES))
        d = self._device(track_index, device_index, kind, chain, chain_device)
        if not hasattr(d, name):
            raise CommandError("%s has no property %s" % (d.name, name))
        if value is not None:
            current = getattr(d, name)
            setattr(d, name, type(current)(value) if isinstance(current, (bool, int, float)) else value)
        v = getattr(d, name)
        return {"device": d.name, name: v if isinstance(v, (bool, int, float)) else str(v)}

    def cmd_device_routing(self, track_index, device_index, input_type=None,
                           input_channel=None, kind="track", chain=None, chain_device=None):
        """Read or set a device's own input routing: the sidechain source of
        Compressor (and any other device exposing input_routing_type)."""
        d = self._device(track_index, device_index, kind, chain, chain_device)
        if not hasattr(d, "input_routing_type"):
            raise CommandError("%s has no sidechain/input routing" % d.name)

        def pick(options, name, what):
            for r in options:
                if r.display_name.lower() == str(name).lower():
                    return r
            raise CommandError("%s '%s' not available: %s"
                               % (what, name, [r.display_name for r in options]))

        if input_type is not None:
            d.input_routing_type = pick(d.available_input_routing_types, input_type, "Source")
        if input_channel is not None:
            d.input_routing_channel = pick(d.available_input_routing_channels, input_channel,
                                           "Channel")
        return {"device": d.name,
                "input": d.input_routing_type.display_name,
                "input_channel": d.input_routing_channel.display_name,
                "inputs": [r.display_name for r in d.available_input_routing_types],
                "input_channels": [r.display_name for r in d.available_input_routing_channels][:12]}

    def cmd_get_rack(self, track_index, device_index, kind="track"):
        """Chains of a rack and the devices inside each one."""
        d = self._device(track_index, device_index, kind)
        if not d.can_have_chains:
            raise CommandError("%s is not a rack" % d.name)
        def chain_info(c_i, c):
            vol = c.mixer_device.volume
            return {"index": c_i, "name": c.name, "mute": c.mute, "solo": c.solo,
                    "volume": round(vol.value, 3), "volume_display": vol.str_for_value(vol.value),
                    "pan": round(c.mixer_device.panning.value, 3),
                    "devices": [self._device_info(i, x) for i, x in enumerate(c.devices)]}

        return {"rack": d.name, "chains": [chain_info(i, c) for i, c in enumerate(d.chains)]}

    def cmd_set_chain(self, track_index, device_index, chain, volume=None, pan=None,
                      mute=None, solo=None, kind="track"):
        """Mix one chain of a rack (e.g. a Drum Rack pad): volume 0-1 (0.85 = 0 dB)."""
        d = self._device(track_index, device_index, kind)
        if not d.can_have_chains or not 0 <= chain < len(d.chains):
            raise CommandError("%s has no chain %d" % (d.name, chain))
        c = d.chains[chain]
        if volume is not None:
            c.mixer_device.volume.value = float(volume)
        if pan is not None:
            c.mixer_device.panning.value = float(pan)
        if mute is not None:
            c.mute = bool(mute)
        if solo is not None:
            c.solo = bool(solo)
        vol = c.mixer_device.volume
        return {"chain": c.name, "volume_display": vol.str_for_value(vol.value),
                "pan": c.mixer_device.panning.value, "mute": c.mute, "solo": c.solo}

    def cmd_move_device(self, track_index, device_index, new_index, kind="track"):
        """Reorder a device inside its track's chain."""
        track = self._track(track_index, kind)
        device = self._device(track_index, device_index, kind)
        self._song.move_device(device, track, int(new_index))
        return {"order": [d.name for d in track.devices]}

    # ------------------------------------------------------------- arrangement

    def cmd_get_arrangement_clips(self, track_index):
        t = self._track(track_index)
        out = []
        for c in t.arrangement_clips:
            item = {"name": c.name, "start": c.start_time, "end": c.end_time}
            if c.is_audio_clip:
                item.update({"file_path": c.file_path, "start_marker": c.start_marker,
                             "end_marker": c.end_marker, "warping": c.warping})
                try:
                    # Seconds from the file start to the clip's start marker.
                    item["start_marker_seconds"] = c.beat_to_sample_time(c.start_marker) / c.sample_rate
                except Exception:
                    pass
            out.append(item)
        return out

    def cmd_arrangement_place(self, track_index, slot_index, time):
        """Copy a Session clip into the Arrangement at `time` (beats)."""
        clip = self._clip(track_index, slot_index)
        self._track(track_index).duplicate_clip_to_arrangement(clip, float(time))
        return {"placed": clip.name, "at": float(time)}

    def cmd_clear_arrangement(self, track_index):
        t = self._track(track_index)
        clips = list(t.arrangement_clips)
        for c in clips:
            t.delete_clip(c)
        return {"removed": len(clips)}

    def cmd_show_view(self, view="Arranger"):
        """Switch Live's main view: 'Arranger' or 'Session'."""
        Live.Application.get_application().view.show_view(view)
        return {"shown": view}

    # ------------------------------------------------------------------ reload

    def cmd_reload(self):
        """Re-import this file and swap the running instance onto the new code,
        so script updates apply without toggling the control surface."""
        import importlib
        import sys
        module = importlib.reload(sys.modules[self.__class__.__module__])
        self.__class__ = module.AbletonMCP
        self._handlers = self._build_handlers()
        return {"reloaded": True, "commands": len(self._handlers)}

    # ------------------------------------------------------------------ meters

    def cmd_get_meters(self):
        """Instant output meter levels (0-1, Live's meter scale) per track and master."""
        song = self._song

        def lv(t):
            try:
                return [round(t.output_meter_left, 4), round(t.output_meter_right, 4)]
            except Exception:
                return [round(t.output_meter_level, 4)] * 2

        return {"is_playing": song.is_playing,
                "tracks": [lv(t) for t in song.tracks],
                "returns": [lv(t) for t in song.return_tracks],
                "master": lv(song.master_track)}

    # ------------------------------------------------------------ introspection

    def cmd_inspect(self, target="song", track_index=None, device_index=None, kind="track"):
        """Developer helper: list the Live API attributes of an object
        (target='device' + track_index/device_index inspects one device)."""
        song = self._song
        if target == "device":
            d = self._device(track_index, device_index, kind)
            return sorted(a for a in dir(d) if not a.startswith("_"))
        objs = {"song": song, "view": song.view,
                "track": song.tracks[0] if len(song.tracks) else None,
                "application": Live.Application.get_application(),
                "browser": self._browser()}
        obj = objs.get(target)
        if obj is None:
            raise CommandError("target must be one of %s" % list(objs))
        return sorted(a for a in dir(obj) if not a.startswith("_"))
