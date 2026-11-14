from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

DATASET_DIR = Path(__file__).resolve().parents[1]
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from firms_pipeline import build_duckdb, transform_sources

SOURCE_HEADER = ["latitude", "longitude", "bright", "scan", "track", "acq_date", "acq_time", "satellite", "instrument", "confidence", "version", "bright_t31", "frp", "daynight", "type"]


def _write_source(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_HEADER)
        writer.writeheader()
        writer.writerows(records)


@pytest.fixture()
def sample_dataset(tmp_path: Path) -> dict:
    """Small local source/download/result fixture, including duplicates and HHMM padding."""
    source_dir = tmp_path / "csv" / "raw"
    common = {
        "latitude": "-34.6037", "longitude": "-58.3816", "bright": "310.2",
        "scan": "1", "track": "1", "acq_date": "2024-01-05", "acq_time": "35",
        "confidence": "80", "version": "6.1", "bright_t31": "295", "frp": "4.5",
        "daynight": "D", "type": "0",
    }
    inputs = {
        "modis_2024_Argentina.csv": [
            {**common, "satellite": "Aqua", "instrument": "MODIS"},
            {**common, "satellite": "Terra", "instrument": "MODIS", "acq_date": "2024-02-01", "acq_time": "1234", "frp": "8.25"},
            {**common, "satellite": "Aqua", "instrument": "MODIS"},
        ],
        "viirs-snpp_2024_Brazil.csv": [
            {**common, "satellite": "N", "instrument": "VIIRS", "acq_time": "5", "acq_date": "2024-01-06", "latitude": "-15.7", "longitude": "-47.9"},
        ],
        "viirs-jpss1_2024_French_Guiana.csv": [
            {**common, "satellite": "N20", "instrument": "VIIRS", "acq_time": "2359", "acq_date": "2024-03-31", "latitude": "4.9", "longitude": "-52.3"},
        ],
    }
    source_files = []
    report_path = tmp_path / "csv" / "download_report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as report_handle:
        fields = ["source", "year", "country", "filename", "url", "expected_size", "local_size", "status", "error"]
        report_writer = csv.DictWriter(report_handle, fieldnames=fields)
        report_writer.writeheader()
        for filename, records in inputs.items():
            prefix, year, country = filename[:-4].split("_", 2)
            path = source_dir / prefix / year / filename
            _write_source(path, records)
            size = path.stat().st_size
            source_files.append(path)
            report_writer.writerow({"source": prefix, "year": year, "country": country, "filename": filename, "url": "fixture://" + filename, "expected_size": size, "local_size": size, "status": "downloaded", "error": ""})
    output_dir = tmp_path / "output"
    raw_csv = output_dir / "focos_brutos_america_sul.csv"
    aggregate_csv = output_dir / "focos_mensais_america_sul.csv"
    database = output_dir / "focos_america_sul.duckdb"
    transformed = transform_sources(source_files, raw_csv, aggregate_csv)
    database_summary = build_duckdb(raw_csv, aggregate_csv, database)
    return {
        "root": tmp_path,
        "source_files": source_files,
        "report": report_path,
        "raw": raw_csv,
        "aggregate": aggregate_csv,
        "database": database,
        "transformed": transformed,
        "database_summary": database_summary,
    }


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


@pytest.fixture()
def production_dataset():
    """Use downloaded project artifacts for exhaustive integration tests when present."""
    import csv

    report_path = DATASET_DIR / "csv" / "download_report.csv"
    raw_path = DATASET_DIR / "output" / "focos_brutos_america_sul.csv"
    aggregate_path = DATASET_DIR / "output" / "focos_mensais_america_sul.csv"
    database_path = DATASET_DIR / "output" / "focos_america_sul.duckdb"
    required = [report_path, raw_path, aggregate_path, database_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        pytest.skip("Reconciliação integral depende dos artefatos completos: " + ", ".join(missing))
    with report_path.open(newline="", encoding="utf-8") as handle:
        report = list(csv.DictReader(handle))
    failures = [row for row in report if row["status"] not in {"downloaded", "skipped"}]
    if failures:
        pytest.skip(f"O relatório contém {len(failures)} downloads incompletos")
    source_files = []
    for row in report:
        path = DATASET_DIR / "csv" / "raw" / row["source"] / str(row["year"]) / row["filename"]
        if not path.is_file() or path.stat().st_size != int(row["expected_size"]):
            pytest.fail(f"CSV local ausente ou com tamanho inválido: {path}")
        source_files.append(path)
    return {"source_files": source_files, "raw": raw_path, "aggregate": aggregate_path, "database": database_path}


def source_projection_sql(source_files: list[Path]) -> str:
    """Independent SQL projection of source records into the normalized raw schema."""
    import duckdb

    con = duckdb.connect()
    try:
        branches = []
        country_map = {
            "Argentina": "Argentina", "Bolivia": "Bolívia", "Brazil": "Brasil",
            "Chile": "Chile", "Colombia": "Colômbia", "Ecuador": "Equador",
            "Guyana": "Guiana", "Paraguay": "Paraguai", "Peru": "Peru",
            "Suriname": "Suriname", "Uruguay": "Uruguai", "Venezuela": "Venezuela",
            "French_Guiana": "Guiana Francesa",
        }
        for path in source_files:
            country_token = path.stem.split("_", 2)[2]
            country = country_map[country_token].replace("'", "''")
            escaped = sql_path(path)
            branches.append(f"""SELECT '{country}'::VARCHAR AS pais,
                strptime(acq_date || lpad(acq_time, 4, '0'), '%Y-%m-%d%H%M')::TIMESTAMP AS data_hora_gmt,
                latitude::DOUBLE AS latitude, longitude::DOUBLE AS longitude,
                CASE satellite WHEN 'N20' THEN 'NOAA20' WHEN 'N' THEN 'SNPP' WHEN 'Aqua' THEN 'AQUA' WHEN 'Terra' THEN 'TERRA' END::VARCHAR AS satelite,
                instrument::VARCHAR AS sensor, frp::DOUBLE AS frp
                FROM read_csv('{escaped}', header=true, all_varchar=true)""")
        return " UNION ALL ".join(branches)
    finally:
        con.close()


def relation_differences(con, left_query: str, right_query: str) -> tuple[int, int]:
    # EXCEPT ALL retains multiplicity, including legitimate duplicate observations.
    left_only = con.execute(
        f"SELECT count(*) FROM (({left_query}) EXCEPT ALL ({right_query}))"
    ).fetchone()[0]
    right_only = con.execute(
        f"SELECT count(*) FROM (({right_query}) EXCEPT ALL ({left_query}))"
    ).fetchone()[0]
    return left_only, right_only
