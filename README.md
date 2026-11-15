# Team TEU — MODIS & VIIRS Hotspot Harmonization

> NASA Space Apps Challenge 2026 · Challenge #9 — **MODIS and VIIRS Hot Spots** (proposed by CONAE, Argentina)

A Python web app, centered on Argentina, for exploring fire hotspot activity from **2000 to today** across South America, with the full drill-down (provinces/states → departments/municipalities) for **Argentina, Brazil and the Netherlands**. MODIS and VIIRS detections are joined into one series in the scale of a single VIIRS satellite, so the sensor change in 2012 stops looking like a rise in fire activity.

**Live site:** https://luk14236-space-apps-teu-2026.hf.space · interface in **Portuguese and English** (PT | EN switch at the top of every page).

## The problem

- **MODIS** (Terra/Aqua, ~1 km pixel, since 2000) is being retired.

- **VIIRS** (S-NPP, NOAA-20, NOAA-21, 375 m pixel, since 2012) is the continuity sensor. It sees smaller fires and splits one fire into several pixels.

- If you join the two series without treatment, a false **step** shows up in 2012 when VIIRS comes in (in Argentina the raw total jumps ~229% from 2011 to 2012). It looks like a rise in fire activity, but it is only the sensor change.

## What the app does

### Fire Hotspot Calendar (`/`)

- **Map whose level of detail follows the zoom**: countries → provinces/states → departments/municipalities → grid of cells → individual hotspots colored by satellite. The province and municipality levels exist for Argentina, Brazil and the Netherlands; the fine 0.05° grid and individual hotspots work everywhere. Click to select, or draw a rectangle/polygon; every chart then shows only that area.

- **Month × year calendar** (Greenpeace Global Fire Calendar style) with monthly means and yearly totals; clicking a cell, month or year filters everything.

- **Timeline brush** with playback, **KPIs** (hotspots, density, season peak, record year, month vs. median) and a **ranking** of the level below.

- **The 2012 step**: yearly totals by sensor (raw × MODIS only × harmonized).

- **Monthly series by satellite, in S-NPP scale**: Aqua observed, S-NPP observed and the harmonized series shown before the first S-NPP observation.

- **Validation (Aqua → S-NPP, estimated × observed)**: in the years both satellites exist, S-NPP estimated from Aqua alone against S-NPP observed, with monthly correlation and out-of-sample error.

- **Season anomaly** (EFFIS style): cumulative year against min–max / p25–p75 / median and monthly anomaly bars.

- **CSV export** of the hotspots in the selected area and period.

### Situation Room (`/sala`)

A decision dashboard organized by Endsley's situation-awareness levels, for **Argentina, Brazil or the Netherlands** (country selector at the top). It compares the last 24 h / 7 days / 30 days with what is **expected** for the time of year (2019–2025 mean of the same month):

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

- The data team fits the Aqua → S-NPP and Terra → S-NPP conversion with a **quasi-Poisson model** per country and delivers the result as `peso_harm` on every hotspot (2000–2025). The app sums it for the **Harmonized** series; their totals match the team's monthly file.

- Hotspots that arrived later without a weight (FIRMS days of 2026) get the model-free part of the same rule: S-NPP = 1, NOAA-20 = 1 only after S-NPP ended (1 Nov 2026), every other satellite = 0.

- The in-app validation chart uses a simple S-NPP/Aqua ratio per calendar month fitted on **2013–2019** (before the Terra/Aqua orbit drift).

- **Validation** for Argentina, 2012–2025: monthly correlation **0.98** between estimated and observed S-NPP; in the years outside the fit (2020–2025) the estimated total differs by about **−2%** from observed.

## Data

