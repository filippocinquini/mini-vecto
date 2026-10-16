"""
dashboard.py - local web dashboard for mini-VECTO: explains the model step by step, runs it in the background
and shows the results.

    python3 dashboard.py            -> opens http://127.0.0.1:8765 in your browser (Ctrl+C to stop)
    python3 dashboard.py --no-browser

Only the Python standard library is used. The server listens on this computer only (127.0.0.1) and can do
just three things: send the page, send the latest results, and launch run_all.py.

  GET  /              dashboard.html
  GET  /api/data      latest results (summaries, masses, friction braking, mission profiles), built from the files
  GET  /api/status    state of a run in progress (step, log)
  POST /api/run       start run_all.py in the background ({"keep_cycles": true} skips missions.py)
  GET  /files/...     Excel workbooks in results/ and the fig_*.png figures (nothing else is served)
"""
import csv, json, os, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
MISSIONS = ["timber_empty", "timber_loaded", "urban_bus", "coach"]
LHV_H2_KWH = 120 / 3.6
STATE = {"running": False, "step": 0, "steps": 0, "label": "", "log": [], "started": None, "finished": None, "returncode": None}
LOCK = threading.Lock()


# ------------------------------------------------------------------ results
def _json(name):
    p = os.path.join(HERE, name)
    return json.load(open(p)) if os.path.exists(p) else None


