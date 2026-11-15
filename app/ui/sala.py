"""Situation room page (/sala). AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Structure follows Endsley's situation awareness levels: perception (alerts, today's hotspots), comprehension
(priority queue, daily anomaly horizon chart, priority quadrant) and projection (season outlook, season clock).
Widgets can be reordered, resized, hidden or added ("Editar painel"); the layout is saved in the browser.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import shapely
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from ..data.repository import Filtro, Repository
from ..data.sala import LABEL, RMIN, Sala, _frame
from ..i18n import months, months_long, ordinal, tr
from . import figures as F
from .layout import nav

fmt, fmt1, fmtk = F.fmt, F.fmt1, F.fmtk


def lab(status: str) -> str:
    return tr(LABEL[status])
STATUS_C = {"crit": "#b42318", "alert": "#c96a00", "watch": "#9a7a00", "ok": "#3f8f6b", "below": "#2f6fb8"}
CLS_C = ["#2f6fb8", "#a9c8ea", "#ecedef", "#f8d3a8", "#f0a35a", "#d9582a", "#8f1d1f"]
CLS_L = ["½×", "¾×", "normal", "1,5×", "2×", "3×", "5×+"]
WIN_L = {1: "24 h", 7: "7 dias", 30: "30 dias"}  # tr() at use
SIZES = ["S", "M", "L", "XL"]
WIDGETS = {
    "map": ("Seleção", "Mapa de anomalia", "Onde está fora do normal? Clique ou desenhe uma área para focar."),
    "tri": ("Ação", "Fila de prioridade", "Quais lugares atender primeiro?"),
    "horizon": ("Compreensão", "Anomalia diária · 90 dias", "Quem está acelerando agora?"),
    "quad": ("Compreensão", "Quadrante de prioridade", "É grande, é anormal ou os dois?"),
    "hoje": ("Percepção", "Focos do último dia", "O que apareceu nas últimas passagens?"),
    "temp": ("Projeção", "Temporada acumulada", "Como o ano se compara e onde deve terminar?"),
    "clock": ("Projeção", "Relógio da temporada", "Em que fase da temporada estamos?"),
    "cal": ("Histórico", "Calendário mês × ano", "Quando costuma queimar aqui?"),
    "harm": ("Histórico", "Série por sensor", "O degrau de 2012 aparece aqui?"),
    "sat": ("Confiança", "Estado dos satélites", "Os dados estão em dia?"),
}
PRESETS = {
    "coord": [["map", "M"], ["tri", "M"], ["horizon", "L"], ["quad", "S"], ["hoje", "S"], ["temp", "S"], ["sat", "S"]],
    "resp": [["map", "L"], ["hoje", "S"], ["tri", "L"], ["sat", "S"], ["horizon", "XL"]],
    "hist": [["cal", "M"], ["temp", "M"], ["harm", "L"], ["clock", "S"], ["horizon", "L"], ["map", "S"]],
}
PRESET_L = {"coord": "Coordenação", "resp": "Resposta imediata", "hist": "Análise histórica"}  # tr() at use
graph_cfg = {"displaylogo": False, "displayModeBar": False}


def ratio_class(r, R, Ex):
    if (R < 3 and Ex < 3) or (r < 0.85 and Ex < 10):
        return 2
    return 0 if r < 0.6 else 1 if r < 0.85 else 2 if r < 1.5 else 3 if r < 2 else 4 if r < 3 else 5 if r < 5 else 6


def fx(r):
    return (fmt(r) if r >= 10 else fmt1(r)) + "×"


def go_btn(src, kind, uid, children, cls="", hl=None):
    """Focus button. `src` keeps ids unique: the same department can be in the alerts, the queue and today's list at once."""
    return html.Button(children, id={"type": "sala-go", "s": src, "k": kind, "id": uid if hl is None else f"{uid}|{hl}"}, n_clicks=0, className=cls)


BODIES = {
    "map": lambda: [html.Div(className="row", children=[
        dcc.RadioItems(id="sala-tool", options=[{"label": tr("✋ Navegar"), "value": "pan"}, {"label": tr("▭ Retângulo"), "value": "select"},
                                                 {"label": tr("⬠ Polígono"), "value": "lasso"}], value="pan", className="seg small", inline=True),
        go_btn("map", "ar", "", tr("Argentina inteira"), cls="mini")]),
        dcc.Graph(id="sala-map", config={"scrollZoom": True, "displaylogo": False, "doubleClick": False, "displayModeBar": False}, className="smap"),
        html.Div(id="sala-maplegend", className="maplegend")],
    "tri": lambda: [html.Div(id="sala-tri", className="tbl"),
                    html.P(tr("Clique no título de uma coluna para ordenar; numa linha para focar."), className="note")],
    "horizon": lambda: [dcc.Graph(id="sala-strip", config=graph_cfg), html.Div(id="sala-hlegend", className="legend"),
                        html.P(tr("Horizon chart: cada faixa de cor dobra a escala (2×, 4×, 8×), então muitas áreas cabem no mesmo espaço. "
                                  "Linhas ordenadas por prioridade; a caixa tracejada é a janela atual."), className="note")],
    "quad": lambda: [dcc.Graph(id="sala-quad", config=graph_cfg)],
    "hoje": lambda: [html.Div(id="sala-hoje")],
    "temp": lambda: [html.Div(id="sala-temp-call", className="callout"), dcc.Graph(id="sala-temp", config=graph_cfg)],
    "clock": lambda: [html.Div(id="sala-clock-call", className="callout"), dcc.Graph(id="sala-clock", config=graph_cfg)],
    "cal": lambda: [dcc.Graph(id="sala-cal", config=graph_cfg)],
    "harm": lambda: [dcc.Graph(id="sala-harm", config=graph_cfg), html.Div(id="sala-harm-note", className="note")],
    "sat": lambda: [html.Div(id="sala-sat")],
}


def widget(wid):
    ey, title, q = (tr(x) for x in WIDGETS[wid])
    tools = html.Div(className="ctools", children=[
        html.Button("◀", id={"type": "sala-tool", "w": wid, "a": "left"}, n_clicks=0, title=tr("Mover para antes")),
        html.Button("▶", id={"type": "sala-tool", "w": wid, "a": "right"}, n_clicks=0, title=tr("Mover para depois")),
        html.Button(tr("Tamanho"), id={"type": "sala-tool", "w": wid, "a": "size"}, n_clicks=0, title=tr("Mudar tamanho (S, M, L, XL)")),
        html.Button("✕", id={"type": "sala-tool", "w": wid, "a": "hide"}, n_clicks=0, title=tr("Ocultar"))])
    return html.Section(id=f"w-{wid}", className="scard s-M", children=[
        html.Div(className="chd", children=[html.Div([html.Span(ey, className="eyebrow"), html.H3(title), html.P(q, className="q")]), tools]),
        html.Div(className="cbody", children=BODIES[wid]())])


