"""Rendering (resampling the master into a WAV) and offline analysis of audio files.

Live's API has no export function, so a render is a real-time recording of the
master through an audio track whose input is "Resampling". Live keeps the new
recording open (0 bytes on disk, share-locked) until the set is saved, so the
render deletes its temporary track and saves the set with Ctrl+S (Windows).
"""
import glob
import os
import sys
import threading
import time
from datetime import datetime

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import ndimage, signal

BANDS = [("sub 20-60", 20, 60), ("bass 60-250", 60, 250), ("low-mid 250-2k", 250, 2000),
         ("high-mid 2k-6k", 2000, 6000), ("air 6k-20k", 6000, 20000)]


def resolve_live_path(path: str) -> str:
    """Live's API mangles non-ASCII characters into U+FFFD; find the real file."""
    if os.path.exists(path):
        return path
    pattern = glob.escape(path).replace("\ufffd", "?")
    hits = glob.glob(pattern)
    if not hits:
        raise FileNotFoundError(path)
    return hits[0]


def _readable(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return len(f.read(16)) == 16
    except OSError:
        return False


def _live_window():
    """(hwnd, title) of the visible Ableton Live main window, or (None, '')."""
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if " - Ableton Live" in buf.value:
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else (None, "")


def seconds_since_user_input() -> float:
    """Seconds since the last keyboard/mouse input on this machine (Windows)."""
    if sys.platform != "win32":
        return float("inf")
    import ctypes
    from ctypes import wintypes as wt

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.WinDLL("user32").GetLastInputInfo(ctypes.byref(info))
    return (ctypes.WinDLL("kernel32").GetTickCount() - info.dwTime) / 1000.0


def save_live_set(timeout: float = 8.0) -> None:
    """Save the Live set with Ctrl+S (Windows only; the API has no save).

    Hardened after a stray 'S' once soloed a track (in Live, S = solo the selected
    track): the chord goes out as ONE atomic SendInput batch, only after checking
    that Live really has the foreground. Callers should select the master track
    first, where a lone 'S' is harmless. Waits until the title loses its '*'."""
    if sys.platform != "win32":
        raise RuntimeError("Automatic save is Windows-only; save the set in Live manually")
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd, title = _live_window()
    if not hwnd:
        raise RuntimeError("Live window not found")
    if "*" not in title:
        return  # already saved
    if seconds_since_user_input() < 30:
        # Someone is using the computer: stealing focus could send their keystrokes
        # to Live (a lone "s" solos a track). Let them save instead.
        raise RuntimeError("user active")
    fg = user32.GetForegroundWindow()
    if fg != hwnd:
        # Attach to the foreground thread so Windows lets us hand focus to Live.
        cur = kernel32.GetCurrentThreadId()
        other = user32.GetWindowThreadProcessId(fg, None)
        user32.AttachThreadInput(cur, other, True)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur, other, False)
        time.sleep(0.3)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("Could not bring Live to the foreground; save manually")

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", _U)]

    VK_CONTROL, VK_S, KEYUP = 0x11, 0x53, 0x0002
    seq = [(VK_CONTROL, 0), (VK_S, 0), (VK_S, KEYUP), (VK_CONTROL, KEYUP)]
    inputs = (INPUT * 4)(*[INPUT(1, _U(ki=KEYBDINPUT(vk, 0, flags, 0, 0))) for vk, flags in seq])
    if user32.SendInput(4, inputs, ctypes.sizeof(INPUT)) != 4:
        raise RuntimeError("SendInput failed (%d)" % ctypes.get_last_error())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if "*" not in _live_window()[1]:
            return
        time.sleep(0.25)
    raise RuntimeError("Save did not complete (title still shows '*')")


def _db(v: float) -> float:
    return float(round(20 * np.log10(max(float(v), 1e-12)), 2))


