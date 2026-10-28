"""
dashboard.py - local web dashboard for mini-VECTO: explains the model, shows every result interactively
(mission replay, engine and e-motor maps, fuel cell curve, battery state), edits the main inputs and runs the
model in the background.

    python3 dashboard.py            -> opens http://127.0.0.1:8765 in your browser (Ctrl+C to stop)
    python3 dashboard.py --no-browser
    python3 dashboard.py --port 8800

Only the Python standard library is needed for the page itself (the model run needs requirements.txt).
The server listens on this computer only (127.0.0.1).

  GET  /                  dashboard.html
  GET  /api/data          mission results (summaries, masses, friction braking, mission profiles)
  GET  /api/model         component data for the interactive maps: engine map grids (measured and model),
                          full-load curves, e-drive loss model, fuel cell curve, battery and vehicle sizes
  GET  /api/trace?m=tag   step-by-step results of one mission for all powertrains (replay, operating points)
  GET  /api/inputs        main editable inputs of vehicles.json, with their current and original values
  POST /api/inputs        save edited inputs into vehicles.json (the first save keeps vehicles.json.bak)
  POST /api/inputs/restore  put vehicles.json.bak back
  GET  /api/status        state of a run in progress (step, log)
  POST /api/run           start run_all.py ({"keep_cycles": bool, "engine_map": "measured" | "model" | null})
  GET  /files/...         Excel workbooks in results/ and the fig_*.png figures (nothing else is served)
"""
import csv, importlib, json, math, os, shutil, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
MISSIONS = ["timber_empty", "timber_loaded", "urban_bus", "coach"]
LHV_H2_KWH = 120 / 3.6
CFG_PATH = os.path.join(HERE, "vehicles.json")
BAK_PATH = CFG_PATH + ".bak"
STATE = {"running": False, "step": 0, "steps": 0, "label": "", "log": [], "started": None, "finished": None,
         "returncode": None, "options": {}}
LOCK = threading.Lock()
CACHE = {}


# ------------------------------------------------------------------ helpers
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


def _mtime(*names):
    return tuple(os.path.getmtime(os.path.join(HERE, n)) if os.path.exists(os.path.join(HERE, n)) else 0 for n in names)


def cached(key, deps, fn):
    """Recompute fn() only when one of the dependency files changed."""
    stamp = _mtime(*deps)
    if key in CACHE and CACHE[key][0] == stamp:
        return CACHE[key][1]
    val = fn()
    CACHE[key] = (stamp, val)
    return val


# ------------------------------------------------------------------ mission results
def _profile(tag):
    """Mission profile: every 100 m for the whole route, stop positions, number of curves."""
    rows = _rows(f"cycle_{tag}_distance.csv")
    if not rows:
        return None
    f = lambda r, k: float(r[k])
    full = rows[::10]
    return {"s_km": [round(f(r, "s_m") / 1000, 2) for r in full],
            "v": [f(r, "v_sim_kmh") for r in full],
            "vlim": [f(r, "v_target_kmh") for r in full],
            "z": [f(r, "altitude_m") for r in full],
            "stops_km": [round(f(r, "s_m") / 1000, 2) for r in rows if f(r, "stop_dwell_s") > 0],
            "curves": sum(1 for i, r in enumerate(rows) if f(r, "curve_radius_m") > 0 and (i == 0 or f(rows[i-1], "curve_radius_m") == 0))}


