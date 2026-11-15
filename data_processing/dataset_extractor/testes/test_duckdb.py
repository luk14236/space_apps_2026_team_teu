import duckdb

from conftest import relation_differences, sql_path
from firms_pipeline import build_duckdb


def test_database_tables_schemas_counts_and_csv_equality(sample_dataset):
    con = duckdb.connect(str(sample_dataset["database"]), read_only=True)
    try:
        table_names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert table_names == {"focos_brutos", "focos_mensais"}
        raw_types = con.execute("DESCRIBE focos_brutos").fetchall()
        assert [r[0] for r in raw_types] == ["pais", "data_hora_gmt", "latitude", "longitude", "satelite", "sensor", "frp", "confidence", "daynight", "type", "peso_harm"]
        assert [r[1] for r in raw_types] == ["VARCHAR", "TIMESTAMP", "DOUBLE", "DOUBLE", "VARCHAR", "VARCHAR", "DOUBLE", "VARCHAR", "VARCHAR", "INTEGER", "DOUBLE"]
        monthly_types = con.execute("DESCRIBE focos_mensais").fetchall()
        assert [r[0] for r in monthly_types] == ["ano", "mes", "pais", "satelite", "sensor", "nfocos", "nfocos_harm", "modelo_harm"]
        assert [r[1] for r in monthly_types] == ["INTEGER", "INTEGER", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT", "BIGINT", "VARCHAR"]
        raw_path = sql_path(sample_dataset["raw"])
        aggregate_path = sql_path(sample_dataset["aggregate"])
        raw_csv_query = f"SELECT pais, strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP, latitude::DOUBLE, longitude::DOUBLE, satelite, sensor, frp::DOUBLE, confidence, daynight, type::INTEGER FROM read_csv('{raw_path}', header=true, all_varchar=true)"
        raw_table_query = "SELECT pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp, confidence, daynight, type FROM focos_brutos"
        assert relation_differences(con, raw_csv_query, raw_table_query) == (0, 0)
        aggregate_csv_query = f"SELECT ano::INTEGER, mes::INTEGER, pais, satelite, sensor, nfocos::BIGINT, nfocos_harm::BIGINT, modelo_harm FROM read_csv('{aggregate_path}', header=true, all_varchar=true)"
        aggregate_table_query = "SELECT ano, mes, pais, satelite, sensor, nfocos, nfocos_harm, modelo_harm FROM focos_mensais"
        assert relation_differences(con, aggregate_csv_query, aggregate_table_query) == (0, 0)
        assert con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0] == sample_dataset["database_summary"]["raw_rows"]
        assert con.execute("SELECT coalesce(sum(nfocos),0) FROM focos_mensais").fetchone()[0] == con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        assert con.execute("SELECT count(*) FROM focos_brutos WHERE data_hora_gmt IS NULL").fetchone()[0] == 0
    finally:
        con.close()


def test_production_database_reconciles_with_both_csvs(production_dataset):
    con = duckdb.connect(str(production_dataset["database"]), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        assert {"focos_brutos", "focos_mensais"} <= tables
        assert tables <= {"focos_brutos", "focos_mensais", "modelos_equacoes"}
        for table, path in [("focos_brutos", production_dataset["raw"]), ("focos_mensais", production_dataset["aggregate"])]:
            escaped = sql_path(path)
            mismatch = con.execute(f"SELECT count(*) FROM (SELECT * FROM {table} EXCEPT ALL SELECT * FROM read_csv('{escaped}', header=true))").fetchone()[0]
            reverse_mismatch = con.execute(f"SELECT count(*) FROM (SELECT * FROM read_csv('{escaped}', header=true) EXCEPT ALL SELECT * FROM {table})").fetchone()[0]
            assert (mismatch, reverse_mismatch) == (0, 0), f"DuckDB e {path.name} divergem: {(mismatch, reverse_mismatch)}"
        raw_rows = con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        monthly_sum = con.execute("SELECT coalesce(sum(nfocos),0) FROM focos_mensais").fetchone()[0]
        assert raw_rows == monthly_sum
    finally:
        con.close()


def test_rebuild_without_monthly_reprocessing_preserves_harmonization_and_models(sample_dataset):
    con = duckdb.connect(str(sample_dataset["database"]))
    try:
        con.execute("UPDATE focos_mensais SET nfocos_harm=12, modelo_harm='AQUA->SNPP | quasi_poisson | potencial' WHERE satelite='AQUA'")
        con.execute("CREATE TABLE modelos_equacoes (pais VARCHAR, satelite_origem VARCHAR, satelite_destino VARCHAR)")
        con.execute("INSERT INTO modelos_equacoes VALUES ('Argentina', 'AQUA', 'SNPP')")
    finally:
        con.close()

    build_duckdb(sample_dataset["raw"], sample_dataset["aggregate"], sample_dataset["database"], reprocess_aggregate=False)

    con = duckdb.connect(str(sample_dataset["database"]), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        assert tables == {"focos_brutos", "focos_mensais", "modelos_equacoes"}
        assert con.execute("SELECT nfocos_harm, modelo_harm FROM focos_mensais WHERE satelite='AQUA'").fetchone() == (12, "AQUA->SNPP | quasi_poisson | potencial")
        assert con.execute("SELECT * FROM modelos_equacoes").fetchall() == [("Argentina", "AQUA", "SNPP")]
    finally:
        con.close()
