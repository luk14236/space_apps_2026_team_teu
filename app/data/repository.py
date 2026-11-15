"""Data access layer: every query the UI needs, on top of the Parquet files from scripts/prepare_data.py.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

The UI never writes SQL. It builds a `Filtro` and calls the methods below, so the data source
can change (new delivery, harmonized weights, NRT feed) without touching the screens.

Time is indexed by month: mi = ano * 12 + (mes - 1).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shapely

from .geo import Geo

SERIES = ("harm", "modis", "raw")
SATS = ("TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21")  # one monthly column each


@dataclass(frozen=True)
class Filtro:
    """What the user selected. Hashable so results can be cached."""
    kind: str = "pais"            # all | pais | prov | dep | shape
    uid: str = "ARG"              # country ISO3, province id or department id
    shape: tuple = ()             # ((lon, lat), ...) polygon in lon/lat; rectangle = 4 corners
    t0: int = 0                   # first month index (inclusive)
    t1: int = 10**6               # last month index (inclusive)
    cal: tuple = ()               # ("cell", ano, mes) | ("month", mes) | ("year", ano)
    sats: tuple = ("AQUA", "NOAA20", "NOAA21", "SNPP", "TERRA")
    serie: str = "raw"

    def without_time(self) -> "Filtro":
        return Filtro(self.kind, self.uid, self.shape, 0, 10**6, (), self.sats, self.serie)


def mi_of(ano, mes):
    return ano * 12 + (mes - 1)


class Repository:
    def __init__(self, processed_dir: Path, geo: Geo):
        self.dir = Path(processed_dir)
        self.geo = geo
        self.ready = False
        self._lock = threading.Lock()
        self._con = None
        if (self.dir / "meta.json").exists():
            self._load()

    def reload(self) -> None:
        """Re-read data/processed after /admin rebuilt it (no restart needed)."""
        with self._lock:
            for fn in (Repository.monthly, Repository.territories, Repository.grid, Repository.points, Repository.count_points,
                       Repository._grid_view, Repository.points_view):
                fn.cache_clear()
            if self._con is not None:
                self._con.close()
            self._con = None
            self.ready = False
        self._load()

    def _load(self) -> None:
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.has_harm = bool(self.meta.get("tem_harmonizacao"))
        self._con = duckdb.connect()
        p = lambda n: (self.dir / n).as_posix()  # noqa: E731
        # Until the data team delivers `peso_harm`, expose the columns as NULL so queries stay the same.
        no_n = "" if self.has_harm else ", NULL::DOUBLE AS n_harm"
        no_w = "" if self.has_harm else ", NULL::DOUBLE AS peso_harm"
        self.has_cells = (self.dir / "cell_025.parquet").exists() and (self.dir / "cell_ar.parquet").exists()
        for name in ("agg_pais", "agg_prov", "agg_dep") + (("cell_025", "cell_ar") if self.has_cells else ()):
            self._con.execute(f"CREATE VIEW {name} AS SELECT *, ano*12+mes-1 AS mi{no_n} FROM read_parquet('{p(name + '.parquet')}')")
        self._con.execute(f"CREATE VIEW focos_arg AS SELECT *, ano*12+mes-1 AS mi{no_w} FROM read_parquet('{p('focos_arg.parquet')}')")
        self._con.execute(f"""CREATE VIEW focos AS SELECT *, ano*12+mes-1 AS mi{no_w}
            FROM read_parquet(['{p('focos_arg.parquet')}', '{p('focos_outros.parquet')}'], union_by_name=true)""")
        self.has_daily = (self.dir / "dia_dep.parquet").exists()
        if self.has_daily:
            for name in ("dia_dep", "dia_pais"):
                self._con.execute(f"CREATE VIEW {name} AS SELECT *{no_n} FROM read_parquet('{p(name + '.parquet')}')")
        self.version = getattr(self, "version", 0) + 1  # bumps on every (re)load; used as a cache key
        r = self.q("SELECT MIN(mi), MAX(mi) FROM agg_pais").iloc[0]
        self.mi0, self.mi1 = int(r.iloc[0]), int(r.iloc[1])
        self.y0, self.y1 = self.mi0 // 12, self.mi1 // 12
        self.sats = tuple(self.meta.get("satelites", []))
        self.ready = True

    # ---------------------------------------------------------------- helpers
    def q(self, sql: str, params: list | None = None) -> pd.DataFrame:
        with self._lock:
            cur = self._con.cursor()
        return cur.execute(sql, params or []).df()

    def value_expr(self, serie: str, agg: bool = True) -> str:
        """SQL for the chosen series. agg=True on the aggregate tables, False on raw points."""
        if serie == "harm" and self.has_harm:
            return "SUM(n_harm)" if agg else "SUM(peso_harm)"
        if serie == "modis":
            return "SUM(n) FILTER (WHERE sensor = 'MODIS')" if agg else "COUNT(*) FILTER (WHERE sensor = 'MODIS')"
        return "SUM(n)" if agg else "COUNT(*)"

    @staticmethod
    def _time_sql(f: Filtro) -> tuple[str, list]:
        sql, prm = ["mi BETWEEN ? AND ?"], [f.t0, f.t1]
        if f.cal:
            if f.cal[0] == "cell":
                sql.append("ano = ? AND mes = ?"); prm += [f.cal[1], f.cal[2]]
            elif f.cal[0] == "month":
                sql.append("mes = ?"); prm.append(f.cal[1])
            elif f.cal[0] == "year":
                sql.append("ano = ?"); prm.append(f.cal[1])
        return " AND ".join(sql), prm

    @staticmethod
    def _sat_sql(f: Filtro) -> tuple[str, list]:
        return f"satelite IN ({','.join('?' * len(f.sats))})", list(f.sats) or ["__none__"]

    def _scope_agg(self, f: Filtro) -> tuple[str, str, list]:
        """(table, where, params) for scopes answered by the aggregate tables."""
        if f.kind == "all":
            return "agg_pais", "TRUE", []
        if f.kind == "pais":
            return "agg_pais", "iso3 = ?", [f.uid]
        if f.kind == "prov":
            return "agg_prov", "prov_id = ?", [f.uid]
        if f.kind == "dep":
            return "agg_dep", "dep_id = ?", [f.uid]
        raise ValueError(f.kind)

    def _points_scope(self, f: Filtro) -> tuple[str, str, list]:
        """(view, where, params) for queries that need individual hotspots."""
        if f.kind == "shape":
            xs = [p[0] for p in f.shape]; ys = [p[1] for p in f.shape]
            view = "focos_arg" if self._inside_argentina(min(xs), min(ys), max(xs), max(ys)) else "focos"
            return view, "lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?", [min(xs), max(xs), min(ys), max(ys)]
        if f.kind == "prov":
            return "focos_arg", "prov_id = ?", [f.uid]
        if f.kind == "dep":
            return "focos_arg", "dep_id = ?", [f.uid]
        if f.kind == "pais":
            return ("focos_arg", "TRUE", []) if f.uid == "ARG" else ("focos", "iso3 = ?", [f.uid])
        return "focos", "TRUE", []

    def _inside_argentina(self, x0, y0, x1, y1) -> bool:
        b = self.geo.paises["ARG"].bbox
        return x0 >= b[0] and y0 >= b[1] and x1 <= b[2] and y1 <= b[3]

    def _shape_mask(self, df: pd.DataFrame, f: Filtro) -> pd.DataFrame:
        if f.kind != "shape" or df.empty:
            return df
        poly = shapely.Polygon(f.shape)
        return df[shapely.contains_xy(poly, df["lon"].to_numpy(), df["lat"].to_numpy())]

    # ---------------------------------------------------------------- monthly series
    @lru_cache(maxsize=256)
    def monthly(self, f: Filtro) -> pd.DataFrame:
        """Full monthly history for the scope (time filters ignored). Columns: raw, modis, viirs, harm + one per satellite."""
        f = f.without_time()
        sat, sp = self._sat_sql(f)
        if f.kind == "shape":
            view, where, prm = self._points_scope(f)
            df = self.q(f"SELECT lon, lat, mi, sensor, satelite, peso_harm FROM {view} WHERE {where} AND {sat}", prm + sp)
            df = self._shape_mask(df, f)
            g = df.groupby("mi")
            out = pd.DataFrame({"raw": g.size(), "modis": g["sensor"].apply(lambda s: (s == "MODIS").sum()),
                                "harm": g["peso_harm"].sum(min_count=1)})
            for s_ in SATS:
                out[s_.lower()] = g["satelite"].apply(lambda s, s_=s_: (s == s_).sum())
        else:
            tab, where, prm = self._scope_agg(f)
            per_sat = ", ".join(f"SUM(n) FILTER (WHERE satelite='{s_}') {s_.lower()}" for s_ in SATS)
            out = self.q(f"""SELECT mi, SUM(n) raw, SUM(n) FILTER (WHERE sensor='MODIS') modis, SUM(n_harm) harm, {per_sat}
                             FROM {tab} WHERE {where} AND {sat} GROUP BY mi""", prm + sp).set_index("mi")
        idx = pd.RangeIndex(self.mi0, self.mi1 + 1, name="mi")
        out = out.reindex(idx).astype("float64")
        cols = ["raw", "modis"] + [s_.lower() for s_ in SATS]
        out[cols] = out[cols].fillna(0)
        out["viirs"] = out["raw"] - out["modis"]
        out["ano"] = out.index // 12
        out["mes"] = out.index % 12 + 1
        return out

    def series(self, f: Filtro) -> pd.Series:
        m = self.monthly(f)
        col = f.serie if (f.serie != "harm" or self.has_harm) else "raw"
        return m[col]

    # ---------------------------------------------------------------- territories (choropleth + ranking)
    @lru_cache(maxsize=256)
    def territories(self, level: str, f: Filtro, parent: str | None = None) -> pd.DataFrame:
        """Counts per unit of `level` (pais|prov|dep) in the selected period. Columns: id, n, pico_mes, frp_max."""
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        val = self.value_expr(f.serie, agg=True)
        key, tab = {"pais": ("iso3", "agg_pais"), "prov": ("prov_id", "agg_prov"), "dep": ("dep_id", "agg_dep")}[level]
        where, prm = "TRUE", []
        if level == "dep" and parent:
            where, prm = "prov_id = ?", [parent]
        if f.kind == "shape":  # count only hotspots inside the drawn area
            view, sw, spp = self._points_scope(f)
            df = self.q(f"SELECT lon, lat, {key} AS id, mes, frp, sensor, peso_harm FROM {view} WHERE {sw} AND {ts} AND {sat}", spp + tp + sp)
            df = self._shape_mask(df, f)
            if f.serie == "modis":
                df = df[df["sensor"] == "MODIS"]
            if df.empty:
                return pd.DataFrame(columns=["id", "n", "pico_mes", "frp_max"])
            w = df["peso_harm"] if (f.serie == "harm" and self.has_harm) else 1
            df = df.assign(w=w)
            g = df.groupby("id")
            out = pd.DataFrame({"n": g["w"].sum(), "frp_max": g["frp"].max()})
            pm = df.groupby(["id", "mes"])["w"].sum().reset_index().sort_values("w").groupby("id").tail(1).set_index("id")["mes"]
            return out.join(pm.rename("pico_mes")).reset_index()
        return self.q(f"""WITH b AS (SELECT {key} AS id, mes, {val} AS v, MAX(frp_max) AS fm FROM {tab}
                              WHERE {where} AND {ts} AND {sat} GROUP BY ALL)
                          SELECT id, SUM(v) AS n, arg_max(mes, v) AS pico_mes, MAX(fm) AS frp_max
                          FROM b GROUP BY id HAVING SUM(v) > 0""", prm + tp + sp)

    # ---------------------------------------------------------------- grid and points
    def _cell_table(self, f: Filtro, deg: float):
        """Pre-aggregated cell table that can answer this grid, or None (then raw hotspots are scanned)."""
        if not self.has_cells or f.kind == "shape":
            return None
        multiple = lambda base: deg >= base - 1e-9 and abs(deg / base - round(deg / base)) < 1e-6  # noqa: E731
        if f.kind in ("prov", "dep") or (f.kind == "pais" and f.uid == "ARG" and deg < 0.25):
            if multiple(0.05):
                where = {"prov": ("prov_id = ?", [f.uid]), "dep": ("dep_id = ?", [f.uid]), "pais": ("TRUE", [])}[f.kind]
                return "cell_ar", 0.05, where
        if f.kind in ("all", "pais") and multiple(0.25):
            return "cell_025", 0.25, ("TRUE", []) if f.kind == "all" else ("iso3 = ?", [f.uid])
        return None

    @lru_cache(maxsize=128)
    def grid(self, f: Filtro, deg: float) -> pd.DataFrame:
        """Hotspots aggregated into deg x deg cells. Columns: gx, gy, n, frp_max, ultimo_mi, pico_mes, + one per satellite."""
        cell = self._cell_table(f, deg)
        if cell:
            tab, base, (where, prm) = cell
            ts, tp = self._time_sql(f)
            sat, sp = self._sat_sql(f)
            val = self.value_expr(f.serie, agg=True)
            sats_cols = ", ".join(f"SUM(n) FILTER (WHERE satelite = '{s}') AS \"{s}\"" for s in self.sats)
            return self.q(f"""WITH b AS (SELECT CAST(floor(gx * {base} / {deg} + 1e-9) AS INTEGER) gx2, CAST(floor(gy * {base} / {deg} + 1e-9) AS INTEGER) gy2,
                                        mi, mes, satelite, sensor, n, n_harm, frp_max FROM {tab} WHERE {where} AND {ts} AND {sat}),
                              m AS (SELECT gx2, gy2, mes, {val} v FROM b GROUP BY ALL),
                              p AS (SELECT gx2, gy2, arg_max(mes, v) pico_mes FROM m GROUP BY ALL)
                              SELECT b.gx2 AS gx, b.gy2 AS gy, {val} AS n, MAX(frp_max) frp_max, MAX(mi) ultimo_mi, {sats_cols}, ANY_VALUE(p.pico_mes) pico_mes
                              FROM b JOIN p USING (gx2, gy2) GROUP BY b.gx2, b.gy2 HAVING n > 0""", prm + tp + sp).fillna({s: 0 for s in self.sats})
        view, where, prm = self._points_scope(f)
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        df = self.q(f"""SELECT CAST(floor(lon/{deg}) AS INTEGER) gx, CAST(floor(lat/{deg}) AS INTEGER) gy, lon, lat,
                               mi, mes, satelite, sensor, frp, peso_harm
                        FROM {view} WHERE {where} AND {ts} AND {sat}""", prm + tp + sp) if f.kind == "shape" else None
        if df is not None:
            df = self._shape_mask(df, f)
            if f.serie == "modis":
                df = df[df["sensor"] == "MODIS"]
            if df.empty:
                return pd.DataFrame(columns=["gx", "gy", "n", "frp_max", "ultimo_mi", "pico_mes"])
            df = df.assign(w=df["peso_harm"] if (f.serie == "harm" and self.has_harm) else 1.0)
            g = df.groupby(["gx", "gy"])
            out = pd.DataFrame({"n": g["w"].sum(), "frp_max": g["frp"].max(), "ultimo_mi": g["mi"].max()})
            pm = df.groupby(["gx", "gy", "mes"])["w"].sum().reset_index().sort_values("w").groupby(["gx", "gy"]).tail(1).set_index(["gx", "gy"])["mes"]
            sats = df.pivot_table(index=["gx", "gy"], columns="satelite", values="w", aggfunc="count", fill_value=0)
            return out.join(pm.rename("pico_mes")).join(sats).reset_index()
        val = self.value_expr(f.serie, agg=False)
        sats_cols = ", ".join(f"COUNT(*) FILTER (WHERE satelite = '{s}') AS \"{s}\"" for s in self.sats)
        return self.q(f"""WITH b AS (SELECT CAST(floor(lon/{deg}) AS INTEGER) gx, CAST(floor(lat/{deg}) AS INTEGER) gy, *
                               FROM {view} WHERE {where} AND {ts} AND {sat}),
                          m AS (SELECT gx, gy, mes, {val} v FROM b GROUP BY ALL)
                          SELECT b.gx, b.gy, {val} AS n, MAX(frp) frp_max, MAX(mi) ultimo_mi, {sats_cols},
                                 (SELECT arg_max(mes, v) FROM m WHERE m.gx=b.gx AND m.gy=b.gy) AS pico_mes
                          FROM b GROUP BY b.gx, b.gy HAVING n > 0""", prm + tp + sp)

    @lru_cache(maxsize=64)
    # ---------------------------------------------------------------- viewport queries (map follows the zoom)
    def grid_view(self, f: Filtro, deg: float, bbox: tuple) -> pd.DataFrame:
        """Cells of `deg` degrees inside the visible bbox (x0, y0, x1, y1); time/satellite/series filters from `f`."""
        return self._grid_view(f, round(deg, 4), tuple(round(v, 2) for v in bbox))

    @lru_cache(maxsize=64)
    def _grid_view(self, f: Filtro, deg: float, bbox: tuple) -> pd.DataFrame:
        x0, y0, x1, y1 = bbox
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        val = self.value_expr(f.serie, agg=True)
        ar = self.geo.paises["ARG"].bbox
        inside_ar = x0 >= ar[0] - 1 and x1 <= ar[2] + 1 and y0 >= ar[1] - 1 and y1 <= ar[3] + 1
        base = 0.25 if deg >= 0.25 - 1e-9 else 0.05
        tab = "cell_025" if base == 0.25 or not inside_ar else "cell_ar"
        if tab == "cell_025":
            base = 0.25
            deg = max(deg, 0.25)
        k = deg / base
        gx0, gx1 = int(np.floor(x0 / base)), int(np.floor(x1 / base))
        gy0, gy1 = int(np.floor(y0 / base)), int(np.floor(y1 / base))
        sats_cols = ", ".join(f"SUM(n) FILTER (WHERE satelite = '{s}') AS \"{s}\"" for s in self.sats)
        df = self.q(f"""WITH b AS (SELECT CAST(floor(gx / {k} + 1e-9) AS INTEGER) gx, CAST(floor(gy / {k} + 1e-9) AS INTEGER) gy,
                                   mi, mes, satelite, sensor, n, n_harm, frp_max FROM {tab}
                                   WHERE gx BETWEEN ? AND ? AND gy BETWEEN ? AND ? AND {ts} AND {sat}),
                           m AS (SELECT gx, gy, mes, {val} v FROM b GROUP BY ALL),
                           p AS (SELECT gx, gy, arg_max(mes, v) pico_mes FROM m GROUP BY ALL)
                        SELECT b.gx, b.gy, {val} AS n, MAX(frp_max) frp_max, MAX(mi) ultimo_mi, {sats_cols}, ANY_VALUE(p.pico_mes) pico_mes
                        FROM b JOIN p USING (gx, gy) GROUP BY b.gx, b.gy HAVING n > 0""", [gx0, gx1, gy0, gy1] + tp + sp)
        df.attrs["deg"] = deg
        return df.fillna({s: 0 for s in self.sats})

    @lru_cache(maxsize=64)
    def points_view(self, f: Filtro, bbox: tuple, limit: int = 6000) -> tuple[pd.DataFrame, int]:
        """Most recent hotspots inside the bbox, and how many there are in total."""
        x0, y0, x1, y1 = bbox
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        ar = self.geo.paises["ARG"].bbox
        view = "focos_arg" if (x0 >= ar[0] - 1 and x1 <= ar[2] + 1 and y0 >= ar[1] - 1 and y1 <= ar[3] + 1) else "focos"
        cond = " AND sensor='MODIS'" if f.serie == "modis" else ""
        where = f"lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? AND {ts} AND {sat}{cond}"
        prm = [x0, x1, y0, y1] + tp + sp
        total = int(self.q(f"SELECT COUNT(*) c FROM {view} WHERE {where}", prm)["c"].iloc[0])
        df = self.q(f"SELECT lat, lon, ts, satelite, sensor, frp FROM {view} WHERE {where} ORDER BY ts DESC LIMIT {int(limit)}", prm)
        return df, total

    def points(self, f: Filtro, limit: int = 5000) -> pd.DataFrame:
        view, where, prm = self._points_scope(f)
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        cond = " AND sensor='MODIS'" if f.serie == "modis" else (" AND (sensor='VIIRS' OR ano < 2012)" if f.serie == "harm" and not self.has_harm else "")
        df = self.q(f"""SELECT lat, lon, ts, satelite, sensor, frp, iso3, {'dep_id, prov_id' if view == 'focos_arg' else 'NULL AS dep_id, NULL AS prov_id'}
                        FROM {view} WHERE {where} AND {ts} AND {sat}{cond} ORDER BY ts DESC LIMIT {int(limit) * 3}""", prm + tp + sp)
        return self._shape_mask(df, f).head(limit)

    @lru_cache(maxsize=64)
    def count_points(self, f: Filtro) -> int:
        view, where, prm = self._points_scope(f)
        ts, tp = self._time_sql(f)
        sat, sp = self._sat_sql(f)
        return int(self.q(f"SELECT COUNT(*) c FROM {view} WHERE {where} AND {ts} AND {sat}", prm + tp + sp)["c"].iloc[0])

    def export(self, f: Filtro, limit: int = 200_000) -> pd.DataFrame:
        df = self.points(f, limit=limit)
        return df.rename(columns={"lat": "latitude", "lon": "longitude", "ts": "data_hora_gmt", "iso3": "pais_iso3"})

    def sat_counts(self, f: Filtro) -> dict[str, int]:
        ts, tp = self._time_sql(f)
        if f.kind == "shape":
            view, where, prm = self._points_scope(f)
            df = self._shape_mask(self.q(f"SELECT lon, lat, satelite FROM {view} WHERE {where} AND {ts}", prm + tp), f)
            return df["satelite"].value_counts().to_dict()
        tab, where, prm = self._scope_agg(f)
        df = self.q(f"SELECT satelite, SUM(n) n FROM {tab} WHERE {where} AND {ts} GROUP BY 1", prm + tp)
        return dict(zip(df["satelite"], df["n"].astype(int)))
