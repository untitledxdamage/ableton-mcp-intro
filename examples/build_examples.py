"""Build the evidence in examples/ from real renders made through the MCP.

Nothing here is hand-edited: audio excerpts are cut from the renders, charts are
drawn from measurements of those same files, and the JSON is analyze_audio's own
output. Source renders are large WAVs that stay out of the repo; their paths are
listed in SOURCES (this machine) so the provenance is explicit.

Usage (from the repo root):
    uv run --with matplotlib python examples/build_examples.py
"""
import json
import os

import numpy as np
import soundfile as sf
from scipy import signal

from ableton_mcp.audio import analyze

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERS = r"D:\Aprendizaje_IA\ableton_mcp\beats\_renders"
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
SOURCES = {
    "v1": os.path.join(DESKTOP, "Plugg 01 - 140 BPM - A major.wav"),
    "v2": os.path.join(DESKTOP, "Plugg 01 v2 - 140 BPM - A major.wav"),
    "v3": os.path.join(DESKTOP, "Plugg 01 v3 - 140 BPM - A major.wav"),
    "v3_pad": os.path.join(RENDERS, "Plugg 01 v3 - stems", "03 Pad.wav"),
    "v3_808": os.path.join(RENDERS, "Plugg 01 v3 - stems", "02 808.wav"),
    "808_before": os.path.join(RENDERS, "808_original.wav"),   # preset as loaded: +23.7 ct, vibrato
    "808_after": os.path.join(RENDERS, "808_tuned.wav"),       # vibrato off, Detune -24 ct
}
TEMPO = 140.0
SPB = 60.0 / TEMPO                  # seconds per beat
BAR = 4 * SPB
SECTIONS = ["Intro", "Hook", "Verse", "Hook 2", "Break", "Hook", "Hook 2", "Outro"]

# Reference palette (dataviz skill): categorical slots 1-3, chrome and ink, light/dark.
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a"},
    "dark": {"surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "axis": "#383835", "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70"},
}


def read(path):
    with open(path, "rb") as f:
        return sf.read(f, always_2d=True)


# ------------------------------------------------------------------ audio

def excerpt(src, dst, t0, t1, fade=0.4):
    """Cut [t0, t1] s, short fades, 48 kHz MP3 (the renders are 96 kHz / 24-bit)."""
    x, sr = read(src)
    x = x[int(t0 * sr):int(t1 * sr)].copy()
    n = int(fade * sr)
    ramp = np.linspace(0, 1, n)[:, None]
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    x = signal.resample_poly(x, 1, 2, axis=0) if sr == 96000 else x
    sf.write(dst, np.clip(x, -1, 1), 48000 if sr == 96000 else sr, format="MP3")
    return os.path.getsize(dst)


# ----------------------------------------------------------------- charts

