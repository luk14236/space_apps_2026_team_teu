# Team TEU — MODIS & VIIRS Hotspot Harmonization

> NASA Space Apps Challenge 2026 · Challenge #9 — **MODIS and VIIRS Hot Spots** (proposed by CONAE, Argentina)

A Python web app, centered on Argentina, for exploring fire hotspot records **from 2000 through the latest loaded observations** across South America, with administrative drill-down (provinces/states → departments/municipalities) for **Argentina, Brazil and the Netherlands**. The project estimates historical counts on the Suomi NPP VIIRS scale to improve comparability across the MODIS–VIIRS transition.

**Live site:** https://luk14236-space-apps-teu-2026.hf.space · interface in **Portuguese and English** (PT | EN switch at the top of every page).

## The problem

- **MODIS** (Terra/Aqua, ~1 km pixel, since 2000) is being retired.

- **VIIRS** (S-NPP, NOAA-20, NOAA-21, 375 m pixel, since 2012) is the continuity sensor. It sees smaller fires and splits one fire into several pixels.

- Combining raw counts across sensors can introduce an artificial **step** when VIIRS observations begin in 2012. An increase in combined detections cannot, by itself, establish an increase in fire activity or quantify how much of the change is due to the sensor.

Hotspot detections are not counts of individual fires or measurements of burned area.

## What the app does

### Fire Hotspot Calendar (`/`)

- **Map whose level of detail follows the zoom**: countries → provinces/states → departments/municipalities → grid of cells → individual hotspots colored by satellite. The province and municipality levels exist for Argentina, Brazil and the Netherlands; the fine 0.05° grid and individual hotspots work everywhere. Click to select, or draw a rectangle/polygon; every chart then shows only that area.

- **Month × year calendar** (Greenpeace Global Fire Calendar style) with monthly means and yearly totals; clicking a cell, month or year filters everything.

- **Timeline brush** with playback, **KPIs** (hotspots, density, season peak, record year, month vs. median) and a **ranking** of the level below.

- **The 2012 step**: yearly totals by sensor (raw × MODIS only × harmonized).

- **Monthly series by satellite, in S-NPP scale**: Aqua observed, S-NPP observed and the harmonized series shown before the first S-NPP observation.

- **Ratio-based diagnostic (Aqua → S-NPP, estimated × observed)**: estimates from calendar-month ratios against observed S-NPP counts, with monthly correlation and post-calibration total error. This is separate from the regression pipeline evaluation below.

- **Season anomaly** (EFFIS style): cumulative year against min–max / p25–p75 / median and monthly anomaly bars.

- **CSV export** of the hotspots in the selected area and period.

### Situation Room (`/sala`)

A decision dashboard organized by Endsley's situation-awareness levels, for **Argentina, Brazil or the Netherlands** (country selector at the top). It compares the last 24 h / 7 days / 30 days with what is **expected** for the time of year (2019–2025 mean of the same month):

alerts by department, priority queue, anomaly map (departments on alert drawn over provinces), 90-day horizon chart, priority quadrant, hotspots of the last day, cumulative season with a projection cone, season clock, satellite status. Widgets can be reordered, resized, hidden and added; three ready-made layouts.

### Admin (`/admin`, hidden, login required)

Four-step flow to **receive deliveries** (inbox folder, browser upload, link, NASA FIRMS API), **check** them, **process and apply** a new version (with a side-by-side comparison and rollback) and **publish** it to the live site. Deliveries and applied versions are recorded in a history. See the import and deployment instructions below.

**Target users:** fire brigades, Civil Defense, scientists and land managers.

## Harmonization approach

Target scale: **one VIIRS satellite (S-NPP)**. Combining counts from multiple VIIRS satellites can introduce additional discontinuities; the historical regression workflow therefore targets S-NPP rather than their sum.

### Country-specific regression

The data pipeline compares six configurations for Argentina / Aqua → S-NPP: Quasi-Poisson and Negative Binomial families, each with proportional, exponential and power mean functions. **Quasi-Poisson + power** has the lowest in-sample MAE. That structure is fitted separately for each country and source satellite; Argentina's coefficients are not copied to other countries.

Aqua is the preferred source because its overpass time is comparable to S-NPP's. Terra is used when Aqua is unavailable for a country/month. The method operates on monthly country totals, not matched fire pixels.

| Output | Meaning |
|---|---|
| `nfocos` | Observed monthly detection count; null for synthetic S-NPP rows |
| `nfocos_harm` | MODIS-model prediction on the S-NPP scale, including overlap months |
| `peso_harm` | Per-detection weight used for the spatial harmonized series |

Before 2012, weights distribute the predicted monthly count across detections from the selected Aqua/Terra source. From 2012 onward, the historical pipeline assigns observed S-NPP detections weight 1 and other detections weight 0. Consequently, the sum of spatial weights reproduces predictions before 2012 and observed S-NPP counts afterward; it does **not** always equal `nfocos_harm`. NOAA-20 is retained as observed data but excluded from this historical regression and weighting workflow.

### Application updates and provisional estimates

For incoming rows without weights, [`app/pipeline/prepare.py`](app/pipeline/prepare.py) fills S-NPP weights with 1 and NOAA-20 weights with 1 for timestamps on or after **2026-11-01**. Other rows from 2012 onward receive 0; earlier MODIS rows remain without a weight because no regression has been supplied. This date-based NOAA-20 fallback does not check for simultaneous S-NPP observations, so overlapping deliveries require review before treating their combined weights as a single-satellite series.

