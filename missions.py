"""
distance-based mission profiles (a "mini-VECTO" cycle generator)

Each mission = a route described along distance s: speed limit, curve radius, road grade,
surface, and stops. A driver model then produces the simulated speed profile v(s):
  1. v_lim(s)    = min(legal limit, curve limit)            (Noreland / Trafikverket)
  2. backward    : slow down in time for curves, limits and stops (decel table)
  3. forward     : accelerate as the driver does (accel table) and as the power allows
Output per mission: distance-based CSV (VECTO style, 10 m step) + 1 Hz time-based CSV + plot.
Buses: since 0.3 the base case runs on the VECTO Urban and Coach cycles (vecto_route), if the files are in
data/private/vecto_cycles; the synthetic bus routes below are kept as a sensitivity case.

Timber truck: accel/decel tables from Noreland, Skogforsk Arbetsrapport 1247-2025, Tab. 3-4.
Buses: accel cap 1.0 m/s2 and decel 0.8 m/s2 (VECTO Heavy Urban output shows max 1.10 / 1.00).
Everything marked ASSUMPTION is ours and should be confirmed with manufacturer data.
"""
import numpy as np, csv, os, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.dirname(os.path.abspath(__file__))
DS = 10.0            # m, distance step (VECTO uses distance-based cycles)
G, RHO = 9.82, 1.2   # as in Noreland

# ------------------------------------------------------------------ driver tables (Noreland)
SPD_BINS = np.array([2.5, 10, 20, 30, 40, 50, 60, 70, 80, 90]) / 3.6   # m/s, class centres
ACC = {("loaded", "winter"): [0.31, 0.26, 0.29, 0.29, 0.25, 0.21, 0.18, 0.16, 0.13, 0.12],
       ("loaded", "summer"): [0.35, 0.31, 0.32, 0.31, 0.27, 0.22, 0.19, 0.17, 0.14, 0.12],
       ("empty", "winter"):  [0.35, 0.33, 0.36, 0.41, 0.39, 0.33, 0.29, 0.24, 0.17, 0.13],
       ("empty", "summer"):  [0.40, 0.39, 0.38, 0.44, 0.43, 0.37, 0.33, 0.28, 0.19, 0.13]}
DEC = {("loaded", "winter"): [0.32, 0.33, 0.38, 0.39, 0.32, 0.26, 0.22, 0.19, 0.15, 0.12],
       ("loaded", "summer"): [0.35, 0.41, 0.42, 0.45, 0.37, 0.29, 0.24, 0.20, 0.16, 0.13],
       ("empty", "winter"):  [0.34, 0.39, 0.46, 0.52, 0.46, 0.38, 0.31, 0.26, 0.20, 0.15],
       ("empty", "summer"):  [0.37, 0.44, 0.48, 0.56, 0.52, 0.43, 0.35, 0.29, 0.22, 0.17]}

def table(tab, v):
    return np.interp(v, SPD_BINS, tab)

# ------------------------------------------------------------------ curve speed (Trafikverket)
def v_curve(R, E=0.0):
    """Max speed [m/s] in a curve of radius R [m], Trafikverket VV 2004:80 (E = superelevation %).
    R > v^2 / ((0.28*exp(-0.0096 V) + E/100) g), V in km/h -> solve by fixed point."""
    if not np.isfinite(R):
        return np.inf
    v = 20.0
    for _ in range(50):
        f = 0.28*np.exp(-0.0096*v*3.6) + E/100
        v = np.sqrt(R*f*G)
    return v

