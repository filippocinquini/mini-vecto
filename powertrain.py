"""
powertrain.py - fuel consumption along the mission cycles (backward-facing, VECTO-like)

Chain, per 10 m step of each cycle_<mission>_distance.csv:
  driving cycle (v, a, grade, surface)
    -> wheel force and power           F = m_eff a + m g sin(a) + Cr m g cos(a) + 1/2 rho CdA v^2
    -> gearbox + axle (I-Shift ratios)  engine speed n and torque T for every gear
    -> gear choice                      the feasible gear with the lowest fuel use ("ideal" shifting)
    -> engine map                       two options, chosen in vehicles.json > "engine_map" > "source":
                                        "measured"  test-bench map of a 13 L diesel engine (176 points, fuel flow
                                                    interpolated in speed and torque), best efficiency 44 %
                                        "model"     semi-empirical map, fuel power = indicated power / indicated
                                                    efficiency, scaled to a 50 % peak
                                        The measured map (data/engine_map_measured.csv) was provided by AB Volvo
                                        for the course; if the file is missing, the model map is used.
    -> auxiliaries                      constant mechanical load on the engine, also at idle
    -> fuel                             diesel, HVO100, or H2 + HVO pilot (H2-ICE HPDI)
Stops: the engine idles for the dwell time (no start-stop). Overrun (engine dragged): fuel cut-off.

Inputs : vehicles.json, cycle_<mission>_distance.csv
Mass  : diesel and HVO100 run at the mission mass; the hydrogen engine runs again with the mass of its tanks
         (vehicles.json > vehicles > vehicle > h2ice_mass). Missions with max_gross_kg keep the gross at the limit
         and the extra mass reduces the payload (see mission_mass).
Outputs: consumption_<mission>.csv  one row per step, energy and fuel mass per fuel option (h2ice columns at the diesel mass)
         consumption_h2ice_<mission>.csv  the same for the hydrogen engine at its own mass
         consumption_summary.csv / .json  totals per mission and fuel
Usage  : python3 powertrain.py
"""
import csv, json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
G, RHO = 9.82, 1.2          # Noreland
DS = 10.0                   # m, cycle step
MISSIONS = ["timber_empty", "timber_loaded", "urban_bus", "coach"]

# ============================================================== engine model (same as maps.py)
VD_REF, P_REF, T_REF = 12.8e-3, 397e3, 2600.0


def interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i-1]) / (xs[i] - xs[i-1])
            return ys[i-1] + t * (ys[i] - ys[i-1])
    return ys[-1]


def w(n):
    return 2 * math.pi * n / 60


def fl_torque_ref(n):
    """Full-load torque of the D13K540 [Nm] (fact sheet: 2600 Nm 1000-1460 rpm, 397 kW 1460-1800 rpm)."""
    if n <= 1460:
        return interp(n, [600, 800, 1000, 1460], [1300, 2000, 2600, 2600])
    if n <= 1800:
        return min(2600, P_REF / w(n))
    return interp(n, [1800, 1900, 2000, 2100], [P_REF / w(1800), 1800, 1300, 600])


def fmep(n):                          # bar
    k = n / 1000
    return 0.80 + 0.35 * k + 0.25 * k * k


IMEP_REF = 4 * math.pi * T_REF / VD_REF / 1e5 + fmep(1200)


def eta_i_shape(n, imep):
    x, k = imep / IMEP_REF, n / 1000
    return (1 - 0.35 * (x - 0.72) ** 2) * (1 - 0.30 * (k - 1.25) ** 2)


def _calibrate():
    """Scale indicated efficiency so the brake-efficiency peak is 50.0 % (assumption for a modern heavy-duty engine)."""
    best = 0
    for i in range(0, 301):
        n = 600 + 5 * i
        for j in range(1, 401):
            T = j * T_REF / 400
            if T > fl_torque_ref(n):
                continue
            b = 4 * math.pi * T / VD_REF / 1e5
            e = eta_i_shape(n, b + fmep(n)) * b / (b + fmep(n))
            best = max(best, e)
    return 0.50 / best


ETA_I_SCALE = _calibrate()


