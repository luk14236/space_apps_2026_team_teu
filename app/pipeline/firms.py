"""Download hotspots from the NASA FIRMS Area API and save them in the data team's CSV format.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Needs a free MAP_KEY (https://firms.modaps.eosdis.nasa.gov/api/map_key). For each satellite and each 5-day
chunk it asks for the science-quality product (*_SP) and falls back to near-real-time (*_NRT) when SP is not
published yet. Points outside the 13 South American countries in data/geo/paises.geojson are dropped.
Output: <out>/focos_brutos_firms_<start>_<end>.csv with extra FIRMS columns confidence, daynight, type.
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}/{date}"
AREA = "-82,-56,-34,13"  # west,south,east,north: South America
SOURCES = {"MODIS": "MODIS", "SNPP": "VIIRS_SNPP", "NOAA20": "VIIRS_NOAA20", "NOAA21": "VIIRS_NOAA21"}
MAX_DAYS = 5  # FIRMS Area API limit per request ("Expects [1..5]")


class FirmsError(Exception):
    pass


def _get(url: str, log: Callable[[str], None], tries: int = 4) -> str:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code < 500:  # FIRMS explains 4xx errors in the body
                return e.read().decode("utf-8", "replace")
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        if k == tries - 1:
            raise FirmsError(f"FIRMS indisponível: {err}")
        log(f"  nova tentativa ({err})")
        time.sleep(5 * (k + 1))
    return ""


def _chunk(key: str, prefix: str, start: date, days: int, log) -> pd.DataFrame:
    for suffix in ("SP", "NRT"):
        source = f"{prefix}_{suffix}"
        txt = _get(API.format(key=key, source=source, area=AREA, days=days, date=start.isoformat()), log)
        if "latitude" not in txt[:300]:
            if "invalid" in txt.lower() and "key" in txt.lower():
                raise FirmsError(f"MAP_KEY recusada pelo FIRMS: {txt[:120]}")
            continue
        df = pd.read_csv(io.StringIO(txt))
        if len(df):
            df["fonte"] = source
            return df
    return pd.DataFrame()


def run(start: date, end: date, out: Path, key: str, geo_dir: Path, sats=("MODIS", "SNPP", "NOAA20", "NOAA21"),
        log: Callable[[str], None] = print) -> Path | None:
    if not key:
        raise FirmsError("Defina FIRMS_MAP_KEY (chave gratuita em https://firms.modaps.eosdis.nasa.gov/api/map_key)")
    frames = []
    for sat in sats:
        d = start
        while d <= end:
            days = min(MAX_DAYS, (end - d).days + 1)
            df = _chunk(key, SOURCES[sat], d, days, log)
            log(f"{sat:7s} {d} +{days}d: {len(df):6d} focos ({df['fonte'].iloc[0] if len(df) else '-'})")
            if len(df):
                frames.append(df)
            d += timedelta(days=days)
            time.sleep(0.3)  # stay well under 5000 requests / 10 min
    if not frames:
        log("Nenhum foco baixado.")
        return None
    raw = pd.concat(frames, ignore_index=True)
    hhmm = raw["acq_time"].astype(int).astype(str).str.zfill(4)
    modis = raw["fonte"].str.startswith("MODIS")
    out_df = pd.DataFrame({
        "data_hora_gmt": pd.to_datetime(raw["acq_date"] + " " + hhmm.str[:2] + ":" + hhmm.str[2:]),
        "latitude": raw["latitude"], "longitude": raw["longitude"],
        "satelite": np.where(modis, raw["satellite"].astype(str).str.upper().replace({"T": "TERRA", "A": "AQUA"}),
                             raw["fonte"].str.extract(r"VIIRS_([A-Z0-9]+)_")[0]),
        "sensor": np.where(modis, "MODIS", "VIIRS"),
        "frp": raw["frp"], "confidence": raw["confidence"].astype(str),
        "daynight": raw["daynight"] if "daynight" in raw else pd.NA,
        "type": raw["type"] if "type" in raw else pd.NA,
    })
    feats = json.loads((geo_dir / "paises.geojson").read_text(encoding="utf-8"))["features"]
    tree = shapely.STRtree([shape(f["geometry"]) for f in feats])
    names = np.array([f["properties"]["nome"] for f in feats], dtype=object)
    idx = np.full(len(out_df), -1)
    pi, gi = tree.query(shapely.points(out_df["longitude"], out_df["latitude"]), predicate="within")
    idx[pi] = gi
    out_df.insert(0, "pais", np.where(idx >= 0, names[np.maximum(idx, 0)], None))
    out_df = out_df[out_df["pais"].notna()].drop_duplicates(["data_hora_gmt", "latitude", "longitude", "satelite"])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"focos_brutos_firms_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    out_df.sort_values("data_hora_gmt").to_csv(path, index=False)
    log(f"{len(out_df):,} focos gravados em {path.name}: " + ", ".join(f"{k} {v:,}" for k, v in out_df.groupby("satelite").size().items()))
    return path
