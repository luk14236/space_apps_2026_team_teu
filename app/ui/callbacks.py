"""Callbacks: one controller updates the shared state; renderers draw from it.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from ..data.repository import Filtro, Repository
from . import figures as F

MESES, MESES_L, fmt, fmt1, fmtk = F.MESES, F.MESES_L, F.fmt, F.fmt1, F.fmtk


def filtro(st: dict, with_time: bool = True) -> Filtro:
    return Filtro(kind=st["kind"], uid=st["uid"] or "", shape=tuple(tuple(p) for p in st["shape"]),
                  t0=st["t0"] if with_time else 0, t1=st["t1"] if with_time else 10**6,
                  cal=tuple(st["cal"]) if with_time else (), sats=tuple(sorted(st["sats"])), serie=st["serie"])


def mlabel(mi: int) -> str:
    return f"{MESES[mi % 12]}/{mi // 12}"


def register(app, repo: Repository) -> None:
    geo = repo.geo

    # ------------------------------------------------------------ helpers that depend on repo
    def scope_name(st) -> str:
        if st["kind"] == "shape":
            return "Área desenhada"
        if st["kind"] == "all":
            return "América do Sul"
        u = geo.unit(st["kind"], st["uid"])
        return u.nome if u else st["uid"]

    def scope_bbox(st):
        if st["kind"] == "shape":
            xs = [p[0] for p in st["shape"]]; ys = [p[1] for p in st["shape"]]
            return (min(xs), min(ys), max(xs), max(ys))
        if st["kind"] == "all":
            return (-82, -56, -34, 13)
        return geo.unit(st["kind"], st["uid"]).bbox

    def scope_area(st) -> float:
        if st["kind"] == "shape":
            import shapely
            poly = shapely.Polygon(st["shape"])
            lat = poly.centroid.y
            return poly.area * 111.32 * np.cos(np.radians(lat)) * 110.57
        if st["kind"] == "all":
            return sum(u.area_km2 for u in geo.paises.values())
        return geo.unit(st["kind"], st["uid"]).area_km2

    def grid_deg(st) -> float:
        x0, y0, x1, y1 = scope_bbox(st)
        span = max(x1 - x0, y1 - y0)
        return 0.5 if span > 20 else 0.25 if span > 8 else 0.1 if span > 3 else 0.05 if span > 1 else 0.025

    def cal_ok(st):
        c = st["cal"]
        if not c:
            return lambda k: True
        if c[0] == "cell":
            return lambda k: k // 12 == c[1] and k % 12 + 1 == c[2]
        if c[0] == "month":
            return lambda k: k % 12 + 1 == c[1]
        return lambda k: k // 12 == c[1]

    def summary(st) -> dict:
        f = filtro(st)
        s = repo.series(f)
        ok = cal_ok(st)
        mask = [(st["t0"] <= k <= st["t1"]) and ok(k) for k in s.index]
        sel = s[mask]
        tot = float(sel.sum())
        bym = sel.groupby(sel.index % 12).sum()
        byy = sel.groupby(sel.index // 12).sum()
        pm = int(bym.idxmax()) if len(bym) and bym.max() > 0 else 0
        py = int(byy.idxmax()) if len(byy) and byy.max() > 0 else repo.y1
        ref = (st["cal"][1] * 12 + st["cal"][2] - 1) if st["cal"] and st["cal"][0] == "cell" else st["t1"]
        hist = [s.get(y * 12 + ref % 12, np.nan) for y in range(repo.y0 + 1, repo.y1 + 1) if y != ref // 12]
        med = float(np.nanmedian(hist)) if hist else 0
        rv = float(s.get(ref, 0))
        pct = (rv - med) / med * 100 if med else 0
        return {"tot": tot, "dens": tot / max(scope_area(st), 1) * 1000, "pm": pm, "pm_share": bym.get(pm, 0) / tot * 100 if tot else 0,
                "py": py, "pyv": float(byy.get(py, 0)), "ref": ref, "rv": rv, "med": med, "pct": pct}

    # ------------------------------------------------------------ controller
    @app.callback(
        Output("st", "data"), Output("search", "value"),
        Input("map", "clickData"), Input("map", "selectedData"),
        Input({"type": "crumb", "k": ALL, "id": ALL}, "n_clicks"), Input({"type": "rank", "k": ALL, "id": ALL}, "n_clicks"),
        Input({"type": "chip", "x": ALL}, "n_clicks"), Input({"type": "preset", "p": ALL}, "n_clicks"),
        Input("search", "value"), Input("cal", "clickData"), Input("anom", "clickData"), Input("timeline", "selectedData"),
        Input("tick", "n_intervals"), Input("clear-shape", "n_clicks"), Input("play", "n_clicks"), Input("viewbtn", "n_clicks"),
        Input("serie", "value"), Input("sats", "value"), Input("layer", "value"), Input("fy", "value"), Input("tool", "value"),
        State("st", "data"), prevent_initial_call=True)
    def control(click, selected, crumbs, ranks, chips, presets, search, calc, anomc, tsel, tick, clear, play, view,
                serie, sats, layer, fy, tool, st):
        st = dict(st)
        tid = ctx.triggered_id
        trig_val = ctx.triggered[0]["value"] if ctx.triggered else None
        reset_search = no_update

        def go_to(kind, uid):
            st.update(kind=kind, uid=uid, shape=[])

        if tid == "map" and ctx.triggered[0]["prop_id"].endswith("clickData") and click:
            cd = click["points"][0].get("customdata")
            if cd and cd[0] in ("pais", "prov", "dep"):
                go_to(cd[0], cd[1])
            elif cd and cd[0] == "cell":
                g, gx, gy = cd[3], cd[1], cd[2]
                st.update(kind="shape", uid="", shape=[[gx * g, gy * g], [(gx + 1) * g, gy * g], [(gx + 1) * g, (gy + 1) * g], [gx * g, (gy + 1) * g]])
        elif tid == "map" and ctx.triggered[0]["prop_id"].endswith("selectedData") and selected:
            box = (selected.get("range") or {})
            lasso = (selected.get("lassoPoints") or {})
            pts = None
            for key in ("map", "mapbox"):
                if key in box:
                    (x0, y0), (x1, y1) = box[key]
                    pts = [[min(x0, x1), min(y0, y1)], [max(x0, x1), min(y0, y1)], [max(x0, x1), max(y0, y1)], [min(x0, x1), max(y0, y1)]]
                elif key in lasso:
                    pts = lasso[key]
            if pts and len(pts) >= 3:
                st.update(kind="shape", uid="", shape=[[round(p[0], 4), round(p[1], 4)] for p in pts], tool="pan")
        elif isinstance(tid, dict) and tid.get("type") in ("crumb", "rank") and trig_val:
            k, uid = tid["k"], tid["id"]
            if k == "cell":
                gx, gy, g = (float(v) for v in uid.split(":"))
                st.update(kind="shape", uid="", shape=[[gx * g, gy * g], [(gx + 1) * g, gy * g], [(gx + 1) * g, (gy + 1) * g], [gx * g, (gy + 1) * g]])
            else:
                go_to(k, uid)
        elif isinstance(tid, dict) and tid.get("type") == "chip" and trig_val:
            x = tid["x"]
            if x == "shape":
                st.update(kind="pais", uid="ARG", shape=[])
            elif x == "time":
                st.update(t0=repo.mi0, t1=repo.mi1)
            elif x == "cal":
                st["cal"] = []
            elif x == "sats":
                st["sats"] = list(repo.sats)
        elif isinstance(tid, dict) and tid.get("type") == "preset" and trig_val:
            p = tid["p"]
            st.update(t0=repo.mi0 if p == "all" else repo.mi1 - (59 if p == "5y" else 11), t1=repo.mi1, playing=False)
        elif tid == "search" and search:
            k, uid = search.split(":", 1)
            go_to(k, uid)
            reset_search = None
        elif tid in ("cal", "anom") and (calc or anomc):
            cd = (calc if tid == "cal" else anomc)["points"][0].get("customdata")
            if cd:
                new = [cd[0], int(cd[1])] + ([int(cd[2])] if cd[0] == "cell" else [])
                st["cal"] = [] if st["cal"] == new else new
        elif tid == "timeline" and tsel and tsel.get("range"):
            x0, x1 = tsel["range"]["x"]
            st.update(t0=max(repo.mi0, int(round(min(x0, x1) + 0.5))), t1=min(repo.mi1, int(round(max(x0, x1) - 0.5))))
            st["t1"] = max(st["t1"], st["t0"])
        elif tid == "tick":
            if st["t1"] >= repo.mi1:
                st["playing"] = False
            else:
                st.update(t0=st["t0"] + 1, t1=st["t1"] + 1)
        elif tid == "play":
            if not st["playing"]:
                if st["t1"] - st["t0"] >= repo.mi1 - repo.mi0 - 1 or st["t1"] >= repo.mi1:
                    st.update(t0=repo.mi0, t1=repo.mi0 + 11)
            st["playing"] = not st["playing"]
        elif tid == "clear-shape":
            if st["kind"] == "shape":
                st.update(kind="pais", uid="ARG", shape=[])
        elif tid == "viewbtn":
            st["mode"] = "map" if st["mode"] == "dash" else "dash"
        elif tid == "serie":
            st["serie"] = serie
        elif tid == "sats":
            st["sats"] = sats or []
        elif tid == "layer":
            st["layer"] = layer
        elif tid == "fy":
            st["fy"] = fy
        elif tid == "tool":
            st["tool"] = tool
        else:
            return no_update, no_update
        return st, reset_search

    # ------------------------------------------------------------ panel
    @app.callback(
        Output("crumbs", "children"), Output("scope-title", "children"), Output("chips", "children"), Output("kpis", "children"),
        Output("cal", "figure"), Output("cal-legend", "children"), Output("harm", "figure"), Output("harm-note", "children"),
        Output("cum", "figure"), Output("cum-call", "children"), Output("cum-title", "children"), Output("anom", "figure"),
        Output("rank-title", "children"), Output("rank", "children"),
        Output("timeline", "figure"), Output("tl-range", "children"), Output("tl-total", "children"),
        Output("tick", "disabled"), Output("play", "children"), Output("main", "className"), Output("viewlbl", "children"),
        Input("st", "data"))
    def render_panel(st):
        f = filtro(st)
        m = repo.monthly(f)
        s = repo.series(f)
        ok = cal_ok(st)

        # breadcrumb + chips
        crumbs = [html.Button("América do Sul", id={"type": "crumb", "k": "all", "id": "all"}, n_clicks=0)]
        k, uid = st["kind"], st["uid"]
        if k in ("prov", "dep") or (k == "pais" and uid == "ARG"):
            crumbs += [" › ", html.Button("Argentina", id={"type": "crumb", "k": "pais", "id": "ARG"}, n_clicks=0)]
            if k in ("prov", "dep"):
                pid = uid if k == "prov" else geo.departamentos[uid].parent
                crumbs += [" › ", html.Button(geo.provincias[pid].nome, id={"type": "crumb", "k": "prov", "id": pid}, n_clicks=0)]
            if k == "dep":
                crumbs += [" › ", html.Span(geo.departamentos[uid].nome, className="cur")]
        elif k == "pais":
            crumbs += [" › ", html.Span(geo.paises[uid].nome, className="cur")]
        elif k == "shape":
            crumbs += [" › ", html.Span("Área desenhada", className="cur")]
        chips = []
        if k == "shape":
            chips.append(("shape", f"Área desenhada · {fmt(scope_area(st))} km²"))
        if st["t0"] != repo.mi0 or st["t1"] != repo.mi1:
            chips.append(("time", f"{mlabel(st['t0'])} – {mlabel(st['t1'])}"))
        if st["cal"]:
            c = st["cal"]
            chips.append(("cal", f"Calendário: {MESES[c[2]-1]}/{c[1]}" if c[0] == "cell" else f"Só {MESES_L[c[1]-1]}" if c[0] == "month" else f"Só {c[1]}"))
        if set(st["sats"]) != set(repo.sats):
            chips.append(("sats", "Satélites: " + ", ".join(sorted(st["sats"])) if st["sats"] else "Nenhum satélite"))
        chip_el = [html.Span([t, html.Button("×", id={"type": "chip", "x": x}, n_clicks=0, title="Remover filtro")], className="chip") for x, t in chips] \
            or [html.Span("Clique no mapa para descer de nível (país › província › departamento › grade) ou desenhe uma área.", className="note")]

        # KPIs
        sm = summary(st)
        cls = "flat" if abs(sm["pct"]) < 15 else ("up" if sm["pct"] > 0 else "down")
        lbl = {"flat": "perto da mediana", "up": "acima da mediana", "down": "abaixo da mediana"}[cls]
        serie_lbl = {"harm": "harmonizados", "modis": "só MODIS", "raw": "MODIS + VIIRS (bruto)"}[st["serie"] if (st["serie"] != "harm" or repo.has_harm) else "raw"]
        kpis = [
            html.Div([html.Span("Focos no período", className="k"), html.Span(fmtk(sm["tot"]), className="v"), html.Span(f"{fmt1(sm['dens'])} por 1.000 km² · {serie_lbl}", className="d")], className="kpi"),
            html.Div([html.Span("Pico da temporada", className="k"), html.Span(MESES[sm["pm"]], className="v"), html.Span(f"{fmt1(sm['pm_share'])}% dos focos", className="d")], className="kpi"),
            html.Div([html.Span("Ano recorde", className="k"), html.Span(str(sm["py"]), className="v"), html.Span(f"{fmtk(sm['pyv'])} focos", className="d")], className="kpi"),
            html.Div([html.Span(f"{MESES[sm['ref'] % 12]}/{sm['ref'] // 12} vs. mediana", className="k"), html.Span(f"{'+' if sm['pct'] > 0 else ''}{fmt(sm['pct'])}%", className="v"),
                      html.Span(lbl, className=f"pill {cls}")], className="kpi"),
        ]

        calfig = F.calendar(m, s, st["t0"], st["t1"], tuple(st["cal"]))
        cal_leg = [html.Span([html.I(className="sw", style={"background": c}), t]) for c, t in F.calendar_legend(s)] + \
                  [html.Span([html.I(className="ln dash acc"), "entrada do VIIRS (2012)"])]
        harmfig, harm_note = F.harmonization(m, repo.has_harm)
        fy = st["fy"] or (st["cal"][1] if st["cal"] and st["cal"][0] in ("cell", "year") else st["t1"] // 12)
        fy = min(max(fy, repo.y0 + 1), repo.y1)
        cumfig, call = F.cumulative(s, fy, repo.y0 + 1, repo.y1)
        anomfig = F.monthly_anomaly(s, fy, repo.y0 + 1, repo.y1)

        rank_title, rows = ranking(st)
        tl = F.timeline(s, st["t0"], st["t1"], ok)
        tl_total = sum(v for kk, v in s.items() if st["t0"] <= kk <= st["t1"] and ok(kk))
        return (crumbs, scope_name(st), chip_el, kpis,
                calfig, cal_leg, harmfig, dcc.Markdown(harm_note, dangerously_allow_html=True),
                cumfig, dcc.Markdown(call, dangerously_allow_html=True), f"{fy} contra o histórico", anomfig,
                rank_title, rows, tl, f"{mlabel(st['t0'])} – {mlabel(st['t1'])}", f"{fmt(tl_total)} focos",
                not st["playing"], "❚❚ Pausar" if st["playing"] else "▶ Reproduzir",
                "main " + st["mode"], "Expandir mapa" if st["mode"] == "dash" else "Voltar ao painel")

    def ranking(st):
        f = filtro(st)
        k, uid = st["kind"], st["uid"]
        if k == "all":
            df, kind, title = repo.territories("pais", f), "pais", "Países com mais focos"
            names = {u: geo.paises[u].nome for u in df["id"]}; areas = {u: geo.paises[u].area_km2 for u in df["id"]}
        elif k == "pais" and uid == "ARG":
            df, kind, title = repo.territories("prov", f), "prov", "Províncias com mais focos"
            names = {u: geo.provincias[u].nome for u in df["id"] if u in geo.provincias}; areas = {u: geo.provincias[u].area_km2 for u in names}
        elif k == "prov":
            df, kind, title = repo.territories("dep", f, uid), "dep", "Departamentos com mais focos"
            names = {u: geo.departamentos[u].nome for u in df["id"] if u in geo.departamentos}; areas = {u: geo.departamentos[u].area_km2 for u in names}
        else:
            deg = 0.05 if k in ("dep", "shape") else 0.25
            g = repo.grid(f, deg)
            if g.empty:
                return "Células mais quentes", [html.Li("Nenhum foco com os filtros atuais.", className="note")]
            g = g.sort_values("n", ascending=False).head(10)
            mx = g["n"].max()
            rows = []
            for i, r in enumerate(g.itertuples()):
                lat, lon = (r.gy + 0.5) * deg, (r.gx + 0.5) * deg
                km2 = deg * 111.32 * np.cos(np.radians(lat)) * deg * 110.57
                pm = MESES_L[int(r.pico_mes) - 1] if pd.notna(r.pico_mes) else "—"
                rows.append(html.Li(html.Button([html.Span(str(i + 1), className="n"),
                                                 html.Span([f"{abs(lat):.2f}°{'S' if lat < 0 else 'N'} {abs(lon):.2f}°{'W' if lon < 0 else 'E'}",
                                                            html.Small(f"pico em {pm}"), html.Span(className="bar", style={"width": f"{r.n / mx * 100:.1f}%"})], className="nm"),
                                                 html.Span(fmt(r.n), className="val"), html.Span(fmt1(r.n / km2 * 1000), className="den")],
                                                id={"type": "rank", "k": "cell", "id": f"{r.gx}:{r.gy}:{deg}"}, n_clicks=0)))
            return f"Células mais quentes ({str(deg).replace('.', ',')}°)", rows
        df = df[df["id"].isin(names)].sort_values("n", ascending=False).head(12)
        if df.empty:
            return title, [html.Li("Nenhum foco com os filtros atuais.", className="note")]
        mx = df["n"].max()
        rows = [html.Li(html.Button([html.Span(str(i + 1), className="n"),
                                     html.Span([names[r.id], html.Small(f"pico em {MESES_L[int(r.pico_mes) - 1]}") if pd.notna(r.pico_mes) else None,
                                                html.Span(className="bar", style={"width": f"{r.n / mx * 100:.1f}%"})], className="nm"),
                                     html.Span(fmt(r.n), className="val"), html.Span(fmt1(r.n / areas[r.id] * 1000), className="den")],
                                    id={"type": "rank", "k": kind, "id": r.id}, n_clicks=0, className="cur" if (k == kind and uid == r.id) else ""))
                for i, r in enumerate(df.itertuples())]
        return title, rows

    # ------------------------------------------------------------ map
    @app.callback(Output("map", "figure"), Output("maplegend", "children"), Input("st", "data"))
    def render_map(st):
        f = filtro(st)
        k, uid, layer = st["kind"], st["uid"], st["layer"]
        traces, legend = [], []
        center, zoom = F.zoom_for(scope_bbox(st), 760 if st["mode"] == "map" else 580, 640 if st["mode"] == "map" else 560)
        grey = [[0, "#eceae4"], [1, "#eceae4"]]

        def units_trace(level, ids_units, df, highlight=True, opacity=0.85):
            dfi = df.set_index("id") if len(df) else pd.DataFrame(columns=["n", "pico_mes", "frp_max"])
            ids, z, cd = [], [], []
            for u in ids_units:
                n = float(dfi["n"].get(u.id, 0)) if len(dfi) else 0.0
                d = n / max(u.area_km2, 1) * 1000
                pm = dfi["pico_mes"].get(u.id) if len(dfi) else None
                nxt = {"pais": "ver províncias" if u.id == "ARG" else "ver a grade de focos", "prov": "ver departamentos", "dep": "ver grade e focos"}[level]
                html_ = (f"<b>{u.nome}</b><br>{fmt(n)} focos · {fmt1(d)} por 1.000 km²" + (f"<br>Pico: {MESES_L[int(pm) - 1]}" if pm is not None and pd.notna(pm) else "")
                         + f"<br><i>clique para {nxt}</i>")
                ids.append(u.id); z.append(d if highlight else 0); cd.append([level, u.id, html_])
            return ids, z, cd

        sel_geo = None
        # countries: context (muted) or main layer
        cdf = repo.territories("pais", f) if k != "shape" else pd.DataFrame(columns=["id", "n", "pico_mes", "frp_max"])
        main_level = "pais" if k == "all" else None
        ids, z, cd = units_trace("pais", geo.paises.values(), cdf, highlight=(k in ("all",)) or (k == "pais" and uid != "ARG"))
        zmax_c = np.quantile([v for v in z if v > 0], 0.95) if any(v > 0 for v in z) else 1
        traces.append(F.choropleth(geo.fc["pais"], ids, z, cd, "países", opacity=0.75 if main_level else 0.55, colorscale=None if (k == "all" or (k == "pais" and uid != "ARG")) else grey, zmax=zmax_c))
        if k == "all" or (k == "pais" and uid != "ARG"):
            legend = ramp_legend(zmax_c, "Focos por 1.000 km²")
        # Argentine provinces
        if k in ("pais", "prov", "dep") and (uid == "ARG" or k in ("prov", "dep")) or (k == "shape"):
            pdf = repo.territories("prov", f) if k != "shape" else pd.DataFrame(columns=["id", "n", "pico_mes", "frp_max"])
            hl = k == "pais" and layer in ("auto", "dens")
            ids, z, cd = units_trace("prov", geo.provincias.values(), pdf, highlight=hl)
            zmax_p = np.quantile([v for v in z if v > 0], 0.95) if any(v > 0 for v in z) else 1
            traces.append(F.choropleth(geo.fc["prov"], ids, z, cd, "províncias", opacity=0.85 if hl else 0.5, colorscale=None if hl else grey, zmax=zmax_p))
            if hl:
                legend = ramp_legend(zmax_p, "Focos por 1.000 km²")
        # departments of the selected province
        if k in ("prov", "dep"):
            pid = uid if k == "prov" else geo.departamentos[uid].parent
            ddf = repo.territories("dep", f, pid)
            deps = [geo.departamentos[d] for d in geo.deps_of.get(pid, [])]
            hl = layer in ("auto", "dens") and (k == "prov" or layer == "dens")
            ids, z, cd = units_trace("dep", deps, ddf, highlight=hl)
            zmax_d = np.quantile([v for v in z if v > 0], 0.95) if any(v > 0 for v in z) else 1
            traces.append(F.choropleth(geo.subset("dep", ids), ids, z, cd, "departamentos", opacity=0.85 if hl else 0.45, line_w=0.5, colorscale=None if hl else grey, zmax=zmax_d))
            if hl:
                legend = ramp_legend(zmax_d, "Focos por 1.000 km²")
        # grid + points
        want_grid = layer == "grid" or (layer == "auto" and (k in ("dep", "shape") or (k == "pais" and uid != "ARG")))
        if want_grid and layer != "dens":
            deg = grid_deg(st)
            g = repo.grid(f, deg)
            while len(g) > 2500 and deg < 2:  # keep the map light: coarser cells when there are too many
                deg *= 2
                g = repo.grid(f, deg)
            if len(g):
                gj = F.grid_geojson(g, deg)
                zmax_g = float(g["n"].quantile(0.97)) or 1
                cd = []
                for r in g.itertuples():
                    lat = (r.gy + 0.5) * deg
                    km2 = deg * 111.32 * np.cos(np.radians(lat)) * deg * 110.57
                    sats = " · ".join(f"{s} {int(getattr(r, s))}" for s in repo.sats if hasattr(r, s) and getattr(r, s))
                    pm = MESES_L[int(r.pico_mes) - 1] if pd.notna(r.pico_mes) else "—"
                    cd.append(["cell", int(r.gx), int(r.gy), deg,
                               f"<b>Célula de {str(deg).replace('.', ',')}° (~{fmt(km2)} km²)</b><br>{fmt(r.n)} focos · pico em {pm}<br>"
                               f"Último: {mlabel(int(r.ultimo_mi))} · FRP máx. {fmt1(r.frp_max)} MW<br>{sats}<br><i>clique para analisar a célula</i>"])
                tr = F.choropleth(gj, [ft["id"] for ft in gj["features"]], g["n"].tolist(), cd, "grade", opacity=0.8, line_w=0, zmax=zmax_g)
                tr.hovertemplate = "%{customdata[4]}<extra></extra>"
                traces.append(tr)
                legend = ramp_legend(zmax_g, f"Focos por célula de {str(deg).replace('.', ',')}°", per_area=False)
        want_pts = layer == "pts" or (layer == "auto" and k in ("dep", "shape"))
        if want_pts and layer != "dens" and repo.count_points(f) <= 20000:
            p = repo.points(f, 5000)
            for sat, grp in p.groupby("satelite"):
                traces.append(go.Scattermap(lat=grp["lat"], lon=grp["lon"], mode="markers", name=sat,
                                            marker=dict(size=7, color=F.SAT_C.get(sat, "#888"), opacity=0.9),
                                            customdata=np.stack([np.full(len(grp), "pt"), grp["ts"].dt.strftime("%d/%m/%Y %H:%M"), grp["frp"].round(1),
                                                                 np.full(len(grp), sat), grp["sensor"]], 1),
                                            hovertemplate="<b>Foco · %{customdata[3]} (%{customdata[4]})</b><br>%{customdata[1]} UTC<br>FRP %{customdata[2]} MW<br>%{lat:.4f}, %{lon:.4f}<extra></extra>"))
            legend = legend + [html.Div([html.Span([html.I(className="dot", style={"background": c}), s]) for s, c in F.SAT_C.items() if s in repo.sats], className="legend")]
        # invisible lattice so box/lasso selection always fires (only while a drawing tool is active)
        if st.get("tool", "pan") != "pan":
            x0, y0, x1, y1 = scope_bbox(st)
            mx_, my_ = (x1 - x0) * 0.6 + 0.5, (y1 - y0) * 0.6 + 0.5
            gx, gy = np.meshgrid(np.linspace(x0 - mx_, x1 + mx_, 20), np.linspace(y0 - my_, y1 + my_, 20))
            traces.append(go.Scattermap(lon=gx.ravel(), lat=gy.ravel(), mode="markers", marker=dict(size=1, opacity=0), hoverinfo="skip", name="sel"))
        # outlines
        layers = []
        if k in ("pais", "prov", "dep"):
            u = geo.unit(k, uid)
            layers.append(dict(sourcetype="geojson", source={"type": "FeatureCollection", "features": [u.feature]}, type="line", color=F.ACCENT, line=dict(width=3)))
        if k == "shape":
            ring = st["shape"] + [st["shape"][0]]
            layers.append(dict(sourcetype="geojson", source={"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring}},
                               type="line", color=F.ACCENT, line=dict(width=2.5, dash=[2, 1])))
        fig = go.Figure(traces)
        fig.update_layout(map=dict(style="carto-positron", center=center, zoom=zoom, layers=layers),
                          margin=dict(l=0, r=0, t=0, b=0), showlegend=False, dragmode=st.get("tool", "pan"),
                          uirevision=f"{k}:{uid}:{len(st['shape'])}:{st['shape'][:1]}", paper_bgcolor="#d9e2ea",
                          hoverlabel=dict(bgcolor=F.FG, font_color="#fff", font_size=12), clickmode="event")
        return fig, legend

    def ramp_legend(zmax, title, per_area=True):
        labels = [fmt1(zmax * (i + 1) / 6) if zmax * (i + 1) / 6 < 10 else fmt(zmax * (i + 1) / 6) for i in range(5)] + ["+"]
        return [html.Div(title, className="note"),
                html.Div([html.Span([html.I(style={"background": c}), lab]) for c, lab in zip(F.RAMP, labels)], className="mlr")]

    # ------------------------------------------------------------ CSV
    @app.callback(Output("download", "data"), Input("csv", "n_clicks"), State("st", "data"), prevent_initial_call=True)
    def download(n, st):
        df = repo.export(filtro(st))
        name = scope_name(st).replace(" ", "_").lower()
        return dcc.send_data_frame(df.to_csv, f"focos_{name}_{mlabel(st['t0']).replace('/', '-')}_{mlabel(st['t1']).replace('/', '-')}.csv", index=False)
