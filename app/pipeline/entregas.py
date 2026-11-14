"""Deliveries ("entregas"): every batch of data we receive is kept as its own version.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

    data/entrada/                      drop zone: paste the data team's .tar.gz / .zip / CSVs here
    data/entregas/<id>/manifest.json   one folder per delivery received (never overwritten)
    data/entregas/<id>/focos_*.csv

manifest.json: id, nome, origem (pasta | upload | link | firms | migrado), recebido_em, ativa, substituida_por,
nota, arquivos[{nome, tipo, tamanho, stats}]. Processing uses the CSVs of the *active* deliveries. When a new delivery
brings a focos_brutos file with the same name as an older one, the older one is switched off (kept, marked as replaced).
"""
from __future__ import annotations

import json
import re
import shutil
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

import duckdb

from .. import config
from . import prepare

ALLOWED_CSV = re.compile(r"^focos_(brutos|mensais)[\w.\-]*\.csv$", re.I)
ARCHIVE = re.compile(r"\.(tar\.gz|tgz|tar|zip)$", re.I)


def root() -> Path:
    return config.DATA_DIR / "entregas"


def inbox() -> Path:
    return config.DATA_DIR / "entrada"


def _slug(s: str) -> str:
    s = re.sub(ARCHIVE, "", Path(s).name)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:60] or "entrega"


