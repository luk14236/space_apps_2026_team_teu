import duckdb

from conftest import relation_differences, source_projection_sql, sql_path
from firms_pipeline import AGGREGATE_COLUMNS


def test_aggregate_matches_independent_source_grouping(sample_dataset):
    con = duckdb.connect()
    try:
        source = source_projection_sql(sample_dataset["source_files"])
        expected = f"SELECT year(data_hora_gmt)::INTEGER AS ano, month(data_hora_gmt)::INTEGER AS mes, pais, satelite, sensor, count(*)::BIGINT AS nfocos FROM ({source}) GROUP BY ALL"
        actual = f"SELECT ano::INTEGER, mes::INTEGER, pais, satelite, sensor, nfocos::BIGINT FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true, all_varchar=true)"
        differences = relation_differences(con, expected, actual)
        assert differences == (0, 0), f"Grupos divergentes esperado->CSV/CSV->esperado: {differences}"
        columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true)").fetchall()]
        assert columns == AGGREGATE_COLUMNS
        null_predictions = con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true, all_varchar=true) WHERE nfocos_harm IS NOT NULL OR modelo_harm IS NOT NULL").fetchone()[0]
        assert null_predictions == 0
        raw_count = con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['raw'])}', header=true)").fetchone()[0]
        aggregate_count, nfocos_sum = con.execute(f"SELECT count(*), sum(nfocos::BIGINT) FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true, all_varchar=true)").fetchone()
        assert raw_count == nfocos_sum == sample_dataset["transformed"]["raw_rows"]
        duplicate_groups = con.execute(f"SELECT count(*) FROM (SELECT ano,mes,pais,satelite,sensor FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true) GROUP BY ALL HAVING count(*) > 1)").fetchone()[0]
        invalid_months = con.execute(f"SELECT count(*) FROM read_csv('{sql_path(sample_dataset['aggregate'])}', header=true) WHERE mes < 1 OR mes > 12").fetchone()[0]
        assert aggregate_count == sample_dataset["transformed"]["aggregate_groups"]
        assert duplicate_groups == invalid_months == 0
    finally:
        con.close()


def test_monthly_csv_is_sorted(sample_dataset):
    con = duckdb.connect()
    try:
        path = sql_path(sample_dataset["aggregate"])
        unsorted = con.execute(f"""WITH rows AS (
            SELECT *, row_number() OVER () AS pos FROM read_csv('{path}', header=true, all_varchar=true)
        ), ordered AS (
            SELECT *, row_number() OVER (ORDER BY ano::INTEGER, mes::INTEGER, pais, satelite, sensor) AS expected_pos FROM rows
        ) SELECT count(*) FROM ordered WHERE pos != expected_pos""").fetchone()[0]
        assert unsorted == 0
    finally:
        con.close()


def test_production_aggregate_reconciles_to_source(production_dataset):
    con = duckdb.connect()
    try:
        source = source_projection_sql(production_dataset["source_files"])
        expected = f"SELECT year(data_hora_gmt)::INTEGER AS ano, month(data_hora_gmt)::INTEGER AS mes, pais, satelite, sensor, count(*)::BIGINT AS nfocos FROM ({source}) GROUP BY ALL"
        actual = f"SELECT ano::INTEGER, mes::INTEGER, pais, satelite, sensor, nfocos::BIGINT FROM read_csv('{sql_path(production_dataset['aggregate'])}', header=true, all_varchar=true)"
        differences = relation_differences(con, expected, actual)
        assert differences == (0, 0), f"Reconciliação integral agregada divergiu: {differences}"
    finally:
        con.close()
