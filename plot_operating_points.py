"""Engine operating points over the efficiency map, per mission (reads consumption_<mission>.csv)."""
import csv, json, os, math
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
import powertrain as ptm
HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, "vehicles.json")))
tags = [("timber_empty","Timber truck, empty"),("timber_loaded","Timber truck, loaded"),("urban_bus","Urban bus"),("coach","Coach")]
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
    cs = ax.contourf(N, T, E, levels=np.linspace(0.20, 0.50, 16), cmap="Blues", alpha=0.75)
    ax.contour(N, T, E, levels=[0.40, 0.45, 0.48, 0.495], colors="#1f2d3d", linewidths=0.6)
    nn = np.linspace(600, 2000, 200); ax.plot(nn, [eng.t_max(x) for x in nn], "k", lw=2)
    rows = list(csv.DictReader(open(os.path.join(HERE, f"consumption_{tag}.csv"))))
    n = np.array([float(r["n_rpm"]) for r in rows]); tq = np.array([float(r["T_engine_Nm"]) for r in rows])
    dt = np.array([float(r["dt_drive_s"]) for r in rows]); ef = np.array([float(r["E_fuel_MJ"]) for r in rows])
    m = (tq > 0) & (dt > 0)
    ax.scatter(n[m], tq[m], s=np.clip(dt[m]*4, 2, 40), c="#d62728", alpha=0.25, lw=0, label="Operating points (size = time)")
    w_eta = np.sum((tq[m]*2*np.pi*n[m]/60*dt[m])) / (np.sum(ef[m])*1e6 + 1e-9)
    ax.set_title(f"{name}: fuel-weighted engine efficiency {w_eta*100:.1f} %", loc="left", fontsize=11)
    ax.set_xlabel("Engine speed [rpm]"); ax.set_ylabel("Torque [Nm]"); ax.set_xlim(600, 2000); ax.set_ylim(0, 2750*eng.k)
axs[0, 0].legend(loc="upper right", fontsize=9)
fig.colorbar(cs, ax=axs, shrink=0.6, label="Brake efficiency")
fig.savefig(os.path.join(HERE, "fig_operating_points.png"), bbox_inches="tight")
print("ok")
