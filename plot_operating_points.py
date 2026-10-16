"""Engine operating points over the efficiency map, per mission (reads consumption_<mission>.csv)."""
import csv, json, os, math
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
import powertrain as ptm
HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, "vehicles.json")))
tags = [("timber_empty","Timber truck, empty"),("timber_loaded","Timber truck, loaded"),("urban_bus","Urban bus"),("coach","Coach")]
summary = {r["mission"]: r for r in json.load(open(os.path.join(HERE, "consumption_summary.json")))}
fig, axs = plt.subplots(2, 2, figsize=(15, 9.5), dpi=140)
for ax, (tag, name) in zip(axs.flat, tags):
    veh = cfg["vehicles"][cfg["missions"][tag]["vehicle"]]
    eng = ptm.Engine(veh["engine"])
    N, T = np.meshgrid(np.linspace(600, 2000, 160), np.linspace(10, 2700*eng.k, 160))
    E = np.full(N.shape, np.nan)
    for i in range(N.shape[0]):
        for j in range(N.shape[1]):
            if T[i, j] <= eng.t_max(N[i, j]):
                E[i, j] = T[i, j]*ptm.w(N[i, j])/eng.fuel_power(N[i, j], T[i, j])
    top = 0.50 if ptm.MAP is None else 0.45                 # colour scale: up to the peak of the map in use
    cs = ax.contourf(N, T, E, levels=np.linspace(0.20, top, 16 if ptm.MAP is None else 11), cmap="Blues", alpha=0.75)
    lines = [0.40, 0.45, 0.48, 0.495] if ptm.MAP is None else [0.36, 0.40, 0.42, 0.435]
    cl = ax.contour(N, T, E, levels=lines, colors="#1f2d3d", linewidths=0.6)
    ax.clabel(cl, fmt=lambda x: f"{x*100:.1f}".rstrip("0").rstrip(".") + " %", fontsize=7)
    if ptm.MAP is not None:                                 # measured points, at the same BMEP for scaled engines
        ax.scatter([p[0] for p in ptm.MAP.points], [p[1]*eng.k for p in ptm.MAP.points], s=7, c="#1f2d3d",
                   marker="+", lw=0.6, label="Measured map points")
    nn = np.linspace(600, 2000, 200); ax.plot(nn, [eng.t_max(x) for x in nn], "k", lw=2)
    rows = list(csv.DictReader(open(os.path.join(HERE, f"consumption_{tag}.csv"))))
    n = np.array([float(r["n_rpm"]) for r in rows]); tq = np.array([float(r["T_engine_Nm"]) for r in rows])
    dt = np.array([float(r["dt_drive_s"]) for r in rows]); ef = np.array([float(r["E_fuel_MJ"]) for r in rows])
    m = (tq > 0) & (dt > 0)
    ax.scatter(n[m], tq[m], s=np.clip(dt[m]*4, 2, 40), c="#d62728", alpha=0.25, lw=0, label="Operating points (size = time)")
    w_eta = summary[tag]["mean_engine_eff_pct"]             # engine work / fuel energy, idling included
    ax.set_title(f"{name}: mean engine efficiency {w_eta:.1f} %", loc="left", fontsize=11)
    ax.set_xlabel("Engine speed [rpm]"); ax.set_ylabel("Torque [Nm]"); ax.set_xlim(600, 2000); ax.set_ylim(0, 2750*eng.k)
axs[0, 0].legend(loc="lower right", fontsize=9)
fig.colorbar(cs, ax=axs, shrink=0.6, label="Brake efficiency")
fig.suptitle("Engine map: " + ptm.MAP_INFO["label"], x=0.125, y=0.94, ha="left", fontsize=11)
fig.savefig(os.path.join(HERE, "fig_operating_points.png"), bbox_inches="tight")
print("ok")