# ============================================================== measured engine map
class MeasuredMap:
    """Fuel flow [g/s] measured on the test bench at (speed, torque) points lying on constant-speed lines.
    Lookup: linear in torque along the two neighbouring speed lines, then linear in speed.
    Above the last measured torque of a line the last slope is kept (the fuel line is almost straight there)."""

    def __init__(self, path, lhv_MJ_per_kg, line_step_rpm=100, min_points=4):
        self.lhv = lhv_MJ_per_kg
        lines, self.points = {}, []
        for r in csv.DictReader(open(path)):
            n, T, f = float(r["n_rpm"]), max(float(r["T_Nm"]), 0.0), float(r["fuel_g_per_s"])
            self.points.append((n, T, f))
            lines.setdefault(round(n / line_step_rpm) * line_step_rpm, []).append((T, f, n))
        self.lines = {}
        for n_nom, pts in lines.items():
            if any(abs(p[2] - n_nom) > 10 for p in pts):          # points between two lines (1450, 1850 rpm): kept
                pts = [p for p in pts if abs(p[2] - n_nom) <= 10]  # only for checking the interpolation
            pts.sort()
            merged = []
            for T, f, _ in pts:                                    # repeated points: mean
                if merged and T - merged[-1][0] < 5:
                    merged[-1] = (0.5 * (merged[-1][0] + T), 0.5 * (merged[-1][1] + f))
                else:
                    merged.append((T, f))
            if len(merged) >= min_points:
                self.lines[n_nom] = ([p[0] for p in merged], [p[1] for p in merged])
        self.speeds = sorted(self.lines)

    def _line(self, n_nom, T):
        ts, fs = self.lines[n_nom]
        if T >= ts[-1]:
            return fs[-1] + (T - ts[-1]) * (fs[-1] - fs[-2]) / (ts[-1] - ts[-2])
        return interp(T, ts, fs)

    def _bracket(self, n):
        s = self.speeds
        n = min(max(n, s[0]), s[-1])
        for i in range(1, len(s)):
            if n <= s[i]:
                return s[i-1], s[i], (n - s[i-1]) / (s[i] - s[i-1])
        return s[-2], s[-1], 1.0

    def fuel_flow(self, n, T):
        """Fuel mass flow [g/s] of the measured engine at speed n [rpm] and torque T [Nm]."""
        lo, hi, t = self._bracket(n)
        return (1 - t) * self._line(lo, T) + t * self._line(hi, T)

    def t_measured_max(self, n):
        lo, hi, t = self._bracket(n)
        return (1 - t) * self.lines[lo][0][-1] + t * self.lines[hi][0][-1]

    def best_point(self):
        return max((T * w(n) / (f * self.lhv * 1e3), n, T) for n, T, f in self.points if T > 50)


MAP, MAP_INFO = None, {"source": "model", "label": "semi-empirical map, 50 % peak brake efficiency"}


def select_engine_map(source=None):
    """Choose the engine map: 'measured' or 'model'. Default: vehicles.json > engine_map > source,
    overridden by the environment variable MINIVECTO_ENGINE_MAP. Falls back to 'model' if the file is missing."""
    global MAP, MAP_INFO
    cfg = CFG.get("engine_map", {})
    source = source or os.environ.get("MINIVECTO_ENGINE_MAP") or cfg.get("source", "model")
    MAP, MAP_INFO = None, {"source": "model", "label": "semi-empirical map, 50 % peak brake efficiency"}
    if source == "measured":
        path = os.path.join(HERE, cfg.get("file", "data/engine_map_measured.csv"))
        if os.path.exists(path):
            MAP = MeasuredMap(path, cfg.get("test_fuel_LHV_MJ_per_kg", 42.7))
            e, n, T = MAP.best_point()
            MAP_INFO = {"source": "measured", "label": f"measured map, {len(MAP.points)} points, best brake efficiency "
                                                       f"{e*100:.1f} % at {n:.0f} rpm and {T:.0f} Nm"}
        else:
            MAP_INFO["label"] += " (measured map file not found: " + cfg.get("file", "") + ")"
            print("NOTE: measured engine map not found, using the semi-empirical map instead.")
    elif source != "model":
        raise SystemExit(f"engine_map source must be 'measured' or 'model', not '{source}'")
    return MAP_INFO


