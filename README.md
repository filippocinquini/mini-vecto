# mini-VECTO

A small, transparent energy-use simulator for heavy-duty vehicles. It compares five powertrains on the same 100 km missions and returns the fuel, hydrogen or electricity used **every 10 metres**, plus the mission average.

Built by Filippo Cinquini, master's student at Chalmers University of Technology, as a supporting tool for coursework in **TRA545 Hydrogen Technologies**: the course project needed a vehicle energy model and none was available, so this one was written from public sources.

> **Status: work in progress.** This is a student model, not a validated engineering tool. Many inputs are assumptions (they are marked as such). It is an independent personal project, not affiliated with or endorsed by Chalmers or any vehicle manufacturer; manufacturer names appear only as sources of public data.

![First kilometres of the four simulated missions](docs/img/fig_mission_zoom.png)

## What it does

| Powertrains | Missions (100 km each) |
|---|---|
| Diesel | Timber truck, empty leg, 20 t |
| HVO100 | Timber truck, loaded leg, 74 t |
| Hydrogen engine (HPDI with HVO100 pilot) | Urban bus, 14.7 t |
| Fuel cell electric | Coach, 17.2 t |
| Battery electric | |

The method follows the logic of VECTO, the EU tool for heavy-duty CO2 certification: a **backward** simulation on a **distance-based** cycle.

```
route (speed limit, grade, surface)
  -> driver model            speed really driven
  -> wheel force             inertia + grade + rolling resistance + air drag
  -> powertrain              gearbox -> engine map            (Diesel, HVO100, H2 engine)
                             gearbox -> motor -> battery      (battery electric)
                             gearbox -> motor -> fuel cell + buffer battery
  -> consumption per 10 m step and per mission
```

## Quick start

You need Python 3.9 or newer.

```bash
git clone https://github.com/filippocinquini/mini-vecto.git
cd tra545-mini-vecto
python3 -m pip install -r requirements.txt
python3 run_all.py
```

The run takes under a minute and prints a table like this:

```
Mean consumption per 100 km
mission         Diesel l   HVO l  H2-ICE kg   FCEV kg new/aged  BEV kWh (battery)
timber_empty        31.9    33.1        8.8          7.5 / 9.6                148
timber_loaded       67.1    69.7       19.3        17.3 / 22.1                278
urban_bus           45.0    46.7       12.5          7.0 / 9.0                121
coach               23.9    24.8        6.7          5.9 / 7.6                111
```

On macOS or Windows you can also double click `RUN_MODEL_mac.command` or `RUN_MODEL_windows.bat`. A step-by-step guide is in [docs/QUICK_START.pdf](docs/QUICK_START.pdf).

## Outputs

| File | Content |
|---|---|
| `results/consumption_<powertrain>.xlsx` | One workbook per powertrain: a Summary sheet (mean consumption, live formulas), one sheet per mission with one row every 10 m, and a Notes sheet with parameters and sources |
| `consumption_*.csv` | The same step data as plain CSV, ready for emission factors |
| `index.html` | Mission explorer: speed, altitude, grade and road surface along each route. Open it in a browser |
| `fig_*.png` | Mission profiles and engine operating points |

Generated files are not stored in the repository; `run_all.py` recreates them.

## Change the vehicles

All vehicle data are in [`vehicles.json`](vehicles.json). Edit a number, save, run again.

| What | Section | Keys |
|---|---|---|
| Mass, drag, rolling resistance | `missions` > mission | `mass_kg`, `CdA_m2`, `cr_asphalt`, `cr_gravel` |
| Engine size and power | `vehicles` > vehicle > `engine` | `rated_power_kW`, `displacement_l` |
| Axle ratio, tyre radius, auxiliaries | `vehicles` > vehicle | `axle_ratio`, `tyre_dynamic_radius_m`, `aux_mech_kW` |
| Gear ratios | `gearboxes` | `ratios`, `eta_indirect`, `eta_direct` |
| Fuels, pilot share of the hydrogen engine | `fuels`, `hpdi` | `LHV_MJ_per_kg`, `pilot_share_full_load` |
| Electric motor | `electric` > `vehicles` > vehicle | `motor_peak_kW`, `n_gears`, `aux_el_kW` |
| Battery (battery electric) | `electric` > `vehicles` > vehicle > `bev` | `battery_kWh`, `soc_start`, `extra_mass_kg` |
| Fuel cell and buffer battery | `electric` > `vehicles` > vehicle > `fcev` | `fc_net_kW`, `battery_kWh`, `extra_mass_kg` |
| Fuel cell efficiency curve | `electric` > `fuel_cell` | `eta_sys_BOL`, `eta_sys_EOL`, `min_load_frac` |

