# Why arrival information is unavailable

The original sources support several different availability mechanisms. A time
can be absent from a published table even when measurements survive, and a time
can be printed without enough information to treat it as a comparable tsunami
first arrival. This supplement records those distinctions for the development
cohort. It leaves the original arrival labels unchanged.

Use `data/processed/arrival-evidence/source-process-v1/` alongside the
[arrival data guide](multi-event.md). The release contains 36 reviewed claims,
13 specific NTWC field links, four NCEI definition-comparison candidates and one
additional approximate national observation. Sources have retained raw bytes,
checksums, locators and access records. Review date: 1 November 2026.

## What the counts mean

The denominator is **1,177 retained NTWC table rows**, including 35 structural or
uncertain mappings. It is not a census of every possible event–station pair.
There are 1,142 accepted field mappings and 388 complete original pairs.

| First reason a retained row lacks a complete pair | Rows |
| --- | ---: |
| At least one arrival/estimate entry absent in the source table | 513 |
| Clock exists but calendar/day context unresolved | 230 |
| Structural or blank row | 35 |
| Qualified clock | 7 |
| Footnoted clock | 3 |
| Column meaning unverified | 1 |
| **Total without a complete pair** | **789** |

The source-absence group contains **297 absent estimates** and **289 absent
observations**, with **73 rows missing both**: 297 + 289 − 73 = 513. Across all
accepted mappings, calendar problems affect 368 rows; 135 also have an absent
field. The first-reason table assigns each row once and therefore is not a full
count of every problem that affects it.

Direct documentary support is much narrower than general process coverage:

| Evidence level | Coverage | Interpretation |
| --- | ---: | --- |
| Explicit near-arrival gap linked to an absent NTWC observation | 4 / 289 fields (1.38%) | The gap is documented; its technical cause is unknown |
| Source-absence rows with at least one directly supported absent field | 4 / 513 rows (0.78%) | Luganville still lacks an explanation for its absent estimate |
| Source-absence rows with every absent timing field directly supported | 3 / 513 rows (0.58%) | Explains availability at the phenomenon level; supplies no new time |
| Conditional arrival-reporting policy on the original page | 289 / 289 absent observation fields | Product definition, not 289 individually established causes |

Of the 586 absent timing fields, **582 still lack a specific documented reason**.
Of the 513 source-absence rows, 509 have no directly supported absent field and
510 have at least one absent field whose specific reason remains unknown.
The four directly supported rows are 0.51% of the broader 789 unresolved rows.
No exact pair was added; the 388/789 split is unchanged.

## What the original documents establish

### A record can exist without an identifiable first arrival

