"""
electric.py - FCEV and BEV energy use along the mission cycles (same backward chain as powertrain.py)

Per 10 m step of cycle_<mission>_distance.csv:
  wheel force and power (same equation and masses as powertrain.py)
    -> gearbox + axle (fixed efficiency), gear with the lowest electric power
    -> electric machine + inverter loss model (per unit of motor peak power)
    -> regenerative braking, limited by driven-axle load, motor, battery and a low-speed cut-off
    -> DC bus = motor + auxiliaries
  BEV : the battery covers the DC bus
  FCEV: fuel cell (through a DC/DC converter) follows the filtered demand with a state-of-charge
        correction; the buffer battery covers the peaks and takes the regenerated energy.
        Hydrogen = fuel cell net energy / system efficiency(load), for a new (BOL) and an aged (EOL) system.

Inputs : vehicles.json ("electric" section), cycle_<mission>_distance.csv
Outputs: consumption_bev_<mission>.csv, consumption_fcev_<mission>.csv (one row per step)
         consumption_summary_electric.json
Usage  : python3 electric.py
"""
import csv, json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
G, RHO, DS = 9.82, 1.2, 10.0
LHV_H2 = 120.0 / 3.6                     # kWh/kg
MISSIONS = ["timber_empty", "timber_loaded", "urban_bus", "coach"]
CFG = json.load(open(os.path.join(HERE, "vehicles.json")))
EL = CFG["electric"]


def interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            return ys[i-1] + (x - xs[i-1]) / (xs[i] - xs[i-1]) * (ys[i] - ys[i-1])
    return ys[-1]


# ============================================================== electric drive
class EDrive:
    """Machine + inverter + gearbox + axle. Everything per unit of motor peak power P_max.
    t = torque / T_max, w = speed / base speed; mechanical power = t * w * P_max; limit t <= min(1, 1/w)."""

    def __init__(self, vcfg, eta_axle):
        e = EL["edrive"]
        self.pmax = vcfg["motor_peak_kW"]
        self.cpsr = e["const_power_speed_ratio"]
        self.eta_tr = e["eta_gear"] * eta_axle
        self.v_base = [vcfg["v_top_kmh"] / 3.6 / self.cpsr / e["gear_step"] ** k for k in range(vcfg["n_gears"])][::-1]
        self.inv = e["inverter_loss"]
        s = e["machine_loss_shape"]
        self.shape = (s["c0"], s["k_cu"], s["k_fe"], s["k_fw"])
        self.scale = 1.0
        best = max(t * w / (t * w + self._machine(t, w)) for t in [i / 50 for i in range(1, 51)]
                   for w in [j / 20 for j in range(2, int(self.cpsr * 20) + 1)] if t <= min(1, 1 / w))
        self.scale = (1 / e["machine_peak_efficiency"] - 1) / (1 / best - 1)   # exact: losses scale linearly
        self.v_cut = e["regen_v_cut_kmh"] / 3.6
        self.mu = e["regen_adhesion_use"]

    def _machine(self, t, w):
        c0, kc, ki, kw = self.shape
        return self.scale * (c0 + kc * t * t + ki * w ** 1.5 + kw * w ** 3)

    def loss(self, t, w):                 # per unit of P_max, machine + inverter
        a = self.inv
        return self._machine(t, w) + a["a0"] + a["a1"] * abs(t) + a["a2"] * t * t

    def step(self, v, F, m_driven):
        """Returns dict: p_el [kW] at the DC bus (negative = regeneration), gear, t, w,
        f_regen [N] wheel force taken by the motor when braking, infeasible flag."""
        if F >= 0:
            p_shaft = F * v / self.eta_tr / 1e3 / self.pmax          # per unit
            best = None
            for g, vb in enumerate(self.v_base, start=1):
                w = v / vb
                if w > self.cpsr:
                    continue
                t = p_shaft / max(w, 1e-6)
                if t > min(1.0, 1.0 / max(w, 1e-6)):
                    continue
                p = p_shaft + self.loss(t, w)
                if best is None or p < best["p"]:
                    best = {"p": p, "gear": g, "t": t, "w": w}
            if best is None:                                         # beyond the motor limit: saturate
                g = 1 if v / self.v_base[0] <= self.cpsr else len(self.v_base)
                for gg, vb in enumerate(self.v_base, start=1):
                    if v / vb <= self.cpsr:
                        g = gg; break
                w = v / self.v_base[g-1]
                t = min(1.0, 1.0 / max(w, 1e-6))
                best = {"p": t * w + self.loss(t, w), "gear": g, "t": t, "w": w, "infeasible": True}
            best["p_el"] = best.pop("p") * self.pmax
            best["f_regen"] = 0.0
            return best
        # braking
        f_reg = 0.0 if v < self.v_cut else min(-F, self.mu * m_driven * G)
        best = {"p_el": 0.0, "gear": 0, "t": 0.0, "w": 0.0, "f_regen": 0.0}
        if f_reg > 0:
            for g, vb in enumerate(self.v_base, start=1):
                w = v / vb
                if w > self.cpsr:
                    continue
                t_lim = min(1.0, 1.0 / max(w, 1e-6))
                p_sh = f_reg * v * self.eta_tr / 1e3 / self.pmax
                t = min(p_sh / max(w, 1e-6), t_lim)
                p = -(t * w) + self.loss(t, w)
                if p < best["p_el"] / self.pmax - 1e-12:
                    best = {"p_el": p * self.pmax, "gear": g, "t": -t, "w": w,
                            "f_regen": t * w * self.pmax * 1e3 / self.eta_tr / v}
        return best


