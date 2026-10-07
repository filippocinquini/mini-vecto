# Reference list

Sources used by the mini-VECTO simulator

Compiled 5 October 2026.

Each entry states what was taken from the source and how it is used:

- **Model**: the value or method is in the simulator.

- **Validation**: used to check the results.

- **LCA phase**: collected for the emission and life cycle work, not yet in the simulator.

- **Background**: read to understand the topic; no number taken.

- **Next step**: available, not yet integrated.

*Where my notes do not hold the full bibliographic record (first names, exact title or year), the entry says so. These entries must be completed from the original document before the final report.*

## 1. Method and regulation

**[1]** European Commission. VECTO (Vehicle Energy Consumption calculation TOol): source repository and example output for the Heavy Urban bus cycle.

> **Model**. Backward, distance-based simulation approach. Cycle length, mean speeds, standstill share and passenger loads of the Heavy Urban cycle.
>
> <https://code.europa.eu/anagnko/vecto/-/commit/0eb466605afdfd5a771cf5e757b9bec6e11748b7.diff>

**[2]** Commission Regulation (EU) 2017/2400, Annex IX: standard auxiliary power values for heavy-duty vehicles.

> **Model**. Auxiliary load of the timber truck (4 kW).
>
> <https://legislation.gov.uk/cy/eur/2017/2400/annex/IX/division/3/2020-01-31?view=plain>

**[3]** Joint Research Centre. Report JRC131046 on bus passenger load and auxiliary (HVAC) energy use. Title given as described in our notes, not verbatim.

> **Model**. Constant average passenger load; range of bus auxiliary power.
>
> <https://publications.jrc.ec.europa.eu/repository/handle/JRC131046>

## 2. Missions, driver model and driving resistances

**[4]** Noreland. (2025). Uppskattning av tids- och drivmedelsåtgång för timmertransporter. Skogforsk Arbetsrapport 1247-2025.

> **Model**, **Validation**. Driver model (backward and forward sweeps), acceleration and deceleration tables (Tables 3 and 4), rolling resistance on asphalt and gravel, CdA, rotating mass, g and air density, road classes. Measured diesel consumption, mean speeds and idle fuel use for validation.
>
> <https://www.skogforsk.se/contentassets/0e3a357029274c5598532effb951c09f/arbetsrapport-1247-2025-uppskattning-av-tids--och-drivmedelsatgang-for-timmertransporter.pdf>

**[5]** Vägverket (Swedish Road Administration). (2004). Vägar och gators utformning. VV Publikation 2004:80.

> **Model**. Safe speed in curves as a function of radius and superelevation.

**[6]** Anttila et al. (2023). Silva Fennica 56(4), article 10798. Timber truck work phases and road effects in Finland.

> **Background**. Background on timber transport work phases, including loading.
>
> <https://silvafennica.fi/raw/10798>

## 3. Engine powertrains: Diesel, HVO100 and hydrogen engine

**[7]** Volvo Trucks. D13K540 Euro 6 SCR engine fact sheet.

> **Model**. Displacement (12.8 L), rated power (397 kW), maximum torque (2600 Nm) and full-load curve.
>
> <https://stpi.it.volvo.com/STPIFiles/Volvo/FactSheet/D13K540,%20EU6SCR_Eng_07_310999624.pdf>

**[8]** Volgen Power. What is the gear ratio of the Volvo I-Shift transmission?

> **Model**. Gear ratios of the 12-speed I-Shift, direct-drive and overdrive versions.
>
> <https://www.volgenpower.com/what-is-the-gear-ratio-of-the-volvo-i-shift-transmission/>

**[9]** AVL. Commercial hydrogen engine with 50 % BTE. Expert article.

> **Model**. Hydrogen HPDI engine: 49.1 to 50.1 % brake thermal efficiency, 97.5 % hydrogen energy share at full load (basis of the 2.5 % pilot share).
>
> <https://www.avl.com/en/expert-article/commercial-hydrogen-engine-50-bte>

**[10]** Fleet Equipment Magazine. Volvo hydrogen ICE trucks (report of the Volvo Trucks announcement).

