"""Situation room metrics: recent days against what is expected for the time of year.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Reference day D = last day with data. For each Argentine department:
    R      hotspots in the last `win` days up to D
    Ex     expected hotspots for those days = mean count of the same calendar month in the baseline years,
           spread evenly over the month's days
    ratio  (R + 0.5) / (Ex + 0.5)
    status crit / alert / watch / ok / below (rules in `status`)
Counts are the harmonized series when `peso_harm` exists, otherwise all sensors (raw). The baseline starts in
BASELINE_FROM so that it has the same VIIRS coverage as recent years.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from .repository import Repository

DAYS = 120            # daily window kept in memory
BASELINE_FROM = 2019  # S-NPP + NOAA-20 both available
RMIN = {1: 6, 7: 20, 30: 50}
RANK = {"crit": 4, "alert": 3, "watch": 2, "ok": 1, "below": 0}
LABEL = {"crit": "Crítico", "alert": "Alerta", "watch": "Atenção", "ok": "Normal", "below": "Abaixo"}


def status(r: float, ex: float, win: int) -> str:
    ratio, rm = (r + 0.5) / (ex + 0.5), RMIN[win]
    if ratio >= 3 and r >= rm:
        return "crit"
    if ratio >= 2 and r >= rm * 0.5:
        return "alert"
    if ratio >= 1.5 and r >= max(3, rm * 0.2):
        return "watch"
    if ratio < 0.6 and ex >= max(10, rm * 0.5):
        return "below"
    return "ok"


class Sala:
    def __init__(self, repo: Repository):
        self.repo = repo

    # ------------------------------------------------------------------ daily matrices (cached per data version)
    def daily(self) -> dict:
        return _daily(self.repo, self.repo.version)

    def metrics(self, win: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        return _metrics(self.repo, self.repo.version, win)

    # ------------------------------------------------------------------ hotspots of the last day, grouped in cells
    def today_cells(self, deps: list[str] | None, deg: float = 0.1) -> pd.DataFrame:
        d = self.daily()
        D = d["D"]
        where, prm = ("dep_id IN (" + ",".join("?" * len(deps)) + ")", list(deps)) if deps else ("TRUE", [])
        df = self.repo.q(f"""SELECT CAST(floor(lon/{deg}) AS INTEGER) gx, CAST(floor(lat/{deg}) AS INTEGER) gy, lon, lat, ts,
                                    CAST(ts AS DATE) dia, satelite, frp, dep_id, prov_id
                             FROM focos_arg WHERE {where} AND ts >= ? AND ts < ?""",
                         prm + [pd.Timestamp(D - timedelta(days=7)), pd.Timestamp(D + timedelta(days=1))])
        if df.empty:
            return df
        df["dia"] = pd.to_datetime(df["dia"]).dt.date
        today = df[df["dia"] == D]
        before = set(map(tuple, df[df["dia"] < D][["gx", "gy"]].drop_duplicates().to_numpy()))
        if today.empty:
            return today
        g = today.groupby(["gx", "gy"])
        out = pd.DataFrame({"n": g.size(), "frp": g["frp"].max(), "lon": g["lon"].mean(), "lat": g["lat"].mean(),
                            "ultimo": g["ts"].max(), "sats": g["satelite"].agg(lambda s: sorted(set(s))),
                            "dep_id": g["dep_id"].agg(lambda s: s.value_counts().index[0])}).reset_index()
        out["novo"] = [(gx, gy) not in before for gx, gy in zip(out["gx"], out["gy"])]
        return out.sort_values(["n", "frp"], ascending=False)

    def window_points(self, deps: list[str] | None, win: int, limit: int = 8000) -> pd.DataFrame:
        """Hotspots of the last `win` days (most recent first), optionally restricted to some departments."""
        D = self.daily()["D"]
        where, prm = ("dep_id IN (" + ",".join("?" * len(deps)) + ")", list(deps)) if deps else ("TRUE", [])
        df = self.repo.q(f"""SELECT lat, lon, ts, CAST(ts AS DATE) dia, satelite, frp FROM focos_arg
                             WHERE {where} AND ts >= ? AND ts < ? ORDER BY ts DESC LIMIT {int(limit)}""",
                         prm + [pd.Timestamp(D - timedelta(days=win - 1)), pd.Timestamp(D + timedelta(days=1))])
        df["dia"] = pd.to_datetime(df["dia"]).dt.date
        return df

    def sat_status(self) -> pd.DataFrame:
        D = self.daily()["D"]
        return self.repo.q("""SELECT satelite, MAX(ts) ultimo, COUNT(*) FILTER (WHERE CAST(ts AS DATE) = ?) hoje
                              FROM focos_arg WHERE ts >= ? GROUP BY 1 ORDER BY 1""", [D, pd.Timestamp(D - timedelta(days=30))])


@lru_cache(maxsize=4)
def _daily(repo: Repository, version: int) -> dict:
    val = "SUM(n_harm)" if repo.has_harm else "SUM(n)"
    D = repo.q("SELECT MAX(dia) d FROM dia_dep")["d"].iloc[0]
    D = pd.Timestamp(D).date()
    start = D - timedelta(days=DAYS - 1)
    days = pd.date_range(start, D, freq="D")
    deps = list(repo.geo.departamentos)
    raw = repo.q(f"SELECT dep_id, dia, {val} n, MAX(frp_max) frp FROM dia_dep WHERE dia >= ? GROUP BY 1, 2", [start])
    raw["dia"] = pd.to_datetime(raw["dia"])
    A = raw.pivot_table(index="dep_id", columns="dia", values="n", aggfunc="sum").reindex(index=deps, columns=days).fillna(0.0)
    F = raw.pivot_table(index="dep_id", columns="dia", values="frp", aggfunc="max").reindex(index=deps, columns=days).fillna(0.0)
    # expected daily rate: mean of the same month in the baseline years / days in month
    base_to = D.year - 1
    years = base_to - BASELINE_FROM + 1
    tot = repo.q(f"SELECT dep_id, mes, {val} AS n FROM agg_dep WHERE ano BETWEEN ? AND ? GROUP BY 1, 2", [BASELINE_FROM, base_to])
    tot["media"] = tot["n"] / years  # years without fire count as zero
    rate = tot.pivot_table(index="dep_id", columns="mes", values="media").reindex(index=deps, columns=range(1, 13)).fillna(0.0)
    dim = np.array([calendar.monthrange(d.year, d.month)[1] for d in days])
    E = pd.DataFrame(rate[[d.month for d in days]].to_numpy() / dim, index=deps, columns=days)
    return {"D": D, "days": days, "A": A, "F": F, "E": E, "baseline": (BASELINE_FROM, base_to)}


def _frame(A: pd.DataFrame, E: pd.DataFrame, F: pd.DataFrame, win: int) -> pd.DataFrame:
    a, e = A.to_numpy(), E.to_numpy()
    R = a[:, -win:].sum(1)
    Ex = e[:, -win:].sum(1)
    prev = a[:, -2 * win:-win].sum(1)
    pers = np.zeros(len(a), dtype=int)
    for i, row in enumerate(a):
        z = np.where(row[::-1] <= 0)[0]
        pers[i] = z[0] if len(z) else len(row)
    df = pd.DataFrame({"R": R, "Ex": Ex, "prev": prev, "pers": pers, "today": a[:, -1], "frp": F.to_numpy()[:, -win:].max(1)}, index=A.index)
    df["ratio"] = (df["R"] + 0.5) / (df["Ex"] + 0.5)
    df["status"] = [status(r, x, win) for r, x in zip(df["R"], df["Ex"])]
    df["trend"] = np.where(df["prev"] > 0, (df["R"] - df["prev"]) / df["prev"].clip(lower=1), np.where(df["R"] > 0, 1.0, 0.0))
    df["score"] = df["status"].map(RANK) * 1000 + np.log2(df["ratio"]) * 50 + np.log10(df["R"] + 1) * 40 + df["pers"].clip(upper=30) * 3
    return df


@lru_cache(maxsize=8)
def _metrics(repo: Repository, version: int, win: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = _daily(repo, version)
    deps = _frame(d["A"], d["E"], d["F"], win)
    parent = pd.Series({k: u.parent for k, u in repo.geo.departamentos.items()})
    deps["prov_id"] = parent.reindex(deps.index)
    deps["nome"] = [repo.geo.departamentos[k].nome for k in deps.index]
    deps["sub"] = [repo.geo.provincias[p].nome if p in repo.geo.provincias else "" for p in deps["prov_id"]]
    gA, gE, gF = (d[k].groupby(parent.reindex(d[k].index)) for k in ("A", "E", "F"))
    provs = _frame(gA.sum(), gE.sum(), gF.max(), win)
    provs["nome"] = [repo.geo.provincias[k].nome for k in provs.index]
    provs["sub"] = [repo.geo.provincias[k].regiao for k in provs.index]
    return deps, provs


def series_for(repo: Repository, deps: list[str]) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    d = _daily(repo, repo.version)
    return d["A"].loc[deps].sum().to_numpy(), d["E"].loc[deps].sum().to_numpy(), d["days"]
