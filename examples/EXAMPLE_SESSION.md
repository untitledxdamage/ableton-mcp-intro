# Example session: "add sidechain and make it more dynamic"

A real exchange from the sessions behind this repo, condensed. It shows what controlling Live through the MCP looks like, including a mistake the agent caught **by measuring** instead of trusting that the commands ran.

> Condensed from the real session. The steps ran against Live 12.2.7 Intro through this bridge; the tool names below are the MCP tools (the same commands exist on the socket). Values are the ones actually used.

---

**User** (original, in Spanish):
> *"Quiero que apliques técnicas como el sidechain, low end, high end, para darle dinamismo."*
> (I want you to apply techniques like sidechain and low-end/high-end treatment to make it more dynamic.)

**Agent:** reads the set, then checks whether Live's API exposes a real sidechain input (it's not a device parameter).

```text
get_session_info()                       → 6 tracks: Drums, 808, Pad, Arp, Bells, Flute
load_device(track_index=2, path="audio_effects/Compressor")
set_sidechain(track_index=2, device_index=3)           → sources: Drums, 808, Pad, … (it exists)
```

**Plan.** A compressor keyed straight from the 808 would stay ducked through its long notes. Instead the agent uses a **ghost trigger**: a silent track that plays a short rimshot on every 808 note, which keys the compressors.

```text
create_track(type="midi", name="SC Trigger")
load_device(track_index=6, path="drums/808 Core Kit.adg")
set_routing(track_index=6, output_type="Sends Only")          # silent in the mix
get_notes(track_index=1, slot_index=1)                        # read the real 808 notes
create_clip(track_index=6, slot_index=1, length=32)
add_notes(track_index=6, slot_index=1, notes=[{pitch: 37, start: <each 808 onset>, duration: 0.1, velocity: 127}, …])
# on Pad, Arp, Bells, Flute and the reverb return:
set_sidechain(track_index=2, device_index=3, source="SC Trigger", channel="Post FX")
set_device_parameters(track_index=2, device_index=3, values={"S/C On": 1, "Model": "Peak"})
set_parameter_real(track_index=2, device_index=3, parameter="Threshold", target=-24)
set_parameter_real(track_index=2, device_index=3, parameter="Release", target=172)
```

**Verification: the agent can't hear, so it renders stems and measures the duck.**

```text
render_to_wav(start_bar=25, end_bar=33, stems=["Pad", "Bells", "Flute", "808", …])
→ duck measured on each 808 hit:  Pad +1.3 dB · Bells -0.4 dB · Flute -0.4 dB
```

**The mistake, found by measuring.** No ducking at all. The cause: the trigger clips existed only in Session View, but the render plays the **Arrangement**, where the trigger track was empty.

```text
arrangement_place(track_index=6, slot_index=…, time=…)   # for each section with 808
render_to_wav(start_bar=25, end_bar=33, stems=[…])
→ duck:  Pad -9.5 dB · Bells -8.8 dB · Flute -5.5 dB · Reverb -9.3 dB
```

**Low end / high end**, each change checked on the stems:

```text
set_parameter_real(track_index=5, device_index=1, parameter="Frequency", target=180)   # Flute high-pass
→ Flute energy below 100 Hz: -37 dB → -58 dB
set_parameter_real(track_index=4, device_index=0, parameter="LP Freq", target=5000)    # Bells brighter
→ Bells energy above 8 kHz: -48 dB → -28 dB
```

A high-pass on the 808 was tried as well. A clean A/B showed it cost 0.6 dB of fundamental and added 1 dB of peak, for no audible benefit, so it was **removed**.

**Result,** measured on the full render (`render_to_wav` + `analyze_audio`):

| Hook entrance | before | after |
|---|---|---|
| Verse → Hook 2 | −1.5 LU | **+5.0 LU** |
| Break → Hook | +2.9 LU | **+8.5 LU** |
| Hook → Hook 2 | −2.1 LU | **+2.5 LU** |

Master: −9.8 LUFS, −1.0 dBTP, no clipping. Before, two of the three hooks came in *quieter* than the bars leading into them; now every hook lifts.

See the charts and the A/B audio in [README.md](README.md).
