"""
cycle_sensitivity.py - the same bus and coach on other driving cycles (sensitivity of the results to the cycle)

Runs powertrain.py (diesel, HVO100, H2-ICE) and electric.py (FCEV, BEV) on the sensitivity cycles written by
missions.py (VECTO Heavy Urban and Suburban for the urban bus; the synthetic routes of version 0.2.1 for both
buses) and puts them next to the base case (VECTO Urban for the urban bus, VECTO Coach for the coach).

Run after missions.py, powertrain.py and electric.py (run_all.py does it). Skipped if the VECTO cycles are not there.
Output: results/cycle_sensitivity.csv  (consumption per 100 km for every powertrain, cycle statistics)
"""
import csv, json, os
import powertrain as pt
import electric as el

HERE = os.path.dirname(os.path.abspath(__file__))
SENS = {"urban_bus": ["urban_bus_heavyurban", "urban_bus_suburban", "urban_bus_synthetic"],
        "coach": ["coach_synthetic"]}


def one(tag):
    """Consumption per 100 km of every powertrain on the cycle of mission `tag`."""
    r = pt.run(tag, write=False)
    x = pt.CFG["vehicles"][r["vehicle"]].get("h2ice_mass", {}).get("extra_mass_kg", 0.0)
    h = pt.run(tag, write=False, extra_mass=x)
    f, b = el.run(tag, "fcev"), el.run(tag, "bev")
    return {"diesel_l_per_100km": r["diesel_l_per_100km"], "hvo100_l_per_100km": r["hvo100_l_per_100km"],
            "h2ice_h2_kg_per_100km": h["h2ice_h2_kg_per_100km"],
            "fcev_h2_kg_per_100km_new": f["h2_kg_per_100km_BOL"], "fcev_h2_kg_per_100km_aged": f["h2_kg_per_100km_EOL"],
            "bev_kWh_per_100km_battery": round(b["battery_kWh_per_km"] * 100, 1),
            "bev_power_deficit_steps": b["power_deficit_steps"]}


def main():
    ms = json.load(open(os.path.join(HERE, "mission_summary.json")))
    rows = []
    for base, tags in SENS.items():
        for tag in [base] + tags:
            if tag not in ms:
                continue
            m = ms[tag]
            row = {"vehicle": base, "mission": tag, "case": "base" if tag == base else "sensitivity",
                   "cycle": m.get("cycle_source", ""), "length_km": m["length_km"], "avg_speed_kmh": m["avg_speed_kmh"],
                   "standstill_pct": m["standstill_share_pct"], "stops_per_km": round(m["stops_with_dwell"] / m["length_km"], 2),
                   "climb_m_per_100km": round(m["total_climb_m"] / m["length_km"] * 100)}
            row.update(one(tag))
            rows.append(row)
            print(f"{tag:22s} diesel {row['diesel_l_per_100km']:6.1f} l | H2-ICE {row['h2ice_h2_kg_per_100km']:5.1f} kg | "
                  f"FCEV {row['fcev_h2_kg_per_100km_new']:4.1f}/{row['fcev_h2_kg_per_100km_aged']:4.1f} kg | BEV {row['bev_kWh_per_100km_battery']:6.1f} kWh")
    if len(rows) <= 2:
        print("No sensitivity cycles found (VECTO cycles missing): nothing to do.")
        return
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "cycle_sensitivity.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("wrote results/cycle_sensitivity.csv")


if __name__ == "__main__":
    main()