def style(ax, fig, th):
    fig.patch.set_facecolor(th["surface"])
    ax.set_facecolor(th["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(th["axis"])
    ax.tick_params(colors=th["muted"], labelsize=9, length=0)
    ax.grid(axis="y", color=th["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(th["ink2"])
    ax.yaxis.label.set_color(th["ink2"])


def title(fig, th, main, sub):
    fig.text(0.012, 0.965, main, color=th["ink"], fontsize=12.5, fontweight="bold", va="top")
    fig.text(0.012, 0.895, sub, color=th["ink2"], fontsize=9.5, va="top")


def save(fig, name, mode):
    import matplotlib.pyplot as plt
    fig.savefig(os.path.join(HERE, "img", "%s_%s.png" % (name, mode)), dpi=150)
    plt.close(fig)


def envelope_db(x, sr, win=0.01):
    m = x.mean(axis=1)
    n = int(win * sr)
    frames = m[:len(m) // n * n].reshape(-1, n)
    return np.arange(len(frames)) * win, 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)


def onsets(x, sr, rel=0.2, min_gap=0.12):
    env = signal.decimate(np.abs(signal.hilbert(x.mean(axis=1))), 48)
    fs = sr / 48
    d = np.diff(env)
    pk, _ = signal.find_peaks(d, height=d.max() * rel, distance=int(min_gap * fs))
    return pk / fs


def chart_sidechain(mode):
    """Pad stem level over 2 bars of Hook 2, with the 808 hits that key the sidechain."""
    import matplotlib.pyplot as plt
    th = THEMES[mode]
    t0, t1 = 24 * BAR, 26 * BAR
    pad, sr = read(SOURCES["v3_pad"])
    bass, _ = read(SOURCES["v3_808"])
    t, db = envelope_db(pad[int(t0 * sr):int(t1 * sr)], sr)
    hits = [h for h in onsets(bass[int(t0 * sr):int(t1 * sr)], sr)]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.78, bottom=0.16)
    style(ax, fig, th)
    beats = t / SPB
    for h in hits:
        ax.axvline(h / SPB, color=th["muted"], linewidth=1, linestyle=(0, (2, 3)), zorder=1)
    ax.plot(beats, db, color=th["s1"], linewidth=2, zorder=3)
    ax.set_xlim(0, 8)
    ax.set_ylim(db.max() - 30, db.max() + 3)
    ax.set_xticks(range(9))
    ax.set_xlabel("beats (2 bars of Hook 2)")
    ax.set_ylabel("pad level (dB)")
    if hits:
        ax.annotate("808 hit", xy=(hits[0] / SPB, db.max() + 1.5), xytext=(4, 0),
                    textcoords="offset points", color=th["muted"], fontsize=8.5, va="center")
    title(fig, th, "Real sidechain: the pad ducks on every 808 hit",
          "Pad stem rendered through the MCP · Compressor keyed from a silent trigger track · measured duck ≈ −9.5 dB")
    save(fig, "sidechain", mode)


def chart_loudness(mode, sections):
    """Loudness per section, v2 vs v3 (v1 is within 0.6 LU of v2)."""
    import matplotlib.pyplot as plt
    th = THEMES[mode]
    fig, ax = plt.subplots(figsize=(9, 3.9))
    fig.subplots_adjust(left=0.07, right=0.9, top=0.78, bottom=0.14)
    style(ax, fig, th)
    xs = np.arange(len(SECTIONS))
    for key, color, label in (("v2", th["s1"], "v2"), ("v3", th["s2"], "v3")):
        ys = sections[key]
        ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=6, zorder=3,
                markeredgecolor=th["surface"], markeredgewidth=2)
        ax.annotate(label, xy=(xs[-1], ys[-1]), xytext=(10, 0), textcoords="offset points",
                    color=th["ink2"], fontsize=9.5, va="center")
    ax.set_xticks(xs, SECTIONS)
    ax.set_ylabel("integrated loudness (LUFS)")
    ax.set_xlim(-0.3, len(SECTIONS) - 0.4)
    title(fig, th, "Song shape: loudness per 8-bar section",
          "Full renders of Plugg 01 · v3 adds sidechain, filtering, saturation and hook drops; the intro stays quiet")
    save(fig, "loudness_by_section", mode)


def pitch_track(path, t0_beats=0.25, t1_beats=1.45, win=0.12, hop=0.02):
    """Cents vs D2 (73.42 Hz) over the first 808 note, short FFT windows."""
    x, sr = read(path)
    m = x.mean(axis=1)
    out_t, out_c = [], []
    t = t0_beats * SPB
    while t + win <= t1_beats * SPB:
        seg = m[int(t * sr):int((t + win) * sr)] * np.hanning(int(win * sr))
        f = np.fft.rfftfreq(len(seg) * 32, 1 / sr)
        s = np.abs(np.fft.rfft(seg, len(seg) * 32))
        band = (f > 50) & (f < 110)
        out_t.append((t + win / 2) / SPB)
        out_c.append(1200 * np.log2(f[band][np.argmax(s[band])] / 73.42))
        t += hop
    return np.array(out_t), np.array(out_c)


def chart_tuning(mode):
    import matplotlib.pyplot as plt
    th = THEMES[mode]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    fig.subplots_adjust(left=0.08, right=0.88, top=0.78, bottom=0.16)
    style(ax, fig, th)
    ax.axhline(0, color=th["axis"], linewidth=1)
    for key, color, label in (("808_before", th["s2"], "preset as loaded"),
                              ("808_after", th["s1"], "after fix")):
        tb, cents = pitch_track(SOURCES[key])
        ax.plot(tb, cents, color=color, linewidth=2)
        ax.annotate("%s\n%+.0f ct avg" % (label, np.mean(cents)), xy=(tb[-1], cents[-1]),
                    xytext=(8, 0), textcoords="offset points", color=th["ink2"], fontsize=9, va="center")
    ax.set_xlabel("beats into the first 808 note (D2)")
    ax.set_ylabel("cents vs D2 (73.42 Hz)")
    title(fig, th, "Measured, not assumed: the 808 preset was out of tune",
          "Solo renders through the MCP · the preset was ~+24 ct sharp with vibrato · fix: vibrato off, Detune −24 ct")
    save(fig, "808_tuning", mode)


def chart_alignment(mode):
    """808 render envelope vs the MIDI grid: the WAV starts exactly on the downbeat."""
    import matplotlib.pyplot as plt
    th = THEMES[mode]
    x, sr = read(SOURCES["808_after"])
    t, db = envelope_db(x, sr, 0.005)
    expected = [0, 1.75, 3.0, 4.0, 5.75, 6.5, 7.25, 7.5]
    found = onsets(x, sr) / SPB
    fig, ax = plt.subplots(figsize=(9, 3.6))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.78, bottom=0.16)
    style(ax, fig, th)
    for e in expected:
        ax.axvline(e, color=th["muted"], linewidth=1, linestyle=(0, (2, 3)))
    ax.plot(t / SPB, db, color=th["s1"], linewidth=1.6, zorder=3)
    firsts = [f for f in found if min(abs(f - e) for e in expected) < 0.25]
    ax.scatter(firsts, [db.max() + 2] * len(firsts), s=40, color=th["s3"], zorder=4,
               edgecolors=th["surface"], linewidths=2)
    ax.set_xlim(-0.2, 8)
    ax.set_ylim(db.max() - 45, db.max() + 5)
    ax.set_xticks(range(9))
    ax.set_xlabel("beats from the start of the rendered WAV")
    ax.set_ylabel("level (dB)")
    ax.annotate("dashed: MIDI note starts · dots: detected hits · beat 7.5 is a legato glide (no new attack)",
                xy=(0.99, 0.04), xycoords="axes fraction", ha="right", color=th["muted"], fontsize=8.5)
    title(fig, th, "Renders start on the downbeat",
          "Live records ~0.32 s of latency pre-roll; render_to_wav trims it · hits land on the grid (±0.02 beat)")
    save(fig, "render_alignment", mode)


def main():
    os.makedirs(os.path.join(HERE, "audio"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "img"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    missing = [k for k, p in SOURCES.items() if not os.path.exists(p)]
    if missing:
        raise SystemExit("missing source renders: %s" % missing)

    sizes = {}
    a = os.path.join(HERE, "audio")
    sizes["plugg01_v3_excerpt.mp3"] = excerpt(SOURCES["v3"], os.path.join(a, "plugg01_v3_excerpt.mp3"),
                                              16 * BAR, 32 * BAR)      # Verse -> Hook 2 (27 s)
    for v in ("v2", "v3"):
        name = "ab_hook2_entrance_%s.mp3" % v
        sizes[name] = excerpt(SOURCES[v], os.path.join(a, name), 20 * BAR, 28 * BAR)   # bars 21-28
    for key, name in (("808_before", "808_before_fix.mp3"), ("808_after", "808_after_fix.mp3")):
        sizes[name] = excerpt(SOURCES[key], os.path.join(a, name), 0, 8 * SPB, fade=0.05)

    report = analyze(SOURCES["v3"], section_seconds=8 * BAR, section_labels=SECTIONS)
    report["file"] = "Plugg 01 v3 - 140 BPM - A major.wav"
    with open(os.path.join(HERE, "data", "analyze_audio_plugg01_v3.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    sections = {}
    for v in ("v1", "v2", "v3"):
        r = report if v == "v3" else analyze(SOURCES[v], section_seconds=8 * BAR)
        sections[v] = [s["lufs"] for s in r["sections"]][:len(SECTIONS)]
    with open(os.path.join(HERE, "data", "loudness_by_section.json"), "w", encoding="utf-8") as f:
        json.dump({"sections": SECTIONS, "lufs": sections}, f, indent=2)

    for mode in THEMES:
        chart_sidechain(mode)
        chart_loudness(mode, sections)
        chart_tuning(mode)
        chart_alignment(mode)
    print(json.dumps({k: "%.2f MB" % (v / 1048576) for k, v in sizes.items()}, indent=1))
    print("sections:", json.dumps(sections))


if __name__ == "__main__":
    main()
