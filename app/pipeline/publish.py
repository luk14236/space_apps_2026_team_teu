"""Publish processed data online: GitHub Release asset + point the Hugging Face Space at it and restart it.

AI-assisted: written with Claude (Anthropic) and reviewed by the team. Used by /admin and scripts/publish_data.py.
Needs, on the machine running it: GitHub CLI (`gh`) logged in, `huggingface_hub` with a write token, HF_SPACE set.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Callable

from .. import config

HISTORY = "publicacoes.json"


def availability() -> tuple[bool, str]:
    if config.ON_SPACE:
        return False, "Este é o site publicado: publique a partir do admin local."
    if not config.HF_SPACE:
        return False, "Defina HF_SPACE (ex.: usuario/space) no .env."
    if not shutil.which("gh"):
        return False, "GitHub CLI (gh) não encontrado nesta máquina."
    try:
        from huggingface_hub import HfApi
        HfApi().whoami()
    except Exception:  # noqa: BLE001
        return False, "Faça login no Hugging Face nesta máquina (hf auth login)."
    return True, ""


def history() -> list[dict]:
    p = config.DATA_DIR / HISTORY
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def bundle(src: Path, out: Path) -> Path:
    with tarfile.open(out, "w") as t:  # parquet is already compressed
        for p in sorted(src.iterdir()):
            if p.is_file():
                t.add(p, arcname=p.name)
    return out


def release(tar: Path, meta: dict, log: Callable[[str], None]) -> str:
    tag = time.strftime("data-%Y%m%d-%H%M")
    fontes = ", ".join(meta["fonte"]) if isinstance(meta["fonte"], list) else str(meta["fonte"])
    notes = f"Dados processados: {meta['total_focos']:,} focos, {meta['inicio'][:10]} a {meta['fim'][:10]}. Fontes: {fontes} (NASA FIRMS).".replace(",", ".")
    log(f"Enviando {tar.stat().st_size / 1e6:.0f} MB para a Release {tag} do GitHub…")
    subprocess.run(["gh", "release", "create", tag, str(tar), "--title", f"Dados {meta['fim'][:10]}", "--notes", notes, "--latest=false"],
                   check=True, cwd=config.ROOT, capture_output=True, text=True)
    repo = subprocess.run(["gh", "repo", "view", "--json", "url", "-q", ".url"], capture_output=True, text=True, check=True, cwd=config.ROOT).stdout.strip()
    return f"{repo}/releases/download/{tag}/processed.tar"


def update_space(url: str, log: Callable[[str], None], timeout_s: int = 900) -> None:
    from huggingface_hub import HfApi
    api = HfApi()
    api.add_space_variable(config.HF_SPACE, "DATA_BUNDLE_URL", url)
    log(f"Space {config.HF_SPACE} reiniciando com os dados novos…")
    api.restart_space(config.HF_SPACE)
    t0, last = time.time(), None
    while time.time() - t0 < timeout_s:
        stage = api.get_space_runtime(config.HF_SPACE).stage
        if stage != last:
            log(f"Space: {stage}")
            last = stage
        if stage == "RUNNING" and time.time() - t0 > 20:
            return
        if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
            raise RuntimeError(f"O Space falhou ao reiniciar ({stage}). Veja os logs em https://huggingface.co/spaces/{config.HF_SPACE}")
        time.sleep(10)
    raise RuntimeError("O Space demorou demais para reiniciar; confira a página dele.")


def publish(log: Callable[[str], None], progress: Callable[[float, str], None] = lambda p, s: None) -> dict:
    src = config.PROCESSED_DIR
    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    progress(5, "Empacotando os dados")
    tar = bundle(src, config.DATA_DIR / "processed.tar")
    try:
        progress(15, "Enviando para o GitHub")
        url = release(tar, meta, log)
    finally:
        tar.unlink(missing_ok=True)
    progress(70, "Atualizando o site")
    update_space(url, log)
    entry = {"quando": time.strftime("%Y-%m-%d %H:%M"), "url": url, "total_focos": meta["total_focos"],
             "inicio": meta["inicio"][:10], "fim": meta["fim"][:10]}
    (config.DATA_DIR / HISTORY).write_text(json.dumps([entry] + history()[:19], ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Site atualizado: {config.SITE_URL or config.HF_SPACE}")
    return entry