# ============================================================== battery
class Battery:
    def __init__(self, kwh, soc0, c_dis, c_chg):
        self.E, self.soc = kwh, soc0
        self.p_dis, self.p_chg = c_dis * kwh, c_chg * kwh
        self.r = EL["battery"]["loss_at_1C"]

    def apply(self, p_term, dt):
        """p_term [kW] at the terminals (+ discharge). Returns (terminal kWh, loss kWh) and updates SOC."""
        loss = self.r * p_term * p_term / self.E
        self.soc -= (p_term + loss) * dt / 3600 / self.E
        return p_term * dt / 3600, loss * dt / 3600


# ============================================================== fuel cell system
class FuelCell:
    def __init__(self, p_rated):
        f = EL["fuel_cell"]
        self.pr, self.f = p_rated, f
        self.pmin, self.ramp = f["min_load_frac"] * p_rated, f["ramp_frac_per_s"] * p_rated
        self.p, self.on, self.starts, self.pf = 0.0, False, 0, 0.0

    def eta(self, p, state):
        return interp(max(p / self.pr, self.f["load_frac"][0]), self.f["load_frac"], self.f["eta_sys_" + state])

    def dcdc(self, p):                    # kW out of the converter
        if p <= 0:
            return 0.0
        d, x = self.f["dcdc_loss"], p / self.pr
        return p - self.pr * (d["p0"] + d["k1"] * x + d["k2"] * x * x)

    def target(self, p_load, soc, dt):
        """Power follower: filtered DC-bus demand + state-of-charge correction, on/off with hysteresis, ramp limit."""
        e = self.f["ems"]
        self.pf += (1 - math.exp(-dt / e["filter_tau_s"])) * (p_load - self.pf)
        p_req = self.pf + self.pr * (e["soc_ref"] - soc) / e["soc_gain_band"]
        if not self.on and p_req >= self.pmin:
            self.on = True; self.starts += 1
        elif self.on and p_req < 0.5 * self.pmin:
            self.on = False
        tgt = min(max(p_req, self.pmin), self.pr) if self.on else 0.0
        self.p_prev, self.dt_last = self.p, dt            # kept for the back-off when the battery is full
        self.p += max(-self.ramp * dt, min(self.ramp * dt, tgt - self.p))
        return self.p


# ============================================================== cycle -> wheel
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


