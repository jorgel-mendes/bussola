# References for metric bounds

Every `MetricDefinition.bounds_rationale` in the seeded demo traces to a source
listed here. OpenDP requires clamping bounds to come from public or domain
knowledge and never from the submitted data, because bounds derived from private
data leak. This file is the audit trail for that requirement.

---

## Primary sources

**[1] EU BAT Conclusions for the production of cement, lime and magnesium oxide**
Commission Implementing Decision 2013/163/EU, *Official Journal of the European
Union* L 100, 9 April 2013.
[BAT Conclusions PDF](https://aida.ineris.fr/sites/default/files/documents-bref/BATCONC_Ciment260313GB.pdf)
· [CLM BREF overview](https://eipie.eu/the-sevilla-process/brefs/production-of-cement-lime-and-magnesium-oxide-clm-bref/)

The legally binding reference under the Industrial Emissions Directive
2010/75/EU. **BAT 6, Table 1** (p. L 100/11) gives BAT-associated energy
consumption levels for new plants and major upgrades:

> Dry process with multistage preheating and precalcination:
> **2 900 – 3 300 MJ/tonne clinker**

Footnoted as: not applicable to special or white cement clinker; measured under
normal, optimised operation excluding start-ups and shutdowns; dependent on
plant capacity and the number of cyclone preheater stages.

**Note for the design document:** the same instrument addresses electrical
energy at **BAT 10**, but prescribes only *techniques* — power management
systems, high-efficiency grinding, improved monitoring, reduced air leaks — and
sets **no numeric BAT-AEL**. That asymmetry is why the two seeded metrics carry
different classes of justification, and it is worth stating explicitly: one
bound is anchored in law, the other in literature.

**[2] Thermochemistry of clinker formation**
[Cement Kilns — Clinker Thermochemistry](https://www.cementkilns.co.uk/ckr_therm.html)

Theoretical reaction enthalpy for Portland clinker formation:
**+1 761 kJ/kg clinker ≈ 1 760 MJ/t**, dominated by calcination of calcium
carbonate (+2 138 kJ/kg). This is a thermodynamic floor — no kiln, of any design,
can consume less and still produce clinker.

**[3] Wet-process and long-kiln fuel intensity**
[LBNL / ENERGY STAR Guide for the Cement Industry](https://www.energystar.gov/sites/default/files/tools/ENERGY%20STAR%20Guide%20for%20the%20Cement%20Industry%2027_08_2013_Rev%20js%20reformat%2011192014.pdf)
· [NRCan Energy Consumption Benchmark Guide: Cement Clinker Production](https://natural-resources.canada.ca/sites/nrcan/files/oee/pdf/publications/industrial/BenchmCement_e.pdf)

Wet kiln fuel use ranges **5.3 – 7.1 GJ/t clinker**, the spread driven by raw
meal moisture content. Reported US wet-kiln averages: 7.0 GJ/t, revised to
6.8 GJ/t in 2009.

**[4] Specific electrical energy consumption**
[CEMBUREAU — thermal energy efficiency](https://lowcarboneconomy.cembureau.eu/5-parallel-routes/energy-efficiency/thermal-energy-efficiency/)
· cross-checked against plant-level surveys reporting **92 – 141 kWh/t cement**,
with typical modern plants near 110 – 120 kWh/t.

**[5] GCCA "Getting the Numbers Right" (GNR)**
[GNR 2.0](https://gccassociation.org/gnr/) ·
[WBCSD CSI background](https://www.wbcsd.org/Sector-Projects/Cement-Sustainability-Initiative/Resources/Cement-Industry-Energy-and-CO2-Performance)

The cement industry's own global benchmarking database — the closest existing
analogue to what Bússola does, and worth citing as related work for that reason
alone. Covers 1990, 2000 and 2005–2024; reports a 25 % reduction in CO₂ per
tonne cementitious and a 17 % improvement in energy efficiency since 1990.
Detailed figures require registration, so no GNR number is used as a bound here.

Its relevance to this project is architectural: GNR is administered by a trusted
third party under a common reporting protocol — exactly the trusted-curator model
of [ADR-0002](adr/0002-central-dp-over-local-dp.md), but with confidentiality
guaranteed by contract rather than by mathematics.

---

## Applied bounds

### `specific_thermal_energy` — MJ/t clinker

| | Value | Source |
|---|---|---|
| Lower bound | **1 760** | [2] theoretical reaction enthalpy — thermodynamic floor |
| BAT-AEL band | 2 900 – 3 300 | [1] BAT 6, Table 1 |
| Upper bound | **7 100** | [3] top of the wet-kiln range |

The bounds deliberately sit **wider** than the BAT-AEL. BAT-AEL describes what a
well-run modern plant achieves; the clamping bounds must contain every plant that
could legitimately report, including old wet-process lines. A value below 1 760
is thermodynamically impossible and indicates a metering or unit-conversion
fault; above 7 100 exceeds the worst installed technology.

### `specific_electrical_energy` — kWh/t cement

| | Value | Source |
|---|---|---|
| Lower bound | **60** | [4] below any reported plant; finish grinding alone accounts for roughly half of typical consumption |
| Typical band | 92 – 141 | [4] |
| Upper bound | **200** | [4] margin above the reported maximum |

No BAT-AEL exists for electrical energy [1, BAT 10], so these bounds rest on
literature rather than law. Stated explicitly because the distinction matters:
a bound anchored in a legal instrument is stronger evidence than one anchored in
a survey.

---

## Denominator discipline

The two metrics use **different denominators**, and this is the single most
common error in cement benchmarking:

- thermal energy is per tonne of **clinker**;
- electrical energy is per tonne of **cement**.

They differ by the clinker factor (clinker/cement ratio), globally around 0.75
and falling as supplementary cementitious materials are substituted. Mixing them
produces a benchmark that is confidently wrong — which is worse than none.

The denominator therefore lives in `MetricDefinition.unit` ("MJ/t clinker",
"kWh/t cement") and is displayed on every published statistic, not left implicit
in the metric name.
