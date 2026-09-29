"""Render stems and the master for the same bars; check the stems sum back to the
master (validates completeness and alignment). Modifies nothing permanently but
saves the set (renders always do). Usage: uv run python tests/stems_check.py OUTDIR [start end]"""
import os
import shutil
import sys

import numpy as np
import soundfile as sf

from ableton_mcp import renderer

out = sys.argv[1]
a, b = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (25, 27)
shutil.rmtree(os.path.join(out, "check - stems"), ignore_errors=True)
renderer.start(a, b, 0, out, "check", None, stems=["all"])
r = renderer.wait(300)
print(r["status"], r.get("error", ""), "soloed:", r.get("soloed"), "warnings:", r.get("warnings"))
for s in r.get("stems", []):
    print("   ", s)
renderer.start(a, b, 0, out, "check_master", None)
m = renderer.wait(300)
print("master:", m["status"], m.get("warnings"))
folder = r["folder"]
stems = [sf.read(os.path.join(folder, f))[0] for f in sorted(os.listdir(folder)) if f.endswith(".wav")]
S = sum(stems)
M, sr = sf.read(os.path.join(out, "check_master.wav"))
n = min(len(S), len(M))
S, M = S[:n], M[:n]
rms = lambda x: 20 * np.log10(np.sqrt((x ** 2).mean()))
print("corr(sum of stems, master) = %.4f | rms stems %.2f dB, master %.2f dB"
      % (np.corrcoef(S.mean(1), M.mean(1))[0, 1], rms(S), rms(M)))