| Source | Use |
|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — MODIS C6.1 | Hotspots 2000 → today |
| NASA FIRMS — VIIRS S-NPP / NOAA-20 / NOAA-21 (375 m) | Hotspots 2012 → today |
| [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Recent days (science product, near real time as fallback; needs a free `MAP_KEY`) |
| [FIRMS country archive](https://firms.modaps.eosdis.nasa.gov/country/) | Netherlands history 2000–2025 (yearly per-country files) |
| [geoBoundaries](https://www.geoboundaries.org/) and [Natural Earth](https://github.com/topojson/world-atlas) | Provinces/states and departments/municipalities of Argentina, Brazil and the Netherlands; country boundaries |

Field descriptions: [FIRMS attribute fields (Earthdata)](https://earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).

Current version: 77,375,757 hotspots covering 13 South American countries and the Netherlands, Nov 2000 → Nov 2026.

## Tech stack

- **Python 3.10+**

- **Dash 3 + Plotly 6**: app, linked charts, MapLibre map (`Choroplethmap` / `Scattermap`)

- **DuckDB + Parquet**: fast queries over ~77 million hotspots, with monthly, daily and grid pre-aggregates; no database server

- **Shapely 2**: assigns each hotspot of Argentina, Brazil and the Netherlands to its province/state and department/municipality (in parallel, per country)

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

### 1. Install the application

Clone the repository, create a virtual environment, and install the dependencies:

```bash
git clone https://github.com/luk14236/space_apps_2026_team_teu.git
cd space_apps_2026_team_teu

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` to configure `ADMIN_USER`, `ADMIN_PASSWORD`, and `FIRMS_MAP_KEY` as needed. The activation command above is for macOS/Linux; on Windows, use the equivalent activation command for your shell.

### 2. Load or process the data

Choose **one** of the following options to prepare the data used by the dashboard. **Option A** is recommended if you only want to run the application; **Option B** is intended for reproducing the extraction, preprocessing, and harmonization workflow.

#### Option A — Use the provided dataset (recommended)

1. [Download the dataset package from Google Drive](https://drive.google.com/file/d/1JJssr22AztPj4p3DzUeQcbEIb2GzpoVI/view?usp=drive_link).
2. Extract the package into the repository's `data/` directory. Ensure the supplied input files are placed under `data/` as expected by the preparation script.
3. From the repository root, generate the application-ready data:

   ```bash
   python scripts/prepare_data.py --raw data --out data/processed
   ```

The preparation step builds the data files and aggregates consumed by the dashboard. If your download has a different directory structure, place the files where the preparation script expects them before running it.

#### Option B — Rebuild the dataset from NASA FIRMS

This workflow uses three Jupyter notebooks, executed **in order**:

| Step | Notebook | Purpose |
| --- | --- | --- |
| 1. Extract | [`01_download_firms.ipynb`](dataset_processing/dataset_extractor/01_download_firms.ipynb) | Download annual FIRMS CSV files by country. |
| 2. Process | [`02_tratamento_firms.ipynb`](dataset_processing/dataset_extractor/02_tratamento_firms.ipynb) | Normalize hotspot detections, generate monthly counts, and build DuckDB. |
| 3. Harmonize | [`regressoes_modis_viirs_por_pais.ipynb`](dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb) | Fit country-specific MODIS-to-S-NPP regressions and generate harmonized outputs. |

Install the processing dependencies from the repository root:

```bash
python -m pip install -r dataset_processing/dataset_extractor/requirements.txt
python -m pip install -r dataset_processing/regression/requirements.txt
```

Open each notebook in JupyterLab and **run all cells to completion** before moving to the next one:

```bash
# 1. Extract FIRMS data
jupyter lab dataset_processing/dataset_extractor/01_download_firms.ipynb

# 2. Process the downloaded data
jupyter lab dataset_processing/dataset_extractor/02_tratamento_firms.ipynb

# 3. Fit regressions and generate harmonized data
jupyter lab dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb
```

The notebook outputs are saved under `data/`. Once the final raw and monthly CSV outputs are available in the input location expected by the application, prepare the dashboard data:

```bash
python scripts/prepare_data.py --raw data --out data/processed
```

Before rebuilding, read the [dataset extraction runbook](dataset_processing/dataset_extractor/README.md), especially the instructions about preserving existing data and rerunning the regression workflow.

#### Alternative — Import a data-team delivery through Admin

To use the administration interface instead of running the preparation script manually:

1. Place the `.tar.gz` delivery containing `focos_brutos*.csv` and `focos_mensais*.csv` in `data/entrada/`.
2. Open `/admin` and sign in.
3. Select **Import** to process the package, then **Apply** to activate the resulting version.

Related command-line utilities: `scripts/prepare_data.py`, `scripts/fetch_firms.py`, and `scripts/publish_data.py`.

> **Data storage:** `data/geo/` is version-controlled. Incoming deliveries and generated datasets are not.

### 3. Run the application

Start the local web app:

```bash
python -m app.main
```

Open **http://127.0.0.1:8050** in your browser. The administration interface is available at **http://127.0.0.1:8050/admin**.

To run the automated tests, install the development dependencies if needed and execute:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

### Data contract

The application accepts hotspot-level inputs with the following required columns:

`pais`, `data_hora_gmt`, `latitude`, `longitude`, `satelite`, `sensor`, `frp`

Optional hotspot fields include:

- `peso_harm` — per-hotspot harmonization weight, used to construct harmonized aggregates.
- `confidence`, `daynight`, `type` — additional FIRMS attributes.

The data team can also provide monthly files (`focos_mensais*.csv`) with aggregated observed and harmonized counts, including `nfocos` and `nfocos_harm`. These monthly fields are distinct from the per-hotspot `peso_harm` field; see the pipeline documentation for how deliveries are imported and checked.

Missing columns and data-quality issues are recorded in `data/processed/meta.json` and shown in the application header.

### Deployment

- **Code:** Each push to `main` runs the tests and, if they pass, deploys the app to Hugging Face Spaces via `.github/workflows/deploy.yml` (requires the `HF_TOKEN` secret).
- **Data:** Step 4 of the Admin workflow (*Publish to the site*) packages the processed dataset as a GitHub Release and restarts the Space with the updated data.

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

- Ren et al., 2026 — [Correction-before-fusion MODIS/VIIRS FRP](https://www.mdpi.com/2072-4292/18/10/1650), **Remote Sensing**

- [MODIS vs VIIRS in forests and low-biomass areas](https://mdpi.com/2072-4292/12/18/2870), **Remote Sensing**, 2020

- UX references: [Global Fire Calendar (Greenpeace)](https://maps.greenpeace.org/projects/firecal/), [EFFIS / GWIS](https://forest-fire.emergency.copernicus.eu/applications), [Global Forest Watch](https://www.globalforestwatch.org/map/), [kepler.gl](https://kepler.gl/), [Perceptual Edge — dashboards for situation awareness](https://www.perceptualedge.com/blog/?p=45), [Horizon charts](https://en.wikipedia.org/wiki/Horizon_chart)

## License

*_TBD._*