class Engine:
    def __init__(self, cfg):
        self.vd = cfg["displacement_l"] / 1000
        self.k = self.vd / VD_REF                    # torque scales with displacement (same BMEP map)
        self.n_idle, self.n_min, self.n_max, self.n_launch = (cfg["n_idle_rpm"], cfg["n_min_drive_rpm"],
                                                              cfg["n_max_rpm"], cfg["n_launch_rpm"])

    def t_max(self, n):
        return fl_torque_ref(n) * self.k

    def fuel_power(self, n, T):
        """Chemical fuel power [W] at speed n [rpm] and brake torque T [Nm] (T >= 0).
        Measured map: fuel flow read at the same BMEP (torque / k) and scaled with displacement (x k).
        Model map: P_fuel = P_indicated / eta_i, with P_ind = (BMEP + FMEP) Vd n/120 (4-stroke)."""
        if MAP is not None:
            return self.k * MAP.fuel_flow(n, T / self.k) * MAP.lhv * 1e3
        bmep = 4 * math.pi * T / self.vd / 1e5
        imep = bmep + fmep(n)
        p_ind = imep * 1e5 * self.vd * n / 120
        eta_i = ETA_I_SCALE * eta_i_shape(n, imep)
        return p_ind / eta_i

    def pilot_share(self, n, T):
        """HPDI pilot energy share: pilot energy per cycle fixed at 2.5 % of the full-load value."""
        e_fl = self.fuel_power(n, self.t_max(n))
        e = self.fuel_power(n, max(T, 0))
        return min(1.0, CFG["hpdi"]["pilot_share_full_load"] * e_fl / e)


# ============================================================== powertrain
class Powertrain:
    def __init__(self, vcfg, gb):
        self.eng = Engine(vcfg["engine"])
        self.ratios = gb["ratios"]
        self.eta_gear = [gb["eta_direct"] if abs(r - 1.0) < 1e-6 else gb["eta_indirect"] for r in self.ratios]
        self.i_ax, self.eta_ax = vcfg["axle_ratio"], vcfg["eta_axle"]
        self.r = vcfg["tyre_dynamic_radius_m"]
        self.aux = vcfg["aux_mech_kW"] * 1e3

    def idle(self, seconds):
        n = self.eng.n_idle
        T = self.aux / w(n)
        return self.eng.fuel_power(n, T) * seconds, n, T

    def step(self, v, F):
        """Mean speed v [m/s] and wheel force F [N] over one step.
        Returns dict with gear, n, T, fuel power [W], and loss split, or infeasible flag."""
        omega_w = v / self.r
        best = None
        for g, (ig, eg) in enumerate(zip(self.ratios, self.eta_gear), start=1):
            i_tot = ig * self.i_ax
            eta = eg * self.eta_ax
            n = omega_w * i_tot * 60 / (2 * math.pi)
            slip = False
            if n > self.eng.n_max:
                continue
            if n < self.eng.n_min:
                if g == 1:                             # launch: clutch slips, engine held at launch speed
                    n, slip = max(n, self.eng.n_launch), True
                else:
                    continue
            T_wheel = F * self.r
            if T_wheel >= 0:
                T_drv = T_wheel / (i_tot * eta)        # engine torque for traction
            else:
                T_drv = T_wheel * eta / i_tot          # vehicle drags the engine (overrun)
            T_aux = self.aux / w(n)
            T = T_drv + T_aux
            if T > self.eng.t_max(n):
                continue
            if T <= 0:                                 # overrun: injection cut, brakes take the rest
                pf = 0.0
            else:
                pf = self.eng.fuel_power(n, T)
            cand = {"gear": g, "n": n, "T": T, "pf": pf, "slip": slip, "T_aux": T_aux,
                    "p_drv": max(T_drv, 0) * w(n), "loss_dl": max(T_drv, 0) * w(n) - max(F, 0) * v}
            if best is None or pf < best["pf"] - 1e-9 or (abs(pf - best["pf"]) < 1e-9 and g > best["gear"]):
                best = cand
        if best is None:                               # demand beyond full load in every gear: saturate
            cands = []
            for g, ig in enumerate(self.ratios, start=1):
                n = min(max(omega_w * ig * self.i_ax * 60 / (2 * math.pi), self.eng.n_launch), self.eng.n_max)
                cands.append((self.eng.t_max(n) * w(n), g, n))
            p, g, n = max(cands)
            T = self.eng.t_max(n)
            best = {"gear": g, "n": n, "T": T, "pf": self.eng.fuel_power(n, T), "slip": False,
                    "T_aux": self.aux / w(n), "p_drv": T * w(n) - self.aux, "loss_dl": 0.0, "infeasible": True}
        return best


# ============================================================== run
def load_cycle(tag):
    rows = list(csv.DictReader(open(os.path.join(HERE, f"cycle_{tag}_distance.csv"))))
    return rows