def build_data():
    ice, el, ms = _json("consumption_summary.json"), _json("consumption_summary_electric.json"), _json("mission_summary.json")
    cfg = _json("vehicles.json")
    if not (ice and el and cfg):
        return {"ok": False, "message": "No results yet: press Run model."}
    ice = {r["mission"]: r for r in ice}
    el = {(r["powertrain"], r["mission"]): r for r in el}
    out = []
    for tag in MISSIONS:
        if tag not in ice or ("bev", tag) not in el:
            continue
        d, b, f = ice[tag], el[("bev", tag)], el[("fcev", tag)]
        mc = cfg["missions"][tag]
        fr = {pt: _sum(_rows(name), "E_friction_brake_kWh") for pt, name in
              (("diesel", f"consumption_{tag}.csv"), ("h2ice", f"consumption_h2ice_{tag}.csv"),
               ("fcev", f"consumption_fcev_{tag}.csv"), ("bev", f"consumption_bev_{tag}.csv"))}
        h2mid = (f["h2_kg_per_100km_BOL"] + f["h2_kg_per_100km_EOL"]) / 2
        pts = [
            {"key": "diesel", "name": "Diesel", "kwh_km": d["fuel_energy_kWh_per_km"], "value": d["diesel_l_per_100km"], "unit": "l/100 km",
             "mass": d["mass_kg"], "extra": d["extra_mass_kg"], "payload_t": d["timber_t_per_round_trip"], "deficit": d["infeasible_steps"],
             "friction_kWh": fr["diesel"], "eff_pct": d["mean_engine_eff_pct"], "ttw_pct": d["mean_tank_to_wheel_eff_pct"]},
            {"key": "hvo100", "name": "HVO100", "kwh_km": d["fuel_energy_kWh_per_km"], "value": d["hvo100_l_per_100km"], "unit": "l/100 km",
             "mass": d["mass_kg"], "extra": d["extra_mass_kg"], "payload_t": d["timber_t_per_round_trip"], "deficit": d["infeasible_steps"],
             "friction_kWh": fr["diesel"], "eff_pct": d["mean_engine_eff_pct"], "ttw_pct": d["mean_tank_to_wheel_eff_pct"]},
            {"key": "h2ice", "name": "H2-ICE", "kwh_km": d["h2ice_fuel_energy_kWh_per_km"], "value": d["h2ice_h2_kg_per_100km"], "unit": "kg H₂/100 km",
             "pilot_l": d.get("h2ice_pilot_hvo_l_per_100km"), "pilot_pct": d.get("h2ice_pilot_energy_share_pct"),
             "mass": d["h2ice_mass_kg"], "extra": d["h2ice_extra_mass_kg"], "payload_t": d["h2ice_timber_t_per_round_trip"], "deficit": None,
             "friction_kWh": fr["h2ice"], "eff_pct": d["mean_engine_eff_pct"],
             "ttw_pct": round(d["h2ice_wheel_work_kWh_per_km"] / d["h2ice_fuel_energy_kWh_per_km"] * 100, 1)},
            {"key": "fcev", "name": "FCEV", "kwh_km": round(h2mid / 100 * LHV_H2_KWH, 3), "value": round(h2mid, 2), "unit": "kg H₂/100 km (mid-life)",
             "range": [f["h2_kg_per_100km_BOL"], f["h2_kg_per_100km_EOL"]],
             "mass": f["mass_kg"], "extra": f["extra_mass_kg"], "payload_t": f["timber_t_per_round_trip"], "deficit": f["power_deficit_steps"],
             "friction_kWh": fr["fcev"], "regen_pct": f["regen_share_of_braking_pct"],
             "fc_eff_pct": [f["mean_fc_sys_eff_BOL_pct"], f["mean_fc_sys_eff_EOL_pct"]], "fc_load_pct": f["fc_mean_load_pct"],
             "fc_starts": f["fc_starts"], "soc": [f["soc_start"], f["soc_end"]], "drive_eff_pct": f["drive_eff_wheel_over_motor_el_pct"],
             "ttw_pct": round(f["wheel_traction_kWh_per_km"] / (h2mid / 100 * LHV_H2_KWH + f["regen_el_kWh_per_km"]) * 100, 1)},
            {"key": "bev", "name": "BEV", "kwh_km": b["battery_kWh_per_km"], "value": round(b["battery_kWh_per_km"] * 100, 1), "unit": "kWh/100 km (battery)",
             "grid_kwh_km": b["grid_kWh_per_km"], "mass": b["mass_kg"], "extra": b["extra_mass_kg"], "payload_t": b["timber_t_per_round_trip"],
             "deficit": b["power_deficit_steps"], "friction_kWh": fr["bev"], "regen_pct": b["regen_share_of_braking_pct"],
             "soc": [b["soc_start"], b["soc_end"]], "used_pct": b["battery_used_pct_of_installed"], "drive_eff_pct": b["drive_eff_wheel_over_motor_el_pct"],
             "ttw_pct": round(b["wheel_traction_kWh_per_km"] / (b["battery_kWh_per_km"] + b["regen_el_kWh_per_km"]) * 100, 1)},
        ]
        s = (ms or {}).get(tag, {})
        out.append({"tag": tag, "title": s.get("title", tag), "vehicle": mc["vehicle"], "km": d["km"], "time_min": d["time_min"],
                    "avg_kmh": s.get("avg_speed_kmh"), "stops": s.get("stops_with_dwell"), "climb_m": s.get("total_climb_m"),
                    "max_grade": s.get("max_grade_pct"), "standstill_pct": s.get("standstill_share_pct"),
                    "cycle_source": s.get("cycle_source"), "n_pax": mc.get("n_pax"),
                    "braking_kWh": round(b["wheel_braking_kWh_per_km"] * d["km"], 1),
                    "wheel_kwh_km": d["wheel_work_kWh_per_km"], "aux_kwh_km": d["aux_kWh_per_km"],
                    "idle_fuel_pct": d["idle_fuel_share_pct"], "shifts": d["gear_shifts"],
                    "extrap_pct": d.get("fuel_above_measured_torque_pct"),
                    "powertrains": pts, "profile": _profile(tag)})
    rdir = os.path.join(HERE, "results")
    files = sorted(f for f in os.listdir(rdir) if f.endswith((".xlsx", ".csv")) and not f.startswith("~$")) if os.path.isdir(rdir) else []
    figs = sorted(f for f in os.listdir(HERE) if f.startswith("fig_") and f.endswith(".png"))
    stamp = os.path.getmtime(os.path.join(HERE, "consumption_summary.json"))
    return {"ok": True, "updated": time.strftime("%d %b %Y, %H:%M", time.localtime(stamp)),
            "engine_map": next(iter(ice.values())).get("engine_map"), "missions": out, "excel": files, "figures": figs}


