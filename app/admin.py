"""/admin: guided data update — bring new data, check it, process, apply to the dashboard, publish online.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Access: user + password login (ADMIN_USER / ADMIN_PASSWORD from the environment or .env); disabled without them.
The page is not linked from the public UI. The page itself (HTML/JS) lives in admin_page.py; this module is the
JSON API it calls. Processing builds a *candidate* in data/processed_next; "Aplicar" swaps it in (the old version is
kept in data/processed_prev for "Voltar à versão anterior").
"""
from __future__ import annotations

import html
import json
import math
import re
import secrets
import shutil
import tarfile
import threading
import time
import zipfile
from collections import deque
from datetime import date, timedelta
from pathlib import Path

import duckdb
from flask import Blueprint, Response, abort, jsonify, redirect, request, session

from . import config
from .admin_page import page_html, shell
from .pipeline import firms, prepare, publish

ALLOWED_CSV = re.compile(r"^focos_(brutos|mensais)[\w.\-]*\.csv$", re.I)
ARCHIVE = re.compile(r"\.(tar\.gz|tgz|tar|zip)$", re.I)
OFF = ".off"  # a file renamed to *.csv.off is kept but not used


class Jobs:
    """One background job at a time, with a rolling log and a progress estimate."""

    def __init__(self):
        self.lock = threading.Lock()
        self.log: deque[str] = deque(maxlen=400)
        self.state = {"running": False, "kind": None, "started": None, "finished": None, "ok": None, "error": None, "pct": 0, "stage": ""}

    def add(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def progress(self, pct: float, stage: str) -> None:
        self.state.update(pct=round(pct), stage=stage)

    def start(self, kind: str, fn) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update(running=True, kind=kind, started=time.time(), finished=None, ok=None, error=None, pct=0, stage="Iniciando")
        self.log.clear()

        def target():
            try:
                fn(self)
                self.state.update(ok=True, pct=100)
            except Exception as e:  # noqa: BLE001 - shown on the admin page
                self.add(f"ERRO: {e}")
                self.state.update(ok=False, error=str(e))
            finally:
                self.state.update(running=False, finished=time.time())
        threading.Thread(target=target, daemon=True).start()
        return True


def read_meta(d: Path) -> dict | None:
    p = d / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def diff(old: dict | None, new: dict) -> dict:
    o_av, n_av = set((old or {}).get("avisos", [])), set(new.get("avisos", []))
    return {"delta_focos": new["total_focos"] - (old or {}).get("total_focos", 0),
            "novos_avisos": sorted(n_av - o_av), "avisos_resolvidos": sorted(o_av - n_av),
            "novas_colunas": sorted(set(new.get("colunas_extras", [])) - set((old or {}).get("colunas_extras", []))),
            "novos_satelites": sorted(set(new.get("satelites", [])) - set((old or {}).get("satelites", [])))}


PREP_STAGES = [("lendo", 5, "Lendo os arquivos"), ("focos_outros", 40, "Outros países gravados"), ("Argentina:", 45, "Atribuindo províncias e departamentos"),
               ("focos_arg", 70, "Argentina gravada"), ("agg_", 75, "Agregados mensais"), ("dia_", 82, "Agregados diários"),
               ("cell_", 90, "Grades do mapa"), ("meta.json", 98, "Conferindo a qualidade")]
FIRMS_LINE = re.compile(r"^\S+\s+\d{4}-\d{2}-\d{2} \+\d+d")


def create_blueprint(get_repo) -> Blueprint:
    bp = Blueprint("admin", __name__)
    jobs = Jobs()
    raw: Path = config.RAW_DIR
    nxt, prev = config.DATA_DIR / "processed_next", config.DATA_DIR / "processed_prev"
    stats_path = raw / ".stats.json"

    # ---------------------------------------------------------------- access
    def configured() -> bool:
        return bool(config.ADMIN_USER and config.ADMIN_PASSWORD)

    def allowed() -> bool:
        return configured() and session.get("admin") is True

    def csrf() -> str:
        session.setdefault("csrf", secrets.token_hex(16))
        return session["csrf"]

    def guard():
        if not allowed():
            abort(403)
        tok = request.headers.get("X-CSRF") or request.form.get("csrf")
        if not tok or tok != session.get("csrf"):
            abort(400, "Sessão expirada. Recarregue a página.")

    # ---------------------------------------------------------------- raw files + quick stats
    def load_stats() -> dict:
        try:
            return json.loads(stats_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def files() -> list[dict]:
        st = load_stats()
        out = []
        for p in sorted(raw.glob("focos_*.csv*")) if raw.exists() else []:
            if not (p.name.endswith(".csv") or p.name.endswith(".csv" + OFF)):
                continue
            base = p.name[:-len(OFF)] if p.name.endswith(OFF) else p.name
            s = p.stat()
            cached = st.get(base)
            fresh = cached if cached and cached.get("size") == s.st_size and cached.get("mtime") == int(s.st_mtime) else None
            out.append({"name": base, "active": not p.name.endswith(OFF), "size": s.st_size, "mtime": int(s.st_mtime),
                        "tipo": "brutos" if "brutos" in base else "mensais", "stats": fresh})
        return out

    def inspect(job: Jobs) -> None:
        st = load_stats()
        todo = [f for f in files() if not f["stats"]]
        con = duckdb.connect()
        for k, f in enumerate(todo):
            job.progress(5 + 90 * k / max(len(todo), 1), f"Conferindo {f['name']}")
            path = raw / (f["name"] if f["active"] else f["name"] + OFF)
            job.add(f"Conferindo {f['name']} ({f['size'] / 1e6:.0f} MB)…")
            src = f"read_csv('{path.as_posix()}', header=true)"
            info = {"size": f["size"], "mtime": f["mtime"]}
            try:
                cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
                if f["tipo"] == "brutos":
                    miss = [c for c in prepare.REQUIRED if c not in cols]
                    info["faltando"] = miss
                    info["extras"] = [c for c in prepare.OPTIONAL if c in cols]
                    if not miss:
                        r = con.execute(f"""SELECT COUNT(*), MIN(data_hora_gmt), MAX(data_hora_gmt), list(DISTINCT upper(satelite) ORDER BY 1),
                                               COUNT(DISTINCT pais) FROM {src}""").fetchone()
                        info.update(linhas=r[0], inicio=str(r[1])[:10], fim=str(r[2])[:10], satelites=sorted(r[3]), paises=r[4])
                else:
                    r = con.execute(f"SELECT COUNT(*), MIN(ano*100+mes), MAX(ano*100+mes), SUM(nfocos) FROM {src}").fetchone()
                    info.update(linhas=r[0], inicio=f"{r[1] // 100}-{r[1] % 100:02d}", fim=f"{r[2] // 100}-{r[2] % 100:02d}", total=int(r[3] or 0))
            except Exception as e:  # noqa: BLE001
                info["erro"] = str(e).splitlines()[0][:200]
            st[f["name"]] = info
            stats_path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        job.add("Arquivos conferidos.")

    # ---------------------------------------------------------------- jobs
    def process(job: Jobs) -> None:
        shutil.rmtree(nxt, ignore_errors=True)

        def log(m: str):
            job.add(m)
            for key, pct, stage in PREP_STAGES:
                if key in m:
                    job.progress(pct, stage)
        meta = prepare.run(raw, nxt, config.GEO_DIR, log=log)
        job.add(f"Nova versão pronta: {meta['total_focos']:,} focos, {meta['inicio'][:10]} a {meta['fim'][:10]}. Confira e clique em Aplicar.".replace(",", "."))

    def pull_firms(start: date, end: date, then_process: bool):
        def run(job: Jobs) -> None:
            total = 4 * math.ceil(((end - start).days + 1) / firms.MAX_DAYS)
            done = [0]

            def log(m: str):
                job.add(m)
                if FIRMS_LINE.match(m):
                    done[0] += 1
                    job.progress(min(95, done[0] / total * (60 if then_process else 95)), f"Baixando do FIRMS ({done[0]}/{total})")
            path = firms.run(start, end, raw, config.FIRMS_MAP_KEY, config.GEO_DIR, log=log)
            if path and then_process:
                job.add("Processando com os focos novos…")
                base = job.progress

                def scaled(p, s):
                    base(60 + p * 0.4, s)
                job.progress = scaled
                try:
                    process(job)
                finally:
                    job.progress = base
        return run

    def do_publish(job: Jobs) -> None:
        publish.publish(job.add, job.progress)

    # ---------------------------------------------------------------- pages
    @bp.route("/admin", methods=["GET"])
    def page():
        if not configured():
            return Response(shell("Admin desativado", "<main class=narrow><section><h2>Admin desativado</h2><p>Defina ADMIN_USER e ADMIN_PASSWORD no servidor.</p></section></main>"),
                            403, mimetype="text/html")
        if not allowed():
            return Response(login_html(csrf(), request.args.get("erro")), mimetype="text/html")
        return Response(page_html(csrf()), mimetype="text/html")

    @bp.route("/admin/login", methods=["POST"])
    def login():
        if request.form.get("csrf") != session.get("csrf"):
            abort(400)
        ok_user = secrets.compare_digest(request.form.get("usuario", ""), config.ADMIN_USER)
        ok_pass = secrets.compare_digest(request.form.get("senha", ""), config.ADMIN_PASSWORD)
        if configured() and ok_user and ok_pass:
            session.clear()
            session["admin"] = True
            return redirect("/admin")
        time.sleep(1)  # slow down guessing
        return redirect("/admin?erro=1")

    @bp.route("/admin/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect("/admin")

    # ---------------------------------------------------------------- API
    @bp.route("/admin/api/state")
    def state():
        if not allowed():
            abort(403)
        live, cand, old = read_meta(config.PROCESSED_DIR), read_meta(nxt), read_meta(prev)
        last = date.fromisoformat(live["fim"][:10]) if live else date(date.today().year, 1, 1) - timedelta(days=1)
        ok_pub, why = publish.availability()
        return jsonify(
            mode="online" if config.ON_SPACE else "local",
            live=live, candidate=cand, candidate_diff=diff(live, cand) if cand else None, prev=old,
            files=files(), job={**jobs.state, "log": list(jobs.log)[-200:]},
            firms={"key": bool(config.FIRMS_MAP_KEY), "start": min(last + timedelta(days=1), date.today()).isoformat(), "end": date.today().isoformat()},
            publish={"available": ok_pub, "reason": why, "space": config.HF_SPACE, "site": config.SITE_URL, "history": publish.history()[:5]},
        )

    def busy():
        return jsonify(ok=False, msg="Já existe uma tarefa em andamento."), 409

    @bp.route("/admin/upload", methods=["POST"])
    def upload():
        guard()
        if jobs.state["running"]:
            return busy()
        raw.mkdir(parents=True, exist_ok=True)
        saved, skipped = [], []
        for f in request.files.getlist("arquivos"):
            name = Path(f.filename or "").name
            if ALLOWED_CSV.match(name):
                tmp = raw / (name + ".part")
                f.save(tmp)
                tmp.replace(raw / name)
                (raw / (name + OFF)).unlink(missing_ok=True)
                saved.append(name)
            elif ARCHIVE.search(name):
                tmp = config.DATA_DIR / "upload.tmp"
                f.save(tmp)
                s, k = extract(tmp, name)
                tmp.unlink(missing_ok=True)
                saved += s
                skipped += k
            elif name:
                skipped.append(name)
        if request.headers.get("X-CSRF"):
            return jsonify(ok=bool(saved), saved=saved, skipped=skipped)
        return redirect("/admin")

    def extract(path: Path, name: str):
        saved, skipped = [], []

        def write(src, base):
            with open(raw / (base + ".part"), "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            (raw / (base + ".part")).replace(raw / base)
            (raw / (base + OFF)).unlink(missing_ok=True)
            saved.append(base)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    base = Path(info.filename).name
                    if info.is_dir():
                        continue
                    if ALLOWED_CSV.match(base):
                        with z.open(info) as src:
                            write(src, base)
                    else:
                        skipped.append(base)
        else:
            with tarfile.open(path, "r:*") as t:
                for m in t:
                    base = Path(m.name).name
                    if not m.isfile():
                        continue
                    if ALLOWED_CSV.match(base):
                        write(t.extractfile(m), base)
                    else:
                        skipped.append(base)
        return saved, skipped

    @bp.route("/admin/api/<action>", methods=["POST"])
    def action(action):
        guard()
        body = request.get_json(silent=True) or {}
        if action in ("toggle", "delete"):
            if jobs.state["running"]:
                return busy()
            name = Path(body.get("name", "")).name
            if not ALLOWED_CSV.match(name):
                abort(400)
            on, off = raw / name, raw / (name + OFF)
            cur = on if on.exists() else off if off.exists() else None
            if cur is None:
                abort(404)
            if action == "delete":
                cur.unlink()
            else:
                cur.rename(off if cur == on else on)
            return jsonify(ok=True)
        if action == "inspect":
            return jsonify(ok=jobs.start("conferir", inspect)) if not jobs.state["running"] else busy()
        if action == "process":
            if not any(f["active"] and f["tipo"] == "brutos" for f in files()):
                return jsonify(ok=False, msg="Nenhum arquivo focos_brutos ativo."), 400
            return jsonify(ok=jobs.start("processar", process)) if not jobs.state["running"] else busy()
        if action == "firms":
            try:
                start, end = date.fromisoformat(body["start"]), date.fromisoformat(body["end"])
            except (KeyError, ValueError):
                return jsonify(ok=False, msg="Datas inválidas."), 400
            if end < start:
                return jsonify(ok=False, msg="A data final é anterior à inicial."), 400
            if not config.FIRMS_MAP_KEY:
                return jsonify(ok=False, msg="Defina FIRMS_MAP_KEY no servidor."), 400
            return jsonify(ok=jobs.start("firms", pull_firms(start, end, bool(body.get("process"))))) if not jobs.state["running"] else busy()
        if action == "apply":
            if jobs.state["running"] or not read_meta(nxt):
                return jsonify(ok=False, msg="Não há versão nova para aplicar."), 400
            shutil.rmtree(prev, ignore_errors=True)
            if config.PROCESSED_DIR.exists():
                config.PROCESSED_DIR.rename(prev)
            nxt.rename(config.PROCESSED_DIR)
            get_repo().reload()
            return jsonify(ok=True)
        if action == "discard":
            shutil.rmtree(nxt, ignore_errors=True)
            return jsonify(ok=True)
        if action == "rollback":
            if jobs.state["running"] or not read_meta(prev):
                return jsonify(ok=False, msg="Não há versão anterior."), 400
            tmp = config.DATA_DIR / "processed_swap"
            shutil.rmtree(tmp, ignore_errors=True)
            config.PROCESSED_DIR.rename(tmp)
            prev.rename(config.PROCESSED_DIR)
            tmp.rename(prev)
            get_repo().reload()
            return jsonify(ok=True)
        if action == "publish":
            ok, why = publish.availability()
            if not ok:
                return jsonify(ok=False, msg=why), 400
            return jsonify(ok=jobs.start("publicar", do_publish)) if not jobs.state["running"] else busy()
        abort(404)

    return bp


def login_html(tok: str, erro=None) -> str:
    msg = "<p class=warn>Usuário ou senha incorretos.</p>" if erro else ""
    return shell("Admin", f"""<main class=narrow><section><h2>Entrar no admin</h2>{msg}
<form method=post action=/admin/login class=login><input type=hidden name=csrf value={html.escape(tok)}>
<label>Usuário <input name=usuario autocomplete=username autofocus required></label>
<label>Senha <input type=password name=senha autocomplete=current-password required></label>
<button class=primary>Entrar</button></form></section></main>""")
