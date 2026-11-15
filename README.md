# Team TEU — MODIS & VIIRS Hotspot Harmonization

> NASA Space Apps Challenge 2026 · Challenge #9 — *MODIS and VIIRS Hot Spots* (proposed by CONAE, Argentina)

A Python web app, centered on Argentina, for exploring fire hotspot activity from **2000 to today**. MODIS and VIIRS detections are joined into one series in the scale of a single VIIRS satellite, so the sensor change in 2012 stops looking like a rise in fire activity.

**Live site:** https://luk14236-space-apps-teu-2026.hf.space · interface in **Portuguese and English** (PT | EN switch at the top of every page).

## The problem

- **MODIS** (Terra/Aqua, ~1 km pixel, since 2000) is being retired.
- **VIIRS** (S-NPP, NOAA-20, NOAA-21, 375 m pixel, since 2012) is the continuity sensor. It sees smaller fires and splits one fire into several pixels.
- If you join the two series without treatment, a false **step** shows up in 2012 when VIIRS comes in (in Argentina the raw total jumps ~229% from 2011 to 2012). It looks like a rise in fire activity, but it is only the sensor change.

## What the app does

### Fire Hotspot Calendar (`/`)

- **Map whose level of detail follows the zoom**: countries → provinces → departments → grid of cells → individual hotspots colored by satellite. Click to select, or draw a rectangle/polygon; every chart then shows only that area.
- **Month × year calendar** (Greenpeace Global Fire Calendar style) with monthly means and yearly totals; clicking a cell, month or year filters everything.
- **Timeline brush** with playback, **KPIs** (hotspots, density, season peak, record year, month vs. median) and a **ranking** of the level below.
- **The 2012 step**: yearly totals by sensor (raw × MODIS only × harmonized).
- **Monthly series by satellite, in S-NPP scale**: Aqua observed, S-NPP observed and the harmonized series that joins them.
- **Validation (Aqua → S-NPP, estimated × observed)**: in the years both satellites exist, S-NPP estimated from Aqua alone against S-NPP observed, with monthly correlation and out-of-sample error.
- **Season anomaly** (EFFIS style): cumulative year against min–max / p25–p75 / median and monthly anomaly bars.
- **CSV export** of the hotspots in the selected area and period.

### Situation Room (`/sala`)

A decision dashboard organized by Endsley's situation-awareness levels. It compares the last 24 h / 7 days / 30 days with what is **expected** for the time of year (2019–2025 mean of the same month):
alerts by department, priority queue, anomaly map (departments on alert drawn over provinces), 90-day horizon chart, priority quadrant, hotspots of the last day, cumulative season with a projection cone, season clock, satellite status. Widgets can be reordered, resized, hidden and added; three ready-made layouts.

### Admin (`/admin`, hidden, login required)

Four-step flow to **receive deliveries** (inbox folder, browser upload, link, NASA FIRMS API), **check** them, **process and apply** a new version (with a side-by-side comparison and rollback) and **publish** it to the live site. Every delivery and every applied version is kept in a history. Full manual: see the handover documents below.

**Target users:** fire brigades, Civil Defense, scientists and land managers.

## Harmonization approach

Target scale: **one VIIRS satellite (S-NPP)**. Summing S-NPP and NOAA-20 would double the counts after 2018 and create new steps, so they are not added up.

| Satellite | Period | Weight (`peso_harm`) |
|---|---|---|
| S-NPP | 2012 → 31 Oct 2026 | 1 |
| NOAA-20 | only where S-NPP is missing (from 1 Nov 2026) | 1, otherwise 0 |
| NOAA-21 | — | 0 |
| Aqua | before 2012 | k_aqua (S-NPP / Aqua ratio, same ~13:30 overpass) |
| Terra | only before Aqua existed (Nov 2000 – Jun 2002) | k_terra, otherwise 0 |
| MODIS | 2012 onwards | 0 |

- The ratios are fitted on the overlap **2013–2019** (before the Terra/Aqua orbit drift), per calendar month, falling back to the all-months ratio when counts are small.
- The data team delivers `peso_harm` per hotspot; the app sums it for the **Harmonized** series. Until that column arrives, the monthly chart draws a **provisional estimate** with the same rule, clearly labelled.
- **Validation** for Argentina, 2012–2025: monthly correlation **0.98** between estimated and observed S-NPP; in the years outside the fit (2020–2025) the estimated total differs by about **−2%** from observed.

## Data

