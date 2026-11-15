"""Turn the raw deliveries (data/raw) into the files the app reads (data/processed).

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Input  (raw dir):
    focos_brutos_*.csv   one row per hotspot: pais, data_hora_gmt, latitude, longitude, satelite, sensor, frp
                         [+ optional confidence, daynight, type, peso_harm]. Several files are merged and
                         de-duplicated (e.g. the data team's history + scripts/fetch_firms.py for recent days).
    focos_mensais_*.csv  optional, only used to cross-check totals.

Output (out dir):
    focos_arg.parquet, focos_outros.parquet   hotspots: countries with provinces/departments in data/geo (Argentina,
                                              Brazil, the Netherlands) with their ids / all other countries
    agg_pais / agg_prov / agg_dep.parquet     monthly counts x satellite
    dia_pais / dia_dep.parquet                daily counts x satellite (situation room)
    cell_025 / cell_ar.parquet                pre-aggregated grids (0.25° and 0.05°, every country)
    meta.json                                 period, columns found and data-quality warnings
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Callable

import duckdb
import numpy as np
import shapely
from shapely.geometry import shape

ISO = {"Argentina": "ARG", "Bolívia": "BOL", "Brasil": "BRA", "Chile": "CHL", "Colômbia": "COL",
       "Equador": "ECU", "Guiana": "GUY", "Guiana Francesa": "GUF", "Paraguai": "PRY", "Peru": "PER",
       "Suriname": "SUR", "Uruguai": "URY", "Venezuela": "VEN", "Países Baixos": "NLD"}
REQUIRED = ["pais", "data_hora_gmt", "latitude", "longitude", "satelite", "sensor", "frp"]
OPTIONAL = ["confidence", "daynight", "type", "peso_harm"]
EXPECTED_SATS = ["TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21"]


# Rows without peso_harm (deliveries that came later, e.g. FIRMS days of 2026 or other countries) get the team's rule
# from 2012 on: S-NPP = 1, NOAA-20 = 1 only after S-NPP delivery ended (2026-11-01), every other satellite = 0.
# Before 2012 there is no fitted model for them, so they stay NULL (left out of the harmonized series).
HARM_FILL = ("CASE WHEN upper(satelite) = 'SNPP' THEN 1.0 "
             "WHEN upper(satelite) = 'NOAA20' AND CAST(data_hora_gmt AS TIMESTAMP) >= TIMESTAMP '2026-11-01' THEN 1.0 "
             "WHEN CAST(data_hora_gmt AS TIMESTAMP) >= TIMESTAMP '2012-01-01' THEN 0.0 END")


class PrepareError(Exception):
    pass


def adm_countries(geo_dir: Path) -> list[str]:
    """ISO3 of the countries that have provinces/departments in data/geo."""
    feats = json.loads((geo_dir / "provincias.geojson").read_text(encoding="utf-8"))["features"]
    return sorted({f["properties"]["pais"] for f in feats})


_TREE: dict = {}


def _init_tree(geo_dir: str, iso3: str) -> None:
    provs = {f["id"]: f["properties"]["pais"] for f in json.loads((Path(geo_dir) / "provincias.geojson").read_text(encoding="utf-8"))["features"]}
    feats = [f for f in json.loads((Path(geo_dir) / "departamentos.geojson").read_text(encoding="utf-8"))["features"]
             if provs.get(f["properties"]["provincia"]) == iso3]
    _TREE.update(tree=shapely.STRtree([shape(f["geometry"]) for f in feats]),
                 dep=np.array([f["id"] for f in feats], dtype=object), prov=np.array([f["properties"]["provincia"] for f in feats], dtype=object))


def _assign_chunk(args) -> np.ndarray:
    lon, lat = args
    tree = _TREE["tree"]
    pts = shapely.points(lon, lat)
    out = np.full(len(lon), -1, dtype=np.int32)
    pi, gi = tree.query(pts, predicate="within")
    out[pi] = gi
    miss = np.where(out < 0)[0]
    if len(miss):  # coast and border pixels: nearest department of the same country
        ni, ng = tree.query_nearest(pts[miss], all_matches=False)
        out[miss[ni]] = ng
    return out


def assign_departments(lon: np.ndarray, lat: np.ndarray, geo_dir: Path, iso3: str = "ARG") -> tuple[np.ndarray, np.ndarray]:
    """(dep_id, prov_id) for each point of one country, in parallel chunks."""
    import multiprocessing as mp
    step = 500_000
    chunks = [(lon[s:s + step], lat[s:s + step]) for s in range(0, len(lon), step)]
    if len(chunks) > 1:
        with mp.get_context("fork").Pool(min(len(chunks), max(1, (os.cpu_count() or 2) - 1)), _init_tree, (str(geo_dir), iso3)) as pool:
            parts = pool.map(_assign_chunk, chunks)
    else:
        _init_tree(str(geo_dir), iso3)
        parts = [_assign_chunk(c) for c in chunks]
    idx = np.concatenate(parts) if parts else np.array([], dtype=np.int32)
    _init_tree(str(geo_dir), iso3)
    return _TREE["dep"][idx], _TREE["prov"][idx]


def run(raw: Path | None, out: Path, geo_dir: Path, log: Callable[[str], None] = print,
        files: tuple[list[Path], list[Path]] | None = None, entregas: list[dict] | None = None) -> dict:
    """raw: folder with focos_*.csv, or pass `files` = (brutos, mensais) explicitly (admin deliveries)."""
    out = Path(out)
    if files is not None:
        brutos, mensais = list(files[0]), list(files[1])
    else:
        raw = Path(raw)
        brutos = sorted(raw.glob("focos_brutos*.csv"))
        mensais = sorted(raw.glob("focos_mensais*.csv"))
    if not brutos:
        raise PrepareError("Nenhum arquivo focos_brutos*.csv para processar.")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    say = lambda m: log(f"[{time.time() - t0:6.1f}s] {m}")  # noqa: E731
    P = lambda n: (out / n).as_posix()  # noqa: E731

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    files = ", ".join(f"'{b.as_posix()}'" for b in brutos)
    src = f"read_csv([{files}], header=true, union_by_name=true)"
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise PrepareError(f"Colunas obrigatórias ausentes: {missing}")
    extra = [c for c in OPTIONAL if c in cols]
    say(f"lendo {', '.join(b.name for b in brutos)} (colunas extras: {extra or 'nenhuma'})")
    if len(brutos) > 1:  # overlapping deliveries: keep one row per hotspot
        con.execute(f"CREATE TEMP VIEW src AS SELECT DISTINCT ON (data_hora_gmt, latitude, longitude, upper(satelite)) * FROM {src}")
        src = "src"

    iso_case = "CASE pais " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in ISO.items()) + " ELSE NULL END"
    sel = f"""{iso_case} AS iso3, CAST(data_hora_gmt AS TIMESTAMP) AS ts,
        CAST(year(data_hora_gmt) AS SMALLINT) AS ano, CAST(month(data_hora_gmt) AS TINYINT) AS mes,
        CAST(latitude AS FLOAT) AS lat, CAST(longitude AS FLOAT) AS lon, upper(satelite) AS satelite,
        upper(sensor) AS sensor, CAST(frp AS FLOAT) AS frp""" + "".join(
        f", CAST({c} AS VARCHAR) AS {c}" if c in ("confidence", "daynight") else
        f", CAST(COALESCE(peso_harm, {HARM_FILL}) AS DOUBLE) AS peso_harm" if c == "peso_harm" else f", {c}" for c in extra)

    warnings: list[str] = []
    unknown = con.execute(f"SELECT DISTINCT pais FROM {src} WHERE ({iso_case}) IS NULL").fetchall()
    if unknown:
        warnings.append(f"Países sem código ISO (ignorados): {[u[0] for u in unknown]}")

    adm = adm_countries(geo_dir)
    adm_sql = ", ".join(f"'{a}'" for a in adm)
    # spatial order inside each country lets DuckDB skip row groups when the map asks for one area
    con.execute(f"COPY (SELECT {sel} FROM {src} WHERE ({iso_case}) IS NOT NULL AND ({iso_case}) NOT IN ({adm_sql}) "
                f"ORDER BY iso3, floor(lat), floor(lon), ts) "
                f"TO '{P('focos_outros.parquet')}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)")
    say("focos_outros.parquet gravado")

    tmp = out / "_adm_tmp"
    tmp.mkdir(exist_ok=True)
    for iso in adm:
        df = con.execute(f"SELECT {sel} FROM {src} WHERE ({iso_case}) = '{iso}'").df()
        say(f"{iso}: {len(df):,} focos; atribuindo províncias e departamentos")
        if df.empty:
            continue
        df["dep_id"], df["prov_id"] = assign_departments(df["lon"].to_numpy("float64"), df["lat"].to_numpy("float64"), geo_dir, iso)
        con.register("adm_df", df)
        con.execute(f"COPY (SELECT * FROM adm_df) TO '{(tmp / (iso + '.parquet')).as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        con.unregister("adm_df")
        del df
    con.execute(f"COPY (SELECT * FROM read_parquet('{tmp.as_posix()}/*.parquet', union_by_name=true) ORDER BY iso3, prov_id, dep_id, ts) "
                f"TO '{P('focos_arg.parquet')}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)")
    shutil.rmtree(tmp, ignore_errors=True)
    say("focos_arg.parquet gravado (países com províncias: " + ", ".join(adm) + ")")

    arg = f"read_parquet('{P('focos_arg.parquet')}')"
    allf = f"read_parquet(['{P('focos_arg.parquet')}', '{P('focos_outros.parquet')}'], union_by_name=true)"
    harm = ", SUM(peso_harm) AS n_harm" if "peso_harm" in extra else ""
    jobs = [("agg_pais", "iso3, ano, mes", allf), ("agg_prov", "iso3, prov_id, ano, mes", arg), ("agg_dep", "iso3, dep_id, prov_id, ano, mes", arg),
            ("dia_pais", "iso3, CAST(ts AS DATE) AS dia", allf), ("dia_dep", "iso3, dep_id, prov_id, CAST(ts AS DATE) AS dia", arg),
            ("cell_025", "iso3, CAST(floor(lon/0.25) AS INTEGER) gx, CAST(floor(lat/0.25) AS INTEGER) gy, ano, mes", allf),
            ("cell_ar", "iso3, prov_id, dep_id, CAST(floor(lon/0.05) AS INTEGER) gx, CAST(floor(lat/0.05) AS INTEGER) gy, ano, mes", allf)]
    for name, keys, source in jobs:
        con.execute(f"COPY (SELECT {keys}, satelite, sensor, COUNT(*) AS n, MAX(frp) AS frp_max{harm} "
                    f"FROM {source} GROUP BY ALL ORDER BY ALL) TO '{P(name + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
        say(f"{name}.parquet gravado")

    total, tmin, tmax, neg_frp, dups = con.execute(f"""SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(*) FILTER (WHERE frp < 0),
        COUNT(*) - COUNT(DISTINCT (ts, lat, lon, satelite)) FROM {allf}""").fetchone()
    if neg_frp:
        warnings.append(f"{neg_frp:,} focos com FRP negativo")
    if dups:
        warnings.append(f"{dups:,} linhas duplicadas (mesma hora, posição e satélite)")
    sats = [r[0] for r in con.execute(f"SELECT DISTINCT satelite FROM {allf} ORDER BY 1").fetchall()]
    warnings += [f"Satélite {s} ausente nos dados" for s in EXPECTED_SATS if s not in sats]
    warnings += [f"Coluna '{c}' ausente" + (" (série harmonizada indisponível)" if c == "peso_harm" else "") for c in OPTIONAL if c not in extra]
    if mensais:
        diff = con.execute(f"""WITH m AS (SELECT {iso_case} iso3, ano, mes, upper(satelite) satelite, SUM(nfocos) n
              FROM read_csv([{', '.join("'" + m.as_posix() + "'" for m in mensais)}], header=true, union_by_name=true) GROUP BY ALL),
            a AS (SELECT iso3, ano, mes, satelite, SUM(n) n FROM read_parquet('{P('agg_pais.parquet')}') GROUP BY ALL)
            SELECT COUNT(*) FROM m LEFT JOIN a USING (iso3, ano, mes, satelite) WHERE m.n IS DISTINCT FROM a.n""").fetchone()[0]
        if diff:
            warnings.append(f"{diff} combinações país/mês/satélite em que focos_mensais não bate com focos_brutos")

    meta = {"gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"), "fonte": [b.name for b in brutos], "total_focos": total,
            "entregas": [{"id": e["id"], "nome": e["nome"]} for e in (entregas or [])],
            "inicio": str(tmin), "fim": str(tmax), "satelites": sats, "colunas_extras": extra,
            "tem_harmonizacao": "peso_harm" in extra, "avisos": warnings}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    say("meta.json gravado")
    return meta