# ------------------------------------------------------------------ component data for the interactive maps
def _line_interp(points, col, step=100):
    """Constant-speed lines of the measured map for any column: {n_nom: ([T...], [val...])}."""
    lines = {}
    for p in points:
        n_nom = round(p["n"] / step) * step
        if abs(p["n"] - n_nom) <= 10:
            lines.setdefault(n_nom, []).append((p["T"], p[col]))
    out = {}
    for n, pts in lines.items():
        pts.sort()
        if len(pts) >= 4:
            out[n] = ([q[0] for q in pts], [q[1] for q in pts])
    return out


def build_model():
    import powertrain, electric
    importlib.reload(powertrain)
    importlib.reload(electric)
    cfg = json.load(open(CFG_PATH))
    # --- engine maps on the reference engine (12.8 L); other engines use the same map at equal BMEP (torque x k)
    ns = list(range(600, 1901, 20))
    Ts = list(range(0, 2701, 30))
    fl = [powertrain.fl_torque_ref(n) for n in ns]
    lhv_test = cfg.get("engine_map", {}).get("test_fuel_LHV_MJ_per_kg", 42.7)

    def model_fuel_W(n, T):                                   # semi-empirical map (same as Engine.fuel_power, k = 1)
        vd = powertrain.VD_REF
        bmep = 4 * math.pi * T / vd / 1e5
        imep = bmep + powertrain.fmep(n)
        return imep * 1e5 * vd * n / 120 / (powertrain.ETA_I_SCALE * powertrain.eta_i_shape(n, imep))

    maps = {}
    path = os.path.join(HERE, cfg.get("engine_map", {}).get("file", "data/engine_map_measured.csv"))
    meas = None
    if os.path.exists(path):
        meas = powertrain.MeasuredMap(path, lhv_test)
        raw = [{k: float(v) if v not in ("", None) else float("nan") for k, v in r.items()} for r in csv.DictReader(open(path))]
        pts = [{"n": r["n_rpm"], "T": max(r["T_Nm"], 0.0), "fuel": r["fuel_g_per_s"], "bsfc": r["bsfc_g_per_kWh"],
                "nox": r["nox_engine_out_mg_per_s"]} for r in raw]
        nox_lines = _line_interp(pts, "nox")
        nox_speeds = sorted(nox_lines)

        def nox_at(n, T):                                     # mg/s, linear in T on two speed lines, only inside the data
            if not nox_speeds or n < nox_speeds[0] or n > nox_speeds[-1]:
                return None
            for i in range(1, len(nox_speeds)):
                if n <= nox_speeds[i]:
                    lo, hi = nox_speeds[i-1], nox_speeds[i]; break
            t = (n - lo) / (hi - lo)
            vals = []
            for nn in (lo, hi):
                ts, vs = nox_lines[nn]
                if T < ts[0] - 1 or T > ts[-1] + 1:
                    return None
                vals.append(powertrain.interp(T, ts, vs))
            return (1 - t) * vals[0] + t * vals[1]

    for src in (["measured"] if meas else []) + ["model"]:
        eta, bsfc, nox = [], [], []
        for j, T in enumerate(Ts):
            re, rb, rn = [], [], []
            for i, n in enumerate(ns):
                if T > fl[i] + 1e-6 or T < 30:
                    re.append(None); rb.append(None); rn.append(None); continue
                p_kw = T * 2 * math.pi * n / 60 / 1e3
                if src == "measured":
                    g = meas.fuel_flow(n, T); fw = g * lhv_test * 1e3
                else:
                    fw = model_fuel_W(n, T); g = fw / (lhv_test * 1e3)
                re.append(round(p_kw * 1e3 / fw, 4))
                rb.append(round(g / p_kw * 3600, 1))
                if src == "measured":
                    x = nox_at(n, T)
                    rn.append(round(x / 1000 / p_kw * 3600, 2) if x is not None and p_kw > 0 else None)
            eta.append(re); bsfc.append(rb)
            if src == "measured":
                nox.append(rn)
        m = {"eta": eta, "bsfc": bsfc}
        if src == "measured":
            m["nox"] = nox
            m["points"] = [[round(p["n"]), round(p["T"]), round(p["bsfc"], 1) if math.isfinite(p["bsfc"]) else None] for p in pts]
            m["t_measured_max"] = [round(meas.t_measured_max(n)) for n in ns]
            e, n0, T0 = meas.best_point()
            m["best"] = {"eta": round(e, 4), "n": round(n0), "T": round(T0)}
        else:
            best = max((v, ns[i], Ts[j]) for j, row in enumerate(eta) for i, v in enumerate(row) if v)
            m["best"] = {"eta": best[0], "n": best[1], "T": best[2]}
        maps[src] = m
    engines = {}
    for vname, v in cfg["vehicles"].items():
        e = v["engine"]
        engines[vname] = {"k": e["displacement_l"] / 12.8, "displacement_l": e["displacement_l"], "rated_kW": e["rated_power_kW"],
                          "n_idle": e["n_idle_rpm"], "n_min": e["n_min_drive_rpm"], "n_max": e["n_max_rpm"],
                          "aux_kW": v["aux_mech_kW"], "axle": v["axle_ratio"], "r_tyre": v["tyre_dynamic_radius_m"],
                          "ratios": cfg["gearboxes"][v["gearbox"]]["ratios"]}
    # --- electric drive (per unit of motor peak power) and vehicle sizes
    EL = cfg["electric"]
    any_v = next(iter(EL["vehicles"]))
    drv = electric.EDrive(EL["vehicles"][any_v], cfg["vehicles"][any_v]["eta_axle"])
    ed = EL["edrive"]
    edrive = {"scale": drv.scale, "shape": ed["machine_loss_shape"], "inverter": ed["inverter_loss"], "cpsr": ed["const_power_speed_ratio"],
              "peak_eff": ed["machine_peak_efficiency"], "regen_v_cut_kmh": ed["regen_v_cut_kmh"], "vehicles": {}}
    for vname, ve in EL["vehicles"].items():
        d = electric.EDrive(ve, cfg["vehicles"][vname]["eta_axle"])
        edrive["vehicles"][vname] = {"pmax": ve["motor_peak_kW"], "n_gears": ve["n_gears"], "v_top_kmh": ve["v_top_kmh"],
                                     "v_base_kmh": [round(x * 3.6, 2) for x in d.v_base], "aux_kW": ve["aux_el_kW"],
                                     "bev": {k: ve["bev"][k] for k in ("battery_kWh", "soc_start", "soc_min", "C_discharge", "C_charge", "extra_mass_kg")},
                                     "fcev": {k: ve["fcev"][k] for k in ("fc_net_kW", "battery_kWh", "C_discharge", "C_charge", "extra_mass_kg")}}
    fc = EL["fuel_cell"]
    return {"engine_source": cfg.get("engine_map", {}).get("source", "model"), "ns": ns, "Ts": Ts, "fl_ref": [round(x, 1) for x in fl],
            "maps": maps, "engines": engines, "edrive": edrive,
            "fuel_cell": {"load_frac": fc["load_frac"], "eta_BOL": fc["eta_sys_BOL"], "eta_EOL": fc["eta_sys_EOL"],
                          "min_load_frac": fc["min_load_frac"], "ramp_frac_per_s": fc["ramp_frac_per_s"], "ems": fc["ems"]},
            "battery": EL["battery"], "fuels": cfg["fuels"], "hpdi": cfg["hpdi"],
            "missions": {t: {"vehicle": cfg["missions"][t]["vehicle"]} for t in MISSIONS if t in cfg["missions"]}}


