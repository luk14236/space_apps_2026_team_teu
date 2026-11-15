"""Shared FIRMS CSV transformation helpers used by the treatment notebook."""

from __future__ import annotations

import csv
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

SOURCE_COUNTRIES = {
    "Argentina": "Argentina",
    "Bolivia": "Bolívia",
    "Brazil": "Brasil",
    "Chile": "Chile",
    "Colombia": "Colômbia",
    "Ecuador": "Equador",
    "Guyana": "Guiana",
    "Paraguay": "Paraguai",
    "Peru": "Peru",
    "Suriname": "Suriname",
    "Uruguay": "Uruguai",
    "Venezuela": "Venezuela",
    "French_Guiana": "Guiana Francesa",
}
SATELLITES = {"N20": "NOAA20", "N": "SNPP", "Aqua": "AQUA", "Terra": "TERRA"}
SENSORS = {"MODIS", "VIIRS"}
RAW_COLUMNS = ["pais", "data_hora_gmt", "latitude", "longitude", "satelite", "sensor", "frp", "confidence", "daynight", "type", "peso_harm"]
AGGREGATE_COLUMNS = ["ano", "mes", "pais", "satelite", "sensor", "nfocos", "nfocos_harm", "modelo_harm"]
SOURCE_COLUMNS = {"acq_date", "acq_time", "latitude", "longitude", "satellite", "instrument", "frp", "confidence", "daynight", "type"}
OBSERVATION_COLUMNS = RAW_COLUMNS[:-1]


def _sql_path(path: Path) -> str:
    return str(Path(path).resolve()).replace("'", "''")


def _relation_differences(con, left_query: str, right_query: str) -> tuple[int, int]:
    left_only = con.execute(f"SELECT count(*) FROM (({left_query}) EXCEPT ALL ({right_query}))").fetchone()[0]
    right_only = con.execute(f"SELECT count(*) FROM (({right_query}) EXCEPT ALL ({left_query}))").fetchone()[0]
    return left_only, right_only


def _csv_observations_query(path: Path) -> str:
    columns = ", ".join(OBSERVATION_COLUMNS)
    return f"SELECT {columns} FROM read_csv('{_sql_path(path)}', header=true, all_varchar=true)"


def _csv_monthly_query(path: Path) -> str:
    return (
        "SELECT ano::INTEGER AS ano, mes::INTEGER AS mes, pais, satelite, sensor, "
        f"nfocos::BIGINT AS nfocos FROM read_csv('{_sql_path(path)}', header=true, all_varchar=true) "
        "WHERE nfocos IS NOT NULL"
    )


def _raw_monthly_query(relation: str) -> str:
    return (
        "SELECT year(data_hora_gmt)::INTEGER AS ano, month(data_hora_gmt)::INTEGER AS mes, "
        "pais, satelite, sensor, count(*)::BIGINT AS nfocos "
        f"FROM {relation} GROUP BY ALL"
    )


def resolve_dataset_dir() -> Path:
    """Resolve this package's directory independently of the current directory."""
    return Path(__file__).resolve().parent


def source_country_from_filename(filename: str) -> str:
    """Extract the FIRMS country token from source CSV naming convention."""
    stem = Path(filename).stem
    parts = stem.split("_", 2)
    if len(parts) != 3:
        raise ValueError(f"Nome de CSV FIRMS inesperado: {filename}")
    return parts[2]