| Source | Use |
|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — MODIS C6.1 | Hotspots 2000 → today |
| NASA FIRMS — VIIRS S-NPP / NOAA-20 / NOAA-21 (375 m) | Hotspots 2012 → today |
| [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Recent days (science product, near real time as fallback; needs a free `MAP_KEY`) |
| [geoBoundaries](https://www.geoboundaries.org/) and [Natural Earth](https://github.com/topojson/world-atlas) | Argentine provinces/departments and country boundaries |

Field descriptions: [FIRMS attribute fields (Earthdata)](https://earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).

Current version: 77,292,426 hotspots from 13 South American countries, Nov 2000 → Nov 2026.

## Tech stack

- **Python 3.10+**
- **Dash 3 + Plotly 6**: app, linked charts, MapLibre map (`Choroplethmap` / `Scattermap`)
- **DuckDB + Parquet**: fast queries over ~77 million hotspots, with monthly, daily and grid pre-aggregates; no database server
- **Shapely 2**: assigns each Argentine hotspot to its province and department
- **Flask** blueprint for the admin; **gunicorn** in production
- **pytest**: tests for every page, the admin and the translations
- **Hugging Face Spaces** (Docker) + **GitHub Actions** for deployment

```
app/
  main.py              entry point (python -m app.main)
  config.py            paths and settings (env vars / .env)
  i18n.py, i18n_en.py  PT/EN interface: Portuguese texts wrapped in tr(), English keyed by them
  data/geo.py          boundaries (data/geo/*.geojson)
  data/repository.py   every query the UI uses (the UI never writes SQL)
  data/sala.py         situation room metrics (expected, ratio, status)
  ui/layout.py         Calendar layout
  ui/callbacks.py      one controller updates the state; renderers draw from it
  ui/figures.py        Plotly figures (calendar, anomaly, harmonization, monthly series, validation, timeline)
  ui/sala.py           Situation Room page
  admin.py, admin_page.py   admin API and page
  pipeline/            deliveries, processing, FIRMS download, publishing
  assets/style.css
scripts/               CLI versions of the admin steps, deploy to Hugging Face
tests/
```

## Getting started

```bash
git clone https://github.com/luk14236/space_apps_2026_team_teu.git
cd space_apps_2026_team_teu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set ADMIN_USER, ADMIN_PASSWORD, FIRMS_MAP_KEY

python -m app.main            # http://127.0.0.1:8050  (admin: /admin)
pytest -q
```

To load data, drop the data team's package (`.tar.gz` with `focos_brutos*.csv` / `focos_mensais*.csv`) into `data/entrada/` and click **Import** in the admin, then **Apply**. Command-line alternatives: `scripts/prepare_data.py`, `scripts/fetch_firms.py`, `scripts/publish_data.py`.

`data/geo/` is versioned; deliveries and processed data are not.

### Data contract

Required columns: `pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp`.
Optional: `peso_harm` (harmonized weight per hotspot; enables the *Harmonized* series), `confidence`, `daynight`, `type`.
Missing columns and data issues are listed in `data/processed/meta.json` and shown in the app header.

### Deployment

- **Code:** every push to `main` runs the tests and, if they pass, deploys to the Hugging Face Space (`.github/workflows/deploy.yml`, needs the `HF_TOKEN` secret).
- **Data:** admin step 4 (*Publish to the site*) packs the processed version into a GitHub Release and restarts the Space with it.

## Team

| Member | Contact |
|---|---|
| Lucas Oliveira | [@luk14236](https://github.com/luk14236) |
| Bruno Denardo | [@brunodenardo](https://github.com/brunodenardo) |
| Abner Rodrigo | [@abnercosta97](https://github.com/abnercosta97) |
| Cícero | cicerocasj@gmail.com |
| Fabiano Morelli | Fabianomorelli@hotmai.com |

## AI usage

As the Space Apps 2026 rules require, we disclose that AI tools (Claude, by Anthropic) helped speed up implementation: code, documentation, translations and data processing. The solution idea, the harmonization method and the design decisions are the team's own. Files with substantial AI-assisted content are marked in their headers.

## References

- [Challenge page — MODIS and VIIRS Hot Spots](https://www.spaceappschallenge.org/2026/challenges/modis-and-viirs-hot-spots/)
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
- [MODIS to VIIRS Transition — LAADS DAAC](https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/)
- [Earthdata Forum — end of S-NPP delivery](https://forum.earthdata.nasa.gov/viewtopic.php?p=26446)
- Ren et al., 2026 — [Correction-before-fusion MODIS/VIIRS FRP](https://www.mdpi.com/2072-4292/18/10/1650), *Remote Sensing*
- [MODIS vs VIIRS in forests and low-biomass areas](https://mdpi.com/2072-4292/12/18/2870), *Remote Sensing*, 2020
- UX references: [Global Fire Calendar (Greenpeace)](https://maps.greenpeace.org/projects/firecal/), [EFFIS / GWIS](https://forest-fire.emergency.copernicus.eu/applications), [Global Forest Watch](https://www.globalforestwatch.org/map/), [kepler.gl](https://kepler.gl/), [Perceptual Edge — dashboards for situation awareness](https://www.perceptualedge.com/blog/?p=45), [Horizon charts](https://en.wikipedia.org/wiki/Horizon_chart)

## License

_TBD._
