"""
run_all.py - runs the whole model with one command:   python3 run_all.py

  1 missions.py              driving cycles (10 m steps): synthetic timber route, VECTO bus cycles + driver model
  2 powertrain.py            Diesel, HVO100, H2-ICE consumption
  3 electric.py              FCEV and BEV consumption
  4 plot_operating_points.py engine operating points figure
  5 export_excel.py          results/consumption_<powertrain>.xlsx
  6 cycle_sensitivity.py     buses on other cycles (results/cycle_sensitivity.csv), if the VECTO cycles are present

Options:  python3 run_all.py --keep-cycles   skip step 1 (cycles unchanged, faster)
          python3 run_all.py --engine-map model      use the semi-empirical engine map (50 % peak)
          python3 run_all.py --engine-map measured   use the measured engine map (44 % peak)
          (default: "engine_map" > "source" in vehicles.json)
"""
import importlib.util, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
missing = [m for m in ("numpy", "matplotlib", "openpyxl") if importlib.util.find_spec(m) is None]
if missing:
    sys.exit("Missing Python packages: " + ", ".join(missing) +
             "\nInstall them with:  " + os.path.basename(sys.executable) + " -m pip install -r requirements.txt")
steps = ["missions.py", "powertrain.py", "electric.py", "plot_operating_points.py", "export_excel.py", "cycle_sensitivity.py"]
if "--keep-cycles" in sys.argv:
    steps = steps[1:]
if "--engine-map" in sys.argv:
    os.environ["MINIVECTO_ENGINE_MAP"] = sys.argv[sys.argv.index("--engine-map") + 1]
t0 = time.time()
for i, s in enumerate(steps, 1):
    print(f"[{i}/{len(steps)}] {s} ...", flush=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, s)], cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-4000:])
        sys.exit(f"Stopped: {s} failed. Check vehicles.json (a missing comma or quote is the usual cause).")
print(f"\nDone in {time.time() - t0:.0f} s.")

# short result table
import json
ice = {r["mission"]: r for r in json.load(open(os.path.join(HERE, "consumption_summary.json")))}
el = {(r["powertrain"], r["mission"]): r for r in json.load(open(os.path.join(HERE, "consumption_summary_electric.json")))}
import powertrain
print("\nEngine map:", powertrain.select_engine_map()["label"])
print("\nMean consumption per 100 km")
print(f"{'mission':<15}{'Diesel l':>9}{'HVO l':>8}{'H2-ICE kg':>11}{'FCEV kg new/aged':>19}{'BEV kWh (battery)':>19}")
for m, r in ice.items():
    f, b = el[("fcev", m)], el[("bev", m)]
    fc = f"{f['h2_kg_per_100km_BOL']:.1f} / {f['h2_kg_per_100km_EOL']:.1f}"
    print(f"{m:<15}{r['diesel_l_per_100km']:>9.1f}{r['hvo100_l_per_100km']:>8.1f}{r['h2ice_h2_kg_per_100km']:>11.1f}"
          f"{fc:>19}{b['battery_kWh_per_km'] * 100:>19.0f}")
print("\nFull results: results/consumption_<powertrain>.xlsx  |  mission explorer: index.html")