NTWC says it reports observed arrival where determinable. That language appears
on 45 of the 46 source pages containing the retained reports, including every
page with an absent observed field. A maximum or later wave can remain measurable
without a defensible first-arrival pick. This conditional rule establishes how
the product is described; it does not identify the reason for each blank.
[Example original NTWC description](https://www.tsunami.gov/previous.events/09-25-03/09-25-03.html).

For **Illapel 2015**, NTWC footnote 4 explicitly marks a gap near arrival for
Honiara, Lata Wharf, Luganville, Suva and Nukuʻalofa. Four lack observation times.
Lata retains its observation at 17:15 on day 260 but lacks an estimate; its data
gap cannot explain the missing forecast. Nuku Hiva retains an exact pair despite
a corruption note. Later missing-day notes at French Frigate Shoals and
Chichijima do not establish loss at the first-arrival opportunity.
[NTWC table and footnotes](https://www.tsunami.gov/previous.events/?p=09-16-2015-Chile%28M8.3%29).

For **Kuril 2006**, the original observing paper explicitly attributes
Starodubsk's undetermined arrival to high background noise while retaining its
maximum measurement. This explains one missing arrival among the **87 separate
documentary observations**, whose 46 absent arrival cells are a different
denominator from the NTWC table. The paper also distinguishes analog-record
resolution, unavailable near-source instruments and later record gaps.
[Rabinovich et al., §2 and Table 1](https://adgeo.copernicus.org/articles/14/105/2008/adgeo-14-105-2008.pdf).

### Damage, transmission and onset ambiguity are different mechanisms

For **Chile 2010**, the IOC assessment describes Talcahuano's two-minute sampling
but hourly transmissions. It bounds failure between 08:29 and 09:29 UTC and
attributes station damage to a broken wall. NTWC separately gives a transmission
stop at 08:30. Neither account establishes why the initial-arrival cell is blank.
Juan Fernández retains an NTWC arrival clock before its transmission stop; IOC
interprets early oscillations as seismic seiche and reports a malfunction
preventing tsunami-height observation. This is a source-definition conflict,
not a license to replace one value with another. The original assessment was
retained from VLIZ after the official JODC host failed.
[IOC Technical Series 92, printed pp.8–10 / PDF pp.20–22](https://www.vliz.be/imisdocs/publications/270412.pdf),
[NTWC event table](https://www.tsunami.gov/previous.events/?p=Chile_02-27-10).

For **Tōhoku 2011**, JMA's table marks Ofunato, Kamaishi,
Ishinomaki-Ayukawa and Soma with note `*6`: earthquake-induced water-level
changes prevented identifying first-wave starts. JMA's evening notice separately
marks data interruption, without dating its onset. Later restoration notices
document damaged gauges and replacement deployments using former names.
These are distinct facts. The four named stations have no rows in the NTWC
Tōhoku table, so they explain none of its missing cells directly.
[JMA Technical Report 133, printed pp.94–99 and 106–108](https://www.jma.go.jp/jma/kishou/books/gizyutu/133/CHAPTER2.pdf),
[11 March instrument notice, attachment 3](https://www.jma.go.jp/jma/press/1103/11f/H2303112000kansokukiki.pdf),
[April restoration](https://www.jma.go.jp/jma/en/News/20110422_satellite_back_up.html),
[July replacement-station notice](https://www.jma.go.jp/jma/en/News/20110725_resumption_tsunami_obs.html).

NCEI records 19070/OFUNATO, 19236/KAMAISHI, 19241/SOMA and 25211/AYUKAWA contain
early arrival clocks despite JMA's unresolved first-wave starts. Two have positive
native durations of four and nine minutes. The supplement flags **four
comparison candidates among 2,224 NCEI records**. It does not establish common
deployments, documentary ancestry or erroneous NCEI values. Resolve their
measurement definitions before using them as onset targets; no label or
eligibility has been changed automatically.

For **Samoa 2009**, NOAA reports that all NOS Pacific sea-level stations were
operational, while 26 of 32 Pacific DART systems operated. Its failed interoffice
hotline concerned warning coordination. The prose does not identify the six
unavailable DART deployments. A warning-communication failure cannot be counted
as a gauge-data failure.
[NWS assessment, printed pp.12 and 32 / PDF pp.20 and 40](https://www.weather.gov/media/publications/assessments/tsuanami_%20south_pacific10.pdf).

### Published clocks can refer to different things

The revised 2011 Pacific guide distinguishes NWPTAC signal appearance from
PTWC/WCATWC amplitude-measurement times. It also documents regional forecast-point
selection and removal of ETA columns after passage or cancellation. These rules
show deliberate product selection and lifecycle, without proving why any
particular summary-table estimate is absent. ITIC identifies that guide as
covering services through 2014; later products require their own definitions.
[2011 guide, §4.9, §5.7.9 and Annex IV](https://www.vliz.be/imisdocs/publications/270420.pdf),
[official product-era overview](https://legacy.itic.ioc-unesco.org/legacy.itic.ioc-unesco.org/indexdd78.html?Itemid=1163&catid=1163&id=1610:262&option=com_content&view=article).

NCEI assembles a historical catalog from heterogeneous original sources and
includes arrival/travel times when available. Its first-wave definition can
differ from an original source reporting a later wave. Its native arrival
components and travel durations should remain distinct.
[NCEI catalog explanation](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/global-historical-data).

### An archive gap can occur after measurement

A first-person NOAA/NCEI curator account documents over 20 DART deployment
packages that had not reached the archive, later coastal backfills and a provider
API error subsequently corrected. It also describes selective station reporting,
especially for smaller events. These establish real archive and reporting
mechanisms, but their aggregate history cannot be assigned to present rows
without matching dates and deployments.
[Sweeney, 2021, pp.2–4](https://repository.library.noaa.gov/view/noaa/34133/noaa_34133_DS1.pdf).

DART II's internal 15-second samples, sparse routine transmissions and event-mode
products are separate. Recovered seafloor data can add information absent from a
real-time feed. Historical CO-OPS instructions likewise distinguish sampling,
averaging, telemetry and status histories. No accessible historical station-log
collection was recovered in this investigation.
[PMEL DART II engineering description](https://nctr.pmel.noaa.gov/Dart/Pdf/DART_II_Description_6_4_05.pdf),
[NCEI recovered DART products](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis/dart-ocean-bottom-pressure),
[CO-OPS 2004 guide, §7.2](https://tidesandcurrents.noaa.gov/publications/tech_rpt_026.pdf).

## Genuine additional observation, retained with uncertainty

Tonga's original cancellation, issued at 02:45 AM on 18 September 2015, reports a
0.1 m wave arriving at Nukuʻalofa at about 02:00 AM. Its Tongan continuation places
this in the same morning. This is additional national observation evidence
alongside NTWC's blank and gap note. The approximate local clock has no approved
UTC conversion, exact instrument match or first-deviation definition, and has
not become an exact NTWC pair.
[Tonga Meteorological Service cancellation](https://met.gov.to/index_files/Tsunami%20Warning%20Cancellation.htm).

## How to use the supplement

- `report_availability.csv.gz`: one row per original NTWC report, with field
  states, first blocker and policy context. Original IDs and source hashes remain.
- `claims.csv.gz` and `sources.csv.gz`: the reviewed statement, evidence class,
  event/station/field scope, native incident bounds, limitation, source and locator.
- `ntwc_field_links.csv.gz`: explicit applicable reasons, context, positive
  controls, exclusions and definition conflicts. Only `direct_field_reason`
  contributes to the direct-support numerator.
- `documentary_field_links.csv.gz`: the separate Starodubsk explanation.
- `ncei_definition_candidates.csv.gz`: four unapproved comparisons needing review.
- `alternative_observations.csv.gz`: the approximate Tonga statement.
- `acquisition_dispositions.csv.gz`: successful and unavailable source routes.
  `inputs.json`, `schema.json`, `summary.json` and `manifest.json` provide hashes,
  definitions and counts.

For EDA, examine availability by field, source, era, network and event; keep
structural rows outside station-observation denominators. For later modeling,
review definition conflicts and preserve approximate, unresolved and qualified
clocks as such. Distinguish observed first arrival, first visible deviation,
maximum-wave time, estimated arrival, issue time and warning delivery. Do not
replace original forecasts with reconstructed propagation times.

Missingness is **not identified as MCAR, MAR or MNAR** by this review. Documented
noise, selection and damage make an assumption of uniformly random loss
questionable, but do not identify a unique statistical mechanism. Test those
assumptions through later study design and sensitivity analysis. General policy
coverage must not be presented as complete causal explanation.

## Reproduction and search limits

```bash
.venv/bin/python scripts/build_source_process.py \
  --inputs artifacts/generated/ntwc-batch/data-completion-v1/snapshot/inputs.json \
  --review config/arrival-source-process-review-v1.json \
  --ledger artifacts/provenance/paper-source-manifest-v5.csv \
  --output data/processed/arrival-evidence/source-process-v1
```

The command requires retained local raw sources and frozen inputs. It refuses to
overwrite an existing release; choose a fresh output directory for replay.
The source ledger identifies URLs and checksums; the three
`config/arrival-source-process-b*.toml` contracts and their acquisition run bundles
record retrieval, including failed routes. Raw documents remain local under
their publishers' terms.

The investigation checked all 46 retained NTWC source pages and followed
historical provider manuals, catalog definitions, archive-curator accounts,
JMA damage/restoration notices and original reports for high-yield development
events. Targeted searches for Illapel's four gaps found no technical component
cause; bounded searches for additional Haida Gwaii 2012 and Kodiak 2018 incidents
also yielded no applicable original explanation. Those results do not establish
that incidents never occurred.

Twenty-one new snapshots were retained through 26 contracts, using 27 HTTP
attempts and 28,450,010 response bytes. Official JODC failures, a Craig draft
redirect, an older CO-OPS page and a noncanonical NTWC URL are retained as failed
or skipped receipts. Two IOC original reports were obtained from VLIZ's archive;
the NTWC guide succeeded through its separately verified canonical host. No
inaccessible-source restriction was bypassed. Historical operator logs, exact
failure start/end times, archive transfer manifests and original pick definitions
remain the most useful evidence to seek when new source access becomes available.
