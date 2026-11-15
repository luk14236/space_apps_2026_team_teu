import csv

import duckdb
import pytest

from conftest import relation_differences, source_projection_sql, sql_path
from firms_pipeline import RAW_COLUMNS, transform_sources


def test_raw_schema_and_full_row_reconciliation(sample_dataset):
    con = duckdb.connect()
    try:
        source_query = source_projection_sql(sample_dataset["source_files"])
        raw_query = f"SELECT pais, strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP AS data_hora_gmt, latitude::DOUBLE, longitude::DOUBLE, satelite, sensor, frp::DOUBLE, confidence, daynight, type::INTEGER FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true, all_varchar=true)"
        differences = relation_differences(con, source_query, raw_query)
        assert differences == (0, 0), f"Linhas divergentes fonte->bruto/bruto->fonte: {differences}"
        columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true)").fetchall()]
        assert columns == RAW_COLUMNS
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true)").fetchone()[0] == 5
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) WHERE data_hora_gmt IS NULL").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) WHERE satelite NOT IN ('NOAA20','SNPP','AQUA','TERRA') OR sensor NOT IN ('MODIS','VIIRS')").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) WHERE pais NOT IN ('Argentina','Brasil','Guiana Francesa')").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) WHERE confidence='n'").fetchone()[0] == 1
        assert con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) WHERE peso_harm IS NOT NULL").fetchone()[0] == 0
        # Exact duplicate source observations remain duplicated in the raw output.
        assert con.execute(f"SELECT count(*) FROM (SELECT * FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true) GROUP BY ALL HAVING count(*) > 1)").fetchone()[0] == 1
    finally:
        con.close()


def test_hour_padding_and_satellite_mapping(sample_dataset):
    con = duckdb.connect()
    try:
        path = sql_path(sample_dataset["raw"])
        assert con.execute(f"SELECT count(*) FROM read_csv('{path}', header=true) WHERE data_hora_gmt = '2024-01-05 00:35:00' AND satelite='AQUA'").fetchone()[0] == 2
        assert con.execute(f"SELECT count(*) FROM read_csv('{path}', header=true) WHERE satelite='SNPP'").fetchone()[0] == 1
        assert con.execute(f"SELECT count(*) FROM read_csv('{path}', header=true) WHERE satelite='NOAA20'").fetchone()[0] == 1
        assert con.execute(f"SELECT count(*) FROM read_csv('{path}', header=true) WHERE sensor='VIIRS'").fetchone()[0] == 2
    finally:
        con.close()


def test_rebuild_preserves_populated_weights_after_exact_reconciliation(sample_dataset):
    with sample_dataset["raw"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["peso_harm"] = "1.25"
    rows[-1]["peso_harm"] = "0.75"
    with sample_dataset["raw"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    result = transform_sources(
        sample_dataset["source_files"], sample_dataset["raw"], sample_dataset["aggregate"], reprocess_aggregate=False
    )

    with sample_dataset["raw"].open(newline="", encoding="utf-8") as handle:
        rebuilt = list(csv.DictReader(handle))
    assert sorted(row["peso_harm"] for row in rebuilt if row["peso_harm"]) == ["0.75", "1.25"]
    assert result["preserved_weights"] == 2


def test_rebuild_rejects_same_total_with_different_monthly_group(sample_dataset):
    with sample_dataset["aggregate"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["mes"] = "12"
    with sample_dataset["aggregate"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(RuntimeError, match="Validação da agregação falhou"):
        transform_sources(
            sample_dataset["source_files"], sample_dataset["raw"], sample_dataset["aggregate"], reprocess_aggregate=False
        )


def test_rebuild_ignores_synthetic_monthly_rows_during_reconciliation(sample_dataset):
    with sample_dataset["aggregate"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.append({
        "ano": "2010", "mes": "1", "pais": "Argentina", "satelite": "SNPP",
        "sensor": "VIIRS", "nfocos": "", "nfocos_harm": "12",
        "modelo_harm": "AQUA->SNPP | quasi_poisson | potencial",
    })
    with sample_dataset["aggregate"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    transform_sources(
        sample_dataset["source_files"], sample_dataset["raw"], sample_dataset["aggregate"],
        reprocess_aggregate=False,
    )

    with sample_dataset["aggregate"].open(newline="", encoding="utf-8") as handle:
        preserved = list(csv.DictReader(handle))
    assert any(not row["nfocos"] and row["nfocos_harm"] == "12" for row in preserved)


def test_production_sources_reconcile_exhaustively(production_dataset):
    con = duckdb.connect()
    try:
        source = source_projection_sql(production_dataset["source_files"])
        raw = f"SELECT pais, strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP AS data_hora_gmt, latitude::DOUBLE, longitude::DOUBLE, satelite, sensor, frp::DOUBLE, confidence, daynight, type::INTEGER FROM read_csv('{sql_path(production_dataset['raw'])}', header=true, all_varchar=true)"
        differences = relation_differences(con, source, raw)
        assert differences == (0, 0), f"Reconciliação integral divergiu: {differences}"
    finally:
        con.close()