# ------------------------------------------------------------------ step-by-step trace of one mission
def build_trace(tag):
    cyc = _rows(f"cycle_{tag}_distance.csv")
    d, h = _rows(f"consumption_{tag}.csv"), _rows(f"consumption_h2ice_{tag}.csv")
    b, f = _rows(f"consumption_bev_{tag}.csv"), _rows(f"consumption_fcev_{tag}.csv")
    if not (cyc and d and b and f):
        return {"ok": False}
    n = min(len(d), len(b), len(f), len(h) if h else len(d))

    def col(rows, key, nd=2, cast=float):
        out = []
        for r in rows[:n]:
            x = cast(r[key])
            out.append(round(x, nd) if nd is not None else x)
        return out

    def cum(rows, key, scale=1.0, nd=4):
        s, out = 0.0, []
        for r in rows[:n]:
            s += float(r[key]) * scale
            out.append(round(s, nd))
        return out

    tr = {"ok": True, "tag": tag, "n": n,
          "s": [round(float(r["s_m"]) / 1000, 3) for r in d[:n]], "t": col(d, "t_s", 1), "dwell": col(d, "dwell_s", 1),
          "v": col(d, "v_kmh", 1), "grade": col(d, "grade_pct", 2), "vlim": [round(float(r["v_target_kmh"]), 1) for r in cyc[:n]],
          "z": [round(float(r["altitude_m"]), 1) for r in cyc[:n]], "P_wheel": col(d, "P_wheel_kW", 1),
          "d_gear": col(d, "gear", None, lambda x: int(float(x))), "d_n": col(d, "n_rpm", 0), "d_T": col(d, "T_engine_Nm", 0),
          "d_P": col(d, "P_engine_kW", 1), "d_eta": col(d, "eta_engine", 3), "d_cum_l": cum(d, "diesel_g", 1e-3 / 0.835, 3),
          "b_gear": col(b, "gear", None, lambda x: int(float(x))), "b_t": col(b, "motor_torque_frac", 3), "b_w": col(b, "motor_speed_frac", 3),
          "b_Pm": col(b, "P_motor_el_kW", 1), "b_Pb": col(b, "P_battery_kW", 1), "b_soc": col(b, "SOC", 4),
          "b_cum": col(b, "E_battery_cum_kWh", 3),
          "f_t": col(f, "motor_torque_frac", 3), "f_w": col(f, "motor_speed_frac", 3), "f_Pm": col(f, "P_motor_el_kW", 1),
          "f_Pfc": col(f, "P_fc_net_kW", 1), "f_load": col(f, "fc_load_frac", 3), "f_Pb": col(f, "P_battery_kW", 1),
          "f_soc": col(f, "SOC", 4), "f_cum": col(f, "h2_cum_kg_BOL", 4)}
    if h:
        tr.update({"h_gear": col(h, "gear", None, lambda x: int(float(x))), "h_n": col(h, "n_rpm", 0), "h_T": col(h, "T_engine_Nm", 0),
                   "h_P": col(h, "P_engine_kW", 1), "h_cum": cum(h, "h2ice_h2_g", 1e-3, 4)})
    return tr