def sala_layout(repo: Repository) -> html.Div:
    if not (repo.ready and repo.has_daily):
        return html.Div(className="app", children=[
            html.Header(className="top", children=[html.Div(className="brand", children=[html.H1(tr("Sala de Situação"))]), nav("sala")]),
            html.Main(className="empty", children=[html.Section(className="sec", children=[
                html.H2(tr("Faltam os agregados diários")),
                html.P(tr("Os dados atuais foram processados antes dos agregados diários (dia_dep.parquet).")),
                html.P(tr("Peça a quem administra o sistema para reprocessar os dados."), className="note")])])])
    s = Sala(repo)
    d = s.daily()
    D = d["D"]
    opts = [{"label": tr("{n} (província)", n=p.nome), "value": f"prov:{p.id}"} for p in repo.geo.provincias.values()]
    opts += [{"label": f"{u.nome} ({repo.geo.provincias[u.parent].nome})", "value": f"dep:{u.id}"} for u in repo.geo.departamentos.values() if u.parent in repo.geo.provincias]
    return html.Div(className="app sala", children=[
        dcc.Store(id="sala-st", data={"win": 7, "kind": "ar", "uid": "", "shape": [], "hl": None, "sort": ["score", -1]}),
        dcc.Store(id="sala-layout", storage_type="local", data={"preset": "coord", "layout": PRESETS["coord"]}),
        dcc.Store(id="sala-edit", data=False), dcc.Store(id="sala-tool-sync"),
        html.Header(className="top", children=[
            html.Div(className="brand", children=[html.H1(tr("Sala de Situação · Focos de Calor")),
                                                   html.Small(tr("Argentina · último dia com dados: {d}", d=f"{D:%d/%m/%Y}"))]),
            html.Span([html.I(className="livedot"), "NRT"], className="live", title=tr("Os dias mais recentes vêm do NASA FIRMS em tempo quase real")),
            nav("sala"),
            html.Div(className="controls", children=[
                dcc.Dropdown(id="sala-search", options=sorted(opts, key=lambda o: o["label"]), placeholder=tr("Província ou departamento"), className="search sm"),
                html.Span(tr("Janela"), className="note"),
                dcc.RadioItems(id="sala-win", options=[{"label": tr(v), "value": k} for k, v in WIN_L.items()], value=7, className="seg", inline=True),
                html.Span(tr("Painel"), className="note"),
                dcc.Dropdown(id="sala-preset", options=[{"label": tr(v), "value": k} for k, v in PRESET_L.items()] + [{"label": tr("Personalizado"), "value": "custom", "disabled": True}],
                             value="coord", clearable=False, className="preset"),
                html.Button(tr("Editar painel"), id="sala-editbtn", n_clicks=0, className="btn")]),
        ]),
        html.Div(className="sala-body", id="sala-body", children=[
            html.Section(className="alerts", children=[
                html.Div(className="acount", children=[html.Span(tr("Alertas ativos"), className="eyebrow"), html.Div(id="sala-acount", className="row"),
                                                       html.Span(id="sala-arule", className="note")]),
                html.Div(id="sala-alerts", className="alist")]),
            html.Section(className="scope", children=[
                html.Div([html.Nav(id="sala-crumbs", className="crumbs"), html.H2(id="sala-title"), html.Div(id="sala-stat", className="stat")]),
                html.Div(id="sala-kpis", className="skpis")]),
            html.Div(id="sala-edits", className="edits"),
            html.Main(className="sgrid", children=[widget(w) for w in WIDGETS]),
            html.Footer(className="foot", children=[
                html.Strong(tr("Como ler")),
                html.Span(tr("Esperado = média do mesmo mês em {a}–{b}, distribuída pelos dias (mesma cobertura de satélites: S-NPP e NOAA-20). "
                             "Status: crítico ≥ 3× o esperado com volume mínimo; alerta ≥ 2×; atenção ≥ 1,5×. Projeção da temporada por anos análogos (p10–p90). "
                             "Os dias mais recentes vêm do NASA FIRMS em tempo quase real (NRT) e podem mudar quando sair o produto científico.",
                             a=d['baseline'][0], b=d['baseline'][1])),
                html.Span(tr("Série harmonizada: quando o time de dados entregar peso_harm, a sala passa a usá-la automaticamente."), className="note")]),
        ]),
    ])