def normalize_row(row: dict[str, str], country_token: str, context: str = "origem") -> dict:
    country = SOURCE_COUNTRIES.get(country_token)
    if country is None:
        raise ValueError(f"País FIRMS inesperado {country_token!r} em {context}")
    satellite = SATELLITES.get((row.get("satellite") or "").strip())
    if satellite is None:
        raise ValueError(f"Satélite inesperado {row.get('satellite')!r} em {context}")
    sensor = (row.get("instrument") or "").strip()
    if sensor not in SENSORS:
        raise ValueError(f"Sensor inesperado {sensor!r} em {context}")
    date_text = (row.get("acq_date") or "").strip()
    time_text = (row.get("acq_time") or "").strip()
    if not time_text.isdigit() or len(time_text) > 4:
        raise ValueError(f"Horário acq_time inválido {time_text!r} em {context}")
    time_text = time_text.zfill(4)
    try:
        acquired = datetime.strptime(date_text + time_text, "%Y-%m-%d%H%M")
    except ValueError as exc:
        raise ValueError(f"Data/hora inválida ({date_text} {time_text}) em {context}") from exc
    try:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        frp = float(row["frp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Valor numérico inválido em {context}: {exc}") from exc
    return {
        "pais": country,
        "data_hora_gmt": acquired.strftime("%Y-%m-%d %H:%M:%S"),
        "latitude": latitude,
        "longitude": longitude,
        "satelite": satellite,
        "sensor": sensor,
        "frp": frp,
        "confidence": row.get("confidence"),
        "daynight": row.get("daynight"),
        "type": int(row["type"]),
        "peso_harm": None,
    }


def transform_sources(source_files: list[Path], raw_csv: Path, aggregate_csv: Path, reprocess_aggregate: bool = True) -> dict:
    """Stream source files into raw CSV and derive monthly counts using DuckDB."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Instale duckdb para executar o tratamento: %pip install duckdb") from exc

    raw_csv.parent.mkdir(parents=True, exist_ok=True)
    aggregate_csv.parent.mkdir(parents=True, exist_ok=True)
    raw_fd, raw_temp_name = tempfile.mkstemp(prefix=raw_csv.name, suffix=".part", dir=raw_csv.parent)
    os.close(raw_fd)
    aggregate_fd, aggregate_temp_name = tempfile.mkstemp(prefix=aggregate_csv.name, suffix=".part", dir=aggregate_csv.parent)
    os.close(aggregate_fd)
    raw_temp, aggregate_temp = Path(raw_temp_name), Path(aggregate_temp_name)
    preserved_temp = None
    rows_written = 0
    group_counts: Counter = Counter()
    try:
        with raw_temp.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=RAW_COLUMNS)
            writer.writeheader()
            for source_path in sorted(map(Path, source_files)):
                country_token = source_country_from_filename(source_path.name)
                with source_path.open("r", newline="", encoding="utf-8-sig") as source:
                    reader = csv.DictReader(source)
                    missing = SOURCE_COLUMNS - set(reader.fieldnames or [])
                    if missing:
                        raise ValueError(f"Colunas ausentes em {source_path}: {sorted(missing)}")
                    for line_number, row in enumerate(reader, start=2):
                        context = f"{source_path}, linha {line_number}"
                        normalized = normalize_row(row, country_token, context)
                        writer.writerow(normalized)
                        dt = datetime.strptime(normalized["data_hora_gmt"], "%Y-%m-%d %H:%M:%S")
                        key = (dt.year, dt.month, normalized["pais"], normalized["satelite"], normalized["sensor"])
                        group_counts[key] += 1
                        rows_written += 1
        if reprocess_aggregate:
            with aggregate_temp.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.writer(destination)
                writer.writerow(AGGREGATE_COLUMNS)
                for (year, month, country, satellite, sensor), count in sorted(group_counts.items()):
                    # Predictions are populated later by the regression pipeline.
                    writer.writerow([year, month, country, satellite, sensor, count, "", ""])

        # Independently verify the aggregate using DuckDB's CSV reader.
        con = duckdb.connect()
        try:
            raw_sql_path = _sql_path(raw_temp)
            aggregate_sql_path = _sql_path(aggregate_temp)
            raw_count = con.execute(f"SELECT count(*) FROM read_csv_auto('{raw_sql_path}')").fetchone()[0]
            if reprocess_aggregate:
                aggregate_sum = con.execute(f"SELECT coalesce(sum(nfocos), 0) FROM read_csv_auto('{aggregate_sql_path}')").fetchone()[0]
                monthly_differences = _relation_differences(
                    con, _raw_monthly_query(f"read_csv('{raw_sql_path}', header=true)"), _csv_monthly_query(aggregate_temp)
                )
            else:
                if not aggregate_csv.is_file():
                    raise FileNotFoundError(f"CSV agregado existente necessário para preservação: {aggregate_csv}")
                if not raw_csv.is_file():
                    raise FileNotFoundError(f"CSV bruto existente necessário para preservar peso_harm: {raw_csv}")
                aggregate_sum = con.execute(f"SELECT coalesce(sum(nfocos), 0) FROM ({_csv_monthly_query(aggregate_csv)})").fetchone()[0]
                monthly_differences = _relation_differences(
                    con, _raw_monthly_query(f"read_csv('{raw_sql_path}', header=true)"), _csv_monthly_query(aggregate_csv)
                )
            if raw_count != rows_written or aggregate_sum != rows_written or monthly_differences != (0, 0):
                raise RuntimeError(
                    "Validação da agregação falhou: "
                    f"bruto={raw_count}, soma nfocos={aggregate_sum}, origem={rows_written}, "
                    f"grupos divergentes={monthly_differences}"
                )

            preserved_weights = 0
            if not reprocess_aggregate:
                observation_differences = _relation_differences(con, _csv_observations_query(raw_temp), _csv_observations_query(raw_csv))
                if observation_differences != (0, 0):
                    raise RuntimeError(
                        "Não é seguro preservar peso_harm: as observações brutas existentes "
                        f"não reconciliam exatamente ({observation_differences})"
                    )
                old_path = _sql_path(raw_csv)
                partition = ", ".join(OBSERVATION_COLUMNS)
                join = " AND ".join(f'new."{column}" IS NOT DISTINCT FROM old."{column}"' for column in OBSERVATION_COLUMNS)
                selected = ", ".join(f'new."{column}"' for column in OBSERVATION_COLUMNS)
                preserved_fd, preserved_name = tempfile.mkstemp(prefix=raw_csv.name, suffix=".weighted.part", dir=raw_csv.parent)
                os.close(preserved_fd)
                preserved_temp = Path(preserved_name)
                preserved_temp.unlink()
                con.execute(f"""COPY (
                    WITH new_rows AS (
                        SELECT *, row_number() OVER (PARTITION BY {partition}) AS occurrence
                        FROM read_csv('{raw_sql_path}', header=true, all_varchar=true)
                    ), old_rows AS (
                        SELECT *, row_number() OVER (PARTITION BY {partition}) AS occurrence
                        FROM read_csv('{old_path}', header=true, all_varchar=true)
                    )
                    SELECT {selected}, old.peso_harm
                    FROM new_rows AS new JOIN old_rows AS old ON {join} AND new.occurrence = old.occurrence
                ) TO '{_sql_path(preserved_temp)}' (HEADER, DELIMITER ',')""")
                preserved_weights = con.execute(
                    f"SELECT count(*) FROM read_csv('{_sql_path(preserved_temp)}', header=true, all_varchar=true) WHERE peso_harm IS NOT NULL"
                ).fetchone()[0]
                os.replace(preserved_temp, raw_temp)
        finally:
            con.close()
        os.replace(raw_temp, raw_csv)
        if reprocess_aggregate:
            os.replace(aggregate_temp, aggregate_csv)
        else:
            aggregate_temp.unlink(missing_ok=True)
        return {"raw_rows": rows_written, "aggregate_groups": len(group_counts), "nfocos_sum": rows_written, "preserved_weights": preserved_weights}
    except Exception:
        raw_temp.unlink(missing_ok=True)
        aggregate_temp.unlink(missing_ok=True)
        if preserved_temp is not None:
            preserved_temp.unlink(missing_ok=True)
        raise


def build_duckdb(raw_csv: Path, aggregate_csv: Path, database_path: Path, reprocess_aggregate: bool = True) -> dict:
    """Build a temporary DuckDB database, validate it, then atomically publish."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Instale duckdb: %pip install duckdb") from exc
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(prefix=database_path.stem + ".part-", suffix=".duckdb", dir=database_path.parent)
    os.close(temp_fd)
    temp_database = Path(temp_name)
    temp_database.unlink()
    if not reprocess_aggregate and not database_path.is_file():
        raise FileNotFoundError(f"Banco DuckDB existente necessário para preservar focos_mensais: {database_path}")
    raw_path = _sql_path(raw_csv)
    aggregate_path = _sql_path(aggregate_csv)
    con = duckdb.connect(str(temp_database))
    try:
        existing_tables = set()
        if database_path.is_file():
            existing_database = _sql_path(database_path)
            con.execute(f"ATTACH '{existing_database}' AS existing_db (READ_ONLY)")
            existing_tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'existing_db'").fetchall()}
            if not reprocess_aggregate:
                required_tables = {"focos_brutos", "focos_mensais"}
                if not required_tables <= existing_tables:
                    raise RuntimeError(f"Banco existente não contém as tabelas necessárias: {sorted(required_tables - existing_tables)}")
            if "modelos_equacoes" in existing_tables:
                con.execute("CREATE TABLE modelos_equacoes AS SELECT * FROM existing_db.modelos_equacoes")
        con.execute(f"""CREATE TABLE incoming_focos_brutos AS
            SELECT pais::VARCHAR AS pais,
                   strptime(data_hora_gmt, '%Y-%m-%d %H:%M:%S')::TIMESTAMP AS data_hora_gmt,
                   latitude::DOUBLE AS latitude, longitude::DOUBLE AS longitude,
                   satelite::VARCHAR AS satelite, sensor::VARCHAR AS sensor, frp::DOUBLE AS frp,
                   confidence::VARCHAR AS confidence, daynight::VARCHAR AS daynight, type::INTEGER AS type,
                   peso_harm::DOUBLE AS peso_harm
            FROM read_csv('{raw_path}', header=true, all_varchar=true)""")
        preserved_weights = 0
        if reprocess_aggregate:
            con.execute("ALTER TABLE incoming_focos_brutos RENAME TO focos_brutos")
        else:
            con.execute(f"""CREATE TABLE incoming_focos_mensais AS
                SELECT ano::INTEGER AS ano, mes::INTEGER AS mes, pais::VARCHAR AS pais,
                       satelite::VARCHAR AS satelite, sensor::VARCHAR AS sensor, nfocos::BIGINT AS nfocos,
                       nfocos_harm::BIGINT AS nfocos_harm, modelo_harm::VARCHAR AS modelo_harm
                FROM read_csv('{aggregate_path}', header=true, all_varchar=true)""")
            observation_columns = ", ".join(OBSERVATION_COLUMNS)
            observation_differences = _relation_differences(
                con,
                f"SELECT {observation_columns} FROM incoming_focos_brutos",
                f"SELECT {observation_columns} FROM existing_db.focos_brutos",
            )
            monthly_differences = _relation_differences(
                con,
                _raw_monthly_query("incoming_focos_brutos"),
                "SELECT ano, mes, pais, satelite, sensor, nfocos FROM incoming_focos_mensais WHERE nfocos IS NOT NULL",
            )
            if observation_differences != (0, 0):
                raise RuntimeError(
                    "Não é seguro preservar peso_harm: as observações brutas não reconciliam "
                    f"exatamente ({observation_differences})"
                )
            if monthly_differences != (0, 0):
                raise RuntimeError(
                    "Não é seguro preservar a harmonização: os grupos mensais divergem "
                    f"({monthly_differences})"
                )
            raw_differences = _relation_differences(
                con, "SELECT * FROM incoming_focos_brutos", "SELECT * FROM existing_db.focos_brutos"
            )
            monthly_artifact_differences = _relation_differences(
                con, "SELECT * FROM incoming_focos_mensais", "SELECT * FROM existing_db.focos_mensais"
            )
            if raw_differences != (0, 0) or monthly_artifact_differences != (0, 0):
                raise RuntimeError(
                    "CSV e DuckDB existentes divergem; preservação cancelada: "
                    f"bruto={raw_differences}, mensal={monthly_artifact_differences}"
                )
            con.execute("ALTER TABLE incoming_focos_brutos RENAME TO focos_brutos")
            con.execute("ALTER TABLE incoming_focos_mensais RENAME TO focos_mensais")
            preserved_weights = con.execute("SELECT count(*) FROM focos_brutos WHERE peso_harm IS NOT NULL").fetchone()[0]
        if reprocess_aggregate:
            con.execute("DROP TABLE IF EXISTS focos_mensais")
            con.execute(f"""CREATE TABLE focos_mensais AS
            SELECT ano::INTEGER AS ano, mes::INTEGER AS mes, pais::VARCHAR AS pais,
                   satelite::VARCHAR AS satelite, sensor::VARCHAR AS sensor, nfocos::BIGINT AS nfocos,
                   nfocos_harm::BIGINT AS nfocos_harm, modelo_harm::VARCHAR AS modelo_harm
            FROM read_csv('{aggregate_path}', header=true, all_varchar=true)""")
        raw_count = con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        monthly_count, monthly_sum = con.execute("SELECT count(*), coalesce(sum(nfocos), 0) FROM focos_mensais").fetchone()
        null_dates = con.execute("SELECT count(*) FROM focos_brutos WHERE data_hora_gmt IS NULL").fetchone()[0]
        monthly_differences = _relation_differences(
            con, _raw_monthly_query("focos_brutos"),
            "SELECT ano, mes, pais, satelite, sensor, nfocos FROM focos_mensais WHERE nfocos IS NOT NULL",
        )
        if null_dates or raw_count != monthly_sum or monthly_differences != (0, 0):
            raise RuntimeError(f"DuckDB inconsistente: bruto={raw_count}, soma nfocos={monthly_sum}, datas nulas={null_dates}")
        con.execute("CHECKPOINT")
    except Exception:
        con.close()
        temp_database.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(temp_database, database_path)
    return {"raw_rows": raw_count, "monthly_groups": monthly_count, "nfocos_sum": monthly_sum, "preserved_weights": preserved_weights}
