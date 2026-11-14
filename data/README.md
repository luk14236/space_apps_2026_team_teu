# Data

```
data/
├── geo/         boundaries used by the app (versioned in git)
│   ├── paises.geojson          13 South American countries (Natural Earth)
│   ├── provincias.geojson      24 Argentine provinces (geoBoundaries ADM1, Entre Ríos split out)
│   └── departamentos.geojson   525 Argentine departments (geoBoundaries ADM2)
├── raw/         deliveries as received (NOT in git)
│   ├── focos_brutos_*.csv      one row per hotspot (data team + scripts/fetch_firms.py)
│   └── focos_mensais_*.csv     monthly totals (only used to cross-check)
├── processed/   what the app reads (NOT in git, regenerated from raw/)
│   ├── focos_arg.parquet       Argentine hotspots + province/department
│   ├── focos_outros.parquet    other countries
│   ├── agg_*.parquet           monthly counts per country / province / department x satellite
│   ├── dia_*.parquet           daily counts (situation room)
│   ├── cell_*.parquet          pre-aggregated map grids (0.25° continent, 0.05° Argentina)
│   └── meta.json               period, columns found and data-quality warnings
└── cache/       downloads used by scripts/build_geo.py (NOT in git)
```

## Updating the data

**Easiest:** open `/admin` in the running app.

1. Upload the data team's package (`.tar.gz` / `.zip`) or the CSVs. Only `focos_brutos*.csv` and `focos_mensais*.csv` are kept.
2. Or download recent days from NASA FIRMS (needs `FIRMS_MAP_KEY`).
3. Click **Processar**. The new version replaces the old one without restarting the app.

**Command line:** same steps.

```bash
python scripts/fetch_firms.py --start 2026-01-01      # optional, needs FIRMS_MAP_KEY
python scripts/prepare_data.py                        # data/raw -> data/processed
```

Several `focos_brutos_*.csv` can coexist: they are merged and duplicate hotspots (same time, position and satellite) are kept once.

## Required columns (focos_brutos)

`pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp`

Optional, used when present: `peso_harm` (harmonized weight, enables the *Harmonized* series), `confidence`, `daynight`, `type`.