Routes (length, speed limits, stops, hills) are defined in `missions.py`, section `MISSIONS`.

The engine map scales with `displacement_l`, while `rated_power_kW` limits the speed profile: change both in proportion (the reference is 397 kW for 12.8 L).

## Repository layout

| File | Role |
|---|---|
| `run_all.py` | Runs everything in order |
| `missions.py` | Routes and driver model; writes the cycles |
| `powertrain.py` | Diesel, HVO100 and hydrogen engine |
| `electric.py` | Battery electric and fuel cell electric |
| `export_excel.py` | Builds the Excel workbooks |
| `plot_operating_points.py` | Engine operating points figure |
| `build_site.py` | Packs the cycles for `index.html` |
| `vehicles.json` | All vehicle and powertrain data |
| `cycle_*.csv`, `data/` | The four mission cycles (kept so `index.html` works without running anything) |
| `docs/` | Quick-start guide, reference list, figures |

## How the model compares with published data

| Quantity | Model | Literature | Source |
|---|---|---|---|
| Diesel, loaded timber truck [l/100 km] | 67.1 | 52–69 | Noreland 2025, measured fleet |
| Diesel, empty timber truck [l/100 km] | 31.9 | 34–47 | Noreland 2025, measured fleet |
| Idle fuel [l/h] | 2.8 | about 2.4 | Noreland 2025 |
| Fuel cell bus [kg H2/100 km] | 7.0–9.0 | 7.7 | JIVE 2, measured, 12 m buses |
| Electric timber truck, loaded / empty [kWh/km] | 2.78 / 1.48 | 2.5 / 1.5 | Skogforsk 2023, planning values |

![Engine operating points on the efficiency map](docs/img/fig_operating_points.png)

## Known limits

- The engine map is semi-empirical (friction model plus an assumed indicated-efficiency shape, scaled to a 50 % peak). It is not a measured map.
- All powertrains use the same vehicle mass: batteries and hydrogen tanks add no weight unless you set `extra_mass_kg`.
- Routes are synthetic, not GPS tracks.
- Gear shifting is ideal (lowest fuel use at each step); there is no engine start-stop.
- Several fuel cell and electric-drive inputs are assumptions: part-load points of the efficiency curve, minimum load, ramp rate, DC/DC losses, regeneration limits, bus and coach component sizes.
- No cabin heating model, and no crane work for the timber truck.

Each assumption is flagged in the `notes` of `vehicles.json` and in the Notes sheet of the workbooks.

## References

The full list, with what was taken from each source, is in [docs/REFERENCES.md](docs/REFERENCES.md). The main ones:

- European Commission, VECTO, and Regulation (EU) 2017/2400.
- Noreland (2025), Skogforsk Arbetsrapport 1247-2025: driver model, resistances and measured fuel use of Swedish timber trucks.
- Grunditz and Thiringer (2017), Chalmers Technical Report 2017:1: electric drive loss modelling.
- Gibbons and Kleen (2026), DOE Hydrogen Program Record 26002; Wang and Ahluwalia (2025), *Energies*: fuel cell system efficiency when new and aged.
- Skogforsk Arbetsrapport 1176-2023: electric timber truck planning values.

## Authors

Filippo Cinquini, Chalmers University of Technology, 2026. See [CITATION.cff](CITATION.cff) to cite this work.

The model design, the choice of sources and the checks are mine; the code was written with the help of an AI assistant (Claude, Anthropic). Review it before relying on it.

## License

Code released under the [MIT License](LICENSE). Numbers taken from the cited sources remain the property of their authors.
