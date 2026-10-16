"""
compare_engine_maps.py - same missions, two engine maps: semi-empirical (50 % peak) and measured (44 % peak)

  python3 compare_engine_maps.py        (run after run_all.py; needs data/engine_map_measured.csv)

Only the engine powertrains change (Diesel, HVO100, hydrogen engine); FCEV and BEV do not use the engine map.
Output: results/engine_map_comparison.csv
"""
import csv, os
import powertrain as pt

KEYS = [("diesel_l_per_100km", "Diesel l/100km"), ("hvo100_l_per_100km", "HVO100 l/100km"),
        ("h2ice_h2_kg_per_100km", "H2-ICE kg/100km"), ("mean_engine_eff_pct", "engine eff. %"),
        ("idle_diesel_l_per_h", "idle l/h")]
res = {}
for src in ("model", "measured"):
    if pt.select_engine_map(src)["source"] != src:
        raise SystemExit("Measured map not found: run import_engine_map.py first.")
    res[src] = {tag: pt.run(tag, write=False) for tag in pt.MISSIONS}
pt.select_engine_map()
rows = []
print(f"{'mission':<15}{'quantity':<18}{'model 50 %':>11}{'measured':>10}{'change':>9}")
for tag in pt.MISSIONS:
    for k, name in KEYS:
        a, b = res["model"][tag][k], res["measured"][tag][k]
        rows.append({"mission": tag, "quantity": name, "model_map_50pct": a, "measured_map": b,
                     "change_pct": round((b / a - 1) * 100, 1)})
        print(f"{tag:<15}{name:<18}{a:>11.1f}{b:>10.1f}{(b / a - 1) * 100:>+8.1f}%")
    print(f"{'':<15}fuel burnt above the highest measured torque: {res['measured'][tag]['fuel_above_measured_torque_pct']} %")
os.makedirs(os.path.join(pt.HERE, "results"), exist_ok=True)
with open(os.path.join(pt.HERE, "results", "engine_map_comparison.csv"), "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    wr.writeheader(); wr.writerows(rows)
print("\nSaved: results/engine_map_comparison.csv")