> **Background**. HPDI with HVO pilot fuel, zero-emission vehicle classification, road tests from 2026.
>
> <https://www.fleetequipmentmag.com/volvo-hydrogen-ice-trucks/>

## 4. Electric drive and battery electric vehicle

**[11]** Grunditz, E. A. and Thiringer, T. (2017). Modelling and scaling procedure of a vehicle electric drive system. Technical Report 2017:1, Chalmers University of Technology.

> **Model**. Loss structure of the electric machine and inverter, peak machine efficiency of 96.4 to 97.1 % (we use 96.5 %), gearbox efficiency of 97 %.
>
> <https://publications.lib.chalmers.se/records/fulltext/253488/local_253488.pdf>

**[12]** Nordelöf, A., Grunditz, E., Tillman, A.-M., Thiringer, T. and Alatalo, M. A scalable life cycle inventory of an electrical automotive traction machine, Part I. Chalmers University of Technology.

> **LCA phase**. Confirms the 96 to 97 % machine efficiency; inventory data for the electric machine in the LCA.

**[13]** Volvo Trucks. Volvo FH Electric: product page and fact sheet.

> **Model**. Motor power 490 kW peak, 540 kWh installed, up to 460 kWh usable.
>
> <https://www.volvotrucks.com/en-en/trucks/electric/volvo-fh-electric.html>

**[14]** Volvo Buses. Volvo 7900 Electric: press release (2017) and data sheet of the articulated version (2019).

> **Model**. Motor power 200 kW, 2-speed gearbox, battery options.
>
> <https://www.volvogroup.com/en/news-and-media/news/2017/oct/new-volvo-7900-electric-offers-greater-range.html>

**[15]** Daimler Truck. Mercedes-Benz eActros 600: press releases (world premiere; first vehicles in customer fleets).

> **Model**, **Validation**. Four-speed electric axle; 621 kWh LFP battery; reported consumption at 40 t used as a benchmark.
>
> <https://www.daimlertruck.com/en/newsroom/pressrelease/mercedes-benz-trucks-celebrates-world-premiere-of-the-battery-electric-long-haul-truck-eactros-600-52428265>

**[16]** Skogforsk. (2023). Elektrifiering av skogsbrukets vägtransporter. Arbetsrapport 1176-2023.

> **Model**, **Validation**. Planning values of 2.5 kWh/km loaded and 1.5 kWh/km empty for electric timber trucks (battery sizing and validation); charger efficiency of 90 %.
>
> <https://www.skogforsk.se/contentassets/4c2446509a3d4a9ea0f20509d48dce41/arbetsrapport-1176-2023-elektrifiering-av-skogsbrukets-vagtransporter.pdf>

**[17]** Skogforsk. (2023). Elektrifiering av tunga vägtransporter: mycket mer än teknik. Arbetsrapport 1166-2023.

> **Validation**. Modelled consumption of heavy electric trucks, as a second benchmark.
>
> <https://www.skogforsk.se/cd_20230621155159/contentassets/a63d7a4e49494e4094f185802c176e74/1166-2023-elektrifiering-av-tunga-vagtransporter---mycket-mer-an-teknik.pdf>

**[18]** Borén, S. (2020). Electric buses' sustainability effects, noise, energy use, and costs. International Journal of Sustainable Transportation. doi:10.1080/15568318.2019.1666324

> **Validation**. Measured consumption of Volvo electric buses on Gothenburg route 55: 0.93 kWh/km for propulsion plus 0.28 kWh/km of HVO for heating.
>
> <https://www.tandfonline.com/doi/full/10.1080/15568318.2019.1666324>

## 5. Fuel cell electric vehicle

**[19]** Gibbons, W. and Kleen, G. (2026). Heavy-Duty Fuel Cell System Cost, 2024. DOE Hydrogen Program Record 26002. U.S. Department of Energy.

> **Model**. Fuel cell system efficiency when new: 64.5 % peak near 25 % load, 56 % at rated power.
>
> <https://www.energy.gov/documents/record-26002-heavy-duty-fuel-cell-system-cost-2024>