# ------------------------------------------------------------------ editable inputs
def _I(path, label, unit="", lo=None, hi=None, step=None, kind="num", options=None):
    return {"path": path, "label": label, "unit": unit, "min": lo, "max": hi, "step": step, "kind": kind, "options": options}


INPUT_GROUPS = [
    {"title": "Missions", "note": "Mass and road load of each mission. Mass changes also change the driving cycle: run with the cycles rebuilt.",
     "items": [
         _I("missions.urban_bus.curb_kg", "Urban bus · curb mass", "kg", 8000, 20000, 100),
         _I("missions.urban_bus.n_pax", "Urban bus · passengers", "", 0, 100, 1),
         _I("missions.urban_bus.CdA_m2", "Urban bus · drag area CdA", "m²", 3, 12, 0.1),
         _I("missions.urban_bus.cr_asphalt", "Urban bus · rolling resistance", "–", 0.003, 0.012, 0.0001),
         _I("missions.coach.curb_kg", "Coach · curb mass", "kg", 8000, 22000, 100),
         _I("missions.coach.n_pax", "Coach · passengers", "", 0, 60, 1),
         _I("missions.coach.CdA_m2", "Coach · drag area CdA", "m²", 3, 12, 0.1),
         _I("missions.coach.cr_asphalt", "Coach · rolling resistance", "–", 0.003, 0.012, 0.0001),
         _I("missions.timber_empty.mass_kg", "Timber truck · empty mass", "kg", 12000, 30000, 100),
         _I("missions.timber_loaded.mass_kg", "Timber truck · loaded mass", "kg", 30000, 90000, 500),
         _I("missions.timber_empty.CdA_m2", "Timber truck · drag area (empty)", "m²", 4, 14, 0.1),
         _I("missions.timber_loaded.CdA_m2", "Timber truck · drag area (loaded)", "m²", 4, 14, 0.1)]},
    {"title": "Engines", "note": "Diesel, HVO100 and hydrogen engine. The engine map scales with displacement: change power and displacement together (397 kW per 12.8 L).",
     "items": [
         _I("engine_map.source", "Engine map", "", kind="select", options=["measured", "model"]),
         _I("vehicles.timber_truck.engine.rated_power_kW", "Timber truck · rated power", "kW", 200, 600, 1),
         _I("vehicles.timber_truck.engine.displacement_l", "Timber truck · displacement", "l", 6, 17, 0.1),
         _I("vehicles.urban_bus.engine.rated_power_kW", "Urban bus · rated power", "kW", 150, 400, 1),
         _I("vehicles.urban_bus.engine.displacement_l", "Urban bus · displacement", "l", 5, 13, 0.1),
         _I("vehicles.coach.engine.rated_power_kW", "Coach · rated power", "kW", 200, 500, 1),
         _I("vehicles.coach.engine.displacement_l", "Coach · displacement", "l", 6, 16, 0.1),
         _I("vehicles.urban_bus.aux_mech_kW", "Urban bus · auxiliaries", "kW", 0, 30, 0.5),
         _I("vehicles.coach.aux_mech_kW", "Coach · auxiliaries", "kW", 0, 30, 0.5),
         _I("vehicles.timber_truck.aux_mech_kW", "Timber truck · auxiliaries", "kW", 0, 30, 0.5),
         _I("hpdi.pilot_share_full_load", "H2-ICE · pilot fuel share at full load", "–", 0, 0.2, 0.005),
         _I("vehicles.timber_truck.h2ice_mass.extra_mass_kg", "Timber truck · H2-ICE extra mass", "kg", -1000, 3000, 10),
         _I("vehicles.urban_bus.h2ice_mass.extra_mass_kg", "Urban bus · H2-ICE extra mass", "kg", -1000, 3000, 10),
         _I("vehicles.coach.h2ice_mass.extra_mass_kg", "Coach · H2-ICE extra mass", "kg", -1000, 3000, 10)]},
    {"title": "Electric drive and batteries", "note": "Battery-electric (BEV) and fuel cell (FCEV) vehicles. Extra mass is net of the removed diesel parts.",
     "items": [
         _I("electric.vehicles.timber_truck.motor_peak_kW", "Timber truck · motor peak power", "kW", 200, 800, 5),
         _I("electric.vehicles.urban_bus.motor_peak_kW", "Urban bus · motor peak power", "kW", 100, 500, 5),
         _I("electric.vehicles.coach.motor_peak_kW", "Coach · motor peak power", "kW", 100, 600, 5),
         _I("electric.vehicles.timber_truck.bev.battery_kWh", "Timber truck · BEV battery", "kWh", 100, 1200, 10),
         _I("electric.vehicles.urban_bus.bev.battery_kWh", "Urban bus · BEV battery", "kWh", 100, 800, 10),
         _I("electric.vehicles.coach.bev.battery_kWh", "Coach · BEV battery", "kWh", 100, 1000, 10),
         _I("electric.vehicles.timber_truck.bev.extra_mass_kg", "Timber truck · BEV extra mass", "kg", -1000, 8000, 10),
         _I("electric.vehicles.urban_bus.bev.extra_mass_kg", "Urban bus · BEV extra mass", "kg", -1000, 6000, 10),
         _I("electric.vehicles.coach.bev.extra_mass_kg", "Coach · BEV extra mass", "kg", -1000, 6000, 10),
         _I("electric.edrive.machine_peak_efficiency", "Motor peak efficiency", "–", 0.85, 0.99, 0.001),
         _I("electric.edrive.regen_v_cut_kmh", "Regeneration cut-off speed", "km/h", 0, 30, 0.5),
         _I("electric.battery.loss_at_1C", "Battery loss at 1C", "–", 0, 0.1, 0.005),
         _I("electric.battery.charger_efficiency", "Charger efficiency", "–", 0.7, 1, 0.01)]},
    {"title": "Fuel cell", "note": "Fuel cell size, buffer battery and energy management of the FCEVs.",
     "items": [
         _I("electric.vehicles.timber_truck.fcev.fc_net_kW", "Timber truck · fuel cell net power", "kW", 50, 600, 5),
         _I("electric.vehicles.urban_bus.fcev.fc_net_kW", "Urban bus · fuel cell net power", "kW", 30, 300, 5),
         _I("electric.vehicles.coach.fcev.fc_net_kW", "Coach · fuel cell net power", "kW", 30, 400, 5),
         _I("electric.vehicles.timber_truck.fcev.battery_kWh", "Timber truck · buffer battery", "kWh", 10, 300, 5),
         _I("electric.vehicles.urban_bus.fcev.battery_kWh", "Urban bus · buffer battery", "kWh", 10, 300, 5),
         _I("electric.vehicles.coach.fcev.battery_kWh", "Coach · buffer battery", "kWh", 10, 300, 5),
         _I("electric.vehicles.timber_truck.fcev.extra_mass_kg", "Timber truck · FCEV extra mass", "kg", -2000, 5000, 10),
         _I("electric.vehicles.urban_bus.fcev.extra_mass_kg", "Urban bus · FCEV extra mass", "kg", -2000, 5000, 10),
         _I("electric.vehicles.coach.fcev.extra_mass_kg", "Coach · FCEV extra mass", "kg", -2000, 5000, 10),
         _I("electric.fuel_cell.min_load_frac", "Minimum load", "of rated", 0, 0.5, 0.01),
         _I("electric.fuel_cell.ramp_frac_per_s", "Ramp rate", "of rated per s", 0.01, 1, 0.01),
         _I("electric.fuel_cell.ems.filter_tau_s", "Power-follower time constant", "s", 1, 600, 1),
         _I("electric.fuel_cell.ems.soc_ref", "Buffer battery target charge", "–", 0.3, 0.8, 0.01)]},
]


