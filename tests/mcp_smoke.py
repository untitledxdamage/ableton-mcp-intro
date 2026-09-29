"""Smoke test of the MCP server over real stdio JSON-RPC (what Claude sees).
Live must be open with the AbletonMCP_Intro control surface. Read-only: it never
changes the set. Usage: uv run python tests/mcp_smoke.py [path-to-wav]
"""
import json
import subprocess
import sys
import time

CALLS = [
    ("ping", {}),
    ("get_session_info", {}),
    ("get_routing", {"track_index": 0}),
    ("get_rack", {"track_index": 0, "device_index": 0}),
    ("render_status", {}),
]


def main():
    if len(sys.argv) > 1:
        CALLS.append(("analyze_audio", {"path": sys.argv[1], "section_seconds": 30}))
    # Same interpreter, no `uv run`: that would try to re-sync and fail while another
    # client (Claude) keeps the ableton-mcp.exe entry point open.
    proc = subprocess.Popen([sys.executable, "-c", "from ableton_mcp import main; main()"],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8")

    def send(msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def recv(want_id):
        while True:
            msg = json.loads(proc.stdout.readline())
            if msg.get("id") == want_id:
                return msg

    send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                     "clientInfo": {"name": "smoke", "version": "1"}}})
    recv(0)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = recv(1)["result"]["tools"]
    print("%d tools" % len(tools))
    failures = 0
    for i, (name, args) in enumerate(CALLS, start=2):
        t0 = time.time()
        send({"jsonrpc": "2.0", "id": i, "method": "tools/call",
              "params": {"name": name, "arguments": args}})
        res = recv(i)["result"]
        ok = not res.get("isError")
        failures += not ok
        text = res["content"][0]["text"] if res.get("content") else ""
        print("[%s] %-18s %5.2fs  %s" % ("OK " if ok else "ERR", name, time.time() - t0,
                                         text.replace("\n", " ")[:150]))
    proc.terminate()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
