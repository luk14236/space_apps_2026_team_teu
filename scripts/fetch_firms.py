"""CLI: download recent hotspots from NASA FIRMS into data/raw.

    export FIRMS_MAP_KEY=...            # free key: https://firms.modaps.eosdis.nasa.gov/api/map_key
    python scripts/fetch_firms.py --start 2026-01-01 --end 2026-11-14
    python scripts/prepare_data.py

AI-assisted: written with Claude (Anthropic) and reviewed by the team. Logic lives in app/pipeline/firms.py
(also used by the /admin page).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.pipeline.firms import FirmsError, run  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=f"{date.today().year}-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--out", default=str(config.RAW_DIR))
    ap.add_argument("--sats", default="MODIS,SNPP,NOAA20,NOAA21")
    a = ap.parse_args()
    try:
        run(date.fromisoformat(a.start), date.fromisoformat(a.end), Path(a.out), config.FIRMS_MAP_KEY, config.GEO_DIR,
            tuple(a.sats.split(",")), log=lambda m: print(m, flush=True))
    except FirmsError as e:
        raise SystemExit(str(e))