# ------------------------------------------------------------------ route builder
class Route:
    def __init__(self, name):
        self.name = name
        self.segs = []            # (length_m, limit_kmh, surface, road_class, grade_amp_pct, wavelength_m)
        self.curves = []          # (s_m, radius_m)
        self.stops = []           # (s_m, dwell_s, kind)
        self.slow = []            # (s_start, s_end, limit_kmh) local restrictions (roundabouts, junctions)

    def seg(self, L, limit, surface, rc, amp, wl):
        self.segs.append((L, limit, surface, rc, amp, wl))

    def build(self, seed):
        rng = np.random.default_rng(seed)
        L = sum(s[0] for s in self.segs)
        s = np.arange(0, L + DS/2, DS)
        n = len(s)
        lim = np.zeros(n); surf = np.empty(n, dtype=object); rc = np.empty(n, dtype=object)
        amp = np.zeros(n); wl = np.zeros(n)
        x0 = 0
        for (Lg, limit, sf, c, a, w) in self.segs:
            m = (s >= x0) & (s <= x0 + Lg)
            lim[m] = limit; surf[m] = sf; rc[m] = c; amp[m] = a; wl[m] = w
            x0 += Lg
        # grade: sum of 3 random-phase sinusoids scaled to the segment amplitude (reproducible seed)
        grade = np.zeros(n)
        for k, frac in enumerate([1.0, 0.5, 0.25]):
            ph = rng.uniform(0, 2*np.pi)
            grade += frac*np.sin(2*np.pi*s/(wl*(0.6 + 0.4*k) + 1e-9) + ph)
        grade = grade/1.75*amp/100                          # -> fraction
        # close the loop: same elevation at both ends (no net potential energy bias) - ASSUMPTION
        z = np.concatenate([[0], np.cumsum(grade[:-1]*DS)])
        grade -= z[-1]/L
        # smooth transitions
        k = int(60/DS); ker = np.ones(k)/k
        grade = np.convolve(grade, ker, mode="same")
        z = np.concatenate([[0], np.cumsum(grade[:-1]*DS)])
        # speed limit incl. curves and local restrictions
        vlim = lim/3.6
        radius = np.full(n, np.inf)                          # curve radius per step [m], inf = straight
        for (sc, R) in self.curves:
            vc = v_curve(R)
            m = np.abs(s - sc) <= max(30, R*0.3)            # curve arc length ~ 0.6 R
            vlim[m] = np.minimum(vlim[m], vc)
            radius[m] = np.minimum(radius[m], R)
        for (a0, a1, l) in self.slow:
            m = (s >= a0) & (s <= a1)
            vlim[m] = np.minimum(vlim[m], l/3.6)
        dwell = np.zeros(n)
        for (sp, d, kind) in self.stops:
            i = int(round(sp/DS)); i = min(max(i, 0), n-1)
            vlim[i] = 0.0; dwell[i] += d
        vlim[0] = 0.0; vlim[-1] = 0.0
        self.s, self.vlim, self.grade, self.z, self.surf, self.rc, self.dwell = s, vlim, grade, z, surf, rc, dwell
        self.limit_kmh = lim; self.radius = radius
        return self

    def reversed(self, name):
        r = Route(name)
        r.s = self.s.copy()
        r.vlim = self.vlim[::-1].copy(); r.grade = -self.grade[::-1].copy()
        r.z = self.z[::-1].copy(); r.surf = self.surf[::-1].copy(); r.rc = self.rc[::-1].copy()
        r.dwell = self.dwell[::-1].copy(); r.limit_kmh = self.limit_kmh[::-1].copy(); r.radius = self.radius[::-1].copy()
        return r