def wheel_steps(tag, extra_mass=0.0):
    mcfg = CFG["missions"][tag]
    m, _ = mission_mass(mcfg, extra_mass)           # extra_mass_kg of the powertrain (battery, tanks), capped at max_gross_kg
    m_eff = m + mcfg["rot_mass_kg"]
    rows = list(csv.DictReader(open(os.path.join(HERE, f"cycle_{tag}_distance.csv"))))
    for i in range(len(rows) - 1):
        r0, r1 = rows[i], rows[i+1]
        v0, v1 = float(r0["v_sim_kmh"]) / 3.6, float(r1["v_sim_kmh"]) / 3.6
        vm, a = 0.5 * (v0 + v1), (v1 * v1 - v0 * v0) / (2 * DS)
        grade = float(r0["grade_pct"]) / 100
        al = math.atan(grade)
        cr = mcfg["cr_gravel"] if r0["surface"] == "gravel" else mcfg["cr_asphalt"]
        F = m_eff * a + m * G * math.sin(al) + cr * m * G * math.cos(al) + 0.5 * RHO * mcfg["CdA_m2"] * vm * vm
        dwell = float(r0["stop_dwell_s"])
        dt = max(float(r1["t_s"]) - float(r0["t_s"]) - dwell, 1e-6)
        yield {"s_m": int(float(r0["s_m"])), "t_s": round(float(r0["t_s"]), 1), "dt_drive_s": round(dt, 2), "dwell_s": dwell,
               "v_kmh": round(vm * 3.6, 2), "a_mps2": round(a, 3), "grade_pct": round(grade * 100, 2), "surface": r0["surface"],
               "F_wheel_N": round(F), "P_wheel_kW": round(F * vm / 1e3, 2), **lateral_and_braking(r0, vm, F, m, m_eff),
               "E_wheel_traction_kWh": round(max(F, 0) * DS / 3.6e6, 6), "E_wheel_braking_kWh": round(max(-F, 0) * DS / 3.6e6, 6),
               "_v": vm, "_F": F, "_dt": dt, "_v0": v0, "_v1": v1}


