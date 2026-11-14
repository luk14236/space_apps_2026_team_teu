#!/usr/bin/env bash
# Container entry point. AI-assisted: written with Claude (Anthropic) and reviewed by the team.
# 1. If data/processed is empty and DATA_BUNDLE_URL is set, download and unpack the processed data.
# 2. Start the app with gunicorn.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f data/processed/meta.json ] && [ -n "${DATA_BUNDLE_URL:-}" ]; then
  echo "Baixando dados processados de ${DATA_BUNDLE_URL}"
  mkdir -p data/processed
  python - <<'EOF'
import os, tarfile, urllib.request, shutil, tempfile
url = os.environ["DATA_BUNDLE_URL"]
with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
    with urllib.request.urlopen(url, timeout=600) as r:
        shutil.copyfileobj(r, tmp, 8 << 20)
    tmp.flush()
    with tarfile.open(tmp.name) as t:
        for m in t.getmembers():  # only plain files, no paths outside data/processed
            if m.isfile() and "/" not in m.name and not m.name.startswith("."):
                t.extract(m, "data/processed")
print("Dados prontos:", sorted(os.listdir("data/processed")))
EOF
fi

exec gunicorn app.main:server --bind "0.0.0.0:${PORT:-7860}" --workers 1 --threads 8 --timeout 180