# ------------------------------------------------------------------ VECTO cycle importer
def vecto_route(path, name):
    """Route from a VECTO distance-based cycle file: columns <s> [m], <v> [km/h] target speed, <grad> [%], <stop> [s]
    (a 5th column, e.g. <HW> in the coach cycle, is ignored). Target speed and grade hold from one row to the next;
    a row with a stop time (or v = 0) is a stop at that distance. The same driver model as for the synthetic routes
    turns the target speed into the driven speed, so accelerations follow the bus caps below, not VECTO's driver."""
    rows = []
    for k, r in enumerate(csv.reader(open(path, encoding="utf-8-sig"))):
        if k == 0 or not r or not r[0].strip():
            continue
        rows.append([float(x) for x in r[:4]])
    S, V, Gr, St = (np.array(c) for c in zip(*rows))
    L = float(np.floor(S[-1] / DS) * DS)
    s = np.arange(0, L + DS/2, DS)
    n = len(s)
    idx = np.clip(np.searchsorted(S, s, side="right") - 1, 0, len(S) - 1)
    r = Route(name)
    r.s = s
    r.limit_kmh = V[idx].copy()
    r.vlim = V[idx] / 3.6
    r.grade = Gr[idx] / 100
    r.z = np.concatenate([[0], np.cumsum(r.grade[:-1] * DS)])
    r.surf = np.array(["asphalt"] * n, dtype=object)
    r.rc = np.array(["VECTO " + os.path.splitext(os.path.basename(path))[0]] * n, dtype=object)
    r.radius = np.full(n, np.inf)
    r.dwell = np.zeros(n)
    for Si, Vi, Sti in zip(S, V, St):
        if Sti > 0 or Vi == 0:
            i = min(max(int(round(Si / DS)), 0), n - 1)
            r.vlim[i] = 0.0
            r.dwell[i] += Sti
    r.vlim[0] = 0.0; r.vlim[-1] = 0.0
    r.source = "VECTO cycle " + os.path.basename(path)
    return r


# ------------------------------------------------------------------ vehicle for power limit
CR = {"asphalt": 0.00676, "gravel": 0.0126}   # Noreland (0 degC); buses use asphalt value scaled below

class Veh:
    def __init__(self, name, m, m_rot, cda, p_wheel_max, cr_scale=1.0, acc=None, dec=None,
                 acc_cap=None, dec_cap=None):
        self.name, self.m, self.m_rot, self.cda = name, m, m_rot, cda
        self.p = p_wheel_max; self.cr_scale = cr_scale
        self.acc, self.dec, self.acc_cap, self.dec_cap = acc, dec, acc_cap, dec_cap

    def a_driver(self, v):
        if self.acc is not None:
            return table(self.acc, v)
        return self.acc_cap

    def d_driver(self, v):
        if self.dec is not None:
            return table(self.dec, v)
        return self.dec_cap

    def f_res(self, v, grade, surf):
        cr = CR.get(surf, CR["asphalt"])*self.cr_scale
        al = np.arctan(grade)
        return self.m*G*(cr*np.cos(al) + np.sin(al)) + 0.5*RHO*self.cda*v*v

    def a_power(self, v, grade, surf):
        F = self.p/max(v, 1.0)
        return (F - self.f_res(v, grade, surf))/(self.m + self.m_rot)

# ------------------------------------------------------------------ driver model (backward + forward sweep)
def drive(route, veh):
    s, vlim, n = route.s, route.vlim, len(route.s)
    # backward sweep: be able to reach every downstream limit with comfortable deceleration
    vb = vlim.copy()
    for i in range(n-2, -1, -1):
        d = veh.d_driver(vb[i+1])
        vb[i] = min(vb[i], np.sqrt(vb[i+1]**2 + 2*d*DS))
    # forward sweep: accelerate like the driver, limited by power; hills can slow the truck
    v = np.zeros(n)
    for i in range(n-1):
        if vb[i] == 0.0 and i > 0:
            v[i] = 0.0
        a_drv = veh.a_driver(v[i])
        a_pow = veh.a_power(v[i], route.grade[i], route.surf[i])
        a = min(a_drv, a_pow)
        v2 = v[i]**2 + 2*a*DS
        v[i+1] = min(np.sqrt(max(v2, 0.3**2)), vb[i+1])   # 0.3 m/s floor = crawl on a very steep climb
    v[-1] = 0.0
    # time per step
    vm = 0.5*(v[:-1] + v[1:])
    dt = np.where(vm > 0.05, DS/np.maximum(vm, 0.05), 0.0)
    # steps starting or ending at a standstill: use constant-acceleration kinematics
    for i in range(n-1):
        if v[i] < 0.05 or v[i+1] < 0.05:
            vv = max(v[i], v[i+1])
            dt[i] = 2*DS/max(vv, 0.3)
    t = np.concatenate([[0], np.cumsum(dt + route.dwell[:-1])])
    a = np.zeros(n); a[:-1] = (v[1:]**2 - v[:-1]**2)/(2*DS)
    drive.dt = dt
    return v, t, a