def _rows(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return list(csv.DictReader(f))


def _sum(rows, key):
    return round(sum(float(r[key]) for r in rows if r.get(key) not in (None, "")), 3)


def _profile(tag):
    """Mission profile: every 100 m for the whole route, every 10 m for the first 3 km (zoom), stop positions."""
    rows = _rows(f"cycle_{tag}_distance.csv")
    if not rows:
        return None
    f = lambda r, k: float(r[k])
    full = rows[::10]
    zoom = [r for r in rows if f(r, "s_m") <= 3000]
    return {"s_km": [round(f(r, "s_m") / 1000, 2) for r in full],
            "v": [f(r, "v_sim_kmh") for r in full],
            "vlim": [f(r, "v_target_kmh") for r in full],
            "z": [f(r, "altitude_m") for r in full],
            "zoom_s_km": [round(f(r, "s_m") / 1000, 3) for r in zoom],
            "zoom_v": [f(r, "v_sim_kmh") for r in zoom],
            "zoom_vlim": [f(r, "v_target_kmh") for r in zoom],
            "stops_km": [round(f(r, "s_m") / 1000, 2) for r in rows if f(r, "stop_dwell_s") > 0],
            "curves": sum(1 for i, r in enumerate(rows) if f(r, "curve_radius_m") > 0 and (i == 0 or f(rows[i-1], "curve_radius_m") == 0))}


def build_data():
    ice, el, ms = _json("consumption_summary.json"), _json("consumption_summary_electric.json"), _json("mission_summary.json")
    cfg = _json("vehicles.json")
    if not (ice and el and cfg):
        return {"ok": False, "message": "No results yet: press Run."}
    ice = {r["mission"]: r for r in ice}
    el = {(r["powertrain"], r["mission"]): r for r in el}
    out = []
    for tag in MISSIONS:
        if tag not in ice:
            continue
        d, b, f = ice[tag], el[("bev", tag)], el[("fcev", tag)]
        mc = cfg["missions"][tag]
        fr = {pt: _sum(_rows(name), "E_friction_brake_kWh") for pt, name in
              (("diesel", f"consumption_{tag}.csv"), ("h2ice", f"consumption_h2ice_{tag}.csv"),
               ("fcev", f"consumption_fcev_{tag}.csv"), ("bev", f"consumption_bev_{tag}.csv"))}
        h2mid = (f["h2_kg_per_100km_BOL"] + f["h2_kg_per_100km_EOL"]) / 2
        pts = [
            {"key": "diesel", "name": "Diesel", "kwh_km": d["fuel_energy_kWh_per_km"], "value": d["diesel_l_per_100km"], "unit": "l/100 km",
             "mass": d["mass_kg"], "extra": d["extra_mass_kg"], "payload_t": d["timber_t_per_round_trip"], "deficit": d["infeasible_steps"], "friction_kWh": fr["diesel"]},
            {"key": "hvo100", "name": "HVO100", "kwh_km": d["fuel_energy_kWh_per_km"], "value": d["hvo100_l_per_100km"], "unit": "l/100 km",
             "mass": d["mass_kg"], "extra": d["extra_mass_kg"], "payload_t": d["timber_t_per_round_trip"], "deficit": d["infeasible_steps"], "friction_kWh": fr["diesel"]},
            {"key": "h2ice", "name": "H2-ICE", "kwh_km": d["h2ice_fuel_energy_kWh_per_km"], "value": d["h2ice_h2_kg_per_100km"], "unit": "kg H₂/100 km",
             "mass": d["h2ice_mass_kg"], "extra": d["h2ice_extra_mass_kg"], "payload_t": d["h2ice_timber_t_per_round_trip"], "deficit": None, "friction_kWh": fr["h2ice"]},
            {"key": "fcev", "name": "FCEV", "kwh_km": round(h2mid / 100 * LHV_H2_KWH, 3), "value": round(h2mid, 2), "unit": "kg H₂/100 km (mid-life)",
             "range": [f["h2_kg_per_100km_BOL"], f["h2_kg_per_100km_EOL"]],
             "mass": f["mass_kg"], "extra": f["extra_mass_kg"], "payload_t": f["timber_t_per_round_trip"], "deficit": f["power_deficit_steps"], "friction_kWh": fr["fcev"],
             "regen_pct": f["regen_share_of_braking_pct"]},
            {"key": "bev", "name": "BEV", "kwh_km": b["battery_kWh_per_km"], "value": round(b["battery_kWh_per_km"] * 100, 1), "unit": "kWh/100 km (battery)",
             "grid_kwh_km": b["grid_kWh_per_km"], "mass": b["mass_kg"], "extra": b["extra_mass_kg"], "payload_t": b["timber_t_per_round_trip"],
             "deficit": b["power_deficit_steps"], "friction_kWh": fr["bev"], "regen_pct": b["regen_share_of_braking_pct"]},
        ]
        s = (ms or {}).get(tag, {})
        out.append({"tag": tag, "title": s.get("title", tag), "km": d["km"], "time_min": d["time_min"],
                    "avg_kmh": s.get("avg_speed_kmh"), "stops": s.get("stops_with_dwell"), "climb_m": s.get("total_climb_m"),
                    "n_pax": mc.get("n_pax"), "braking_kWh": round(b["wheel_braking_kWh_per_km"] * d["km"], 1),
                    "powertrains": pts, "profile": _profile(tag)})
    files = sorted(f for f in os.listdir(os.path.join(HERE, "results")) if f.endswith(".xlsx") and not f.startswith("~$")) if os.path.isdir(os.path.join(HERE, "results")) else []
    figs = sorted(f for f in os.listdir(HERE) if f.startswith("fig_") and f.endswith(".png"))
    stamp = os.path.getmtime(os.path.join(HERE, "consumption_summary.json"))
    return {"ok": True, "updated": time.strftime("%d %b %Y, %H:%M", time.localtime(stamp)),
            "engine_map": next(iter(ice.values())).get("engine_map"), "missions": out, "excel": files, "figures": figs}


# ------------------------------------------------------------------ background run
def _run(keep_cycles):
    cmd = [sys.executable, "-u", os.path.join(HERE, "run_all.py")] + (["--keep-cycles"] if keep_cycles else [])
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    for line in p.stdout:
        line = line.rstrip()
        with LOCK:
            STATE["log"] = (STATE["log"] + [line])[-60:]
            if line.startswith("[") and "/" in line.split("]")[0]:       # "[2/5] powertrain.py ..."
                a, n = line[1:].split("]")[0].split("/")
                STATE.update(step=int(a), steps=int(n), label=line.split("]", 1)[1].strip(" ."))
    p.wait()
    with LOCK:
        STATE.update(running=False, finished=time.time(), returncode=p.returncode)


def start_run(keep_cycles):
    with LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, step=0, steps=4 if keep_cycles else 5, label="starting", log=[],
                     started=time.time(), finished=None, returncode=None)
    threading.Thread(target=_run, args=(keep_cycles,), daemon=True).start()
    return True


# ------------------------------------------------------------------ web server
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/dashboard.html"):
            return self._send(200, open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
        if path == "/api/data":
            return self._send(200, json.dumps(build_data()), "application/json")
        if path == "/api/status":
            with LOCK:
                return self._send(200, json.dumps(STATE), "application/json")
        if path.startswith("/files/"):
            name = os.path.basename(path[len("/files/"):])           # no sub-folders, no ".."
            if name.endswith(".xlsx"):
                p = os.path.join(HERE, "results", name)
                ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif name.startswith("fig_") and name.endswith(".png"):
                p, ctype = os.path.join(HERE, name), "image/png"
            else:
                return self._send(404, "not found", "text/plain")
            if os.path.exists(p):
                return self._send(200, open(p, "rb").read(), ctype)
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path == "/api/run":
            n = int(self.headers.get("Content-Length") or 0)
            opts = json.loads(self.rfile.read(n) or b"{}")
            ok = start_run(bool(opts.get("keep_cycles")))
            return self._send(200 if ok else 409, json.dumps({"started": ok}), "application/json")
        return self._send(404, "not found", "text/plain")

    def log_message(self, *args):                                      # keep the terminal quiet
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"mini-VECTO dashboard on {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