def _get(d, path):
    for k in path.split("."):
        d = d[k]
    return d


def _set(d, path, val):
    ks = path.split(".")
    for k in ks[:-1]:
        d = d[k]
    d[ks[-1]] = val


def get_inputs():
    cfg = json.load(open(CFG_PATH))
    orig = json.load(open(BAK_PATH)) if os.path.exists(BAK_PATH) else None
    groups = []
    for g in INPUT_GROUPS:
        items = []
        for it in g["items"]:
            try:
                v = _get(cfg, it["path"])
            except (KeyError, TypeError):
                continue
            o = None
            if orig is not None:
                try:
                    o = _get(orig, it["path"])
                except (KeyError, TypeError):
                    o = None
            items.append(dict(it, value=v, original=o))
        groups.append({"title": g["title"], "note": g["note"], "items": items})
    return {"groups": groups, "has_backup": orig is not None}


def save_inputs(changes):
    allowed = {it["path"]: it for g in INPUT_GROUPS for it in g["items"]}
    raw = open(CFG_PATH, encoding="utf-8").read()
    cfg = json.loads(raw)
    bad = []
    for path, val in changes.items():
        it = allowed.get(path)
        if not it:
            bad.append(path); continue
        if it["kind"] == "select":
            if val not in it["options"]:
                bad.append(path); continue
        else:
            try:
                val = float(val)
            except (TypeError, ValueError):
                bad.append(path); continue
            if not math.isfinite(val):
                bad.append(path); continue
            old = _get(cfg, path)
            if isinstance(old, int) and float(val).is_integer():
                val = int(val)
        _set(cfg, path, val)
    if bad:
        return {"ok": False, "message": "Not saved, invalid values: " + ", ".join(bad)}
    if not os.path.exists(BAK_PATH):
        shutil.copyfile(CFG_PATH, BAK_PATH)
    end = "\n" if raw.endswith("\n") else ""
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=4, ensure_ascii=False) + end)
    return {"ok": True, "message": f"Saved {len(changes)} value(s) to vehicles.json (original kept in vehicles.json.bak)."}