def resample_1hz(route, v, t):
    """Time-based 1 Hz trace (s, v, grade), including dwell at stops."""
    T = np.arange(0, t[-1] + 1e-6, 1.0)
    # build a monotonic time axis including dwell plateaus
    tt, ss, vv = [], [], []
    for i in range(len(route.s)):
        tt.append(t[i]); ss.append(route.s[i]); vv.append(v[i])
        if route.dwell[i] > 0:
            tt.append(t[i] + route.dwell[i]); ss.append(route.s[i]); vv.append(0.0)
    # note t already includes dwell for i+1 onward; the plateau entry above shifts correctly
    tt = np.array(tt); ss = np.array(ss); vv = np.array(vv)
    order = np.argsort(tt, kind="stable"); tt, ss, vv = tt[order], ss[order], vv[order]
    sT = np.interp(T, tt, ss); vT = np.interp(T, tt, vv)
    gT = np.interp(sT, route.s, route.grade)
    return T, sT, vT, gT

def stats(route, v, t):
    L = route.s[-1]; T = t[-1]
    dwell = float(np.sum(route.dwell))
    moving = T - dwell
    z = route.z
    climb = np.sum(np.clip(np.diff(z), 0, None))
    return {"length_km": round(L/1000, 1), "duration_min": round(T/60, 1),
            "avg_speed_kmh": round(L/T*3.6, 1),
            "avg_driving_speed_kmh": round(L/max(moving, 1)*3.6, 1),
            "standstill_share_pct": round(dwell/T*100, 1),
            "stops_with_dwell": int(np.sum(route.dwell > 0)), "total_climb_m": round(climb),
            "max_grade_pct": round(float(np.max(np.abs(route.grade))*100), 1)}

