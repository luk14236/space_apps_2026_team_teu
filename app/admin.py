"""/admin: receive data deliveries (kept as versions), process them, apply to the dashboard and publish online.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Access: user + password login (ADMIN_USER / ADMIN_PASSWORD from the environment or .env); disabled without them.
The page is not linked from the public UI. HTML/JS lives in admin_page.py; this module is the JSON API.

Flow: deliveries (app/pipeline/entregas.py) -> process the active ones into data/processed_next (candidate) ->
"Aplicar" swaps it into data/processed (previous kept in data/processed_prev) -> "Publicar" sends it online.
Every applied version is logged in data/versoes.json.
"""
from __future__ import annotations

import html
import json
import math
import re
import secrets
import shutil
import threading
import time
from collections import deque
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, redirect, request, session

from . import config
from .i18n import tr
from .admin_page import page_html, shell
from .pipeline import entregas, firms, prepare, publish


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
            "novos_avisos": sorted(n_av - o_av), "avisos_resolvidos": sorted(o_av - n_av)}


PREP_STAGES = [("lendo", 5, "Lendo os arquivos"), ("focos_outros", 40, "Outros países gravados"), ("Argentina:", 45, "Atribuindo províncias e departamentos"),
               ("focos_arg", 70, "Argentina gravada"), ("agg_", 75, "Agregados mensais"), ("dia_", 82, "Agregados diários"),
               ("cell_", 90, "Grades do mapa"), ("meta.json", 98, "Conferindo a qualidade")]
FIRMS_LINE = re.compile(r"^\S+\s+\d{4}-\d{2}-\d{2} \+\d+d")