When delivered harmonization is unavailable, the monthly chart has a provisional ratio-based estimate. The separate in-app diagnostic also uses **S-NPP/Aqua ratios by calendar month calibrated on 2013–2019**, not the Quasi-Poisson model. It reports correlation across eligible overlap months and aggregate percentage error for eligible years after 2019. Results depend on the selected area and loaded observations; they are not validation metrics for the regression pipeline.

### Results and limitations

The [regression report](dataset_processing/regression/README.md) records these Argentina / Aqua → S-NPP results:

| Measure | Result |
|---|---|
| Fit and evaluation period | January 2012–December 2025, 168 paired months |
| MAE | 3,287.39 hotspots/month |
| RMSE | 4,970.02 hotspots/month |
| Largest absolute monthly error | 19,260.15 hotspots, January 2022 |

These are **in-sample** results: the same observations were used for fitting and evaluation. They do not establish future predictive accuracy. Independent temporal validation, vegetation-aware models and regional calibration are planned improvements.

Country-level relationships can hide local differences in vegetation, fire characteristics and satellite observation conditions. Spatially distributed weights are not independently validated local reconstructions. The Situation Room supports investigation and planning; its projections are not a validated fire forecast.

## Data

| Source | Use |
|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — MODIS C6.1 | Historical and recent Terra/Aqua detections, subject to loaded coverage |
| NASA FIRMS — VIIRS S-NPP / NOAA-20 / NOAA-21 (375 m) | Observed VIIRS records; S-NPP is the historical regression target |
| [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Recent days (science product, near real time as fallback; needs a free `MAP_KEY`) |
| [FIRMS country archive](https://firms.modaps.eosdis.nasa.gov/country/) | Netherlands history 2000–2025 (yearly per-country files) |
| [geoBoundaries](https://www.geoboundaries.org/) and [Natural Earth](https://github.com/topojson/world-atlas) | Provinces/states and departments/municipalities of Argentina, Brazil and the Netherlands; country boundaries |

Field descriptions: [FIRMS attribute fields (Earthdata)](https://earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).

The application recognizes 13 South American countries/territories and the Netherlands. Actual coverage, record counts and latest dates depend on the installed delivery. Check `data/processed/meta.json` and the application header for the active dataset rather than assuming a fixed total or real-time completeness.

## Tech stack

- **Python 3.10+**

- **Dash 3 + Plotly 6**: app, linked charts, MapLibre map (`Choroplethmap` / `Scattermap`)

- **DuckDB + Parquet**: analytical queries with monthly, daily and grid pre-aggregates; no database server

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

Open each notebook in JupyterLab and **run all cells to completion** before moving to the next one. Install JupyterLab separately if it is not available (`python -m pip install jupyterlab`). For a fresh rebuild, set `DRY_RUN = False` in the download notebook and `REPROCESSAR_AGREGADO = True` in the treatment notebook; read the extraction runbook before changing these options for an existing dataset.

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

## AI usage

As the Space Apps 2026 rules require, we disclose that Claude (Anthropic) assisted with code, documentation, translations and data-processing implementation. An OpenAI assistant also helped review submission requirements, prepare presentation text and layout, capture the live application with Selenium, and revise this README. The solution idea, harmonization method and design decisions are the team's own, as declared by the team. AI-assisted implementation files include disclosure headers; this section records assistance with the submission materials and this document. Live application screenshots and statistical charts are distinct from generative imagery.

## References

- [Challenge page — MODIS and VIIRS Hot Spots](https://www.spaceappschallenge.org/2026/challenges/modis-and-viirs-hot-spots/)

- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)

- [MODIS to VIIRS Transition — LAADS DAAC](https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/)

- [Earthdata Forum — end of S-NPP delivery](https://forum.earthdata.nasa.gov/viewtopic.php?p=26446)

- [Fire Radiative Power Correction and Spatiotemporal Fusion Based on MYD14 and VNP14IMG](https://doi.org/10.3390/rs18101650), **Remote Sensing**, 2026, 18(10), 1650. See the regression documentation for its methodological role.

- [MODIS vs VIIRS in forests and low-biomass areas](https://mdpi.com/2072-4292/12/18/2870), **Remote Sensing**, 2020

- UX references: [Global Fire Calendar (Greenpeace)](https://maps.greenpeace.org/projects/firecal/), [EFFIS / GWIS](https://forest-fire.emergency.copernicus.eu/applications), [Global Forest Watch](https://www.globalforestwatch.org/map/), [kepler.gl](https://kepler.gl/), [Perceptual Edge — dashboards for situation awareness](https://www.perceptualedge.com/blog/?p=45), [Horizon charts](https://en.wikipedia.org/wiki/Horizon_chart)

- Map attribution: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) and [CARTO](https://carto.com/attributions), alongside the boundary sources listed above.

- Software dependencies: [application requirements](requirements.txt), [extraction requirements](dataset_processing/dataset_extractor/requirements.txt), and [regression requirements](dataset_processing/regression/requirements.txt). Third-party software and data retain their respective licenses and attribution requirements.

## License

The project license has not yet been selected. Public repository access does not itself grant an open-source license. Third-party data, code and visual resources remain subject to their own terms.
