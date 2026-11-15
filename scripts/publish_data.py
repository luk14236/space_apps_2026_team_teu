"""CLI: publish data/processed online (GitHub Release + Hugging Face Space), same as admin step 4.

AI-assisted: written with Claude (Anthropic) and reviewed by the team. Logic lives in app/pipeline/publish.py.
Needs `gh` logged in, `hf auth login`, and HF_SPACE in .env.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import publish  # noqa: E402

if __name__ == "__main__":
    ok, why = publish.availability()
    if not ok:
        raise SystemExit(why)
    entry = publish.publish(lambda m: print(m, flush=True), lambda p, s: print(f"[{p:3.0f}%] {s}", flush=True))
    print(f"DATA_BUNDLE_URL={entry['url']}")