def register_sala(app, repo: Repository) -> None:
    geo = repo.geo

    # ------------------------------------------------------------------ layout (presets + edit mode)
    @app.callback(Output("sala-layout", "data"), Output("sala-preset", "value"),
                  Input("sala-preset", "value"), Input({"type": "sala-tool", "w": ALL, "a": ALL}, "n_clicks"),
                  Input({"type": "sala-add", "w": ALL}, "n_clicks"), Input({"type": "sala-reset", "x": ALL}, "n_clicks"),
                  State("sala-layout", "data"))
    def edit_layout(preset, tools, adds, reset, data):
        data = dict(data or {"preset": "coord", "layout": PRESETS["coord"]})
        lay = [list(x) for x in data["layout"]]
        tid = ctx.triggered_id
        if tid is None:  # page load: show the preset saved in this browser
            return no_update, data.get("preset", "coord")
        if tid == "sala-preset":
            if preset == data.get("preset") or preset not in PRESETS:
                return no_update, no_update
            return {"preset": preset, "layout": PRESETS[preset]}, no_update
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update
        if tid["type"] == "sala-reset":
            p = data.get("preset") if data.get("preset") in PRESETS else "coord"
            return {"preset": p, "layout": PRESETS[p]}, p
        if tid["type"] == "sala-add":
            lay.append([tid["w"], "M"])
        else:
            k = next((i for i, x in enumerate(lay) if x[0] == tid["w"]), None)
            if k is None:
                return no_update, no_update
            a = tid["a"]
            if a == "left" and k > 0:
                lay[k - 1], lay[k] = lay[k], lay[k - 1]
            elif a == "right" and k < len(lay) - 1:
                lay[k + 1], lay[k] = lay[k], lay[k + 1]
            elif a == "size":
                lay[k][1] = SIZES[(SIZES.index(lay[k][1]) + 1) % 4]
            elif a == "hide":
                lay.pop(k)
        return {"preset": "custom", "layout": lay}, "custom"

    @app.callback(Output("sala-edit", "data"), Output("sala-editbtn", "children"), Input("sala-editbtn", "n_clicks"), State("sala-edit", "data"), prevent_initial_call=True)
    def toggle_edit(n, on):
        return not on, tr("Concluir edição") if not on else tr("Editar painel")

    @app.callback([Output(f"w-{w}", "className") for w in WIDGETS] + [Output(f"w-{w}", "style") for w in WIDGETS] +
                  [Output("sala-edits", "children"), Output("sala-body", "className")],
                  Input("sala-layout", "data"), Input("sala-edit", "data"))
    def apply_layout(data, editing):
        lay = (data or {}).get("layout") or PRESETS["coord"]
        pos = {w: (i, size) for i, (w, size) in enumerate(lay)}
        cls = [f"scard s-{pos[w][1]}" if w in pos else "scard" for w in WIDGETS]
        sty = [{"order": pos[w][0]} if w in pos else {"display": "none"} for w in WIDGETS]
        hidden = [w for w in WIDGETS if w not in pos]
        if editing:
            edits = [html.Span(tr("Modo de edição: ◀ ▶ reordenam, Tamanho alterna S/M/L/XL e ✕ oculta. O layout fica salvo neste navegador.")),
                     *([html.Span(tr("Adicionar:"))] + [html.Button("+ " + tr(WIDGETS[w][1]), id={"type": "sala-add", "w": w}, n_clicks=0, className="mini") for w in hidden] if hidden else []),
                     html.Button(tr("Restaurar o painel"), id={"type": "sala-reset", "x": 1}, n_clicks=0, className="mini")]
        else:
            edits = []
        return cls + sty + [edits, "sala-body" + (" editing" if editing else "")]

    # ------------------------------------------------------------------ scope / selection state
    @app.callback(Output("sala-st", "data"), Output("sala-search", "value"),
                  Input("sala-win", "value"), Input({"type": "sala-go", "s": ALL, "k": ALL, "id": ALL}, "n_clicks"),
                  Input("sala-map", "clickData"), Input("sala-map", "selectedData"), Input("sala-quad", "clickData"),
                  Input("sala-strip", "clickData"), Input("sala-search", "value"), Input({"type": "sala-sort", "k": ALL}, "n_clicks"),
                  State("sala-st", "data"), prevent_initial_call=True)
    def control(win, clicks, mapc, msel, quadc, stripc, search, sorts, st):
        st = dict(st)
        tid = ctx.triggered_id
        prop = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        val = ctx.triggered[0]["value"] if ctx.triggered else None
        # buttons re-created by a render fire all at once with n_clicks=0: only a single real click counts
        if isinstance(tid, dict) and (len(ctx.triggered) != 1 or not val):
            return no_update, no_update
        reset_search = no_update
        if tid == "sala-win":
            st["win"] = win
        elif tid == "sala-search":
            if not search:
                return no_update, no_update
            k, uid = search.split(":", 1)
            st.update(kind=k, uid=uid, shape=[], hl=None)
            reset_search = None
        elif isinstance(tid, dict) and tid.get("type") == "sala-sort":
            if not val:
                return no_update, no_update
            k = tid["k"]
            st["sort"] = [k, -st["sort"][1]] if st.get("sort", [None])[0] == k else [k, -1]
        elif isinstance(tid, dict) and tid.get("type") == "sala-go":
            if not val:
                return no_update, no_update
            uid, _, hl = tid["id"].partition("|")
            st.update(kind=tid["k"], uid=uid, shape=[], hl=[float(v) for v in hl.split(",")] if hl else None)
        elif tid == "sala-map" and prop.endswith("selectedData"):
            pts = None
            for key in ("map", "mapbox"):
                if key in ((msel or {}).get("range") or {}):
                    (x0, y0), (x1, y1) = msel["range"][key]
                    pts = [[min(x0, x1), min(y0, y1)], [max(x0, x1), min(y0, y1)], [max(x0, x1), max(y0, y1)], [min(x0, x1), max(y0, y1)]]
                elif key in ((msel or {}).get("lassoPoints") or {}):
                    pts = msel["lassoPoints"][key]
            if not pts or len(pts) < 3:
                return no_update, no_update
            st.update(kind="shape", uid="", shape=[[round(p[0], 4), round(p[1], 4)] for p in pts], hl=None)
        elif tid in ("sala-map", "sala-quad", "sala-strip"):
            data = {"sala-map": mapc, "sala-quad": quadc, "sala-strip": stripc}[tid]
            cd = data and data["points"][0].get("customdata")
            if cd and cd[0] == "pt":  # a hotspot sits on top of the areas: focus the area it belongs to
                dep = geo.departamentos.get(cd[1])
                if not dep:
                    return no_update, no_update
                cd = ["prov", dep.parent] if st["kind"] == "ar" else ["dep", dep.id]
            if not cd or cd[0] not in ("prov", "dep"):
                return no_update, no_update
            st.update(kind=cd[0], uid=cd[1], shape=[], hl=None)
        else:
            return no_update, no_update
        return st, reset_search

    app.clientside_callback(  # switch pan / box / lasso in the browser instead of resending the whole figure
        """function(tool){const g=document.querySelector('#sala-map .js-plotly-plot');
           if(g&&window.Plotly){Plotly.relayout(g,{dragmode:tool});} return tool;}""",
        Output("sala-tool-sync", "data"), Input("sala-tool", "value"), prevent_initial_call=True)

    dep_geoms = {}

    def shape_deps(shape):
        """Departments the drawn area touches (the daily metrics exist per department)."""
        if not dep_geoms:
            dep_geoms.update({k: shapely.geometry.shape(d.feature["geometry"]) for k, d in geo.departamentos.items()})
        poly = shapely.Polygon(shape).buffer(0)
        deps = [k for k, g in dep_geoms.items() if g.intersects(poly)]
        return deps or [min(geo.departamentos.values(), key=lambda d: (d.centroid[0] - poly.centroid.x) ** 2 + (d.centroid[1] - poly.centroid.y) ** 2).id]

    # ------------------------------------------------------------------ main render
    @app.callback(
        Output("sala-acount", "children"), Output("sala-arule", "children"), Output("sala-alerts", "children"),
        Output("sala-crumbs", "children"), Output("sala-title", "children"), Output("sala-stat", "children"), Output("sala-kpis", "children"),
        Output("sala-map", "figure"), Output("sala-maplegend", "children"), Output("sala-tri", "children"),
        Output("sala-strip", "figure"), Output("sala-hlegend", "children"), Output("sala-quad", "figure"), Output("sala-hoje", "children"),
        Output("sala-temp", "figure"), Output("sala-temp-call", "children"), Output("sala-clock", "figure"), Output("sala-clock-call", "children"),
        Output("sala-cal", "figure"), Output("sala-harm", "figure"), Output("sala-harm-note", "children"), Output("sala-sat", "children"),
        Input("sala-st", "data"), State("sala-tool", "value"))
    def render(st, tool):
        s = Sala(repo)
        win, kind, uid = st["win"], st["kind"], st["uid"]
        deps_m, provs_m = s.metrics(win)
        d = s.daily()
        D = d["D"]
        wl = tr(WIN_L[win])

        if kind == "prov":
            scope_deps = geo.deps_of.get(uid, [])
            units, unit_kind, scope_row, name = deps_m.loc[scope_deps], "dep", provs_m.loc[uid], geo.provincias[uid].nome
        elif kind == "dep":
            pid = geo.departamentos[uid].parent
            scope_deps = [uid]
            units, unit_kind, scope_row, name = deps_m.loc[geo.deps_of.get(pid, [])], "dep", deps_m.loc[uid], geo.departamentos[uid].nome
        elif kind == "shape":
            scope_deps = shape_deps(st["shape"])
            units, unit_kind = deps_m.loc[scope_deps], "dep"
            name = tr("Área desenhada · {n} departamentos", n=len(scope_deps)) if len(scope_deps) != 1 else tr("Área desenhada · 1 departamento")
            name = [name, html.Small(tr(" (números somam os departamentos que a área toca)"), className="note")]
            scope_row = _frame(d["A"].loc[scope_deps].sum().to_frame().T, d["E"].loc[scope_deps].sum().to_frame().T,
                               d["F"].loc[scope_deps].max().to_frame().T, win).iloc[0]
        else:
            scope_deps = list(geo.departamentos)
            units, unit_kind, name = provs_m, "prov", "Argentina"
            scope_row = _frame(d["A"].sum().to_frame().T, d["E"].sum().to_frame().T, d["F"].max().to_frame().T, win).iloc[0]
        tri = deps_m if kind == "ar" else units

        al = deps_m[deps_m["status"].isin(["crit", "alert", "watch"])].sort_values("score", ascending=False)
        cnt = al["status"].value_counts()
        acount = [html.Span([str(cnt.get(k, 0)), html.Small(tr(lbl))], style={"color": STATUS_C[k]}) for k, lbl in (("crit", "crít."), ("alert", "alerta"), ("watch", "atenção"))]
        alerts = [go_btn("alert", "dep", i, [html.Span(lab(r.status), className=f"pill {r.status}"), html.Span(f"{r.nome} · {r['sub']}", className="pl"),
                                    html.Span([html.B(fx(r.ratio)), tr(" o esperado · "), html.B(fmt(r.R)), tr(" focos em {w} · ativo há ", w=wl), html.B(str(r.pers)), " d"], className="hd")],
                         cls=f"acard {r.status}") for i, r in al.head(14).iterrows()] or [html.Span(tr("Nenhum departamento fora do normal nesta janela."), className="note")]

        crumbs = [go_btn("crumb", "ar", "", "Argentina")]
        if kind in ("prov", "dep"):
            pid = uid if kind == "prov" else geo.departamentos[uid].parent
            crumbs += [" › ", go_btn("crumb", "prov", pid, geo.provincias[pid].nome)]
        if kind == "dep":
            crumbs += [" › ", html.Span(name, className="cur")]
        if kind == "shape":
            crumbs += [" › ", html.Span(tr("Área desenhada"), className="cur")]
        stat = [html.Span(lab(scope_row["status"]), className=f"pill {scope_row['status']}"),
                html.Span(tr("{r} o esperado para {w} nesta época do ano", r=fx(scope_row['ratio']), w=wl), className="note")]
        trd = scope_row["trend"]
        cells = s.today_cells(None if kind == "ar" else scope_deps)
        n_new = int(cells["novo"].sum()) if len(cells) else 0
        kp = [(tr("Focos · {w}", w=wl), fmtk(scope_row["R"]), tr("{a} {s}% vs. {w} anteriores", a='▲' if trd > .15 else '▼' if trd < -.15 else '▶',
                                                                    s=f"{'+' if trd >= 0 else ''}{fmt(min(trd, 9.99) * 100)}", w=wl)),
              (tr("Esperado"), fmtk(scope_row["Ex"]), tr("média {a}–{b}", a=d['baseline'][0], b=d['baseline'][1])),
              (tr("Relação"), fx(scope_row["ratio"]), lab(scope_row["status"]).lower()),
              (tr("Em {d}", d=f"{D:%d/%m}"), fmt(scope_row["today"]),
               tr("1 célula nova de 0,1°") if n_new == 1 else tr("{n} células novas de 0,1°", n=n_new)),
              (tr("Persistência"), f"{int(scope_row['pers'])}{'+' if scope_row['pers'] >= len(d['days']) - 1 else ''} d", tr("dias seguidos com focos")),
              (tr("FRP máximo"), f"{fmt(scope_row['frp'])} MW" if scope_row["frp"] else "—", tr("maior intensidade na janela"))]
        kpis = [html.Div([html.Span(a, className="k"), html.Span(b, className="v"), html.Span(c, className="d")], className="kpi") for a, b, c in kp]

        mapfig, maplegend = sala_map(st, units, unit_kind, scope_deps, s, D, win, tool or "pan", al)
        sort_k, sort_dir = st.get("sort", ["score", -1])
        tri_el = triage(tri, sort_k, sort_dir, kind, uid, d, win)
        strip, hleg = horizon(units.sort_values("score", ascending=False).head(12), unit_kind, d, win)
        quad = quad_fig(units, unit_kind, win, kind, uid)
        hoje = today_list(cells, D)
        f = scope_filter(st)
        v = repo.series(f)
        temp, call = season_fig(v, D)
        clock, clock_call = clock_fig(v, D)
        m = repo.monthly(f)
        cal = F.calendar(m, v, repo.mi0, repo.mi1, ())
        cal.update_layout(height=470)
        harm, harm_note = F.harmonization(m, repo.has_harm)
        sat = sat_table(s.sat_status(), D)
        return (acount, tr("Crítico: ≥3× o esperado e ≥{n} focos em {w}", n=RMIN[win], w=wl), alerts, crumbs, name, stat, kpis,
                mapfig, maplegend, tri_el, strip, hleg, quad, hoje, temp, call, clock, clock_call, cal, harm,
                dcc.Markdown(harm_note, dangerously_allow_html=True), sat)

    def scope_filter(st) -> Filtro:
        serie = "harm" if repo.has_harm else "raw"
        if st["kind"] == "shape":
            return Filtro(kind="shape", uid="", shape=tuple(tuple(p) for p in st["shape"]), serie=serie)
        if st["kind"] in ("prov", "dep"):
            return Filtro(kind=st["kind"], uid=st["uid"], serie=serie)
        return Filtro(kind="pais", uid="ARG", serie=serie)

    # ------------------------------------------------------------------ map
    def dep_label(dep_id):
        d = geo.departamentos.get(dep_id)
        return f"{d.nome} · {geo.provincias[d.parent].nome}" if d and d.parent in geo.provincias else ""  # proper names

    def sala_map(st, units, unit_kind, scope_deps, s: Sala, D, win, tool, alert_deps):
        kind, uid = st["kind"], st["uid"]
        traces = []
        grey = [[0, "#eceae4"], [1, "#eceae4"]]
        ids = list(geo.paises)
        traces.append(go.Choroplethmap(geojson=geo.fc["pais"], locations=ids, z=[0] * len(ids), featureidkey="id", colorscale=grey, showscale=False,
                                       marker_opacity=0.5, marker_line_width=0.5, hoverinfo="skip"))
        if unit_kind == "dep":
            pids = list(geo.provincias)
            traces.append(go.Choroplethmap(geojson=geo.fc["prov"], locations=pids, z=[0] * len(pids), featureidkey="id", colorscale=grey, showscale=False,
                                           marker_opacity=0.6, marker_line_width=0.8, customdata=[["prov", p, geo.provincias[p].nome] for p in pids],
                                           hovertemplate="%{customdata[2]}" + tr("<br><i>clique para focar</i>") + "<extra></extra>"))
            fc = geo.subset("dep", units.index)
        else:
            fc = geo.fc["prov"]
        def hover(r):
            return tr("<b>{n}</b><br>{s} · {r} o esperado<br>{R} focos (esperado {E})<br>Último dia: {t} · ativo há {p} d<br><i>clique para focar</i>",
                      n=r.nome, s=lab(r.status), r=fx(r.ratio), R=fmt(r.R), E=fmt1(r.Ex), t=fmt(r.today), p=r.pers)
        z = [ratio_class(r.ratio, r.R, r.Ex) for r in units.itertuples()]
        cd = [[unit_kind, i, hover(r)] for i, r in units.iterrows()]
        traces.append(go.Choroplethmap(geojson=fc, locations=list(units.index), z=z, zmin=0, zmax=6, featureidkey="id",
                                       colorscale=[[k / 6, c] for k, c in enumerate(CLS_C)], showscale=False, marker_opacity=0.9,
                                       marker_line_width=0.6, marker_line_color="#8f877b", customdata=cd, hovertemplate="%{customdata[2]}<extra></extra>"))
        if kind == "ar":  # departments on alert drawn over the provinces, so the alert list can be found on the map
            hot = alert_deps
            if len(hot):
                traces.append(go.Choroplethmap(geojson=geo.subset("dep", hot.index), locations=list(hot.index), featureidkey="id",
                                               z=[ratio_class(r.ratio, r.R, r.Ex) for r in hot.itertuples()], zmin=0, zmax=6,
                                               colorscale=[[k / 6, c] for k, c in enumerate(CLS_C)], showscale=False, marker_opacity=0.95,
                                               marker_line_width=1.4, marker_line_color="#3b2a20",
                                               customdata=[["dep", i, f"{hover(r)}<br>{r['sub']}"] for i, r in hot.iterrows()],
                                               hovertemplate="%{customdata[2]}<extra></extra>"))
        only_today = kind == "ar" and win > 1  # whole country: show only the last day to keep it readable
        pts = s.window_points(None if kind == "ar" else scope_deps, 1 if only_today else win)
        if len(pts):
            today = pts["dia"] == D
            for flag, color, size in ((False, F.ACCENT, 5), (True, "#111", 7)):
                g = pts[today == flag]
                if len(g):
                    where = [dep_label(x) for x in g["dep_id"]]
                    traces.append(go.Scattermap(lat=g["lat"], lon=g["lon"], mode="markers", marker=dict(size=size, color=color, opacity=0.85),
                                                customdata=np.stack([["pt"] * len(g), g["dep_id"].fillna(""), g["ts"].dt.strftime("%d/%m/%Y %H:%M"),
                                                                     g["satelite"], g["frp"].round(1), where], 1),
                                                hovertemplate=tr("<b>Foco · %{customdata[3]}</b><br>%{customdata[5]}<br>%{customdata[2]} UTC · FRP %{customdata[4]} MW"
                                                                 "<br><i>clique para focar</i>") + "<extra></extra>"))
        layers = []
        if kind in ("prov", "dep"):
            u = geo.unit(kind, uid)
            layers.append(dict(sourcetype="geojson", source={"type": "FeatureCollection", "features": [u.feature]}, type="line", color="#111", line=dict(width=3)))
            bbox = u.bbox
        elif kind == "shape":
            ring = st["shape"] + [st["shape"][0]]
            layers.append(dict(sourcetype="geojson", source={"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring}}, type="line",
                               color=F.ACCENT, line=dict(width=2.5)))
            xs, ys = [p[0] for p in st["shape"]], [p[1] for p in st["shape"]]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        else:
            bbox = geo.paises["ARG"].bbox
        if st.get("hl"):  # cell picked in "Focos do último dia"
            gx, gy, g = st["hl"]
            x0, y0 = gx * g, gy * g
            layers.append(dict(sourcetype="geojson", type="line", color="#111", line=dict(width=3),
                               source={"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[x0, y0], [x0 + g, y0], [x0 + g, y0 + g], [x0, y0 + g], [x0, y0]]}}))
            bbox = (x0 - 0.3, y0 - 0.3, x0 + g + 0.3, y0 + g + 0.3)
        # invisible grid so box/lasso always return a selection, even over empty land
        gxs, gys = np.meshgrid(np.linspace(bbox[0] - 3, bbox[2] + 3, 20), np.linspace(bbox[1] - 3, bbox[3] + 3, 20))
        traces.append(go.Scattermap(lon=gxs.ravel(), lat=gys.ravel(), mode="markers", marker=dict(size=1, opacity=0), hoverinfo="skip"))
        center, zoom = F.zoom_for(bbox, 600, 430)
        fig = go.Figure(traces)
        fig.update_layout(map=dict(style="carto-positron", center=center, zoom=zoom, layers=layers), margin=dict(l=0, r=0, t=0, b=0),
                          height=430, showlegend=False, uirevision=f"{kind}:{uid}:{st.get('hl')}:{len(st['shape'])}", dragmode=tool,
                          hoverlabel=dict(bgcolor=F.FG, font_color="#fff"), clickmode="event", separators=F.separators())
        legend = [html.Div(tr("Focos na janela vs. esperado"), className="note"),
                  html.Div([html.Span([html.I(style={"background": c}), tr(t)]) for c, t in zip(CLS_C, CLS_L)], className="mlr"),
                  html.Div(([html.Span([html.I(className="dot", style={"background": F.ACCENT}), tr("focos da janela ({w})", w=tr(WIN_L[win]))])] if not only_today else []) +
                           [html.Span([html.I(className="dot", style={"background": "#111"}), tr("focos em {d}", d=f"{D:%d/%m}")])] +
                           ([html.Span(tr("províncias coloridas; por cima, os departamentos em alerta"))] if kind == "ar" else []), className="legend")]
        return fig, legend

    # ------------------------------------------------------------------ priority queue (sortable)
    COLS = [("score", "Status"), ("nome", "Lugar"), ("R", "Focos"), ("Ex", "Esperado"), ("ratio", "× normal"), ("trend", "Tendência"),
            ("pers", "Dias ativos"), ("frp", "FRP máx."), (None, "Últimos 30 dias")]  # tr() at use

    def triage(rows: pd.DataFrame, sort_k, sort_dir, kind, uid, d, win):
        rows = rows[(rows["R"] > 0) | (rows["status"] != "ok")]
        if sort_k == "nome":
            rows = rows.sort_values("nome", ascending=sort_dir > 0, key=lambda c: c.str.normalize("NFD"))
        else:
            rows = rows.sort_values(sort_k, ascending=sort_dir > 0)
        rows = rows.head(12)
        head = html.Tr([html.Th(html.Button([tr(lbl), (" ↓" if sort_dir < 0 else " ↑") if k == sort_k else ""], id={"type": "sala-sort", "k": k},
                                            n_clicks=0, className="thbtn") if k else tr(lbl)) for k, lbl in COLS])
        A, E = d["A"], d["E"]
        body = []
        for i, r in rows.iterrows():
            t = r.trend
            arrow, cls = ("▲", "up") if t > .15 else ("▼", "dn") if t < -.15 else ("▶", "fl")
            a30 = A.loc[i].to_numpy()[-30:]
            mx = max(a30.max(), E.loc[i].to_numpy()[-30:].max(), 1)
            bars = [html.I(style={"height": f"{max(1, v / mx * 22):.0f}px", "background": "var(--accent)" if k >= 30 - win else "#c9cfd6"}) for k, v in enumerate(a30)]
            body.append(html.Tr(className="trow" + (" sel" if kind == "dep" and uid == i else ""), children=[
                html.Td(html.Span(lab(r.status), className=f"pill {r.status}")),
                html.Td(go_btn("tri", "dep", i, [r.nome, html.Small(r['sub'])], cls="plbtn")),
                html.Td(fmt(r.R), className="num"), html.Td(fmt1(r.Ex), className="num"), html.Td(html.B(fx(r.ratio)), className="num"),
                html.Td(f"{arrow} {'+' if t >= 0 else ''}{fmt(min(t, 9.99) * 100)}%", className=f"trend {cls}"),
                html.Td(str(r.pers), className="num"), html.Td(fmt(r.frp) if r.frp else "—", className="num"),
                html.Td(html.Span(bars, className="spark"))]))
        return html.Table([html.Thead(head), html.Tbody(body)], className="tri") if body else html.P(tr("Sem focos nesta área."), className="note")

    # ------------------------------------------------------------------ horizon chart (each colour band doubles the scale)
    def horizon(units: pd.DataFrame, unit_kind, d, win):
        A, E = d["A"], d["E"]
        if unit_kind == "prov":
            parent = pd.Series({k: u.parent for k, u in geo.departamentos.items()})
            A, E = A.groupby(parent.reindex(A.index)).sum(), E.groupby(parent.reindex(E.index)).sum()
        n = 90
        a = A.loc[units.index].T.rolling(3, min_periods=1).sum().T.iloc[:, -n:]
        e = E.loc[units.index].T.rolling(3, min_periods=1).sum().T.iloc[:, -n:]
        z = np.log2((a.to_numpy() + 1) / (e.to_numpy() + 1))
        days = a.columns
        rows = len(units)
        up, dn = ["#f0a35a", "#d9582a", "#8f1d1f"], ["#a9c8ea", "#2f6fb8"]
        xs, bases, heights, colors, hover, custom = [], [], [], [], [], []
        for r_i, (u, row) in enumerate(zip(units.index, z)):
            base = rows - 1 - r_i
            nome = units.loc[u, "nome"]
            for k, dd in enumerate(days):
                txt = tr("<b>{n}</b> · {d}<br>{a} focos (esperado {e})<br>3 dias: {r} o esperado", n=nome, d=f"{dd:%d/%m}",
                         a=fmt(A.loc[u].iloc[-n + k]), e=fmt1(E.loc[u].iloc[-n + k]), r=fx(2 ** row[k]))
                bands = [(np.clip(row[k] - b, 0, 1), c) for b, c in enumerate(up)] + [(np.clip(-row[k] - b, 0, 1), c) for b, c in enumerate(dn)]
                xs.append(dd); bases.append(base); heights.append(0.9); colors.append("#f1f2f4"); hover.append(txt); custom.append([unit_kind, u])
                for h, c in bands:
                    if h > 0:
                        xs.append(dd); bases.append(base); heights.append(h * 0.9); colors.append(c); hover.append(txt); custom.append([unit_kind, u])
        fig = go.Figure(go.Bar(x=xs, y=heights, base=bases, marker_color=colors, marker_line_width=0, width=86400000, text=hover, textposition="none",
                               hovertemplate="%{text}<extra></extra>", customdata=custom))
        F.base_layout(fig, 40 + 28 * rows, barmode="overlay", bargap=0)
        names = [units.loc[u, "nome"][:24] + f"  {fx(units.loc[u, 'ratio'])}" for u in units.index]
        fig.update_yaxes(tickvals=[rows - 1 - i + 0.45 for i in range(rows)], ticktext=names, showgrid=False, range=[0, rows],
                         tickfont=dict(family="IBM Plex Sans", size=11, color=F.FG))
        fig.update_layout(margin=dict(l=190, r=10, t=6, b=24))
        fig.add_vrect(x0=days[-win] - pd.Timedelta(hours=12), x1=days[-1] + pd.Timedelta(hours=12), line=dict(color=F.FG, width=1.5, dash="dot"), fillcolor="rgba(0,0,0,0)")
        legend = [html.Span(tr("abaixo do esperado")), *[html.I(className="sw", style={"background": c}) for c in reversed(dn)],
                  html.I(className="sw", style={"background": "#f1f2f4", "outline": "1px solid #d9dde2"}),
                  *[html.I(className="sw", style={"background": c}) for c in up], html.Span(tr("2×, 4×, 8× acima"))]
        return fig, legend

    # ------------------------------------------------------------------ quadrant
    def quad_fig(units: pd.DataFrame, unit_kind: str, win: int, kind, uid):
        u = units[(units["R"] > 0) | (units["Ex"] > 1)]
        x = np.log2(u["ratio"]).clip(-2, 4)
        y = np.log10(u["R"] + 1)
        yl = np.log10(RMIN[win] + 1)
        ymax = max(float(y.max()) * 1.1 if len(y) else 1, yl * 1.3)
        fig = go.Figure()
        fig.add_shape(type="rect", x0=1, x1=4.2, y0=yl, y1=ymax, fillcolor="rgba(180,35,24,.08)", line_width=0)
        for xx, yy, t, c, anc in ((4.1, ymax * .97, "AGIR AGORA", "#b42318", "right"), (-1.9, ymax * .97, "VOLUME ALTO, NORMAL", F.MUTED, "left"),
                                  (4.1, 0.03, "SURTO INICIAL", "#c96a00", "right"), (-1.9, 0.03, "NORMAL", F.MUTED, "left")):
            fig.add_annotation(x=xx, y=yy, text=tr(t), showarrow=False, xanchor=anc, yanchor="top" if yy > 0.1 else "bottom", font=dict(size=9.5, color=c))
        fig.add_vline(x=1, line=dict(color="#b42318", dash="dash", width=1))
        fig.add_hline(y=yl, line=dict(color="#b42318", dash="dash", width=1))
        top = set(u.sort_values("score", ascending=False).query("status != 'ok'").head(5).index)
        sel = lambda i: kind == unit_kind and uid == i  # noqa: E731
        fig.add_trace(go.Scatter(x=x, y=y, mode="markers+text", text=[r.nome[:16] if i in top else "" for i, r in u.iterrows()], textposition="middle right",
                                 textfont=dict(size=10, color=F.FG),
                                 marker=dict(size=[7 + np.sqrt(p + 1) * 2.2 for p in u["pers"]], color=[STATUS_C[s_] for s_ in u["status"]],
                                             opacity=[0.45 if s_ == "ok" else 0.85 for s_ in u["status"]],
                                             line=dict(color=["#111" if sel(i) else "#fff" for i in u.index], width=[2.5 if sel(i) else 1 for i in u.index])),
                                 customdata=[[unit_kind, i, tr("<b>{n}</b><br>{s} · {r} o esperado<br>{R} focos · ativo há {p} d", n=r.nome, s=lab(r.status), r=fx(r.ratio), R=fmt(r.R), p=r.pers)]
                                             for i, r in u.iterrows()],
                                 hovertemplate="%{customdata[2]}<extra></extra>"))
        F.base_layout(fig, 340)
        fig.update_xaxes(range=[-2.1, 4.2], tickvals=[-2, -1, 0, 1, 2, 3, 4], ticktext=["¼×", "½×", "1×", "2×", "4×", "8×", "16×"], title=dict(text=tr("quantas vezes o esperado"), font=dict(size=10)))
        fig.update_yaxes(range=[0, ymax], tickvals=[0, 1, 2, 3, 4], ticktext=["0", "9", "99", "999", fmt(9999)], title=dict(text=tr("focos (escala log)"), font=dict(size=10)))
        fig.update_layout(margin=dict(l=50, r=10, t=8, b=40))
        return fig

    # ------------------------------------------------------------------ today's hotspots
    def today_list(cells: pd.DataFrame, D):
        if cells is None or not len(cells):
            return html.P(tr("Nenhum foco em {d} nesta área.", d=f"{D:%d/%m/%Y}"), className="note")
        tot, new = int(cells["n"].sum()), int(cells["novo"].sum())
        items = []
        for r in cells.head(8).itertuples():
            dep = geo.departamentos.get(r.dep_id)
            items.append(html.Li(go_btn("hoje", "dep", r.dep_id, [
                html.Span([str(r.n), html.Small(tr("focos"))], className="n"),
                html.Span([html.B(dep.nome if dep else "—"), html.Span(f"{geo.provincias[dep.parent].nome if dep else ''} · {abs(r.lat):.2f}°S {abs(r.lon):.2f}°W")], className="w"),
                html.Span([html.Span(tr("NOVO"), className="new") if r.novo else None, html.Span(f"{pd.Timestamp(r.ultimo):%H:%M} UTC"),
                           html.Span([html.I(style={"background": F.SAT_C.get(x, '#888')}, title=x) for x in r.sats], className="sats")], className="r")],
                cls="feedbtn", hl=f"{r.gx},{r.gy},0.1")))
        return [html.Div([html.B(fmt(tot)), tr(" focos em {d} em ", d=f"{D:%d/%m}"), html.B(str(len(cells))), tr(" células de 0,1° · "), html.B(str(new)),
                          tr(" sem focos nos 7 dias anteriores. Clique para ver a célula no mapa.")], className="callout"), html.Ul(items, className="feed")]

    # ------------------------------------------------------------------ season: cumulative + projection, and season clock
    def season_fig(v: pd.Series, D):
        Y = D.year
        last = D.month - 1 if D.day < 28 else D.month
        cum = lambda y: np.cumsum([v.get(y * 12 + k, 0.0) for k in range(12)])  # noqa: E731
        hist = np.array([cum(y) for y in range(max(2012, repo.y0 + 1), Y)])
        cur = cum(Y)[:max(last, 1)]
        MS = months()
        mn, mx_, p25, p50, p75 = hist.min(0), hist.max(0), *np.quantile(hist, [0.25, 0.5, 0.75], 0)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=MS, y=mx_, mode="lines", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MS, y=mn, mode="lines", fill="tonexty", fillcolor="rgba(91,101,112,.13)", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MS, y=p75, mode="lines", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MS, y=p25, mode="lines", fill="tonexty", fillcolor=F.ACCENT_SOFT, line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MS, y=p50, mode="lines", line=dict(color=F.MUTED, dash="dash", width=1.4), hovertemplate=tr("mediana %{y:,.0f}") + "<extra></extra>"))
        call = ""
        if last >= 1:
            li = last - 1
            proj = ""
            if last < 12:
                ratio = lambda j, q: np.quantile(hist[:, j] / np.maximum(hist[:, li], 1), q)  # noqa: E731
                xs = MS[li:]
                lo, md, hi = ([cur[li] * ratio(j, q) for j in range(li, 12)] for q in (0.1, 0.5, 0.9))
                fig.add_trace(go.Scatter(x=xs, y=hi, mode="lines", line=dict(color=F.ACCENT, width=1, dash="dot"), hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=xs, y=lo, mode="lines", fill="tonexty", fillcolor="rgba(194,65,12,.10)", line=dict(color=F.ACCENT, width=1, dash="dot"), hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=xs, y=md, mode="lines", line=dict(color=F.ACCENT, width=2, dash="dash"), hovertemplate=tr("projeção %{y:,.0f}") + "<extra></extra>"))
                proj = tr(" Projeção para dezembro: <b>{m}</b> (faixa {a}–{b}, anos análogos).", m=fmt(md[-1]), a=fmt(lo[-1]), b=fmt(hi[-1]))
            fig.add_trace(go.Scatter(x=MS[:last], y=cur[:last], mode="lines+markers", line=dict(color=F.ACCENT, width=3), marker=dict(size=6),
                                     hovertemplate=tr("{y} até %{{x}}: %{{y:,.0f}}", y=Y) + "<extra></extra>"))
            at = hist[:, li]
            rank = int((at > cur[li]).sum()) + 1
            dd = (cur[li] - p50[li]) / p50[li] * 100 if p50[li] else 0
            call = tr("<b>{y}</b> até {m}: <b>{n}</b> focos, {d}% contra a mediana, <b>{r}</b> maior de {t} anos.",
                      y=Y, m=months_long()[li], n=fmt(cur[li]), d=f"{'+' if dd >= 0 else ''}{fmt(dd)}", r=ordinal(rank), t=len(at) + 1) + proj
        F.base_layout(fig, 260)
        return fig, dcc.Markdown(call, dangerously_allow_html=True)

    def clock_fig(v: pd.Series, D):
        Y = D.year
        med = [float(np.median([v.get(y * 12 + k, 0.0) for y in range(max(2012, repo.y0 + 1), Y)])) for k in range(12)]
        cur = [float(v.get(Y * 12 + k, np.nan)) if k <= D.month - 1 else None for k in range(12)]
        theta = [k * 30 + 15 for k in range(12)]
        pk = int(np.argmax(med))
        cm = D.month - 1
        share = med[cm] / med[pk] if med[pk] else 0
        phase = tr("Pico da temporada" if share >= .7 else "Fora de temporada" if share < .2 else ("Temporada subindo" if med[(cm + 1) % 12] > med[cm] else "Temporada descendo"))
        ML = months_long()
        fig = go.Figure()
        fig.add_trace(go.Barpolar(r=med, theta=theta, width=[26] * 12, marker_color="rgba(91,101,112,.25)", marker_line_color="#c9cfd6",
                                  customdata=ML, hovertemplate=tr("<b>%{customdata}</b><br>mediana: %{r:,.0f} focos") + "<extra></extra>"))
        fig.add_trace(go.Barpolar(r=cur, theta=theta, width=[11] * 12,
                                  marker_color=["#b42318" if (c is not None and c > m * 1.5) else F.ACCENT for c, m in zip(cur, med)],
                                  customdata=ML, hovertemplate=tr("<b>%{{customdata}} de {y}</b><br>%{{r:,.0f}} focos", y=Y) + "<extra></extra>"))
        ang = (cm + (D.day - 1) / 31) * 30
        rmax = max(max(med), max([c for c in cur if c is not None] or [0])) * 1.05 or 1
        fig.add_trace(go.Scatterpolar(r=[0, rmax], theta=[ang, ang], mode="lines", line=dict(color=F.FG, width=2.5), hoverinfo="skip"))
        fig.update_layout(height=320, margin=dict(l=30, r=30, t=20, b=20), paper_bgcolor="#fff", showlegend=False, font=F.FONT,
                          polar=dict(bgcolor="#fff", angularaxis=dict(direction="clockwise", rotation=90, tickvals=theta, ticktext=months(), gridcolor="#eceef1"),
                                     radialaxis=dict(showticklabels=False, gridcolor="#eceef1", range=[0, rmax])),
                          hoverlabel=dict(bgcolor=F.FG, font_color="#fff"), separators=F.separators())
        call = html.Span([html.B(phase), tr(". Pico típico em {p}. {m} costuma ter {s}% do volume do mês de pico. "
                                            "A linha preta marca {d}; barras laranja são {y}, vermelhas quando passam de 1,5× a mediana.",
                                            p=ML[pk], m=months()[cm], s=fmt(share * 100), d=f"{D:%d/%m}", y=Y)])
        return fig, call

    def sat_table(df: pd.DataFrame, D):
        if df.empty:
            return html.P(tr("Sem detecções nos últimos 30 dias."), className="note")
        rows = [html.Tr([html.Td(html.I(className="dot", style={"background": F.SAT_C.get(r.satelite, "#888")})), html.Td(r.satelite),
                         html.Td(f"{pd.Timestamp(r.ultimo):%d/%m %H:%M} UTC", className="num"), html.Td(fmt(r.hoje), className="num")]) for r in df.itertuples()]
        missing = [s_ for s_ in ("TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21") if s_ not in set(df["satelite"])]
        return [html.Table([html.Thead(html.Tr([html.Th(""), html.Th(tr("Satélite")), html.Th(tr("Última detecção")), html.Th(tr("Em {d}", d=f"{D:%d/%m}"))])), html.Tbody(rows)], className="tri"),
                html.P(tr("Sem dados recentes de: {s}. ", s=", ".join(missing)) if missing else "", className="note"),
                html.P(tr("A entrega do S-NPP foi encerrada em 01/11/2026; NOAA-20 e NOAA-21 seguem cobrindo o VIIRS."), className="note")]
