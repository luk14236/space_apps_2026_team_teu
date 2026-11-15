"""Deploy the app to a Hugging Face Space (Docker SDK) through the Hub API.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

    hf auth login                                    # once, with a *write* token
    python scripts/deploy_hf.py [--space user/space] [--data-url URL] [--secrets]

Uploads only what the container needs (Dockerfile, requirements, app/, scripts/, data/geo/) plus a README with the
Space configuration. --data-url sets DATA_BUNDLE_URL (omit to keep the current data); --secrets copies ADMIN_USER,
ADMIN_PASSWORD, SECRET_KEY and FIRMS_MAP_KEY from .env as Space secrets. Also run by .github/workflows/deploy.yml.
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402,F401  (loads .env into the environment)

import os  # noqa: E402

from huggingface_hub import HfApi  # noqa: E402

SPACE_README = """---
title: Calendário de Focos · Team TEU
emoji: 🔥
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: MODIS + VIIRS hotspots calendar and situation room
---

NASA Space Apps Challenge 2026 · MODIS and VIIRS Hot Spots · Team TEU.
Source code: https://github.com/luk14236/space_apps_2026_team_teu
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default=os.environ.get("HF_SPACE"), help="usuario/space (default: HF_SPACE)")
    ap.add_argument("--data-url", help="new DATA_BUNDLE_URL; omit to keep the one already set in the Space")
    ap.add_argument("--message", default="Deploy")
    ap.add_argument("--secrets", action="store_true", help="also copy ADMIN_USER, ADMIN_PASSWORD, SECRET_KEY, FIRMS_MAP_KEY from .env")
    a = ap.parse_args()
    if not a.space:
        raise SystemExit("Informe --space ou defina HF_SPACE.")
    api = HfApi()
    api.create_repo(a.space, repo_type="space", space_sdk="docker", exist_ok=True)
    if a.data_url:
        api.add_space_variable(a.space, "DATA_BUNDLE_URL", a.data_url)
    if a.secrets:
        for k in ("ADMIN_USER", "ADMIN_PASSWORD", "SECRET_KEY", "FIRMS_MAP_KEY"):
            if os.environ.get(k):
                api.add_space_secret(a.space, k, os.environ[k])
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "README.md").write_text(SPACE_README, encoding="utf-8")
        api.upload_file(path_or_fileobj=str(Path(tmp) / "README.md"), path_in_repo="README.md", repo_id=a.space, repo_type="space")
    deployable = ["Dockerfile", "requirements.txt", "app/**", "scripts/**", "data/geo/**"]
    api.upload_folder(folder_path=str(ROOT), repo_id=a.space, repo_type="space", commit_message=a.message[:200],
                      allow_patterns=deployable, ignore_patterns=["**/__pycache__/**", "*.pyc"],
                      delete_patterns=["app/**", "scripts/**", "data/geo/**"])  # files removed from the repo disappear from the Space too
    print(f"https://huggingface.co/spaces/{a.space}")