class _Stream:
    """Running state for a streaming (block-by-block) analysis."""

    def __init__(self, sr, channels):
        self.sr, self.ch = sr, channels
        self.n = self.clipped = 0
        self.peak = self.true_peak = self.sumsq = 0.0
        # K-weighting (BS.1770): pyloudnorm's two biquads, run with carried state.
        meter = pyln.Meter(sr)
        self.kfilters = [(f.b, f.a, f.passband_gain) for f in meter._filters.values()]
        self.kstate = [[np.zeros(len(a) - 1) for _ in range(channels)] for _, a, _ in self.kfilters]
        self.bin_len = int(round(0.1 * sr))  # 100 ms sub-blocks
        self.bin_energy, self.bin_peak = [], []
        self.bin_carry = np.zeros((0, channels))
        self.raw_carry = np.zeros((0, channels), np.float32)
        # Spectrum: Hann segments of 8192 with 50 % overlap on the mono sum.
        self.nfft = 8192
        self.win = np.hanning(self.nfft)
        self.psd = np.zeros(self.nfft // 2 + 1)
        self.fft_carry = np.zeros(0)
        # Correlations as running sums (full band and < 150 Hz).
        self.corr, self.low_corr = np.zeros(5), np.zeros(5)
        self.low_sos = signal.butter(4, 150, "low", fs=sr, output="sos")
        self.low_state = np.zeros((self.low_sos.shape[0], 2, channels))
        self.tp_tail = np.zeros((0, channels), np.float32)
        # Texture (Foley/ambience): mono mean-square energy per 50 ms frame.
        self.f50 = int(round(0.05 * sr))
        self.f50_energy = []
        self.f50_carry = np.zeros(0)

    @staticmethod
    def _add_corr(acc, left, right):
        acc += (left.sum(), right.sum(), (left * left).sum(), (right * right).sum(), (left * right).sum())

    @staticmethod
    def corr_of(acc, n):
        sl, sr_, sll, srr, slr = acc
        var = (sll - sl * sl / n) * (srr - sr_ * sr_ / n)
        return round(float((slr - sl * sr_ / n) / np.sqrt(var)), 3) if var > 0 else 1.0

    def feed(self, blk):
        a = np.abs(blk)
        self.n += len(blk)
        self.peak = max(self.peak, float(a.max()))
        self.clipped += int((a >= 0.999).sum())
        x = blk.astype(np.float64)
        self.sumsq += float((x * x).sum())
        # True peak: 4x oversampling with 64 samples of context from the last block.
        ctx = np.concatenate([self.tp_tail, blk])
        self.true_peak = max(self.true_peak, float(np.abs(signal.resample_poly(ctx, 4, 1, axis=0)).max()))
        self.tp_tail = blk[-64:]
        # K-weighted energy per 100 ms bin.
        kw = x.copy()
        for stage, (b, a_, gain) in enumerate(self.kfilters):
            for c in range(self.ch):
                kw[:, c], self.kstate[stage][c] = signal.lfilter(b, a_, kw[:, c], zi=self.kstate[stage][c])
            kw *= gain
        kw = np.concatenate([self.bin_carry, kw])
        raw = np.concatenate([self.raw_carry, blk])
        full = len(kw) // self.bin_len * self.bin_len
        if full:
            self.bin_energy.extend((kw[:full] ** 2).reshape(-1, self.bin_len, self.ch).sum(axis=1).tolist())
            self.bin_peak.extend(np.abs(raw[:full]).reshape(-1, self.bin_len * self.ch).max(axis=1).tolist())
        self.bin_carry, self.raw_carry = kw[full:], raw[full:]
        mono_blk = x.mean(axis=1)
        m50 = np.concatenate([self.f50_carry, mono_blk])
        full50 = len(m50) // self.f50 * self.f50
        if full50:
            self.f50_energy.extend((m50[:full50] ** 2).reshape(-1, self.f50).mean(axis=1).tolist())
        self.f50_carry = m50[full50:]
        # Spectrum of the mono sum.
        mono = np.concatenate([self.fft_carry, mono_blk])
        hop, i = self.nfft // 2, 0
        while i + self.nfft <= len(mono):
            seg = mono[i:i + self.nfft]
            self.psd += np.abs(np.fft.rfft((seg - seg.mean()) * self.win)) ** 2
            i += hop
        self.fft_carry = mono[i:]
        if self.ch == 2:
            self._add_corr(self.corr, x[:, 0], x[:, 1])
            low, self.low_state = signal.sosfilt(self.low_sos, x, axis=0, zi=self.low_state)
            self._add_corr(self.low_corr, low[:, 0], low[:, 1])

    def lufs(self, first_bin=0, last_bin=None):
        """BS.1770-4 gated loudness from 400 ms blocks (4 bins, 75 % overlap)."""
        e = np.asarray(self.bin_energy[first_bin:last_bin])
        if len(e) < 4:
            return None
        z = (e[:-3] + e[1:-2] + e[2:-1] + e[3:]) / (4 * self.bin_len)
        lk = -0.691 + 10 * np.log10(np.maximum(z.sum(axis=1), 1e-20))
        above = lk > -70
        if not above.any():
            return None  # silence: no block above the -70 LUFS gate
        rel = -0.691 + 10 * np.log10(z[above].mean(axis=0).sum()) - 10
        final = z[above & (lk > rel)]
        return float(round(-0.691 + 10 * np.log10(final.mean(axis=0).sum()), 2))


def _texture(st, freqs):
    """Foley/ambience descriptors, validated on a Foley/ambience project (docs/VALIDACION.md):
    - contrast_db: p95 - p10 of the 50 ms RMS. A real fireplace is ~25-30 dB; a bed at
      7 dB read as "falling water", the fixed one reached 21 dB.
    - crackle_ratio: p99 / median of 50 ms energy (transient-rich textures >= 4).
    - tonal_peak: most prominent spectral line vs its local median (+-470 Hz), as a
      magnitude ratio. On noise-like ambiences a high value is a hum (generated fire
      audio: 117-230 Hz); > 3x notch it, > 6x reject. Meaningless on tonal music."""
    e = np.maximum(np.asarray(st.f50_energy), 1e-20)
    if len(e) < 20:
        return {}
    db = 10 * np.log10(e)
    mag = np.sqrt(st.psd)
    half = max(1, int(round(470 / (freqs[1] - freqs[0]))))
    local = ndimage.median_filter(mag, size=2 * half + 1, mode="nearest")
    rel = np.where(local > 0, mag / np.maximum(local, 1e-20), 0.0)
    band = (freqs >= 100) & (freqs <= 16000)
    k = int(np.argmax(np.where(band, rel, 0.0)))
    return {"contrast_db": float(round(np.percentile(db, 95) - np.percentile(db, 10), 1)),
            "crackle_ratio": float(round(np.percentile(e, 99) / np.median(e), 1)),
            "tonal_peak_hz": float(round(freqs[k], 1)),
            "tonal_prominence": float(round(rel[k], 1))}


def analyze(path: str, section_seconds: float | None = None,
            section_labels: list[str] | None = None, block_seconds: float = 1.0) -> dict:
    """Loudness, peaks, spectrum balance and stereo image of an audio file.
    Streams the file in blocks, so memory stays small for any length."""
    with open(resolve_live_path(path), "rb") as f, sf.SoundFile(f) as snd:
        sr, ch, subtype, frames = snd.samplerate, snd.channels, snd.subtype, snd.frames
        st = _Stream(sr, ch)
        for blk in snd.blocks(blocksize=int(block_seconds * sr), dtype="float32", always_2d=True):
            st.feed(blk)
    freqs = np.fft.rfftfreq(st.nfft, 1 / sr)
    total = st.psd[(freqs >= 20) & (freqs <= 20000)].sum()
    bands = {name: _db(np.sqrt(st.psd[(freqs >= lo) & (freqs < hi)].sum() / total))
             for name, lo, hi in BANDS} if total > 0 else {}
    rms = np.sqrt(st.sumsq / (st.n * ch))
    result = {
        "file": os.path.basename(path),
        "format": "%d Hz, %s, %d ch, %.2f s" % (sr, subtype, ch, frames / sr),
        "integrated_lufs": st.lufs(),
        "peak_dbfs": _db(st.peak),
        "true_peak_dbtp": _db(st.true_peak),
        "rms_dbfs": _db(rms),
        "crest_db": float(round(_db(st.peak) - _db(rms), 2)),
        "clipped_samples": st.clipped,
        "silent": st.peak == 0.0,
        "band_balance_db": bands,
        "texture": _texture(st, freqs) if st.peak > 0 else {},
    }
    if ch == 2:
        result["stereo_correlation"] = st.corr_of(st.corr, st.n)
        result["low_end_correlation_150hz"] = st.corr_of(st.low_corr, st.n)
    if section_seconds:
        per = section_seconds / 0.1
        sections = []
        for i in range(int(np.ceil(len(st.bin_energy) / per))):
            a, b = int(round(i * per)), int(round((i + 1) * per))
            if min(b, len(st.bin_energy)) - a < 10:  # skip tails shorter than 1 s
                continue
            label = section_labels[i] if section_labels and i < len(section_labels) else str(i + 1)
            sections.append({"section": label, "from_s": round(a * 0.1, 1),
                             "lufs": st.lufs(a, b), "peak_dbfs": _db(max(st.bin_peak[a:b]))})
        result["sections"] = sections
    return result


def trim_copy(source: str, dest: str, head_seconds: float, length_seconds: float) -> None:
    """Copy `source` to `dest` keeping `length_seconds` from `head_seconds` on, in the
    same sample format. Streams in blocks; files are opened through Python because
    libsndfile can't open non-ASCII paths on Windows."""
    with open(source, "rb") as fin, sf.SoundFile(fin) as snd:
        sr = snd.samplerate
        remaining = int(round(length_seconds * sr))
        snd.seek(min(int(round(head_seconds * sr)), snd.frames))
        with open(dest, "wb") as fout, sf.SoundFile(fout, "w", sr, snd.channels, snd.subtype,
                                                     format="WAV") as out:
            while remaining > 0:
                blk = snd.read(min(remaining, sr * 5), dtype="float64", always_2d=True)
                if not len(blk):
                    break
                out.write(blk)
                remaining -= len(blk)


class Renderer:
    """Records the master (or one stem per track) in real time, one job at a time,
    in a background thread. See docs/ARQUITECTURA.md for the full sequence."""

    def __init__(self, live):
        self.live = live
        self.state = {"status": "idle"}
        self._thread = None

    def start(self, start_bar, end_bar, tail_bars, output_dir, filename, section_bars,
              stems=None):
        if self._thread and self._thread.is_alive():
            raise RuntimeError("A render is already running")
        live = self.live
        info = live.send("get_session_info")
        if not info.get("file_path"):
            raise RuntimeError("Save the Live set once (Ctrl+S) before rendering")
        tempo = info["tempo"]
        start = (start_bar - 1) * 4.0
        if end_bar:
            end = (end_bar - 1) * 4.0
        else:
            ends = [c["end"] for t in info["tracks"]
                    for c in live.send("get_arrangement_clips", track_index=t["index"])]
            if not ends:
                raise RuntimeError("The Arrangement is empty; place clips first")
            end = max(ends)
        seconds = (end - start + tail_bars * 4.0) * 60.0 / tempo
        base = filename or "%s %s" % (
            os.path.splitext(os.path.basename(resolve_live_path(info["file_path"])))[0],
            datetime.now().strftime("%Y-%m-%d %H%M"))
        base = base[:-4] if base.lower().endswith(".wav") else base
        out_dir = output_dir or os.path.join(os.path.expanduser("~"), "Desktop")

        if stems is None:
            jobs = [{"name": "Render", "input": "Resampling", "channel": None,
                     "dest": os.path.join(out_dir, base + ".wav")}]
        else:
            names = [t["name"] for t in info["tracks"]] + [t["name"] for t in info["return_tracks"]]
            wanted = names if stems == ["all"] else stems
            missing = [n for n in wanted if n not in names]
            if missing:
                raise RuntimeError("Unknown tracks %s; available: %s" % (missing, names))
            folder = os.path.join(out_dir, base + " - stems")
            jobs = [{"name": "Stem %s" % n, "input": n, "channel": "Post Mixer",
                     "dest": os.path.join(folder, "%02d %s.wav" % (i + 1, n))}
                    for i, n in enumerate(wanted)]
        self.state = {"status": "recording", "seconds": round(seconds, 1), "started": time.time(),
                      "destination": jobs[0]["dest"] if stems is None else os.path.dirname(jobs[0]["dest"])}
        section_seconds = section_bars * 4 * 60.0 / tempo if section_bars else None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        args=(info, start, seconds, jobs, section_seconds))
        self._thread.start()
        return dict(self.state, bars="%s-%s (+%d tail)" % (start_bar, end / 4 + 1, tail_bars),
                    sources=[j["input"] for j in jobs])

    def _run(self, info, start, seconds, jobs, section_seconds):
        live = self.live
        created = []  # record-track indexes, in creation order
        armed = [t["index"] for t in info["tracks"] if t.get("arm")]
        flags = {t["index"]: (t["solo"], t["mute"]) for t in info["tracks"]}
        soloed = [t["name"] for t in info["tracks"] if t["solo"]]  # reported: renders obey solo
        try:
            for i in armed:
                live.send("set_track", track_index=i, arm=False)
            for job in jobs:
                idx = live.send("create_track", type="audio", name=job["name"])["index"]
                created.append(idx)
                live.send("set_routing", track_index=idx, input_type=job["input"],
                          input_channel=job["channel"])
                live.send("set_track", track_index=idx, monitoring="off", arm=True)
            live.send("transport", action="stop")
            live.send("transport", action="back_to_arranger")
            old_start = info.get("start_time", 0.0)
            live.send("set_song_options", loop=False, start_time=start, record_mode=True)
            live.send("transport", action="play")
            time.sleep(seconds + 0.3)
            live.send("transport", action="stop")
            live.send("set_song_options", record_mode=False, start_time=old_start)
            for job, idx in zip(jobs, created):
                clips = live.send("get_arrangement_clips", track_index=idx)
                if not clips:
                    raise RuntimeError("Nothing was recorded on %s" % job["name"])
                job["recorded"] = clips[-1]["file_path"]
                # Live records a latency pre-roll hidden behind the clip's start
                # marker; cut it so every file starts exactly on the downbeat.
                job["head"] = clips[-1].get("start_marker_seconds", 0.0)
            for idx in sorted(created, reverse=True):
                live.send("delete_track", track_index=idx)
            created = []
            for i in armed:  # restore before saving so the saved set is clean
                live.send("set_track", track_index=i, arm=True)
            armed = []
            self.state["status"] = "saving"
            live.send("select_track", track_index=0, kind="master")  # a stray 'S' is harmless here
            try:
                save_live_set()
            except RuntimeError as e:
                self.state.update({"status": "waiting_for_save", "reason": str(e),
                                   "action": "Press Ctrl+S in Live to finish the render"})
            for t in live.send("get_session_info")["tracks"]:
                before = flags.get(t["index"])
                if before and (t["solo"], t["mute"]) != before:
                    live.send("set_track", track_index=t["index"], solo=before[0], mute=before[1])
                    self.state.setdefault("warnings", []).append(
                        "restored solo/mute on %s after saving" % t["name"])
            results = []
            for job in jobs:
                source = resolve_live_path(job["recorded"])
                wait = 900 if self.state.get("status") == "waiting_for_save" else 20
                deadline = time.time() + wait
                while not _readable(source):
                    if time.time() > deadline:
                        raise RuntimeError("Live still holds the recording; save the set (Ctrl+S)")
                    time.sleep(0.5)
                os.makedirs(os.path.dirname(job["dest"]), exist_ok=True)
                trim_copy(source, job["dest"], job["head"], seconds)
                results.append(job["dest"])
            if len(jobs) == 1 and jobs[0]["input"] == "Resampling":
                self.state = {"status": "done", "file": results[0], "soloed": soloed,
                              "warnings": self.state.get("warnings", []),
                              "analysis": analyze(results[0], section_seconds)}
            else:
                summary = []
                for path in results:
                    a = analyze(path)
                    summary.append({"file": os.path.basename(path), "lufs": a["integrated_lufs"],
                                    "peak_dbfs": a["peak_dbfs"], "true_peak_dbtp": a["true_peak_dbtp"]})
                self.state = {"status": "done", "folder": os.path.dirname(results[0]),
                              "soloed": soloed, "warnings": self.state.get("warnings", []),
                              "stems": summary}
        except Exception as e:
            self.state = {"status": "error", "error": "%s: %s" % (type(e).__name__, e)}
            try:
                live.send("transport", action="stop")
                live.send("set_song_options", record_mode=False)
                for idx in sorted(created, reverse=True):
                    live.send("delete_track", track_index=idx)
            except Exception:
                pass
        finally:
            for i in armed:
                try:
                    live.send("set_track", track_index=i, arm=True)
                except Exception:
                    pass

    def wait(self, timeout):
        if self._thread:
            self._thread.join(timeout)
        return self.status()

    def status(self):
        s = dict(self.state)
        if s.get("status") == "recording":
            s["elapsed"] = round(time.time() - s["started"], 1)
        return s
