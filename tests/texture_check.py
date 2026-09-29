"""Print the texture (Foley/ambience) metrics of audio files, to validate them
against known references. Usage: uv run python tests/texture_check.py FILE [FILE ...]"""
import os
import sys
import time

from ableton_mcp.audio import analyze

for path in sys.argv[1:]:
    t = time.time()
    a = analyze(path)
    print("%-30s %s  LUFS %s  (%.1f s)" % (os.path.basename(path)[:30], a["texture"],
                                          a["integrated_lufs"], time.time() - t))