def restore_inputs():
    if not os.path.exists(BAK_PATH):
        return {"ok": False, "message": "No backup to restore."}
    shutil.copyfile(BAK_PATH, CFG_PATH)
    os.remove(BAK_PATH)
    return {"ok": True, "message": "vehicles.json restored to the version before the dashboard edits."}


# ------------------------------------------------------------------ background run
def _run(keep_cycles, engine_map):
    cmd = [sys.executable, "-u", os.path.join(HERE, "run_all.py")] + (["--keep-cycles"] if keep_cycles else [])
    if engine_map in ("measured", "model"):
        cmd += ["--engine-map", engine_map]
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    except OSError as e:
        with LOCK:
            STATE.update(running=False, finished=time.time(), returncode=1, log=[str(e)])
        return
    for line in p.stdout:
        line = line.rstrip()
        with LOCK:
            STATE["log"] = (STATE["log"] + [line])[-80:]
            if line.startswith("[") and "/" in line.split("]")[0]:       # "[2/6] powertrain.py ..."
                a, n = line[1:].split("]")[0].split("/")
                STATE.update(step=int(a), steps=int(n), label=line.split("]", 1)[1].strip(" ."))
    p.wait()
    with LOCK:
        STATE.update(running=False, finished=time.time(), returncode=p.returncode)


