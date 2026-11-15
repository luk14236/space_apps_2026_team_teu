"""CLI: data/raw -> data/processed.  python scripts/prepare_data.py [--raw DIR] [--out DIR]

AI-assisted: written with Claude (Anthropic) and reviewed by the team. Logic lives in app/pipeline/prepare.py
(also used by the /admin page).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.pipeline.prepare import PrepareError, run  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(config.RAW_DIR))
    ap.add_argument("--out", default=str(config.PROCESSED_DIR))
    a = ap.parse_args()
    try:
        meta = run(Path(a.raw).expanduser(), Path(a.out).expanduser(), config.GEO_DIR, log=lambda m: print(m, flush=True))
    except PrepareError as e:
        raise SystemExit(str(e))
    print(json.dumps(meta, ensure_ascii=False, indent=2))
