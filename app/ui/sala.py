"""Situation room page (/sala). AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Structure follows Endsley's situation awareness levels: perception (alerts, today's hotspots),
comprehension (priority queue, daily anomaly strip, priority quadrant) and projection (season outlook).
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from ..data.repository import Filtro, Repository
from ..data.sala import LABEL, RMIN, Sala
from . import figures as F
from .layout import nav

fmt, fmt1, fmtk, MESES, MESES_L = F.fmt, F.fmt1, F.fmtk, F.MESES, F.MESES_L
STATUS_C = {"crit": "#b42318", "alert": "#c96a00", "watch": "#9a7a00", "ok": "#3f8f6b", "below": "#2f6fb8"}
CLS_C = ["#2f6fb8", "#a9c8ea", "#ecedef", "#f8d3a8", "#f0a35a", "#d9582a", "#8f1d1f"]
CLS_L = ["½×", "¾×", "normal", "1,5×", "2×", "3×", "5×+"]
WIN_L = {1: "24 h", 7: "7 dias", 30: "30 dias"}


def ratio_class(r, R, Ex):
    if R < 3 and Ex < 3:
        return 2
    if r < 0.85 and Ex < 10:
        return 2
    return 0 if r < 0.6 else 1 if r < 0.85 else 2 if r < 1.5 else 3 if r < 2 else 4 if r < 3 else 5 if r < 5 else 6


def fx(r):
    return (fmt(r) if r >= 10 else fmt1(r)) + "×"


def go_btn(kind, uid, children, cls=""):
    return html.Button(children, id={"type": "sala-go", "k": kind, "id": uid}, n_clicks=0, className=cls)


def card(id_, eyebrow, title, question, *body, size="M"):
    return html.Section(className=f"scard s-{size}", id=id_, children=[
        html.Div(className="chd", children=[html.Span(eyebrow, className="eyebrow"), html.H3(title), html.P(question, className="q")]),
        html.Div(className="cbody", children=list(body))])


def sala_layout(repo: Repository) -> html.Div:
    if not (repo.ready and repo.has_daily):
        return html.Div(className="app", children=[
            html.Header(className="top", children=[html.Div(className="brand", children=[html.H1("Sala de Situação")]), nav("sala")]),
            html.Main(className="empty", children=[html.Section(className="sec", children=[
                html.H2("Faltam os agregados diários"), html.P("Os dados atuais foram processados antes dos agregados diários (dia_dep.parquet)."),
                html.P("Peça a quem administra o sistema para reprocessar os dados.", className="note")])])])
    s = Sala(repo)
    d = s.daily()
    D = d["D"]
    graph_cfg = {"displaylogo": False, "displayModeBar": False}
    return html.Div(className="app sala", children=[
        dcc.Store(id="sala-st", data={"win": 7, "kind": "ar", "uid": ""}),
        html.Header(className="top", children=[
            html.Div(className="brand", children=[html.H1("Sala de Situação · Focos de Calor"),
                                                   html.Small(f"Argentina · último dia com dados: {D:%d/%m/%Y} · esperado = média {d['baseline'][0]}–{d['baseline'][1]}")]),
            nav("sala"),
            html.Div(className="controls", children=[html.Span("Janela", className="note"),
                                                     dcc.RadioItems(id="sala-win", options=[{"label": v, "value": k} for k, v in WIN_L.items()], value=7, className="seg", inline=True)]),
        ]),
        html.Div(className="sala-body", children=[
            html.Section(className="alerts", children=[
                html.Div(className="acount", children=[html.Span("Alertas ativos", className="eyebrow"), html.Div(id="sala-acount", className="row"),
                                                       html.Span(id="sala-arule", className="note")]),
                html.Div(id="sala-alerts", className="alist")]),
            html.Section(className="scope", children=[
                html.Div([html.Nav(id="sala-crumbs", className="crumbs"), html.H2(id="sala-title"), html.Div(id="sala-stat", className="stat")]),
                html.Div(id="sala-kpis", className="skpis")]),
            html.Main(className="sgrid", children=[
                card("w-map", "Seleção", "Mapa de anomalia", "Onde está fora do normal? Clique para focar.",
                     dcc.Graph(id="sala-map", config={"scrollZoom": True, "displaylogo": False}, className="smap"), html.Div(id="sala-maplegend", className="maplegend")),
                card("w-tri", "Ação", "Fila de prioridade", "Quais lugares atender primeiro?", html.Div(id="sala-tri", className="tbl"),
                     html.P("Ordem: gravidade, quanto acima do esperado, volume e dias seguidos com focos. Clique numa linha para focar.", className="note")),
                card("w-strip", "Compreensão", "Anomalia diária · 90 dias", "Quem está acelerando agora?",
                     dcc.Graph(id="sala-strip", config=graph_cfg),
                     html.P("Cada linha é uma área; cada coluna, um dia (média de 3 dias). Azul: abaixo do esperado; laranja e vermelho: acima. A faixa destacada é a janela atual.", className="note"), size="L"),
                card("w-quad", "Compreensão", "Quadrante de prioridade", "É grande, é anormal ou os dois?", dcc.Graph(id="sala-quad", config=graph_cfg), size="S"),
                card("w-hoje", "Percepção", "Focos do último dia", "O que apareceu nas últimas passagens?", html.Div(id="sala-hoje"), size="S"),
                card("w-temp", "Projeção", "Temporada acumulada", "Como o ano se compara e onde deve terminar?",
                     html.Div(id="sala-temp-call", className="callout"), dcc.Graph(id="sala-temp", config=graph_cfg), size="S"),
                card("w-sat", "Confiança", "Estado dos satélites", "Os dados estão em dia?", html.Div(id="sala-sat"), size="S"),
            ]),
        ]),
    ])


def register_sala(app, repo: Repository) -> None:
    geo = repo.geo

    @app.callback(Output("sala-st", "data"),
                  Input("sala-win", "value"), Input({"type": "sala-go", "k": ALL, "id": ALL}, "n_clicks"),
                  Input("sala-map", "clickData"), Input("sala-quad", "clickData"), Input("sala-strip", "clickData"),
                  State("sala-st", "data"), prevent_initial_call=True)
    def control(win, clicks, mapc, quadc, stripc, st):
        st = dict(st)
        tid = ctx.triggered_id
        if tid == "sala-win":
            st["win"] = win
        elif isinstance(tid, dict) and ctx.triggered[0]["value"]:
            st.update(kind=tid["k"], uid=tid["id"])
        elif tid in ("sala-map", "sala-quad", "sala-strip"):
            data = {"sala-map": mapc, "sala-quad": quadc, "sala-strip": stripc}[tid]
            cd = data and data["points"][0].get("customdata")
            if not cd:
                return no_update
            st.update(kind=cd[0], uid=cd[1])
        else:
            return no_update
        return st

    @app.callback(
        Output("sala-acount", "children"), Output("sala-arule", "children"), Output("sala-alerts", "children"),
        Output("sala-crumbs", "children"), Output("sala-title", "children"), Output("sala-stat", "children"), Output("sala-kpis", "children"),
        Output("sala-map", "figure"), Output("sala-maplegend", "children"), Output("sala-tri", "children"),
        Output("sala-strip", "figure"), Output("sala-quad", "figure"), Output("sala-hoje", "children"),
        Output("sala-temp", "figure"), Output("sala-temp-call", "children"), Output("sala-sat", "children"),
        Input("sala-st", "data"))
    def render(st):
        s = Sala(repo)
        win, kind, uid = st["win"], st["kind"], st["uid"]
        deps_m, provs_m = s.metrics(win)
        d = s.daily()
        D = d["D"]
        wl = WIN_L[win]

        # ---------------- scope
        if kind == "prov":
            scope_deps = geo.deps_of.get(uid, [])
            units, unit_kind, scope_row, name = deps_m.loc[scope_deps], "dep", provs_m.loc[uid], geo.provincias[uid].nome
        elif kind == "dep":
            pid = geo.departamentos[uid].parent
            scope_deps = [uid]
            units, unit_kind, scope_row, name = deps_m.loc[geo.deps_of.get(pid, [])], "dep", deps_m.loc[uid], geo.departamentos[uid].nome
        else:
            scope_deps = list(geo.departamentos)
            units, unit_kind, name = provs_m, "prov", "Argentina"
            from ..data.sala import _frame
            scope_row = _frame(d["A"].sum().to_frame().T, d["E"].sum().to_frame().T, d["F"].max().to_frame().T, win).iloc[0]
        tri = deps_m.loc[scope_deps] if kind == "prov" else (units if kind == "dep" else deps_m)

        # ---------------- alerts (always the whole country)
        al = deps_m[deps_m["status"].isin(["crit", "alert", "watch"])].sort_values("score", ascending=False)
        cnt = al["status"].value_counts()
        acount = [html.Span([str(cnt.get(k, 0)), html.Small(lbl)], style={"color": STATUS_C[k]}) for k, lbl in (("crit", "crít."), ("alert", "alerta"), ("watch", "atenção"))]
        alerts = [go_btn("dep", i, [html.Span(LABEL[r.status], className=f"pill {r.status}"), html.Span(f"{r.nome} · {r['sub']}", className="pl"),
                                    html.Span([html.B(fx(r.ratio)), " o esperado · ", html.B(fmt(r.R)), f" focos em {wl} · ativo há ", html.B(str(r.pers)), " d"], className="hd")],
                         cls=f"acard {r.status}") for i, r in al.head(14).iterrows()] or [html.Span("Nenhum departamento fora do normal nesta janela.", className="note")]

        crumbs = [go_btn("ar", "", "Argentina")]
        if kind in ("prov", "dep"):
            pid = uid if kind == "prov" else geo.departamentos[uid].parent
            crumbs += [" › ", go_btn("prov", pid, geo.provincias[pid].nome)]
        if kind == "dep":
            crumbs += [" › ", html.Span(name, className="cur")]
        stat = [html.Span(LABEL[scope_row["status"]], className=f"pill {scope_row['status']}"),
                html.Span(f"{fx(scope_row['ratio'])} o esperado para {wl} nesta época do ano", className="note")]
        tr = scope_row["trend"]
        today_cells = s.today_cells(None if kind == "ar" else scope_deps)
        n_new = int(today_cells["novo"].sum()) if len(today_cells) else 0
        kp = [("Focos · " + wl, fmtk(scope_row["R"]), f"{'▲' if tr > .15 else '▼' if tr < -.15 else '▶'} {'+' if tr >= 0 else ''}{fmt(min(tr, 9.99) * 100)}% vs. {wl} anteriores"),
              ("Esperado", fmtk(scope_row["Ex"]), f"média {d['baseline'][0]}–{d['baseline'][1]}"),
              ("Relação", fx(scope_row["ratio"]), LABEL[scope_row["status"]].lower()),
              (f"Em {D:%d/%m}", fmt(scope_row["today"]), f"{n_new} célula{'s' if n_new != 1 else ''} nova{'s' if n_new != 1 else ''} de 0,1°"),
              ("Persistência", f"{int(scope_row['pers'])} d", "dias seguidos com focos"),
              ("FRP máximo", f"{fmt(scope_row['frp'])} MW" if scope_row["frp"] else "—", "maior intensidade na janela")]
        kpis = [html.Div([html.Span(a, className="k"), html.Span(b, className="v"), html.Span(c, className="d")], className="kpi") for a, b, c in kp]

        mapfig, maplegend = sala_map(units, unit_kind, kind, uid)
        tri_el = triage(tri.sort_values("score", ascending=False).head(12), kind, uid, d, win)
        strip = strip_fig(units.sort_values("score", ascending=False).head(12), unit_kind, d, win)
        quad = quad_fig(units, unit_kind, win, kind, uid)
        hoje = today_list(today_cells, D)
        temp, call = season_fig(kind, uid, D)
        sat = sat_table(s.sat_status(), D)
        return (acount, f"Crítico: ≥3× o esperado e ≥{RMIN[win]} focos em {wl}", alerts, crumbs, name, stat, kpis,
                mapfig, maplegend, tri_el, strip, quad, hoje, temp, call, sat)

    # ------------------------------------------------------------------ pieces
    def sala_map(units: pd.DataFrame, unit_kind: str, kind: str, uid: str):
        traces = []
        grey = [[0, "#eceae4"], [1, "#eceae4"]]
        ids = list(geo.paises)
        traces.append(go.Choroplethmap(geojson=geo.fc["pais"], locations=ids, z=[0] * len(ids), featureidkey="id", colorscale=grey, showscale=False,
                                       marker_opacity=0.5, marker_line_width=0.5, hoverinfo="skip"))
        if unit_kind == "dep":
            pids = list(geo.provincias)
            traces.append(go.Choroplethmap(geojson=geo.fc["prov"], locations=pids, z=[0] * len(pids), featureidkey="id", colorscale=grey, showscale=False,
                                           marker_opacity=0.6, marker_line_width=0.8, customdata=[["prov", p, geo.provincias[p].nome] for p in pids],
                                           hovertemplate="%{customdata[2]}<br><i>clique para focar</i><extra></extra>"))
            fc = geo.subset("dep", units.index)
        else:
            fc = geo.fc["prov"]
        z = [ratio_class(r.ratio, r.R, r.Ex) for r in units.itertuples()]
        cd = [[unit_kind, i, f"<b>{r.nome}</b><br>{LABEL[r.status]} · {fx(r.ratio)} o esperado<br>{fmt(r.R)} focos (esperado {fmt1(r.Ex)})<br>"
                                f"Último dia: {fmt(r.today)} · ativo há {r.pers} d<br><i>clique para focar</i>"] for i, r in units.iterrows()]
        scale = [[k / 6, c] for k, c in enumerate(CLS_C)]
        traces.append(go.Choroplethmap(geojson=fc, locations=list(units.index), z=z, zmin=0, zmax=6, featureidkey="id", colorscale=scale, showscale=False,
                                       marker_opacity=0.9, marker_line_width=0.6, marker_line_color="#8f877b", customdata=cd,
                                       hovertemplate="%{customdata[2]}<extra></extra>"))
        layers = []
        if kind in ("prov", "dep"):
            u = geo.unit(kind, uid)
            layers.append(dict(sourcetype="geojson", source={"type": "FeatureCollection", "features": [u.feature]}, type="line", color="#111", line=dict(width=3)))
            bbox = u.bbox if kind == "prov" else geo.provincias[u.parent].bbox
        else:
            bbox = geo.paises["ARG"].bbox
        center, zoom = F.zoom_for(bbox, 520, 430)
        fig = go.Figure(traces)
        fig.update_layout(map=dict(style="carto-positron", center=center, zoom=zoom, layers=layers), margin=dict(l=0, r=0, t=0, b=0),
                          height=430, showlegend=False, uirevision=f"{kind}:{uid}", hoverlabel=dict(bgcolor=F.FG, font_color="#fff"))
        legend = [html.Div("Focos na janela vs. esperado", className="note"),
                  html.Div([html.Span([html.I(style={"background": c}), lab]) for c, lab in zip(CLS_C, CLS_L)], className="mlr")]
        return fig, legend

    def triage(rows: pd.DataFrame, kind, uid, d, win):
        head = html.Tr([html.Th(h) for h in ("Status", "Lugar", "Focos", "Esperado", "× normal", "Tendência", "Dias ativos", "FRP máx.", "Últimos 30 dias")])
        body = []
        A, E = d["A"], d["E"]
        for i, r in rows.iterrows():
            t = r.trend
            arrow, cls = ("▲", "up") if t > .15 else ("▼", "dn") if t < -.15 else ("▶", "fl")
            a30, e30 = A.loc[i].to_numpy()[-30:], E.loc[i].to_numpy()[-30:]
            mx = max(a30.max(), e30.max(), 1)
            bars = [html.I(style={"height": f"{max(1, v / mx * 22):.0f}px", "background": "var(--accent)" if k >= 30 - win else "#c9cfd6"}) for k, v in enumerate(a30)]
            body.append(html.Tr(className="row" + (" sel" if kind == "dep" and uid == i else ""), children=[
                html.Td(html.Span(LABEL[r.status], className=f"pill {r.status}")),
                html.Td(go_btn("dep", i, [r.nome, html.Small(r['sub'])], cls="plbtn")),
                html.Td(fmt(r.R), className="num"), html.Td(fmt1(r.Ex), className="num"), html.Td(html.B(fx(r.ratio)), className="num"),
                html.Td(f"{arrow} {'+' if t >= 0 else ''}{fmt(min(t, 9.99) * 100)}%", className=f"trend {cls}"),
                html.Td(str(r.pers), className="num"), html.Td(fmt(r.frp) if r.frp else "—", className="num"),
                html.Td(html.Span(bars, className="spark"))]))
        return html.Table([html.Thead(head), html.Tbody(body)], className="tri") if body else html.P("Sem focos nesta área.", className="note")

    def strip_fig(units: pd.DataFrame, unit_kind: str, d, win):
        A, E = d["A"], d["E"]
        parent = {k: u.parent for k, u in geo.departamentos.items()}
        if unit_kind == "prov":
            A = A.groupby(pd.Series(parent).reindex(A.index)).sum()
            E = E.groupby(pd.Series(parent).reindex(E.index)).sum()
        a = A.loc[units.index].T.rolling(3, min_periods=1).sum().T.iloc[:, -90:]
        e = E.loc[units.index].T.rolling(3, min_periods=1).sum().T.iloc[:, -90:]
        z = np.log2((a.to_numpy() + 1) / (e.to_numpy() + 1)).clip(-3, 3)
        names = [r.nome[:24] for r in units.itertuples()]
        days = a.columns
        txt = [[f"<b>{names[i]}</b> · {days[k]:%d/%m}<br>{fmt(A.loc[u].iloc[-90 + k])} focos no dia (esperado {fmt1(E.loc[u].iloc[-90 + k])})<br>3 dias: {fx(2 ** z[i, k])} o esperado"
                for k in range(len(days))] for i, u in enumerate(units.index)]
        scale = [[0, "#2f6fb8"], [0.33, "#a9c8ea"], [0.5, "#f4f4f2"], [0.62, "#f8d3a8"], [0.75, "#f0a35a"], [0.88, "#d9582a"], [1, "#8f1d1f"]]
        fig = go.Figure(go.Heatmap(z=z, x=days, y=names, zmin=-3, zmax=3, colorscale=scale, showscale=False, xgap=0.5, ygap=2, text=txt,
                                   hovertemplate="%{text}<extra></extra>", customdata=[[[unit_kind, u]] * len(days) for u in units.index]))
        F.base_layout(fig, 40 + 26 * len(units))
        fig.update_layout(margin=dict(l=150, r=10, t=6, b=24))
        fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(family="IBM Plex Sans", size=11, color=F.FG))
        fig.add_vrect(x0=days[-win] - pd.Timedelta(hours=12), x1=days[-1] + pd.Timedelta(hours=12), line=dict(color=F.FG, width=1.5, dash="dot"), fillcolor="rgba(0,0,0,0)")
        return fig

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
            fig.add_annotation(x=xx, y=yy, text=t, showarrow=False, xanchor=anc, yanchor="top" if yy > 0.1 else "bottom", font=dict(size=9.5, color=c))
        fig.add_vline(x=1, line=dict(color="#b42318", dash="dash", width=1))
        fig.add_hline(y=yl, line=dict(color="#b42318", dash="dash", width=1))
        top = set(u.sort_values("score", ascending=False).query("status != 'ok'").head(5).index)
        fig.add_trace(go.Scatter(x=x, y=y, mode="markers+text", text=[r.nome[:16] if i in top else "" for i, r in u.iterrows()], textposition="middle right",
                                 textfont=dict(size=10, color=F.FG),
                                 marker=dict(size=[7 + np.sqrt(p + 1) * 2.2 for p in u["pers"]], color=[STATUS_C[s_] for s_ in u["status"]],
                                             opacity=[0.45 if s_ == "ok" else 0.85 for s_ in u["status"]],
                                             line=dict(color=["#111" if (kind == unit_kind and uid == i) else "#fff" for i in u.index], width=[2.5 if (kind == unit_kind and uid == i) else 1 for i in u.index])),
                                 customdata=[[unit_kind, i, f"<b>{r.nome}</b><br>{LABEL[r.status]} · {fx(r.ratio)} o esperado<br>{fmt(r.R)} focos · ativo há {r.pers} d"] for i, r in u.iterrows()],
                                 hovertemplate="%{customdata[2]}<extra></extra>"))
        F.base_layout(fig, 340)
        fig.update_xaxes(range=[-2.1, 4.2], tickvals=[-2, -1, 0, 1, 2, 3, 4], ticktext=["¼×", "½×", "1×", "2×", "4×", "8×", "16×"], title=dict(text="quantas vezes o esperado", font=dict(size=10)))
        fig.update_yaxes(range=[0, ymax], tickvals=[0, 1, 2, 3, 4], ticktext=["0", "9", "99", "999", "9.999"], title=dict(text="focos (escala log)", font=dict(size=10)))
        fig.update_layout(margin=dict(l=50, r=10, t=8, b=40))
        return fig

    def today_list(cells: pd.DataFrame, D):
        if cells is None or not len(cells):
            return html.P(f"Nenhum foco em {D:%d/%m/%Y} nesta área.", className="note")
        tot, new = int(cells["n"].sum()), int(cells["novo"].sum())
        items = []
        for r in cells.head(8).itertuples():
            dep = geo.departamentos.get(r.dep_id)
            items.append(html.Li(go_btn("dep", r.dep_id, [
                html.Span([str(r.n), html.Small("focos")], className="n"),
                html.Span([html.B(dep.nome if dep else "—"), html.Span(f"{geo.provincias[dep.parent].nome if dep else ''} · {abs(r.lat):.2f}°S {abs(r.lon):.2f}°W")], className="w"),
                html.Span([html.Span("NOVO", className="new") if r.novo else None, html.Span(f"{pd.Timestamp(r.ultimo):%H:%M} UTC"),
                           html.Span([html.I(style={"background": F.SAT_C.get(x, '#888')}, title=x) for x in r.sats], className="sats")], className="r")],
                cls="feedbtn")))
        return [html.Div([html.B(fmt(tot)), f" focos em {D:%d/%m} em ", html.B(str(len(cells))), " células de 0,1° · ", html.B(str(new)),
                          " sem focos nos 7 dias anteriores"], className="callout"), html.Ul(items, className="feed")]

    def season_fig(kind, uid, D):
        f = Filtro(kind="pais", uid="ARG") if kind == "ar" else Filtro(kind=kind, uid=uid)
        f = Filtro(kind=f.kind, uid=f.uid, serie="harm" if repo.has_harm else "raw")
        v = repo.series(f)
        Y = D.year
        last = D.month - 1 if D.day < 28 else D.month  # last complete month (1-based)
        def cum(y):
            return np.cumsum([v.get(y * 12 + k, 0.0) for k in range(12)])
        hist = np.array([cum(y) for y in range(max(2012, repo.y0 + 1), Y)])
        cur = cum(Y)[:max(last, 1)]
        mn, mx_, p25, p50, p75 = hist.min(0), hist.max(0), *np.quantile(hist, [0.25, 0.5, 0.75], 0)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=MESES, y=mx_, mode="lines", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MESES, y=mn, mode="lines", fill="tonexty", fillcolor="rgba(91,101,112,.13)", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MESES, y=p75, mode="lines", line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MESES, y=p25, mode="lines", fill="tonexty", fillcolor=F.ACCENT_SOFT, line_width=0, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=MESES, y=p50, mode="lines", line=dict(color=F.MUTED, dash="dash", width=1.4), hovertemplate="mediana %{y:,.0f}<extra></extra>"))
        call = ""
        if last >= 1:
            li = last - 1
            if last < 12:
                rat = hist[:, 11] / np.maximum(hist[:, li], 1)
                pr = [cur[li] * q for q in np.quantile(rat, [0.1, 0.5, 0.9])]
                xs = MESES[li:]
                lo = [cur[li] * np.quantile(hist[:, j] / np.maximum(hist[:, li], 1), 0.1) for j in range(li, 12)]
                hi = [cur[li] * np.quantile(hist[:, j] / np.maximum(hist[:, li], 1), 0.9) for j in range(li, 12)]
                md = [cur[li] * np.quantile(hist[:, j] / np.maximum(hist[:, li], 1), 0.5) for j in range(li, 12)]
                fig.add_trace(go.Scatter(x=xs, y=hi, mode="lines", line=dict(color=F.ACCENT, width=1, dash="dot"), hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=xs, y=lo, mode="lines", fill="tonexty", fillcolor="rgba(194,65,12,.10)", line=dict(color=F.ACCENT, width=1, dash="dot"), hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=xs, y=md, mode="lines", line=dict(color=F.ACCENT, width=2, dash="dash"), hovertemplate="projeção %{y:,.0f}<extra></extra>"))
                proj = f" Projeção para dezembro: <b>{fmt(pr[1])}</b> (faixa {fmt(pr[0])}–{fmt(pr[2])}, anos análogos)."
            else:
                proj = ""
            fig.add_trace(go.Scatter(x=MESES[:last], y=cur[:last], mode="lines+markers", line=dict(color=F.ACCENT, width=3), marker=dict(size=6),
                                     hovertemplate=f"{Y} até %{{x}}: %{{y:,.0f}}<extra></extra>"))
            at = hist[:, li]
            rank = int((at > cur[li]).sum()) + 1
            dd = (cur[li] - p50[li]) / p50[li] * 100 if p50[li] else 0
            call = (f"<b>{Y}</b> até {MESES_L[li]}: <b>{fmt(cur[li])}</b> focos, {'+' if dd >= 0 else ''}{fmt(dd)}% contra a mediana, "
                    f"<b>{rank}º</b> maior de {len(at) + 1} anos.{proj}")
        F.base_layout(fig, 260)
        return fig, dcc.Markdown(call, dangerously_allow_html=True)

    def sat_table(df: pd.DataFrame, D):
        if df.empty:
            return html.P("Sem detecções nos últimos 30 dias.", className="note")
        rows = [html.Tr([html.Td(html.I(className="dot", style={"background": F.SAT_C.get(r.satelite, "#888")})), html.Td(r.satelite),
                         html.Td(f"{pd.Timestamp(r.ultimo):%d/%m %H:%M} UTC", className="num"), html.Td(fmt(r.hoje), className="num")]) for r in df.itertuples()]
        missing = [s_ for s_ in ("TERRA", "AQUA", "SNPP", "NOAA20", "NOAA21") if s_ not in set(df["satelite"])]
        return [html.Table([html.Thead(html.Tr([html.Th(""), html.Th("Satélite"), html.Th("Última detecção"), html.Th(f"Em {D:%d/%m}")])), html.Tbody(rows)], className="tri"),
                html.P(("Sem dados recentes de: " + ", ".join(missing) + ". ") if missing else "", className="note"),
                html.P("A entrega do S-NPP foi encerrada em 01/11/2026; NOAA-20 e NOAA-21 seguem cobrindo o VIIRS.", className="note")]
