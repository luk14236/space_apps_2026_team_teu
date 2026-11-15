import duckdb

from conftest import relation_differences, source_projection_sql, sql_path
from firms_pipeline import RAW_COLUMNS


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


def test_production_sources_reconcile_exhaustively(production_dataset):
    con = duckdb.connect()
    try:
        source = source_projection_sql(production_dataset["source_files"])
        raw = f"SELECT pais, strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP AS data_hora_gmt, latitude::DOUBLE, longitude::DOUBLE, satelite, sensor, frp::DOUBLE, confidence, daynight, type::INTEGER FROM read_csv('{sql_path(production_dataset['raw'])}', header=true, all_varchar=true)"
        differences = relation_differences(con, source, raw)
        assert differences == (0, 0), f"Reconciliação integral divergiu: {differences}"
    finally:
        con.close()