**[20]** Wang, X. and Ahluwalia, R. K. (2025). Hybrid Fuel Cell Systems for Heavy-Duty Trucks: Configuration, Heat Rejection and Performance. Energies. Argonne National Laboratory.

> **Model**. Fuel cell system efficiency at end of life: 48 to 51 % peak, 40 to 48 % at rated power.

**[21]** Marcinkoski, J. et al. (2019). Hydrogen Class 8 Long Haul Truck Targets. DOE Program Record 19006. U.S. Department of Energy.

> **Background**. Lifetime and efficiency targets for heavy-duty fuel cells; definition of end of life.
>
> <https://www.hydrogen.energy.gov/docs/hydrogenprogramlibraries/pdfs/19006_hydrogen_class8_long_haul_truck_targets.pdf>

**[22]** Lohse-Busch, H. et al. (2020). Automotive fuel cell stack and system efficiency and fuel consumption based on vehicle testing on a chassis dynamometer at -18 °C to +35 °C. International Journal of Hydrogen Energy.

> **Background**. Measured peak efficiencies of 66.0 % (stack) and 63.7 % (system) on a light-duty vehicle; supports reading 60 % as a peak system value.
>
> <https://www.sciencedirect.com/science/article/abs/pii/S0360319919339618>

**[23]** Argonne National Laboratory. Hydrogen-fueled PEFC systems for transportation. OSTI 11997.

> **Background**. Shape of the system efficiency curve: peak at part load.
>
> <https://www.osti.gov/biblio/11997>

**[24]** Argonne National Laboratory. Fuel cell systems for Class-8 long-haul trucks.

> **Background**. Heavy-duty targets; reference sizing of fuel cell and battery.
>
> <https://www.osti.gov/pages/servlets/purl/2536687>

**[25]** Du et al. (2022). Energies 15(12), 4325. Energy management of a fuel cell hybrid vehicle with dynamic programming.

> **Background**. Background for the energy management strategy.
>
> <https://www.mdpi.com/1996-1073/15/12/4325>

**[26]** Volvo Trucks. (June 2022). Fuel cell truck with 1000 km range: press release, as reported by electrive.

> **Model**. Fuel cell power of the timber truck: 2 x 150 kW.
>
> <https://www.electrive.com/2022/06/21/volvo-trucks-presents-fc-truck-with-1000-km-range/>

**[27]** Daimler Truck. (2022). Mercedes-Benz GenH2 Truck, outlook at IAA Transportation 2022.

> **Model**, **Validation**. Buffer battery of 70 kWh and 400 kW; 80 kg of liquid hydrogen for about 1000 km (benchmark).
>
> <https://hydrogen-central.com/mercedes-benz-trucks-provides-outlook-hydrogen-based-genh2-truck-iaa-transportation-2022-in-hanover/>

**[28]** Hyundai Motor. XCIENT Fuel Cell: press releases and product page.

> **Model**, **Validation**. Fuel cell power of 180 kW as reference for the coach; about 7.8 kg/100 km implied by the stated range (benchmark).
>
> <https://ecv.hyundai.com/global/en/products/xcient-fuel-cell-truck-fcev/>

**[29]** JIVE 2 project. (2025). Final results, as reported by Urban Transport Magazine; UITP Project Brief 2025, JIVE 2 Roadshow.

> **Validation**. Measured hydrogen consumption of fuel cell buses: 7.7 kg/100 km (12 m), 8.9 kg/100 km (18 m).
>
> <https://www.urban-transport-magazine.com/en/jive-2-europes-largest-fuel-cell-bus-project-has-concluded/>

## 6. Emissions and life cycle assessment (collected for the next phase)

**[30]** Sand, M. et al. (2023). A multi-model assessment of the Global Warming Potential of hydrogen. Communications Earth & Environment 4, 203. doi:10.1038/s43247-023-00857-8

> **LCA phase**. GWP100 of hydrogen: 11.6 ± 2.8.
>
> <https://www.nature.com/articles/s43247-023-00857-8>

**[31]** PA Consulting. Reducing the cost impact of hydrogen leakage (compilation of Frazer-Nash and Columbia University leakage estimates).