def export(route, v, t, a, tag):
    with open(os.path.join(OUT, f"cycle_{tag}_distance.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["s_m", "v_target_kmh", "v_sim_kmh", "a_sim_mps2", "grade_pct", "altitude_m",
                    "surface", "road_class", "stop_dwell_s", "t_s", "curve_radius_m"])
        for i in range(len(route.s)):
            w.writerow([int(route.s[i]), round(min(route.vlim[i], 40)*3.6, 1), round(v[i]*3.6, 2), round(a[i], 3),
                        round(route.grade[i]*100, 2), round(route.z[i], 1), route.surf[i], route.rc[i],
                        round(route.dwell[i], 1), round(t[i], 1),
                        round(route.radius[i], 1) if np.isfinite(route.radius[i]) else 0])   # 0 = straight road
    T, sT, vT, gT = resample_1hz(route, v, t)
    with open(os.path.join(OUT, f"cycle_{tag}_1Hz.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "s_m", "v_kmh", "grade_pct"])
        for i in range(len(T)):
            w.writerow([int(T[i]), round(sT[i], 1), round(vT[i]*3.6, 2), round(gT[i]*100, 2)])


# ------------------------------------------------------------------ power at the wheel, consistent with powertrain.py
_VJ = json.load(open(os.path.join(OUT, "vehicles.json"))) if os.path.exists(os.path.join(OUT, "vehicles.json")) else None
def p_wheel_max(vehicle, fallback):
    """Max sustained wheel power [W] = (rated - aux) x gearbox x axle x 0.97 margin for discrete gears."""
    if _VJ is None:
        return fallback
    v = _VJ["vehicles"][vehicle]; gb = _VJ["gearboxes"][v["gearbox"]]
    return (v["engine"]["rated_power_kW"] - v["aux_mech_kW"])*1e3*gb["eta_indirect"]*v["eta_axle"]*0.97

def gross_mass(c):
    """Mission mass without powertrain extra mass: curb + passengers (buses) or mass_kg (timber truck)."""
    if "curb_kg" in c:
        return c["curb_kg"] + c["n_pax"] * c["kg_per_pax"]
    return c["mass_kg"]


def mp(tag, m, rot, cda, cr_scale=1.0):
    """Mass, rotating mass, CdA and rolling-resistance scale of a mission, read from vehicles.json ("missions")."""
    if _VJ is None:
        return m, rot, cda, cr_scale
    c = _VJ["missions"][tag]
    return gross_mass(c), c["rot_mass_kg"], c["CdA_m2"], c["cr_asphalt"]/CR["asphalt"]

# ================================================================== MISSIONS
# ---------------- Timber truck: mill -> forest (empty), forest -> mill (loaded), 100 km per leg
tt = Route("Timber truck route, 100 km")
# ASSUMPTION: road mix of a typical Swedish haul (Noreland: road class 0-5 ~80 km/h, 6 <=50, 7-9 private)
tt.seg(1500, 50, "asphalt", "urban/industrial (class 6)", 1.0, 1500)     # mill area
tt.seg(62000, 80, "asphalt", "national road (class 1-3)", 3.0, 7000)     # main road
tt.seg(3000, 60, "asphalt", "village passage (class 5-6)", 1.5, 3000)
tt.seg(21000, 70, "asphalt", "secondary road (class 4-5)", 4.0, 4000)
tt.seg(7500, 70, "gravel", "main forest road (class 7)", 5.0, 2000)
tt.seg(3500, 50, "gravel", "forest road (class 8)", 6.0, 1200)
tt.seg(1500, 30, "gravel", "spur road to landing (class 9)", 7.0, 800)
tt.stops += [(1400, 10, "junction stop"), (63600, 10, "junction stop"), (66600, 10, "junction stop"),
             (87600, 5, "junction to forest road")]
tt.slow += [(20000, 20150, 40), (45000, 45150, 40)]   # roundabouts
rng = np.random.default_rng(7)
for x in np.arange(3000, 63000, 3500): tt.curves.append((x + rng.uniform(-800, 800), rng.uniform(350, 900)))
for x in np.arange(67000, 88000, 1400): tt.curves.append((x + rng.uniform(-300, 300), rng.uniform(150, 450)))
for x in np.arange(88200, 99500, 450): tt.curves.append((x + rng.uniform(-100, 100), rng.uniform(45, 180)))
tt.build(seed=11)
# segments are listed mill -> forest: the empty leg runs that way, the loaded leg runs it in reverse
tt_empty, tt_loaded = tt, tt.reversed("Timber truck, loaded leg (forest -> mill)")
tt_empty.name = "Timber truck, empty leg (mill -> forest)"

truck_empty = Veh("Timber truck empty", *mp("timber_empty", 20000, 1400, 10.4)[:3], p_wheel_max("timber_truck", 397e3*0.93),
                  acc=ACC[("empty", "summer")], dec=DEC[("empty", "summer")])
truck_loaded = Veh("Timber truck loaded", *mp("timber_loaded", 74000, 1400, 10.4)[:3], p_wheel_max("timber_truck", 397e3*0.93),
                   acc=ACC[("loaded", "summer")], dec=DEC[("loaded", "summer")])

# ---------------- Urban bus: 100 km = 5 round trips on a 10 km line, stop every ~400 m
ub = Route("Urban bus, 100 km (5 round trips of a 10 km line)")
ub.seg(100000, 50, "asphalt", "urban street", 2.5, 1500)
x = 0
kstop = 0
while x < 100000 - 200:
    x += 400                                           # ASSUMPTION: 400 m stop spacing
    kstop += 1
    if x >= 100000 - 50: break
    if abs((x % 10000)) < 1:                           # line terminus every 10 km
        ub.stops.append((x, 300, "terminus layover"))  # ASSUMPTION 5 min layover
    else:
        ub.stops.append((x, 20, "bus stop"))           # ASSUMPTION 20 s dwell
for x0 in np.arange(200, 100000, 800):                 # traffic lights every 800 m, 1 in 3 red
    if int(x0/800) % 3 == 0: ub.stops.append((x0, 25, "red light"))
for x0 in np.arange(1000, 100000, 2500): ub.slow.append((x0, x0 + 300, 30))   # 30 km/h zones
for x0 in np.arange(600, 100000, 1100): ub.curves.append((x0, 25))             # street corners
ub.build(seed=21)
# ASSUMPTION: 12 m low-floor bus, curb ~12 t (VECTO example: 13.6 t incl. 1.6 t low load) + avg 40 pax x 68 kg
urban_bus = Veh("Urban bus 12 m", *mp("urban_bus", 14700, 600, 6.5)[:3], p_wheel_max("urban_bus", 250e3*0.90), cr_scale=mp("urban_bus", 0, 0, 0, 0.95)[3],
                acc_cap=1.0, dec_cap=0.8)

# ---------------- Coach: 100 km intercity (motorway + rural), 3 intermediate stops
co = Route("Coach, 100 km intercity")
co.seg(4000, 50, "asphalt", "city exit", 1.0, 800)
co.seg(6000, 70, "asphalt", "suburban road", 1.5, 1200)
co.seg(70000, 100, "asphalt", "motorway", 3.0, 7000)      # ASSUMPTION 100 km/h coach limit on motorway
co.seg(16000, 80, "asphalt", "rural road", 4.0, 3500)
co.seg(4000, 50, "asphalt", "city entry", 1.0, 800)
co.stops += [(2000, 60, "stop"), (10500, 5, "junction"), (48000, 120, "bus station"),
             (82000, 5, "junction"), (98000, 60, "stop")]
co.slow += [(9800, 10000, 40), (80500, 80700, 40)]
for x0 in np.arange(81000, 96000, 1200): co.curves.append((x0, 350))
co.build(seed=31)
# ASSUMPTION: 13 m coach, ~14 t curb + 40 pax x 80 kg incl. luggage
coach = Veh("Coach 13 m", *mp("coach", 17200, 700, 5.0)[:3], p_wheel_max("coach", 340e3*0.93), cr_scale=mp("coach", 0, 0, 0, 0.95)[3], acc_cap=0.8, dec_cap=0.6)

# ---------------- VECTO bus cycles (provided by AB Volvo, oct 2026; kept in data/private/vecto_cycles, not published)
# Base case: urban bus on VECTO Urban, coach on VECTO Coach. Sensitivity: Heavy Urban, Suburban and the synthetic routes above.
# If the files are missing the synthetic routes are used as base case (as before, version 0.2.1).
VECTO_DIR = os.path.join(OUT, "data", "private", "vecto_cycles")
VECTO_FILES = {"urban_bus": ("Urban.csv", "Urban bus, VECTO Urban cycle"),
               "coach": ("Coach.csv", "Coach, VECTO Coach cycle"),
               "urban_bus_heavyurban": ("HeavyUrban.csv", "Urban bus, VECTO Heavy Urban cycle"),
               "urban_bus_suburban": ("Suburban.csv", "Urban bus, VECTO Suburban cycle")}


def vecto(tag):
    f, title = VECTO_FILES[tag]
    p = os.path.join(VECTO_DIR, f)
    return vecto_route(p, title) if os.path.exists(p) else None


ub.source = co.source = tt_empty.source = tt_loaded.source = "synthetic route (missions.py)"
ub_v, co_v = vecto("urban_bus"), vecto("coach")
if ub_v is None or co_v is None:
    print("NOTE: VECTO bus cycles not found in data/private/vecto_cycles: synthetic bus and coach routes used.")
missions = [("timber_empty", tt_empty, truck_empty), ("timber_loaded", tt_loaded, truck_loaded),
            ("urban_bus", ub_v or ub, urban_bus), ("coach", co_v or co, coach)]
sensitivity = []
if ub_v is not None:
    sensitivity += [(t, r, urban_bus) for t in ("urban_bus_heavyurban", "urban_bus_suburban") if (r := vecto(t)) is not None]
    sensitivity.append(("urban_bus_synthetic", ub, urban_bus))
if co_v is not None:
    sensitivity.append(("coach_synthetic", co, coach))

summary = {}
fig, axes = plt.subplots(4, 1, figsize=(11, 13), dpi=140)
for ax, (tag, route, veh) in zip(axes, missions):
    v, t, a = drive(route, veh)
    export(route, v, t, a, tag)
    st = stats(route, v, t); st["vehicle"] = veh.name
    st["vehicle_params"] = {"mass_kg": veh.m, "rot_mass_kg": veh.m_rot, "CdA_m2": veh.cda,
                            "p_wheel_max_kW": round(veh.p/1e3, 1), "cr_scale": veh.cr_scale}
    st["title"] = route.name
    st["cycle_source"] = route.source
    summary[tag] = st
    km = route.s/1000
    ax.plot(km, np.minimum(route.vlim, 40)*3.6, color="#b8c4d2", lw=1.0, label="Speed limit incl. curves")
    ax.plot(km, v*3.6, color="#1c5bcc", lw=1.1, label="Simulated speed (driver model)")
    ax.set_ylabel("Speed [km/h]"); ax.set_ylim(0, 110); ax.set_xlim(0, km[-1])
    ax2 = ax.twinx(); ax2.fill_between(km, route.z - route.z.min(), color="#8f6214", alpha=0.12, lw=0)
    ax2.set_ylabel("Relative altitude [m]", color="#8f6214")
    ax.set_title(f"{route.name} — {st['duration_min']} min, avg {st['avg_speed_kmh']} km/h "
                 f"(moving {st['avg_driving_speed_kmh']} km/h), standstill {st['standstill_share_pct']} %",
                 fontsize=10, loc="left")
    ax.grid(alpha=0.25)
axes[0].legend(loc="lower right", fontsize=8)
axes[-1].set_xlabel("Distance [km]")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_mission_profiles.png"))

# zoom figure: first 5 km of each mission
fig, axes = plt.subplots(2, 2, figsize=(11, 6.5), dpi=140)
for ax, (tag, route, veh) in zip(axes.flat, missions):
    v, t, a = drive(route, veh)
    km = route.s/1000; m = km <= (5 if "timber" in tag or tag == "coach" else 3)
    if tag == "timber_loaded":
        m = km <= 12
    ax.plot(km[m], np.minimum(route.vlim, 40)[m]*3.6, color="#b8c4d2", lw=1.2)
    ax.plot(km[m], v[m]*3.6, color="#1c5bcc", lw=1.3)
    ax.set_title(route.name + (" — first 12 km (forest roads)" if tag == "timber_loaded" else " — zoom"), fontsize=9, loc="left")
    ax.set_xlabel("Distance [km]"); ax.set_ylabel("km/h"); ax.grid(alpha=0.25); ax.set_ylim(0, 105)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_mission_zoom.png"))

# sensitivity cycles: same vehicles, other cycles (no figures; results in cycle_sensitivity.py)
for tag, route, veh in sensitivity:
    v, t, a = drive(route, veh)
    export(route, v, t, a, tag)
    st = stats(route, v, t); st["vehicle"] = veh.name; st["title"] = route.name
    st["cycle_source"] = route.source; st["sensitivity"] = True
    summary[tag] = st

with open(os.path.join(OUT, "mission_summary.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(json.dumps(summary, indent=2))

# refresh the interactive site data (data/missions_data.js) if the builder is next to this script
try:
    import build_site
    build_site.main()
except ImportError:
    pass
