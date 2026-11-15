# FIRMS Dataset Extraction

This directory contains the download and treatment workflow for the South American NASA FIRMS data used by the project. Run the notebooks in order because the treatment step validates the download report and source files produced by the first step.

## Requirements

From the repository root:

```bash
python -m pip install -r dataset_processing/dataset_extractor/requirements.txt
```

The notebooks also require Jupyter. Install or launch it from the project environment used for data processing.

## Execution order

### 1. Download the FIRMS source files

Open:

```bash
jupyter lab dataset_processing/dataset_extractor/01_download_firms.ipynb
```

The notebook starts with `DRY_RUN = True`. A dry run queries the FIRMS manifest and records the planned work without downloading the CSVs. Set `DRY_RUN = False` and rerun the notebook when the selection is correct.

Downloads are organized under:

```text
dataset_processing/dataset_extractor/csv/raw/<source>/<year>/<filename>.csv
```

The notebook also writes:

```text
dataset_processing/dataset_extractor/csv/download_report.csv
```

Each download is first written to a `.part` file, checked against the manifest size, and then moved to its final `.csv` name. A valid existing file with the expected size is preserved and reported as skipped. The report must contain only completed `downloaded` or `skipped` entries before treatment can proceed.

### 2. Transform and load the data

Open:

```bash
jupyter lab dataset_processing/dataset_extractor/02_tratamento_firms.ipynb
```

The notebook reads only the local source CSVs listed in `download_report.csv`; it does not download data. It normalizes rows while streaming them, preserves duplicate source detections, validates counts, and produces:

```text
data/focos_brutos_america_sul.csv
data/focos_mensais_america_sul.csv
data/focos_america_sul.duckdb
```

`focos_brutos_america_sul.csv` contains one row per source detection and initially leaves `peso_harm` empty. `focos_mensais_america_sul.csv` groups observed counts by year, month, country, satellite, and sensor; when regenerated, `nfocos_harm` and `modelo_harm` start empty. The DuckDB database contains `focos_brutos` and `focos_mensais`, and preserves `modelos_equacoes` when that table already exists.

## Preservation semantics

The treatment notebook currently defaults to `REPROCESSAR_AGREGADO = False`:

- The raw CSV and `focos_brutos` table are rebuilt from the downloaded FIRMS files.
- The existing monthly CSV is not replaced.
- The existing `focos_mensais` table, including harmonized values and synthetic rows, is copied into the rebuilt database.
- An existing `modelos_equacoes` table is copied into the rebuilt database.
- Existing `peso_harm` values are preserved when the rebuilt observations reconcile exactly with the current raw CSV and DuckDB table. The workflow stops instead of carrying weights onto changed observations.

For the first clean run, set `REPROCESSAR_AGREGADO = True`; preservation mode requires existing raw/monthly CSVs and a synchronized DuckDB database.

With `REPROCESSAR_AGREGADO = True`, the raw and monthly CSVs and both corresponding DuckDB tables are rebuilt from source detections. Observed detections and counts are preserved, but monthly harmonized values and synthetic SNPP rows are cleared by regeneration. An existing `modelos_equacoes` table is still preserved in the rebuilt database.

CSV outputs are prepared in temporary files, validated, and individually moved into place. The DuckDB database is built and validated as a temporary database before its file replaces the previous database. These filesystem replacements reduce the chance of publishing partial files, but the CSV and database replacements are not one cross-file atomic transaction.

## Rerun regression after a rebuild

After rebuilding raw data, rerun the regression notebook:

```bash
jupyter lab dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb
```

Rerun regression whenever `REPROCESSAR_AGREGADO = True`, because regenerating the monthly aggregate clears `nfocos_harm`, `modelo_harm`, synthetic SNPP rows, and spatial weights. With `REPROCESSAR_AGREGADO = False`, exact reconciliation preserves those values; a mismatch aborts the rebuild. See the [regression documentation](../regression/README.md) for the model and publication behavior.

## Tests

From the repository root:

```bash
pytest dataset_processing/dataset_extractor/testes -v
```

Fixture-based tests run without the complete dataset. Full production reconciliation tests require all downloaded source files and generated outputs at the expected paths.

## Shared dataset folder

The project also records a [shared dataset link](dataset_link.md). Its provenance, version, license, contents, and checksums are not yet documented; do not infer those details from the link.
