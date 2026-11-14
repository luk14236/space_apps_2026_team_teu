# Team TEU — MODIS & VIIRS Hotspot Harmonization

> NASA Space Apps Challenge 2026 · Challenge #9 — *MODIS and VIIRS Hot Spots* (proposed by CONAE, Argentina)

An interactive web map, centered on Argentina, for exploring fire hotspot activity from **2000 to today**. MODIS and VIIRS detections are merged into one series in which the source sensor no longer matters.

> **Status:** work in progress. This README will be updated as the project evolves.

## The problem

- **MODIS** (Terra/Aqua, ~1 km pixel, since 2000) is being retired.
- **VIIRS** (S-NPP, NOAA-20, NOAA-21, 375 m pixel, since 2012) is the continuity sensor. It sees smaller fires and splits one fire into several pixels.
- If you join the two series without treatment, a false **step** shows up in 2012 when VIIRS comes in. It looks like a rise in fire activity, but it is only the sensor change.

## What the app does (planned)

- **Map navigation** with Argentina as the default view.
- **Draw an area** on the map with the mouse (rectangle or polygon). Every chart updates to show **only that area**.
- **Filter by location**: search a province, department, or place, or type lat/long.
- **Fire calendar**: a month × year heatmap of harmonized hotspot counts.
- **Answers to key questions**:
  - Which months of the year have the most fire?
  - Which years had the most activity?
  - Is the current month above or below the historical median (anomaly)?
- **CSV export** of the hotspots in the selected area.
- Accessible color ramps.

**Target users:** fire brigades, Civil Defense, scientists, and land managers.

## Data

| Source | Use |
|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — MODIS C6.1 (`MODIS_SP`/`MODIS_NRT`) | Hotspots 2000 → today |
| NASA FIRMS — VIIRS S-NPP / NOAA-20 / NOAA-21 | Hotspots 2012 → today |
| [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Queries by bounding box and date (needs a free `MAP_KEY`) |

Field descriptions: [FIRMS attribute fields (Earthdata)](https://earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).

## Harmonization approach

_TBD — to be defined by the team._

## Tech stack

- **Python 3.10+**
- **Dash 3 + Plotly 6**: app, linked charts, MapLibre map (`Choroplethmap` / `Scattermap`)
- **DuckDB + Parquet**: fast queries over ~73 million hotspots, no database server
- **Shapely 2**: assigns each Argentine hotspot to its province and department
- **pytest**: smoke tests on the processed data

```
app/
  main.py            entry point (python -m app.main)
  config.py          paths and server settings (env vars)
  data/geo.py        boundaries (data/geo/*.geojson)
  data/repository.py every query the UI uses (the UI never writes SQL)
  ui/layout.py       page layout
  ui/callbacks.py    one controller updates the state; renderers draw from it
  ui/figures.py      Plotly figures (calendar, anomaly, harmonization, timeline, map helpers)
  assets/style.css
scripts/
  build_geo.py       downloads and simplifies boundaries -> data/geo/
  prepare_data.py    data team CSV -> data/processed/*.parquet + meta.json
tests/
```

## Getting started

```bash
git clone <repo-url>
cd space_apps_2026_team_teu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. put the data team's delivery in data/raw/ (focos_brutos_*.csv, focos_mensais_*.csv)
python scripts/prepare_data.py            # or: --raw /path/to/output
# 2. run the app
python -m app.main                        # http://127.0.0.1:8050
# tests
pytest -q
```

`data/geo/` (boundaries) is versioned. `data/raw/` and `data/processed/` are not; regenerate them with the script.
Settings: `FOCOS_PROCESSED_DIR`, `FOCOS_GEO_DIR`, `HOST`, `PORT`, `DASH_DEBUG=1`.

### Data contract

`prepare_data.py` requires `pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp` and uses these optional columns when present:
`peso_harm` (harmonized weight per hotspot; enables the *Harmonized* series), `confidence`, `daynight`, `type`.
Missing columns and data issues are listed in `data/processed/meta.json` and shown in the app header.

## Team

_TBD._

## AI usage

As the Space Apps 2026 rules require, we disclose that AI tools (Claude) helped speed up implementation: code, documentation, and data processing. The solution idea and design decisions are the team's own. Files with substantial AI-assisted content will be marked in their headers.

## References

- [Challenge page — MODIS and VIIRS Hot Spots](https://www.spaceappschallenge.org/2026/challenges/modis-and-viirs-hot-spots/)
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
- [MODIS to VIIRS Transition — LAADS DAAC](https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/)
- Ren et al., 2026 — [Correction-before-fusion MODIS/VIIRS FRP](https://www.mdpi.com/2072-4292/18/10/1650), *Remote Sensing*
- [MODIS vs VIIRS in forests and low-biomass areas](https://mdpi.com/2072-4292/12/18/2870), *Remote Sensing*, 2020
- UX inspiration: [Global Fire Calendar (Greenpeace)](https://maps.greenpeace.org/projects/firecal/), [GWIS (JRC)](https://gwis.jrc.ec.europa.eu/applications), [EFFIS](https://effis.jrc.ec.europa.eu/)

## License

_TBD._
