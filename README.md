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
| NASA FIRMS — VIIRS S-NPP / NOAA-20 | Hotspots 2012 → today |
| [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Queries by bounding box and date (needs a free `MAP_KEY`) |

Field descriptions: [FIRMS attribute fields (Earthdata)](https://earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs).

## Harmonization approach

The current pipeline builds an **SNPP-only harmonized series**. It fits country-specific MODIS-to-SNPP count models from paired monthly observations, using the globally selected **Quasi-Poisson + power** specification for both AQUA → SNPP and TERRA → SNPP. AQUA is the preferred MODIS predictor for each country/month; TERRA is the fallback whenever AQUA is unavailable, in any year.

The model estimates an SNPP-scale monthly count (`nfocos_harm`) wherever a MODIS monthly count exists. Observed SNPP counts remain separate in `nfocos`; missing SNPP country/month rows are created as explicitly synthetic estimates. NOAA-20 observations are retained in the data but are not used to fit the regressions or construct the harmonized series.

For spatial display, modeled pre-2012 totals are distributed over detections from the selected MODIS source. From 2012 onward, observed SNPP detections receive weight `1`; model-only months without observed SNPP have no spatial weight. See the [regression documentation](dataset_processing/regression/README.md) for formulas, metrics, limitations, and persistence details.

## Tech stack

_TBD._

## Getting started

```bash
# clone
git clone <repo-url>
cd space_apps_2026_team_teu
```

### Data processing

The data workflow is notebook-based and must run in this order:

1. Download the annual FIRMS country CSVs with [`01_download_firms.ipynb`](dataset_processing/dataset_extractor/01_download_firms.ipynb).
2. Normalize detections, create monthly counts, and build DuckDB with [`02_tratamento_firms.ipynb`](dataset_processing/dataset_extractor/02_tratamento_firms.ipynb).
3. Fit the MODIS → SNPP regressions and publish harmonized fields with [`regressoes_modis_viirs_por_pais.ipynb`](dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb).

Install the processing dependencies and launch the notebooks from the repository root:

```bash
python -m pip install -r dataset_processing/dataset_extractor/requirements.txt
python -m pip install -r dataset_processing/regression/requirements.txt
jupyter lab dataset_processing/dataset_extractor/01_download_firms.ipynb
```

After the download completes, open the treatment notebook and then the regression notebook:

```bash
jupyter lab dataset_processing/dataset_extractor/02_tratamento_firms.ipynb
jupyter lab dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb
```

The generated datasets are written under `data/`. Read the [dataset extraction runbook](dataset_processing/dataset_extractor/README.md) before rebuilding them, especially its preservation and regression-rerun notes.

## Team

_TBD._

## AI usage

As the Space Apps 2026 rules require, we disclose that AI tools (Claude and ChatGPT) helped speed up implementation: code, documentation, and data processing. The solution idea and design decisions are the team's own. Files with substantial AI-assisted content will be marked in their headers.

## References

- [Challenge page — MODIS and VIIRS Hot Spots](https://www.spaceappschallenge.org/2026/challenges/modis-and-viirs-hot-spots/)
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
- [MODIS to VIIRS Transition — LAADS DAAC](https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/)
- Ren et al., 2026 — [Correction-before-fusion MODIS/VIIRS FRP](https://www.mdpi.com/2072-4292/18/10/1650), *Remote Sensing*
- [MODIS vs VIIRS in forests and low-biomass areas](https://mdpi.com/2072-4292/12/18/2870), *Remote Sensing*, 2020
- UX inspiration: [Global Fire Calendar (Greenpeace)](https://maps.greenpeace.org/projects/firecal/), [GWIS (JRC)](https://gwis.jrc.ec.europa.eu/applications), [EFFIS](https://effis.jrc.ec.europa.eu/)

## License

_TBD._
