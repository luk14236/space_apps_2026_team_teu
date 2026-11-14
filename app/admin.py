"""/admin: upload deliveries, pull recent days from FIRMS, rebuild the processed data and swap it in.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Access: user + password login (ADMIN_USER / ADMIN_PASSWORD, read from the environment or .env).
Without them the admin is disabled. The page is not linked from the public UI.
"""
from __future__ import annotations

import html
import json
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

from flask import Blueprint, Response, abort, jsonify, redirect, request, session

from . import config
from .pipeline import firms, prepare

ALLOWED_CSV = re.compile(r"^focos_(brutos|mensais)[\w.\-]*\.csv$", re.I)
ARCHIVE = re.compile(r"\.(tar\.gz|tgz|tar|zip)$", re.I)


class Jobs:
    """One background job at a time (processing or FIRMS download), with a rolling log."""

    def __init__(self):
        self.lock = threading.Lock()
        self.log: deque[str] = deque(maxlen=400)
        self.state = {"running": False, "kind": None, "started": None, "finished": None, "ok": None, "error": None}

    def add(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def start(self, kind: str, fn) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update(running=True, kind=kind, started=time.time(), finished=None, ok=None, error=None)
        self.log.clear()

        def target():
            try:
                fn(self.add)
                self.state.update(ok=True)
            except Exception as e:  # noqa: BLE001 - reported to the admin page
                self.add(f"ERRO: {e}")
                self.state.update(ok=False, error=str(e))
            finally:
                self.state.update(running=False, finished=time.time())
        threading.Thread(target=target, daemon=True).start()
        return True


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def create_blueprint(get_repo) -> Blueprint:
    bp = Blueprint("admin", __name__)
    jobs = Jobs()
    raw: Path = config.RAW_DIR

    # ---------------------------------------------------------------- access
    def configured() -> bool:
        return bool(config.ADMIN_USER and config.ADMIN_PASSWORD)

    def allowed() -> bool:
        return configured() and session.get("admin") is True

    def guard():
        if not allowed():
            abort(403)
        if request.method == "POST" and request.form.get("csrf") != session.get("csrf"):
            abort(400, "Formulário expirado. Recarregue a página.")

    def csrf() -> str:
        session.setdefault("csrf", secrets.token_hex(16))
        return session["csrf"]

    # ---------------------------------------------------------------- jobs
    def rebuild(log) -> None:
        nxt, cur, old = config.DATA_DIR / "processed_next", config.PROCESSED_DIR, config.DATA_DIR / "processed_old"
        shutil.rmtree(nxt, ignore_errors=True)
        meta = prepare.run(raw, nxt, config.GEO_DIR, log=log)
        shutil.rmtree(old, ignore_errors=True)
        if cur.exists():
            cur.rename(old)
        nxt.rename(cur)
        get_repo().reload()
        shutil.rmtree(old, ignore_errors=True)
        log(f"Dados atualizados: {meta['total_focos']:,} focos, {meta['inicio'][:10]} a {meta['fim'][:10]}. O painel já usa a nova versão.")

    def pull_firms(start: date, end: date, then_rebuild: bool):
        def job(log):
            path = firms.run(start, end, raw, config.FIRMS_MAP_KEY, config.GEO_DIR, log=log)
            if path and then_rebuild:
                log("Reprocessando com os focos novos…")
                rebuild(log)
        return job

    # ---------------------------------------------------------------- routes
    @bp.route("/admin", methods=["GET"])
    def page():
        if not allowed():
            if configured():
                return Response(render_login(csrf(), request.args.get("erro")), mimetype="text/html")
            return Response(render_message("Admin desativado", "Defina ADMIN_USER e ADMIN_PASSWORD no servidor (variáveis de ambiente ou arquivo .env)."), 403, mimetype="text/html")
        return Response(render_page(), mimetype="text/html")

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
        session.pop("admin", None)
        return redirect("/admin")

    @bp.route("/admin/upload", methods=["POST"])
    def upload():
        guard()
        if jobs.state["running"]:
            return redirect("/admin?msg=" + "Aguarde a tarefa em andamento terminar.")
        raw.mkdir(parents=True, exist_ok=True)
        saved, skipped = [], []
        for f in request.files.getlist("arquivos"):
            name = Path(f.filename or "").name
            if ALLOWED_CSV.match(name):
                tmp = raw / (name + ".part")
                f.save(tmp)
                tmp.replace(raw / name)
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
        msg = (f"Recebido: {', '.join(saved)}." if saved else "Nenhum arquivo aceito.") + \
              (f" Ignorado: {', '.join(skipped)} (só focos_brutos*.csv e focos_mensais*.csv)." if skipped else "")
        if saved and request.form.get("processar"):
            jobs.start("processar", rebuild)
            msg += " Processamento iniciado."
        return redirect("/admin?msg=" + msg)

    def extract(path: Path, name: str):
        saved, skipped = [], []
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    base = Path(info.filename).name
                    if not info.is_dir() and ALLOWED_CSV.match(base):
                        with z.open(info) as src, open(raw / (base + ".part"), "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        (raw / (base + ".part")).replace(raw / base)
                        saved.append(base)
                    elif not info.is_dir():
                        skipped.append(base)
        else:
            with tarfile.open(path, "r:*") as t:
                for m in t:
                    base = Path(m.name).name
                    if m.isfile() and ALLOWED_CSV.match(base):
                        src = t.extractfile(m)
                        with open(raw / (base + ".part"), "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        (raw / (base + ".part")).replace(raw / base)
                        saved.append(base)
                    elif m.isfile():
                        skipped.append(base)
        return saved, skipped

    @bp.route("/admin/delete", methods=["POST"])
    def delete():
        guard()
        name = Path(request.form.get("nome", "")).name
        target = raw / name
        if ALLOWED_CSV.match(name) and target.exists() and not jobs.state["running"]:
            target.unlink()
            return redirect("/admin?msg=" + f"{name} removido. Reprocesse para aplicar.")
        return redirect("/admin?msg=Não foi possível remover.")

    @bp.route("/admin/process", methods=["POST"])
    def process():
        guard()
        ok = jobs.start("processar", rebuild)
        return redirect("/admin?msg=" + ("Processamento iniciado." if ok else "Já existe uma tarefa em andamento."))

    @bp.route("/admin/firms", methods=["POST"])
    def firms_route():
        guard()
        try:
            start = date.fromisoformat(request.form["inicio"])
            end = date.fromisoformat(request.form["fim"])
        except (KeyError, ValueError):
            return redirect("/admin?msg=Datas inválidas.")
        if end < start:
            return redirect("/admin?msg=A data final é anterior à inicial.")
        ok = jobs.start("firms", pull_firms(start, end, bool(request.form.get("processar"))))
        return redirect("/admin?msg=" + ("Download do FIRMS iniciado." if ok else "Já existe uma tarefa em andamento."))

    @bp.route("/admin/status")
    def status():
        if not allowed():
            abort(403)
        return jsonify(state=jobs.state, log=list(jobs.log))

    # ---------------------------------------------------------------- html
    def render_page() -> str:
        meta_path = config.PROCESSED_DIR / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        files = sorted(raw.glob("*.csv")) if raw.exists() else []
        msg = request.args.get("msg", "")
        tok = csrf()
        rows = "".join(
            f"<tr><td>{html.escape(p.name)}</td><td class=num>{human(p.stat().st_size)}</td>"
            f"<td>{time.strftime('%d/%m/%Y %H:%M', time.localtime(p.stat().st_mtime))}</td>"
            f"<td><form method=post action=/admin/delete onsubmit=\"return confirm('Remover {html.escape(p.name)}?')\">"
            f"<input type=hidden name=csrf value={tok}><input type=hidden name=nome value=\"{html.escape(p.name)}\">"
            f"<button class=link>Remover</button></form></td></tr>" for p in files) or "<tr><td colspan=4 class=muted>Nenhum arquivo em data/raw.</td></tr>"
        if meta:
            avisos = "".join(f"<li>{html.escape(a)}</li>" for a in meta["avisos"]) or "<li>Nenhum.</li>"
            fontes = meta["fonte"] if isinstance(meta["fonte"], list) else [meta["fonte"]]
            status = (f"<dl><dt>Focos</dt><dd>{meta['total_focos']:,}".replace(",", ".") + "</dd>"
                      f"<dt>Período</dt><dd>{meta['inicio'][:10]} a {meta['fim'][:10]}</dd>"
                      f"<dt>Satélites</dt><dd>{', '.join(meta['satelites'])}</dd>"
                      f"<dt>Harmonização</dt><dd>{'sim' if meta['tem_harmonizacao'] else 'não (falta peso_harm)'}</dd>"
                      f"<dt>Processado em</dt><dd>{meta['gerado_em']}</dd>"
                      f"<dt>Arquivos</dt><dd>{html.escape(', '.join(fontes))}</dd></dl><h3>Avisos</h3><ul>{avisos}</ul>")
        else:
            status = "<p class=muted>Ainda não há dados processados.</p>"
        last = meta["fim"][:10] if meta else f"{date.today().year}-01-01"
        start = (date.fromisoformat(last) + timedelta(days=1)) if meta else date.fromisoformat(last)
        start = min(start, date.today())
        key_ok = bool(config.FIRMS_MAP_KEY)
        body = f"""
<header><div><h1>Admin · Calendário de Focos</h1><small>Envie as entregas do time de dados, puxe os dias recentes do FIRMS e atualize o painel.</small></div>
<nav><a href="/">Painel</a><a href="/sala">Sala de Situação</a><form method=post action=/admin/logout><input type=hidden name=csrf value={tok}><button class=link>Sair</button></form></nav></header>
{f'<p class=flash>{html.escape(msg)}</p>' if msg else ''}
<main>
<section><h2>1. Enviar arquivos</h2>
<p class=muted>Aceita <code>focos_brutos*.csv</code>, <code>focos_mensais*.csv</code> ou o pacote do time de dados (<code>.tar.gz</code>, <code>.zip</code>): só esses CSVs são extraídos. Arquivo com o mesmo nome é substituído.</p>
<form method=post action=/admin/upload enctype=multipart/form-data>
<input type=hidden name=csrf value={tok}><input type=file name=arquivos multiple required accept=".csv,.gz,.tgz,.tar,.zip">
<label><input type=checkbox name=processar value=1 checked> Processar logo depois do envio</label>
<button class=primary>Enviar</button></form>
<h3>Arquivos em <code>data/raw</code></h3><table><thead><tr><th>Arquivo</th><th>Tamanho</th><th>Modificado</th><th></th></tr></thead><tbody>{rows}</tbody></table>
</section>
<section><h2>2. Dias recentes do NASA FIRMS</h2>
<p class=muted>Baixa MODIS, S-NPP, NOAA-20 e NOAA-21 da América do Sul (científico quando publicado, senão tempo quase real) e grava em <code>data/raw</code>.</p>
{'' if key_ok else '<p class=warn>Defina FIRMS_MAP_KEY no servidor para habilitar.</p>'}
<form method=post action=/admin/firms><input type=hidden name=csrf value={tok}>
<label>De <input type=date name=inicio value="{start.isoformat()}"></label><label>até <input type=date name=fim value="{date.today().isoformat()}"></label>
<label><input type=checkbox name=processar value=1 checked> Processar depois</label>
<button class=primary {'disabled' if not key_ok else ''}>Baixar do FIRMS</button></form>
</section>
<section><h2>3. Processar e publicar</h2>
<p class=muted>Junta todos os CSVs de <code>data/raw</code> (sem duplicar focos), recalcula províncias, departamentos, agregados e grades, e troca os dados do painel sem reiniciar.</p>
<form method=post action=/admin/process><input type=hidden name=csrf value={tok}><button class=primary>Processar agora</button></form>
<h3>Tarefa</h3><p id=jobstate class=muted>—</p><pre id=log></pre>
</section>
<section><h2>Dados no ar</h2>{status}</section>
</main>
<script>
async function poll(){{try{{const r=await fetch('/admin/status');const j=await r.json();const s=j.state;
document.getElementById('jobstate').textContent=s.running?('Em andamento: '+s.kind):(s.ok===null?'Nenhuma tarefa nesta sessão.':(s.ok?'Concluída: '+s.kind:'Falhou: '+(s.error||'')));
document.getElementById('log').textContent=j.log.join('\\n');if(s.running)setTimeout(poll,2000);else if(window._wasRunning)location.reload();window._wasRunning=s.running;}}catch(e){{setTimeout(poll,5000)}}}}
poll();
</script>"""
        return shell("Admin", body)

    def render_login(tok: str, erro=None) -> str:
        msg = "<p class=warn>Usuário ou senha incorretos.</p>" if erro else ""
        return shell("Admin", f"""<main class=narrow><section><h2>Entrar no admin</h2>{msg}
<form method=post action=/admin/login class=login><input type=hidden name=csrf value={tok}>
<label>Usuário <input name=usuario autocomplete=username autofocus required></label>
<label>Senha <input type=password name=senha autocomplete=current-password required></label>
<button class=primary>Entrar</button></form></section></main>""")

    def render_message(title: str, text: str) -> str:
        return shell(title, f"<main class=narrow><section><h2>{html.escape(title)}</h2><p>{html.escape(text)}</p><p><a href='/'>Voltar ao painel</a></p></section></main>")

    return bp


def shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=robots content=noindex><meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Calendário de Focos</title><style>
:root{{--bg:#eceff2;--surface:#fff;--fg:#1a1f25;--muted:#5b6570;--line:#d9dde2;--accent:#c2410c;--warn:#9a6700}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 "IBM Plex Sans",system-ui,sans-serif}}
header{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 16px;background:var(--surface);border-bottom:1px solid var(--line)}}
h1{{font-size:18px;margin:0}}h2{{font-size:16px;margin:0 0 6px}}h3{{font-size:13px;margin:14px 0 6px}}small,.muted{{color:var(--muted)}}
nav{{display:flex;gap:14px;align-items:center}}nav a{{color:var(--fg)}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px;padding:12px 16px;max-width:1400px}}main.narrow{{max-width:460px;display:block}}
section{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}}
form{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}}
button.primary{{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:7px 14px;font-weight:600;cursor:pointer}}button[disabled]{{opacity:.5;cursor:not-allowed}}
button.link{{border:0;background:none;color:var(--accent);cursor:pointer;padding:0;text-decoration:underline}}
table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left}}.num{{text-align:right;font-family:monospace}}
pre{{background:#111;color:#e8e8e8;border-radius:6px;padding:10px;max-height:320px;overflow:auto;font-size:12px;white-space:pre-wrap}}pre:empty{{display:none}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0}}
.flash{{margin:12px 16px 0;padding:8px 12px;background:#fff6db;border:1px solid #f1dc9a;border-radius:6px}}.warn{{color:var(--warn)}}
code{{font-size:12px}}form.login{{flex-direction:column;align-items:stretch}}form.login label{{display:flex;flex-direction:column;gap:4px}}form.login input{{padding:7px 9px;border:1px solid var(--line);border-radius:6px;font:inherit}}</style></head><body>{body}</body></html>"""
