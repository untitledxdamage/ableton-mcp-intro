"""End-to-end check of the AbletonMCP_Intro Remote Script, straight over the socket.
Run with Live open and the AbletonMCP_Intro control surface active:
    uv run python test_bridge.py
It builds a small test set (track 'MCP Test'), then undoes nothing: delete the
track afterwards or run with --cleanup.
"""
import json
import socket
import sys

sock = socket.create_connection(("127.0.0.1", 9880), timeout=30)
buf = b""


def call(cmd, **params):
    global buf
    sock.sendall((json.dumps({"id": 1, "cmd": cmd, "params": params}) + "\n").encode())
    while b"\n" not in buf:
        buf += sock.recv(65536)
    line, buf = buf.split(b"\n", 1)
    return json.loads(line)


def check(label, cmd, **params):
    r = call(cmd, **params)
    status = "OK " if r["ok"] else "ERR"
    body = r.get("result") if r["ok"] else r.get("error")
    text = json.dumps(body, ensure_ascii=False)
    print("[%s] %-28s %s" % (status, label, text[:220]))
    return body if r["ok"] else None


check("ping", "ping")
info = check("session info", "get_session_info")
n_tracks = len(info["tracks"])

t = check("create midi track", "create_track", type="midi", name="MCP Test")["index"]
check("load Drift", "load_device", track_index=t, query="Drift", category="instruments")
check("create clip", "create_clip", track_index=t, slot_index=0, length=4, name="Acordes")
chord = [{"pitch": p, "start": 0, "duration": 2, "velocity": 90} for p in (57, 60, 64)]
chord += [{"pitch": p, "start": 2, "duration": 2, "velocity": 85, "probability": 0.8}
          for p in (53, 57, 60)]
check("add notes", "add_notes", track_index=t, slot_index=0, notes=chord)
check("get notes", "get_notes", track_index=t, slot_index=0)
check("load Auto Filter", "load_device", track_index=t, query="Auto Filter",
      category="audio_effects")
ti = check("track info", "get_track_info", track_index=t)
devs = ti["devices"]
filt = next((d["index"] for d in devs if "Filter" in d["name"]), None)
if filt is not None:
    params = check("filter params", "get_device_parameters", track_index=t, device_index=filt)
    names = [p["name"] for p in params["parameters"]]
    print("      params:", ", ".join(names))
    freq = next((n for n in names if n.lower().startswith("frequency")), None)
    if freq:
        check("set filter freq", "set_device_parameters", track_index=t,
              device_index=filt, values={freq: 0.4})
        pts = [{"time": i * 0.25, "value": 0.2 + i * 0.045, "duration": 0.25} for i in range(16)]
        check("clip automation", "set_clip_automation", track_index=t, slot_index=0,
              device_index=filt, parameter=freq, points=pts)
check("quantize", "quantize_clip", track_index=t, slot_index=0, grid="1/16")
check("set track", "set_track", track_index=t, volume=0.75, pan=-0.2, color_index=12)
check("duplicate clip", "duplicate_clip", track_index=t, slot_index=0,
      target_track=t, target_slot=1)
check("search browser", "search_browser", query="Kit", category="drums", max_results=5)
check("browse drums", "browse", path="drums")
check("search Drift", "search_browser", query="Drift", max_results=3)
check("search 808 kit", "search_browser", query="808", category="drums", max_results=3)
# Round-trip global settings and put the user's values back.
old_scene = info["scenes"][0]["name"]
check("scene rename", "set_scene", scene_index=0, name="Test")
check("scene restore", "set_scene", scene_index=0, name=old_scene)
check("tempo", "set_tempo", bpm=96)
check("tempo restore", "set_tempo", bpm=info["tempo"])
check("error path", "get_notes", track_index=t, slot_index=7)
check("inspect song", "inspect", target="song")

if "--cleanup" in sys.argv:
    check("delete test track", "delete_track", track_index=t)