def run(tag, kind):
    mcfg = CFG["missions"][tag]
    vname = mcfg["vehicle"]
    ve = EL["vehicles"][vname]
    drv = EDrive(ve, CFG["vehicles"][vname]["eta_axle"])
    aux = ve["aux_el_kW"]
    extra = ve[kind].get("extra_mass_kg", 0.0)
    m_sim, payload = mission_mass(mcfg, extra)
    m_eff_sim = m_sim + mcfg["rot_mass_kg"]
    m_drv = m_sim * ve["driven_axle_load_share"][tag]
    if kind == "bev":
        b = ve["bev"]; bat = Battery(b["battery_kWh"], b["soc_start"], b["C_discharge"], b["C_charge"])
        soc_max, soc_min = b["soc_start"], b["soc_min"]
    else:
        f = ve["fcev"]; e = EL["fuel_cell"]["ems"]
        bat = Battery(f["battery_kWh"], e["soc_ref"], f["C_discharge"], f["C_charge"])
        soc_max, soc_min = e["soc_max"], e["soc_min"]
        fc = FuelCell(f["fc_net_kW"])
    soc0 = bat.soc
    out, cum, n_inf = [], 0.0, 0
    for st in wheel_steps(tag, extra):
        v, F, dt = st.pop("_v"), st.pop("_F"), st.pop("_dt")
        v0s, v1s = st.pop("_v0"), st.pop("_v1")
        # Braking to a standstill: below the regeneration cut-off speed (regen_v_cut_kmh) the friction brakes stop the
        # vehicle. With 10 m steps the last braking step has a mean speed above the cut-off, so the kinetic energy below
        # the cut-off, 1/2 m_eff v_cut^2, is taken off the regenerable braking force of that step (friction brakes).
        F_reg = F
        if F < 0 and v1s < 0.05:
            F_reg = min(F + 0.5 * m_eff_sim * min(v0s, drv.v_cut) ** 2 / DS, 0.0)
        acc = {k: 0.0 for k in ["mot", "regen", "aux", "bat", "loss", "fc", "dc", "h2b", "h2e", "fric"]}
        d = {"gear": 0, "t": 0.0, "w": 0.0, "p_el": 0.0, "f_regen": 0.0}
        deficit, p_fc_drive, p_bat_drive, p_mot_drive = 0, 0.0, 0.0, 0.0
        for sub, tt in (("dwell", st["dwell_s"]), ("drive", dt)):
            if tt <= 0:
                continue
            if sub == "drive" and v >= 0.05:
                if F < 0 and F_reg >= 0:                         # whole step on the friction brakes
                    d = {"gear": 0, "t": 0.0, "w": 0.0, "p_el": 0.0, "f_regen": 0.0}
                else:
                    d = drv.step(v, F_reg, m_drv)
                if d.get("infeasible"):
                    deficit = 1
            p_mot = d["p_el"] if sub == "drive" and v >= 0.05 else 0.0
            p_chg_ok = bat.p_chg if bat.soc < soc_max else 0.0
            p_dc = p_fc = 0.0
            if kind == "fcev":
                p_fc = fc.target(p_mot + aux, bat.soc, tt)
                p_dc = fc.dcdc(p_fc)
                short = (p_mot + aux - p_dc) - (bat.p_dis if bat.soc > soc_min else 0.0)
                if short > 0:                                    # battery cannot cover the peak: fuel cell steps up
                    p_fc = min(fc.pr, p_fc + short / 0.97); fc.p = p_fc; fc.on = True
                    p_dc = fc.dcdc(p_fc)
                    if (p_mot + aux - p_dc) - bat.p_dis > 1.0:
                        deficit = 1
            p_bat = p_mot + aux - p_dc
            if p_bat < -p_chg_ok:                                # more charging than the battery accepts
                # Priority to regeneration (free energy): 1) the fuel cell backs off, but stays on at its minimum load
                # and within its ramp limit; 2) regeneration is reduced (friction brakes); 3) only if the battery still
                # cannot take the fuel cell power (e.g. SOC at soc_max) the fuel cell goes below its minimum load.
                exc = -p_chg_ok - p_bat
                if kind == "fcev" and p_fc > 0:
                    floor = max(fc.pmin, fc.p_prev - fc.ramp * fc.dt_last)
                    p_new = max(floor, p_fc - exc / 0.97)
                    if p_new < p_fc:
                        p_fc = p_new; fc.p = p_fc; p_dc = fc.dcdc(p_fc)
                        exc = -p_chg_ok - (p_mot + aux - p_dc)
                if exc > 0:
                    cut = min(exc, max(-p_mot, 0.0))
                    p_mot += cut; exc -= cut
                if exc > 0 and kind == "fcev":
                    p_fc = max(0.0, p_fc - exc / 0.97); fc.p = p_fc; p_dc = fc.dcdc(p_fc)
                p_bat = p_mot + aux - p_dc
            if kind == "bev" and (p_bat > bat.p_dis or bat.soc <= soc_min):
                deficit = 1
            e_t, e_l = bat.apply(p_bat, tt)
            h = tt / 3600
            acc["mot"] += max(p_mot, 0) * h; acc["regen"] += max(-p_mot, 0) * h; acc["aux"] += aux * h
            acc["bat"] += e_t; acc["loss"] += e_l
            if kind == "fcev":
                acc["fc"] += p_fc * h; acc["dc"] += p_dc * h
                if p_fc > 0:
                    acc["h2b"] += p_fc * h / fc.eta(p_fc, "BOL") / LHV_H2
                    acc["h2e"] += p_fc * h / fc.eta(p_fc, "EOL") / LHV_H2
            if sub == "drive":
                p_fc_drive, p_bat_drive, p_mot_drive = p_fc, p_bat, p_mot
                if F < 0:
                    used = d["f_regen"] * (max(-p_mot, 0) / -d["p_el"] if d["p_el"] < 0 else 0.0)
                    acc["fric"] += (-F - used) * DS / 3.6e6
        n_inf += deficit
        st.update({"gear": d["gear"], "motor_torque_frac": round(d["t"], 3), "motor_speed_frac": round(d["w"], 3),
                   "P_motor_el_kW": round(p_mot_drive, 2), "E_motor_el_kWh": round(acc["mot"], 6),
                   "E_regen_el_kWh": round(acc["regen"], 6), "E_friction_brake_kWh": round(acc["fric"], 6),
                   "E_aux_kWh": round(acc["aux"], 6)})
        if kind == "bev":
            cum += acc["bat"]
            st.update({"P_battery_kW": round(p_bat_drive, 2), "E_battery_kWh": round(acc["bat"], 6),
                       "E_battery_loss_kWh": round(acc["loss"], 6), "SOC": round(bat.soc, 5),
                       "E_battery_cum_kWh": round(cum, 4), "power_deficit": deficit})
        else:
            cum += acc["h2b"]
            st.update({"P_fc_net_kW": round(p_fc_drive, 2), "fc_load_frac": round(p_fc_drive / fc.pr, 3),
                       "eta_fc_sys_BOL": round(fc.eta(p_fc_drive, "BOL"), 4) if p_fc_drive > 0 else 0,
                       "E_fc_net_kWh": round(acc["fc"], 6), "E_dcdc_out_kWh": round(acc["dc"], 6),
                       "P_battery_kW": round(p_bat_drive, 2), "E_battery_kWh": round(acc["bat"], 6),
                       "E_battery_loss_kWh": round(acc["loss"], 6), "SOC": round(bat.soc, 5),
                       "h2_g_BOL": round(acc["h2b"] * 1e3, 5), "h2_g_EOL": round(acc["h2e"] * 1e3, 5),
                       "h2_cum_kg_BOL": round(cum, 5), "power_deficit": deficit})
        out.append(st)
    with open(os.path.join(HERE, f"consumption_{kind}_{tag}.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        wr.writeheader(); wr.writerows(out)
    km = len(out) * DS / 1000
    S = lambda k: sum(r[k] for r in out)
    res = {"powertrain": kind, "mission": tag, "km": km, "wheel_traction_kWh_per_km": round(S("E_wheel_traction_kWh") / km, 3),
           "wheel_braking_kWh_per_km": round(S("E_wheel_braking_kWh") / km, 3),
           "regen_el_kWh_per_km": round(S("E_regen_el_kWh") / km, 3),
           "regen_share_of_braking_pct": round(S("E_regen_el_kWh") / max(S("E_wheel_braking_kWh"), 1e-9) * 100, 1),
           "motor_el_kWh_per_km": round(S("E_motor_el_kWh") / km, 3), "aux_kWh_per_km": round(S("E_aux_kWh") / km, 3),
           "drive_eff_wheel_over_motor_el_pct": round(S("E_wheel_traction_kWh") / S("E_motor_el_kWh") * 100, 1),
           "soc_start": round(soc0, 4), "soc_end": round(bat.soc, 4), "power_deficit_steps": n_inf}
    res.update({"mass_kg": m_sim, "extra_mass_kg": extra, "payload_kg": payload, "n_pax": mcfg.get("n_pax"),
                "timber_t_per_round_trip": round(payload / 1000, 2) if payload is not None else None})
    if kind == "bev":
        e_chem = (soc0 - bat.soc) * bat.E
        eta_chg = EL["battery"]["charger_efficiency"] * (1 - bat.r * EL["battery"]["depot_charge_C_rate"])
        res.update({"battery_kWh_per_km": round(e_chem / km, 3), "grid_kWh_per_km": round(e_chem / eta_chg / km, 3),
                    "battery_used_pct_of_installed": round((soc0 - bat.soc) * 100, 1)})
    else:
        e_fc, e_dc = S("E_fc_net_kWh"), S("E_dcdc_out_kWh")
        dE = (soc0 - bat.soc) * bat.E
        for s_ in ("BOL", "EOL"):
            h2 = S(f"h2_g_{s_}") / 1e3
            eta_fc = e_fc / (h2 * LHV_H2)
            corr = dE / (eta_fc * (e_dc / e_fc) * (1 - bat.r) * LHV_H2)
            res.update({f"h2_kg_per_100km_{s_}_raw": round(h2 / km * 100, 3),
                        f"h2_kg_per_100km_{s_}": round((h2 + corr) / km * 100, 3), f"mean_fc_sys_eff_{s_}_pct": round(eta_fc * 100, 1)})
        res.update({"fc_starts": fc.starts, "fc_mean_load_pct": round(e_fc / (sum(r["dt_drive_s"] + r["dwell_s"] for r in out) / 3600) / fc.pr * 100, 1)})
    return res


if __name__ == "__main__":
    results = []
    for kind in ("bev", "fcev"):
        for tag in MISSIONS:
            r = run(tag, kind); results.append(r); print(json.dumps(r))
    json.dump(results, open(os.path.join(HERE, "consumption_summary_electric.json"), "w"), indent=2)