def _write(m: dict) -> None:
    (root() / m["id"] / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def load(eid: str) -> dict:
    return json.loads((root() / eid / "manifest.json").read_text(encoding="utf-8"))


def all_entregas() -> list[dict]:
    if not root().exists():
        return []
    out = [json.loads(p.read_text(encoding="utf-8")) for p in root().glob("*/manifest.json")]
    return sorted(out, key=lambda m: m["recebido_em"], reverse=True)


def inbox_files() -> list[dict]:
    if not inbox().exists():
        return []
    return [{"nome": p.name, "tamanho": p.stat().st_size, "modificado": int(p.stat().st_mtime)}
            for p in sorted(inbox().iterdir()) if p.is_file() and (ARCHIVE.search(p.name) or ALLOWED_CSV.match(p.name))]


def _new(nome: str, origem: str, nota: str = "") -> tuple[dict, Path]:
    eid = time.strftime("%Y%m%d-%H%M%S") + "_" + _slug(nome)
    d = root() / eid
    d.mkdir(parents=True)
    return {"id": eid, "nome": nome, "origem": origem, "recebido_em": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ativa": True, "substituida_por": None, "nota": nota, "arquivos": []}, d


def _finish(m: dict, d: Path, log: Callable[[str], None]) -> dict:
    if not m["arquivos"]:
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("Nenhum focos_brutos*.csv ou focos_mensais*.csv encontrado.")
    _write(m)
    # a new delivery replaces older ones that bring files with the same names
    names = {a["nome"] for a in m["arquivos"]}
    for old in all_entregas():
        if old["id"] != m["id"] and old["ativa"] and names & {a["nome"] for a in old["arquivos"]}:
            old.update(ativa=False, substituida_por=m["id"])
            _write(old)
            log(f"Entrega anterior '{old['nome']}' desligada (substituída por esta). Ela continua guardada no histórico.")
    log(f"Entrega '{m['nome']}' recebida: {', '.join(sorted(names))}.")
    return m


def _add_file(m: dict, d: Path, name: str, src) -> None:
    tmp = d / (name + ".part")
    with open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst, 8 << 20)
    tmp.replace(d / name)
    m["arquivos"].append({"nome": name, "tipo": "brutos" if "brutos" in name.lower() else "mensais", "tamanho": (d / name).stat().st_size, "stats": None})


def from_path(path: Path, origem: str, log: Callable[[str], None] = print, nome: str | None = None, nota: str = "") -> dict:
    """Create a delivery from an archive or a CSV on disk (only focos_* CSVs are kept)."""
    m, d = _new(nome or path.name, origem, nota)
    skipped = []
    try:
        if ALLOWED_CSV.match(path.name):
            with open(path, "rb") as src:
                _add_file(m, d, path.name, src)
        elif path.name.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    base = Path(info.filename).name
                    if not info.is_dir() and ALLOWED_CSV.match(base):
                        log(f"Extraindo {base} ({info.file_size / 1e6:.0f} MB)…")
                        with z.open(info) as src:
                            _add_file(m, d, base, src)
                    elif not info.is_dir():
                        skipped.append(base)
        elif ARCHIVE.search(path.name):
            with tarfile.open(path, "r:*") as t:
                for mem in t:
                    base = Path(mem.name).name
                    if mem.isfile() and ALLOWED_CSV.match(base):
                        log(f"Extraindo {base} ({mem.size / 1e6:.0f} MB)…")
                        _add_file(m, d, base, t.extractfile(mem))
                    elif mem.isfile():
                        skipped.append(base)
        else:
            raise ValueError(f"Formato não suportado: {path.name}")
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    if skipped:
        log(f"Ignorados (não são CSVs de focos): {', '.join(skipped)}")
    return _finish(m, d, log)


def from_url(url: str, log: Callable[[str], None] = print, progress: Callable[[float, str], None] = lambda p, s: None) -> dict:
    if not re.match(r"^https?://", url):
        raise ValueError("Use um link http(s).")
    inbox().mkdir(parents=True, exist_ok=True)
    name = Path(url.split("?")[0]).name or "download"
    tmp = inbox() / ("." + name + ".download")
    log(f"Baixando {url}…")
    req = urllib.request.Request(url, headers={"User-Agent": "calendario-focos-admin"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as dst:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(8 << 20):
            dst.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total * 60, f"Baixando ({done / 1e6:.0f} de {total / 1e6:.0f} MB)")
    final = tmp.with_name(name)
    tmp.replace(final)
    try:
        return from_path(final, "link", log, nome=name, nota=url)
    finally:
        final.unlink(missing_ok=True)


def from_files(named_streams: list[tuple[str, object]], origem: str, nome: str, log: Callable[[str], None] = print) -> dict:
    """Uploaded CSVs (already filtered by name) as one delivery."""
    m, d = _new(nome, origem)
    for name, stream in named_streams:
        _add_file(m, d, name, stream)
    return _finish(m, d, log)


def set_active(eid: str, active: bool) -> None:
    m = load(eid)
    m["ativa"] = active
    if active:
        m["substituida_por"] = None
    _write(m)


def set_note(eid: str, nota: str) -> None:
    m = load(eid)
    m["nota"] = nota[:300]
    _write(m)


def delete(eid: str) -> None:
    d = root() / Path(eid).name
    if (d / "manifest.json").exists():
        shutil.rmtree(d)


def active_files() -> tuple[list[Path], list[Path], list[dict]]:
    used = [m for m in all_entregas() if m["ativa"]]
    brutos = [root() / m["id"] / a["nome"] for m in used for a in m["arquivos"] if a["tipo"] == "brutos"]
    mensais = [root() / m["id"] / a["nome"] for m in used for a in m["arquivos"] if a["tipo"] == "mensais"]
    return brutos, mensais, used


def inspect_all(log: Callable[[str], None] = print, progress: Callable[[float, str], None] = lambda p, s: None) -> None:
    """Fill in quick stats (rows, period, satellites, columns) for files not inspected yet."""
    todo = [(m, a) for m in all_entregas() for a in m["arquivos"] if not a.get("stats")]
    con = duckdb.connect()
    for k, (m, a) in enumerate(todo):
        progress(5 + 90 * k / max(len(todo), 1), f"Conferindo {a['nome']}")
        log(f"Conferindo {m['nome']} / {a['nome']} ({a['tamanho'] / 1e6:.0f} MB)…")
        src = f"read_csv('{(root() / m['id'] / a['nome']).as_posix()}', header=true)"
        info: dict = {}
        try:
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
            if a["tipo"] == "brutos":
                info["faltando"] = [c for c in prepare.REQUIRED if c not in cols]
                info["extras"] = [c for c in prepare.OPTIONAL if c in cols]
                if not info["faltando"]:
                    r = con.execute(f"""SELECT COUNT(*), MIN(data_hora_gmt), MAX(data_hora_gmt), list(DISTINCT upper(satelite)),
                                           COUNT(DISTINCT pais) FROM {src}""").fetchone()
                    info.update(linhas=r[0], inicio=str(r[1])[:10], fim=str(r[2])[:10], satelites=sorted(r[3]), paises=r[4])
            else:
                r = con.execute(f"SELECT COUNT(*), MIN(ano*100+mes), MAX(ano*100+mes), SUM(nfocos) FROM {src}").fetchone()
                info.update(linhas=r[0], inicio=f"{r[1] // 100}-{r[1] % 100:02d}", fim=f"{r[2] // 100}-{r[2] % 100:02d}", total=int(r[3] or 0))
        except Exception as e:  # noqa: BLE001
            info["erro"] = str(e).splitlines()[0][:200]
        fresh = load(m["id"])
        for f in fresh["arquivos"]:
            if f["nome"] == a["nome"]:
                f["stats"] = info
        _write(fresh)
    log("Entregas conferidas.")


def migrate_raw(raw: Path, log: Callable[[str], None] = print) -> None:
    """One-off: turn loose CSVs in data/raw (old layout) into deliveries. Files are moved, not copied."""
    if not raw.exists() or all_entregas():
        return
    csvs = [p for p in raw.iterdir() if p.is_file() and ALLOWED_CSV.match(p.name.removesuffix(".off"))]
    groups: dict[str, list[Path]] = {}
    for p in csvs:
        key = "FIRMS " + p.stem.split("firms_")[-1] if "firms" in p.name else "Entrega inicial do time de dados"
        groups.setdefault(key, []).append(p)
    for nome, files in sorted(groups.items(), key=lambda kv: "firms" in kv[0].lower()):
        m, d = _new(nome, "firms" if nome.startswith("FIRMS") else "migrado", "Migrada da pasta data/raw")
        for p in files:
            name = p.name.removesuffix(".off")
            p.rename(d / name)
            m["arquivos"].append({"nome": name, "tipo": "brutos" if "brutos" in name else "mensais", "tamanho": (d / name).stat().st_size, "stats": None})
        m["ativa"] = not any(p.name.endswith(".off") for p in files)
        _write(m)
        log(f"Migrada: {nome}")
        time.sleep(1.1)  # distinct ids / ordering
