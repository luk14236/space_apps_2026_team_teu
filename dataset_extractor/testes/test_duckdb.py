import duckdb

from conftest import relation_differences, sql_path


def test_database_tables_schemas_counts_and_csv_equality(sample_dataset):
    con = duckdb.connect(str(sample_dataset["database"]), read_only=True)
    try:
        table_names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert table_names == {"focos_brutos", "focos_mensais"}
        raw_types = con.execute("DESCRIBE focos_brutos").fetchall()
        assert [r[0] for r in raw_types] == ["pais", "data_hora_gmt", "latitude", "longitude", "satelite", "sensor", "frp"]
        assert [r[1] for r in raw_types] == ["VARCHAR", "TIMESTAMP", "DOUBLE", "DOUBLE", "VARCHAR", "VARCHAR", "DOUBLE"]
        monthly_types = con.execute("DESCRIBE focos_mensais").fetchall()
        assert [r[0] for r in monthly_types] == ["ano", "mes", "pais", "satelite", "sensor", "nfocos"]
        assert [r[1] for r in monthly_types] == ["INTEGER", "INTEGER", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT"]
        raw_path = sql_path(sample_dataset["raw"])
        aggregate_path = sql_path(sample_dataset["aggregate"])
        raw_csv_query = f"SELECT pais, strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP, latitude::DOUBLE, longitude::DOUBLE, satelite, sensor, frp::DOUBLE FROM read_csv('{raw_path}', header=true, all_varchar=true)"
        raw_table_query = "SELECT pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp FROM focos_brutos"
        assert relation_differences(con, raw_csv_query, raw_table_query) == (0, 0)
        aggregate_csv_query = f"SELECT ano::INTEGER, mes::INTEGER, pais, satelite, sensor, nfocos::BIGINT FROM read_csv('{aggregate_path}', header=true, all_varchar=true)"
        aggregate_table_query = "SELECT ano, mes, pais, satelite, sensor, nfocos FROM focos_mensais"
        assert relation_differences(con, aggregate_csv_query, aggregate_table_query) == (0, 0)
        assert con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0] == sample_dataset["database_summary"]["raw_rows"]
        assert con.execute("SELECT coalesce(sum(nfocos),0) FROM focos_mensais").fetchone()[0] == con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        assert con.execute("SELECT count(*) FROM focos_brutos WHERE data_hora_gmt IS NULL").fetchone()[0] == 0
    finally:
        con.close()


def test_production_database_reconciles_with_both_csvs(production_dataset):
    con = duckdb.connect(str(production_dataset["database"]), read_only=True)
    try:
        assert {row[0] for row in con.execute("SHOW TABLES").fetchall()} == {"focos_brutos", "focos_mensais"}
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