def start_run(keep_cycles, engine_map):
    with LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, step=0, steps=5 if keep_cycles else 6, label="starting", log=[],
                     started=time.time(), finished=None, returncode=None,
                     options={"keep_cycles": keep_cycles, "engine_map": engine_map})
    threading.Thread(target=_run, args=(keep_cycles, engine_map), daemon=True).start()
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

    def _json(self, obj, code=200):
        return self._send(code, json.dumps(obj, separators=(",", ":"), allow_nan=False), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        try:
            if path in ("/", "/dashboard.html"):
                return self._send(200, open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
            if path == "/api/data":
                return self._json(build_data())
            if path == "/api/model":
                return self._json(cached("model", ["vehicles.json", "data/engine_map_measured.csv"], build_model))
            if path == "/api/trace":
                tag = (q.get("m") or ["urban_bus"])[0]
                if tag not in MISSIONS:
                    return self._send(404, "unknown mission", "text/plain")
                deps = [f"cycle_{tag}_distance.csv", f"consumption_{tag}.csv", f"consumption_h2ice_{tag}.csv",
                        f"consumption_bev_{tag}.csv", f"consumption_fcev_{tag}.csv"]
                return self._json(cached("trace_" + tag, deps, lambda: build_trace(tag)))
            if path == "/api/inputs":
                return self._json(get_inputs())
            if path == "/api/status":
                with LOCK:
                    return self._json(STATE)
            if path.startswith("/files/"):
                name = os.path.basename(path[len("/files/"):])           # no sub-folders, no ".."
                if name.endswith(".xlsx") or name.endswith(".csv"):
                    p = os.path.join(HERE, "results", name)
                    ctype = "text/csv" if name.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                elif name.startswith("fig_") and name.endswith(".png"):
                    p, ctype = os.path.join(HERE, name), "image/png"
                else:
                    return self._send(404, "not found", "text/plain")
                if os.path.exists(p):
                    return self._send(200, open(p, "rb").read(), ctype)
            return self._send(404, "not found", "text/plain")
        except Exception as e:                                          # show the reason in the page, keep serving
            return self._json({"ok": False, "message": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        try:
            if self.path == "/api/run":
                opts = self._body()
                ok = start_run(bool(opts.get("keep_cycles")), opts.get("engine_map"))
                return self._json({"started": ok}, 200 if ok else 409)
            if self.path == "/api/inputs":
                with LOCK:
                    if STATE["running"]:
                        return self._json({"ok": False, "message": "A run is in progress: wait for it to finish."}, 409)
                return self._json(save_inputs(self._body().get("changes", {})))
            if self.path == "/api/inputs/restore":
                return self._json(restore_inputs())
            return self._send(404, "not found", "text/plain")
        except Exception as e:
            return self._json({"ok": False, "message": f"{type(e).__name__}: {e}"}, 500)

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