> **LCA phase**. Hydrogen leakage at refuelling stations: 0.3 to 0.9 % for compressed gas.
>
> <https://www.paconsulting.com/insights/reducing-the-cost-impact-of-hydrogenleakage-four-ways-to-address-fugitive-emissions>

**[32]** Esquivel-Elizondo, S. et al. (2023). Frontiers in Energy Research. doi:10.3389/fenrg.2023.1207208

> **LCA phase**. Ranges of hydrogen leakage along the supply chain.
>
> <https://www.frontiersin.org/journals/energy-research/articles/10.3389/fenrg.2023.1207208/full>

**[33]** Lawrence Livermore National Laboratory. Boil-off losses at liquid hydrogen stations. OSTI 1466121.

> **LCA phase**. Boil-off as a function of station size.
>
> <https://www.osti.gov/biblio/1466121>

**[34]** Ricardo and University of Brighton. Examining trade-offs between NOx emissions and hydrogen slip for hydrogen engines.

> **LCA phase**. Qualitative link between hydrogen slip and NOx in the hydrogen engine.
>
> <https://research.brighton.ac.uk/en/publications/examining-trade-offs-between-nox-emissions-and-hydrogen-slip-for-/>

**[35]** Karlsruhe Institute of Technology. (2025). Automotive and Engine Technology. Heavy-duty hydrogen engine: tailpipe CO2 from lubricating oil only.

> **LCA phase**. Tailpipe CO2 of the hydrogen engine apart from the pilot fuel.
>
> <https://publikationen.bibliothek.kit.edu/1000188626/170944160>

**[36]** O'Connell, A., Pavlenko, N., Bieker, G. and Searle, S. (2023). A comparison of the life-cycle greenhouse gas emissions of European heavy-duty vehicles and fuels. International Council on Clean Transportation.

> **LCA phase**. Benchmark for the comparative LCA.
>
> <https://theicct.org/publication/lca-ghg-emissions-hdv-fuels-europe-feb23/>

**[37]** Emilsson, E. and Dahllöf, L. (2019). Lithium-ion vehicle battery production. IVL Swedish Environmental Research Institute, Report C 444.

> **LCA phase**. Battery production: 61 to 106 kg CO2-eq per kWh.
>
> <https://www.ivl.se/english/ivl/press/press-releases/2019-12-04-new-report-on-climate-impact-of-electric-car-batteries.html>

**[38]** Nordelöf, A., Romare, M. and Tivander, J. (2019). Life cycle assessment of city buses powered by electricity, hydrogenated vegetable oil or diesel. Transportation Research Part D. Chalmers University of Technology. Title as described in our notes.

> **LCA phase**. Benchmark LCA of city buses on Gothenburg route 55.
>
> <https://www.sciencedirect.com/science/article/pii/S1361920919302792>

**[39]** Life cycle assessment of hydrogen-powered city buses in the High V.LO-City project. (2021). SN Applied Sciences. doi:10.1007/s42452-021-04933-6

> **LCA phase**. Fuel cell bus LCA; station electricity of 7 to 9 kWh per kg of hydrogen.
>
> <https://link.springer.com/article/10.1007/s42452-021-04933-6>

**[40]** U.S. Department of Energy. Hydrogen Program Records 24005 (PEM electrolysis), 9013 (compression and liquefaction energy) and 19001 (liquefaction).

> **LCA phase**. Electricity needed to produce, compress and liquefy hydrogen.
>
> <https://www.hydrogen.energy.gov/docs/hydrogenprogramlibraries/pdfs/24005-clean-hydrogen-production-cost-pem-electrolyzer.pdf>

**[41]** Sandgren, A. and Nilsson, J. (2021). Emissionsfaktor för nordisk elmix. IVL/SMED Rapport 4 2021. Title as described in our notes.

> **LCA phase**. Carbon intensity of the Nordic electricity mix.
>
> <https://naturvardsverket.diva-portal.org/smash/get/diva2:1540012/FULLTEXT01.pdf>

**[42]** IPCC. (2006). Guidelines for National Greenhouse Gas Inventories: default emission factor for diesel.

> **LCA phase**. Tailpipe CO2 of fossil diesel, 74.1 g/MJ, in the first cruise calculator.