def gross_mass(c):
    """Mission mass without powertrain extra mass: curb + passengers (buses) or mass_kg (timber truck)."""
    if "curb_kg" in c:
        return c["curb_kg"] + c["n_pax"] * c["kg_per_pax"]
    return c["mass_kg"]


def lateral_and_braking(r0, v, F, m, m_eff):
    """Curve radius of the step, lateral acceleration v^2/R and lateral force m v^2/R (whole vehicle, all tyres),
    braking deceleration supplied by the brakes (friction + regeneration) = -F_wheel / m_eff when F_wheel < 0."""
    R = float(r0.get("curve_radius_m") or 0.0)            # 0 = straight road
    a_lat = v * v / R if R > 0 else 0.0
    return {"curve_radius_m": round(R, 1), "a_lat_mps2": round(a_lat, 3), "F_lat_N": round(m * a_lat),
            "a_brake_mps2": round(max(-F, 0.0) / m_eff, 3)}


def mission_mass(mcfg, extra=0.0):
    """Simulated mass and payload of a mission. extra = powertrain mass on top of the diesel vehicle.
    With max_gross_kg (legal gross limit, e.g. timber_loaded at the Swedish BK4 74 t) the gross mass stays at the
    limit and the extra mass reduces the payload; payload_kg = gross - tare_kg - extra (None if tare_kg is not given)."""
    m = gross_mass(mcfg) + extra
    if "max_gross_kg" in mcfg:
        m = min(m, mcfg["max_gross_kg"])
    payload = m - mcfg["tare_kg"] - extra if "tare_kg" in mcfg else None
    return m, payload