def create_blueprint(get_repo) -> Blueprint:
    bp = Blueprint("admin", __name__)
    jobs = Jobs()
    nxt, prev = config.DATA_DIR / "processed_next", config.DATA_DIR / "processed_prev"
    versions_path = config.DATA_DIR / "versoes.json"

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
            abort(400, tr("Sessão expirada. Recarregue a página."))

    # ---------------------------------------------------------------- versions log
    def versions() -> list[dict]:
        try:
            return json.loads(versions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def log_version(meta: dict, acao: str) -> None:
        entry = {"quando": time.strftime("%Y-%m-%d %H:%M"), "acao": acao, "total_focos": meta["total_focos"],
                 "inicio": meta["inicio"][:10], "fim": meta["fim"][:10], "processado_em": meta["gerado_em"],
                 "entregas": [e["nome"] for e in meta.get("entregas", [])] or meta.get("fonte", [])}
        versions_path.write_text(json.dumps([entry] + versions()[:49], ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- jobs
    def after_receive(job: Jobs, then_process: bool) -> None:
        entregas.inspect_all(job.add, lambda p, s: job.progress(60 + p * 0.1 if then_process else 50 + p * 0.5, s))
        if then_process:
            job.add("Processando com a entrega nova…")
            process(job, base=70, span=30)

    def process(job: Jobs, base: float = 0, span: float = 100) -> None:
        brutos, mensais, used = entregas.active_files()
        if not brutos:
            raise ValueError("Nenhuma entrega ativa com focos_brutos.")
        shutil.rmtree(nxt, ignore_errors=True)

        def log(m: str):
            job.add(m)
            for key, pct, stage in PREP_STAGES:
                if key in m:
                    job.progress(base + pct * span / 100, stage)
        job.add("Entregas usadas: " + "; ".join(e["nome"] for e in used))
        meta = prepare.run(None, nxt, config.GEO_DIR, log=log, files=(brutos, mensais), entregas=used)
        job.add(f"Versão nova pronta: {meta['total_focos']:,} focos, {meta['inicio'][:10]} a {meta['fim'][:10]}. Confira e clique em Aplicar.".replace(",", "."))

    def import_inbox(name: str, then_process: bool):
        def run(job: Jobs) -> None:
            path = entregas.inbox() / Path(name).name
            if not path.exists():
                raise ValueError(f"{name} não está mais na pasta de entrada.")
            job.progress(5, f"Importando {name}")
            entregas.from_path(path, "pasta", job.add)
            path.unlink()
            job.add(f"{name} removido da pasta de entrada (o conteúdo está guardado na entrega).")
            after_receive(job, then_process)
        return run

    def import_url(url: str, then_process: bool):
        def run(job: Jobs) -> None:
            entregas.from_url(url, job.add, job.progress)
            after_receive(job, then_process)
        return run

    def pull_firms(start: date, end: date, then_process: bool):
        def run(job: Jobs) -> None:
            total = 4 * math.ceil(((end - start).days + 1) / firms.MAX_DAYS)
            done = [0]

            def log(m: str):
                job.add(m)
                if FIRMS_LINE.match(m):
                    done[0] += 1
                    job.progress(min(55, done[0] / total * 55), f"Baixando do FIRMS ({done[0]}/{total})")
            tmp = config.DATA_DIR / "firms_tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            path = firms.run(start, end, tmp, config.FIRMS_MAP_KEY, config.GEO_DIR, log=log)
            if path:
                entregas.from_path(path, "firms", job.add, nome=f"FIRMS {start:%d/%m/%Y} a {end:%d/%m/%Y}")
            shutil.rmtree(tmp, ignore_errors=True)
            if path:
                after_receive(job, then_process)
        return run

    # ---------------------------------------------------------------- pages
    @bp.route("/admin", methods=["GET"])
    def page():
        if not configured():
            return Response(shell(tr("Admin desativado"), f"<main class=narrow><section><h2>{tr('Admin desativado')}</h2><p>{tr('Defina ADMIN_USER e ADMIN_PASSWORD no servidor.')}</p></section></main>"),
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
        entregas.migrate_raw(config.RAW_DIR, log=lambda m: None)  # old data/raw layout -> deliveries (one-off, on first admin use)
        live, cand, old = read_meta(config.PROCESSED_DIR), read_meta(nxt), read_meta(prev)
        last = date.fromisoformat(live["fim"][:10]) if live else date(date.today().year, 1, 1) - timedelta(days=1)
        ok_pub, why = publish.availability()
        return jsonify(
            mode="online" if config.ON_SPACE else "local",
            live=live, candidate=cand, candidate_diff=diff(live, cand) if cand else None, prev=old,
            entregas=entregas.all_entregas(), inbox=entregas.inbox_files(), inbox_path=str(entregas.inbox()),
            versions=versions()[:10], job={**jobs.state, "stage": tr_stage(jobs.state.get("stage") or ""), "log": list(jobs.log)[-200:]},
            firms={"key": bool(config.FIRMS_MAP_KEY), "start": min(last + timedelta(days=1), date.today()).isoformat(), "end": date.today().isoformat()},
            publish={"available": ok_pub, "reason": tr(why) if why else why, "space": config.HF_SPACE, "site": config.SITE_URL, "history": publish.history()[:5]},
        )

    def busy():
        return jsonify(ok=False, msg=tr("Já existe uma tarefa em andamento.")), 409

    @bp.route("/admin/upload", methods=["POST"])
    def upload():
        """Browser upload: archives become one delivery each; loose CSVs sent together become one delivery."""
        guard()
        if jobs.state["running"]:
            return busy()
        files = request.files.getlist("arquivos")
        csvs = [(Path(f.filename).name, f.stream) for f in files if entregas.ALLOWED_CSV.match(Path(f.filename or "").name)]
        archives = [f for f in files if entregas.ARCHIVE.search(Path(f.filename or "").name)]
        skipped = [Path(f.filename or "").name for f in files if f not in archives and not entregas.ALLOWED_CSV.match(Path(f.filename or "").name)]
        created, msgs = [], []
        try:
            if csvs:
                created.append(entregas.from_files(csvs, "upload", request.form.get("nome") or csvs[0][0], msgs.append)["nome"])
            for f in archives:
                entregas.inbox().mkdir(parents=True, exist_ok=True)
                tmp = entregas.inbox() / ("." + Path(f.filename).name + ".upload")
                f.save(tmp)
                final = tmp.with_name(Path(f.filename).name)
                tmp.replace(final)
                try:
                    created.append(entregas.from_path(final, "upload", msgs.append)["nome"])
                finally:
                    final.unlink(missing_ok=True)
        except ValueError as e:
            return jsonify(ok=False, msg=str(e), skipped=skipped), 400
        if created and request.form.get("processar"):
            jobs.start("receber", lambda job: after_receive(job, True))
        elif created:
            jobs.start("conferir", lambda job: after_receive(job, False))
        return jsonify(ok=bool(created), created=created, skipped=skipped, log=msgs)

    @bp.route("/admin/api/<action>", methods=["POST"])
    def action(action):
        guard()
        body = request.get_json(silent=True) or {}
        running = jobs.state["running"]
        eid = Path(str(body.get("id", ""))).name
        if action in ("toggle", "delete", "note"):
            if running:
                return busy()
            if not (entregas.root() / eid / "manifest.json").exists():
                abort(404)
            if action == "toggle":
                entregas.set_active(eid, not entregas.load(eid)["ativa"])
            elif action == "delete":
                entregas.delete(eid)
            else:
                entregas.set_note(eid, str(body.get("nota", "")))
            return jsonify(ok=True)
        if running:
            return busy()
        if action == "import_inbox":
            return jsonify(ok=jobs.start("importar", import_inbox(str(body.get("name", "")), bool(body.get("process")))))
        if action == "import_url":
            url = str(body.get("url", "")).strip()
            if not re.match(r"^https?://", url):
                return jsonify(ok=False, msg=tr("Cole um link que comece com http:// ou https://.")), 400
            return jsonify(ok=jobs.start("link", import_url(url, bool(body.get("process")))))
        if action == "inspect":
            return jsonify(ok=jobs.start("conferir", lambda job: entregas.inspect_all(job.add, job.progress)))
        if action == "process":
            if not entregas.active_files()[0]:
                return jsonify(ok=False, msg=tr("Nenhuma entrega ativa com focos_brutos.")), 400
            return jsonify(ok=jobs.start("processar", process))
        if action == "firms":
            try:
                start, end = date.fromisoformat(body["start"]), date.fromisoformat(body["end"])
            except (KeyError, ValueError):
                return jsonify(ok=False, msg=tr("Datas inválidas.")), 400
            if end < start:
                return jsonify(ok=False, msg=tr("A data final é anterior à inicial.")), 400
            if not config.FIRMS_MAP_KEY:
                return jsonify(ok=False, msg=tr("Defina FIRMS_MAP_KEY no servidor.")), 400
            return jsonify(ok=jobs.start("firms", pull_firms(start, end, bool(body.get("process")))))
        if action == "apply":
            meta = read_meta(nxt)
            if not meta:
                return jsonify(ok=False, msg=tr("Não há versão nova para aplicar.")), 400
            shutil.rmtree(prev, ignore_errors=True)
            if config.PROCESSED_DIR.exists():
                config.PROCESSED_DIR.rename(prev)
            nxt.rename(config.PROCESSED_DIR)
            get_repo().reload()
            log_version(meta, "aplicada")
            return jsonify(ok=True)
        if action == "discard":
            shutil.rmtree(nxt, ignore_errors=True)
            return jsonify(ok=True)
        if action == "rollback":
            meta = read_meta(prev)
            if not meta:
                return jsonify(ok=False, msg=tr("Não há versão anterior.")), 400
            tmp = config.DATA_DIR / "processed_swap"
            shutil.rmtree(tmp, ignore_errors=True)
            config.PROCESSED_DIR.rename(tmp)
            prev.rename(config.PROCESSED_DIR)
            tmp.rename(prev)
            get_repo().reload()
            log_version(meta, "restaurada")
            return jsonify(ok=True)
        if action == "publish":
            ok, why = publish.availability()
            if not ok:
                return jsonify(ok=False, msg=why), 400
            return jsonify(ok=jobs.start("publicar", lambda job: publish.publish(job.add, job.progress)))
        abort(404)

    return bp


def tr_stage(stage: str) -> str:
    """Job stages are written in Portuguese by the background thread; translate them when the page asks."""
    for pre in ("Importando ", "Baixando do FIRMS "):
        if stage.startswith(pre):
            return tr(pre.strip()) + " " + stage[len(pre):]
    return tr(stage) if stage else stage


def login_html(tok: str, erro=None) -> str:
    from .admin_page import lang_switch
    msg = f"<p class=warn>{tr('Usuário ou senha incorretos.')}</p>" if erro else ""
    return shell("Admin", f"""<main class=narrow><section><div class=sh><h2>{tr("Entrar no admin")}</h2>{lang_switch("/admin")}</div>{msg}
<form method=post action=/admin/login class=login><input type=hidden name=csrf value={html.escape(tok)}>
<label>{tr("Usuário")} <input name=usuario autocomplete=username autofocus required></label>
<label>{tr("Senha")} <input type=password name=senha autocomplete=current-password required></label>
<button class=primary>{tr("Entrar")}</button></form></section></main>""")