def run(tag, write=True, extra_mass=0.0, out_name=None):
    mcfg = CFG["missions"][tag]
    vcfg = CFG["vehicles"][mcfg["vehicle"]]
    pt = Powertrain(vcfg, CFG["gearboxes"][vcfg["gearbox"]])
    m, payload = mission_mass(mcfg, extra_mass)
    m_eff = m + mcfg["rot_mass_kg"]
    rows = load_cycle(tag)
    F_ = CFG["fuels"]
    out = []
    tot = {k: 0.0 for k in ["E_fuel_MJ", "diesel_kg", "hvo_kg", "h2_kg", "pilot_hvo_kg", "E_wheel_pos_MJ",
                            "E_brake_MJ", "E_aux_MJ", "E_idle_fuel_MJ", "t_idle_s", "t_move_s", "infeasible_steps",
                            "shifts", "E_engine_MJ", "E_fuel_extrap_MJ"]}
    last_gear = None
    cum = 0.0
    for i in range(len(rows) - 1):
        r0, r1 = rows[i], rows[i+1]
        s = float(r0["s_m"])
        v0, v1 = float(r0["v_sim_kmh"]) / 3.6, float(r1["v_sim_kmh"]) / 3.6
        vm = 0.5 * (v0 + v1)
        a = (v1 * v1 - v0 * v0) / (2 * DS)
        grade = float(r0["grade_pct"]) / 100
        al = math.atan(grade)
        cr = mcfg["cr_gravel"] if r0["surface"] == "gravel" else mcfg["cr_asphalt"]
        F_in, F_gr = m_eff * a, m * G * math.sin(al)
        F_rr, F_air = cr * m * G * math.cos(al), 0.5 * RHO * mcfg["CdA_m2"] * vm * vm
        F = F_in + F_gr + F_rr + F_air
        dwell = float(r0["stop_dwell_s"])
        dt_total = float(r1["t_s"]) - float(r0["t_s"])
        dt = max(dt_total - dwell, 1e-6)

        # idle during a stop at this node
        e_idle = 0.0
        if dwell > 0:
            e_idle, n_i, T_i = pt.idle(dwell)
            tot["t_idle_s"] += dwell
            tot["E_aux_MJ"] += pt.aux * dwell / 1e6

        # driving over this step
        if vm < 0.05:
            e_move, st = 0.0, {"gear": 0, "n": pt.eng.n_idle, "T": 0.0, "pf": 0.0, "slip": False, "loss_dl": 0.0, "T_aux": 0.0}
        else:
            st = pt.step(vm, F)
            e_move = st["pf"] * dt
            if st.get("infeasible"):
                tot["infeasible_steps"] += 1
        if st["gear"] and last_gear and st["gear"] != last_gear:
            tot["shifts"] += 1
        if st["gear"]:
            last_gear = st["gear"]
        tot["t_move_s"] += dt
        tot["E_aux_MJ"] += (pt.aux * dt / 1e6) if vm >= 0.05 else 0.0
        e_step = e_move + e_idle                       # J of fuel energy
        if e_move > 0:
            tot["E_engine_MJ"] += st["T"] * w(st["n"]) * dt / 1e6
            if MAP is not None and st["T"] / pt.eng.k > MAP.t_measured_max(st["n"]) + 1:
                tot["E_fuel_extrap_MJ"] += e_move / 1e6      # fuel burnt above the highest measured torque
        if e_idle > 0:
            tot["E_engine_MJ"] += pt.aux * dwell / 1e6
        # fuel split per option
        diesel_kg = e_step / (F_["diesel"]["LHV_MJ_per_kg"] * 1e6)
        hvo_kg = e_step / (F_["hvo100"]["LHV_MJ_per_kg"] * 1e6)
        ps_move = pt.eng.pilot_share(st["n"], st["T"]) if e_move > 0 else 0.0
        ps_idle = pt.eng.pilot_share(pt.eng.n_idle, pt.aux / w(pt.eng.n_idle)) if e_idle > 0 else 0.0
        e_pilot = e_move * ps_move + e_idle * ps_idle
        h2_kg = (e_step - e_pilot) / (F_["h2"]["LHV_MJ_per_kg"] * 1e6)
        pilot_kg = e_pilot / (F_[CFG["hpdi"]["pilot_fuel"]]["LHV_MJ_per_kg"] * 1e6)
        cum += e_step
        tot["E_fuel_MJ"] += e_step / 1e6
        tot["diesel_kg"] += diesel_kg; tot["hvo_kg"] += hvo_kg; tot["h2_kg"] += h2_kg; tot["pilot_hvo_kg"] += pilot_kg
        tot["E_idle_fuel_MJ"] += e_idle / 1e6
        if F > 0:
            tot["E_wheel_pos_MJ"] += F * DS / 1e6
        else:
            tot["E_brake_MJ"] += -F * DS / 1e6
        eta_eng = (st["T"] * w(st["n"]) / st["pf"]) if st["pf"] > 0 else 0.0
        out.append({
            "s_m": int(s), "t_s": round(float(r0["t_s"]), 1), "dt_drive_s": round(dt, 2), "dwell_s": dwell,
            "v_kmh": round(vm * 3.6, 2), "a_mps2": round(a, 3), "grade_pct": round(grade * 100, 2), "surface": r0["surface"],
            "F_wheel_N": round(F), "P_wheel_kW": round(F * vm / 1e3, 2), **lateral_and_braking(r0, vm, F, m, m_eff),
            "E_friction_brake_kWh": round(max(-F, 0) * DS / 3.6e6, 6),     # ASSUMPTION: all braking on the friction brakes (no engine brake / retarder)
            "gear": st["gear"], "clutch_slip": int(st["slip"]), "n_rpm": round(st["n"]), "T_engine_Nm": round(st["T"], 1),
            "P_engine_kW": round(st["T"] * w(st["n"]) / 1e3, 2), "P_aux_kW": round(pt.aux / 1e3, 2),
            "P_driveline_loss_kW": round(st["loss_dl"] / 1e3, 2), "eta_engine": round(eta_eng, 4),
            "E_fuel_MJ": round(e_step / 1e6, 5), "E_fuel_idle_MJ": round(e_idle / 1e6, 5),
            "diesel_g": round(diesel_kg * 1e3, 3), "hvo100_g": round(hvo_kg * 1e3, 3),
            "h2ice_h2_g": round(h2_kg * 1e3, 4), "h2ice_pilot_hvo_g": round(pilot_kg * 1e3, 4),
            "pilot_share": round(ps_move, 4), "E_fuel_cum_MJ": round(cum / 1e6, 3),
        })
    if write:
        with open(os.path.join(HERE, out_name or f"consumption_{tag}.csv"), "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            wr.writeheader(); wr.writerows(out)
    km = float(rows[-1]["s_m"]) / 1000
    dens_d, dens_h = F_["diesel"]["density_kg_per_l"], F_["hvo100"]["density_kg_per_l"]
    res = {
        "mission": tag, "vehicle": mcfg["vehicle"], "mass_kg": m, "extra_mass_kg": extra_mass, "payload_kg": payload, "n_pax": mcfg.get("n_pax"), "timber_t_per_round_trip": round(payload / 1000, 2) if payload is not None else None, "km": round(km, 1),
        "time_min": round((tot["t_move_s"] + tot["t_idle_s"]) / 60, 1),
        "fuel_energy_MJ_per_km": round(tot["E_fuel_MJ"] / km, 3),
        "fuel_energy_kWh_per_km": round(tot["E_fuel_MJ"] / km / 3.6, 3),
        "diesel_l_per_100km": round(tot["diesel_kg"] / dens_d / km * 100, 2),
        "hvo100_l_per_100km": round(tot["hvo_kg"] / dens_h / km * 100, 2),
        "h2ice_h2_kg_per_100km": round(tot["h2_kg"] / km * 100, 3),
        "h2ice_pilot_hvo_l_per_100km": round(tot["pilot_hvo_kg"] / dens_h / km * 100, 3),
        "h2ice_pilot_energy_share_pct": round(tot["pilot_hvo_kg"] * F_["hvo100"]["LHV_MJ_per_kg"] / max(tot["E_fuel_MJ"], 1e-9) * 100, 2),
        "wheel_work_kWh_per_km": round(tot["E_wheel_pos_MJ"] / km / 3.6, 3),
        "braking_kWh_per_km": round(tot["E_brake_MJ"] / km / 3.6, 3),
        "aux_kWh_per_km": round(tot["E_aux_MJ"] / km / 3.6, 3),
        "mean_tank_to_wheel_eff_pct": round(tot["E_wheel_pos_MJ"] / max(tot["E_fuel_MJ"], 1e-9) * 100, 1),
        "idle_fuel_share_pct": round(tot["E_idle_fuel_MJ"] / max(tot["E_fuel_MJ"], 1e-9) * 100, 1),
        "idle_diesel_l_per_h": round(pt.idle(3600)[0] / (F_["diesel"]["LHV_MJ_per_kg"] * 1e6) / dens_d, 2),
        "gear_shifts": int(tot["shifts"]), "infeasible_steps": int(tot["infeasible_steps"]),
        "mean_engine_eff_pct": round(tot["E_engine_MJ"] / max(tot["E_fuel_MJ"], 1e-9) * 100, 1),
        "engine_map": MAP_INFO["source"],
        "fuel_above_measured_torque_pct": round(tot["E_fuel_extrap_MJ"] / max(tot["E_fuel_MJ"], 1e-9) * 100, 1),
    }
    return res


def merge_h2ice(r, r2):
    """Diesel and HVO results (diesel vehicle mass) + hydrogen-engine results from its own run with h2ice extra mass."""
    out = dict(r)
    out["h2ice_h2_kg_per_100km_at_diesel_mass"] = r["h2ice_h2_kg_per_100km"]
    out.update({k: v for k, v in r2.items() if k.startswith("h2ice_")})
    out.update({"h2ice_mass_kg": r2["mass_kg"], "h2ice_extra_mass_kg": r2["extra_mass_kg"], "h2ice_payload_kg": r2["payload_kg"], "h2ice_timber_t_per_round_trip": r2["timber_t_per_round_trip"],
                "h2ice_fuel_energy_kWh_per_km": r2["fuel_energy_kWh_per_km"], "h2ice_wheel_work_kWh_per_km": r2["wheel_work_kWh_per_km"]})
    return out


if __name__ == "__main__":
    CFG = json.load(open(os.path.join(HERE, "vehicles.json")))
    print("Engine map:", select_engine_map()["label"])
    results = []
    for tag in MISSIONS:
        if not os.path.exists(os.path.join(HERE, f"cycle_{tag}_distance.csv")):
            print("skip", tag); continue
        r = run(tag)                                   # diesel and HVO100 at the diesel vehicle mass
        x = CFG["vehicles"][r["vehicle"]].get("h2ice_mass", {}).get("extra_mass_kg", 0.0)
        r = merge_h2ice(r, run(tag, extra_mass=x, out_name=f"consumption_h2ice_{tag}.csv"))   # hydrogen engine with its tanks
        results.append(r)
        print(json.dumps(r))
    with open(os.path.join(HERE, "consumption_summary.json"), "w") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(HERE, "consumption_summary.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        wr.writeheader(); wr.writerows(results)
else:
    CFG = json.load(open(os.path.join(HERE, "vehicles.json")))
    select_engine_map()
