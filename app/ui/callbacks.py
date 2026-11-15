"""Callbacks: one controller updates the shared state; renderers draw from it.

AI-assisted: written with Claude (Anthropic) and reviewed by the team.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from ..data.repository import Filtro, Repository
from ..i18n import months, months_long, tr
from . import figures as F

fmt, fmt1, fmtk = F.fmt, F.fmt1, F.fmtk


def filtro(st: dict, with_time: bool = True) -> Filtro:
    return Filtro(kind=st["kind"], uid=st["uid"] or "", shape=tuple(tuple(p) for p in st["shape"]),
                  t0=st["t0"] if with_time else 0, t1=st["t1"] if with_time else 10**6,
                  cal=tuple(st["cal"]) if with_time else (), sats=tuple(sorted(st["sats"])), serie=st["serie"])


def mlabel(mi: int) -> str:
    return f"{months()[mi % 12]}/{mi // 12}"


def register(app, repo: Repository) -> None:
    geo = repo.geo

    # ------------------------------------------------------------ helpers that depend on repo
    def scope_name(st) -> str:
        if st["kind"] == "shape":
            return tr("Área desenhada")
        if st["kind"] == "all":
            return tr("América do Sul")
        u = geo.unit(st["kind"], st["uid"])
        return u.nome if u else st["uid"]

    def country_of(st) -> str | None:
        k, uid = st["kind"], st["uid"]
        if k == "pais":
            return uid
        if k == "prov":
            return geo.provincias[uid].parent
        if k == "dep":
            return geo.provincias[geo.departamentos[uid].parent].parent
        return None

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
        Output("harm-m", "figure"), Output("harm-m-note", "children"), Output("harm-chk", "figure"), Output("harm-chk-note", "children"),
        Input("st", "data"))
    def render_panel(st):
        f = filtro(st)
        m = repo.monthly(f)
        s = repo.series(f)
        ok = cal_ok(st)

        # breadcrumb + chips
        crumbs = [html.Button(tr("América do Sul"), id={"type": "crumb", "k": "all", "id": "all"}, n_clicks=0)]
        k, uid = st["kind"], st["uid"]
        country = country_of(st)
        if country == "NLD":  # outside South America: the path starts at the country
            crumbs = []
        if k in ("prov", "dep") or (k == "pais" and uid in repo.adm):
            crumbs += ([" › "] if crumbs else []) + [html.Button(geo.paises[country].nome, id={"type": "crumb", "k": "pais", "id": country}, n_clicks=0)]
            if k in ("prov", "dep"):
                pid = uid if k == "prov" else geo.departamentos[uid].parent
                crumbs += [" › ", html.Button(geo.provincias[pid].nome, id={"type": "crumb", "k": "prov", "id": pid}, n_clicks=0)]
            if k == "dep":
                crumbs += [" › ", html.Span(geo.departamentos[uid].nome, className="cur")]
        elif k == "pais":
            crumbs += ([" › "] if crumbs else []) + [html.Span(geo.paises[uid].nome, className="cur")]
        elif k == "shape":
            crumbs += [" › ", html.Span(tr("Área desenhada"), className="cur")]
        chips = []
        if k == "shape":
            chips.append(("shape", tr("Área desenhada · {a} km²", a=fmt(scope_area(st)))))
        if st["t0"] != repo.mi0 or st["t1"] != repo.mi1:
            chips.append(("time", f"{mlabel(st['t0'])} – {mlabel(st['t1'])}"))
        if st["cal"]:
            c = st["cal"]
            chips.append(("cal", tr("Calendário: {m}", m=f"{months()[c[2]-1]}/{c[1]}") if c[0] == "cell" else tr("Só {m}", m=months_long()[c[1]-1] if c[0] == "month" else c[1])))
        if set(st["sats"]) != set(repo.sats):
            chips.append(("sats", tr("Satélites: {s}", s=", ".join(sorted(st["sats"]))) if st["sats"] else tr("Nenhum satélite")))
        chip_el = [html.Span([t, html.Button("×", id={"type": "chip", "x": x}, n_clicks=0, title=tr("Remover filtro"))], className="chip") for x, t in chips] \
            or [html.Span(tr("Clique no mapa para descer de nível (país › província › departamento › grade) ou desenhe uma área."), className="note")]

        # KPIs
        sm = summary(st)
        cls = "flat" if abs(sm["pct"]) < 15 else ("up" if sm["pct"] > 0 else "down")
        lbl = tr({"flat": "perto da mediana", "up": "acima da mediana", "down": "abaixo da mediana"}[cls])
        serie_lbl = tr({"harm": "harmonizados", "modis": "só MODIS", "raw": "MODIS + VIIRS (bruto)"}[st["serie"] if (st["serie"] != "harm" or repo.has_harm) else "raw"])
        kpis = [
            html.Div([html.Span(tr("Focos no período"), className="k"), html.Span(fmtk(sm["tot"]), className="v"),
                      html.Span(tr("{d} por 1.000 km² · {s}", d=fmt1(sm['dens']), s=serie_lbl), className="d")], className="kpi"),
            html.Div([html.Span(tr("Pico da temporada"), className="k"), html.Span(months()[sm["pm"]], className="v"),
                      html.Span(tr("{p}% dos focos", p=fmt1(sm['pm_share'])), className="d")], className="kpi"),
            html.Div([html.Span(tr("Ano recorde"), className="k"), html.Span(str(sm["py"]), className="v"), html.Span(tr("{n} focos", n=fmtk(sm['pyv'])), className="d")], className="kpi"),
            html.Div([html.Span(tr("{m} vs. mediana", m=f"{months()[sm['ref'] % 12]}/{sm['ref'] // 12}"), className="k"), html.Span(f"{'+' if sm['pct'] > 0 else ''}{fmt(sm['pct'])}%", className="v"),
                      html.Span(lbl, className=f"pill {cls}")], className="kpi"),
        ]

        calfig = F.calendar(m, s, st["t0"], st["t1"], tuple(st["cal"]))
        cal_leg = [html.Span([html.I(className="sw", style={"background": c}), t]) for c, t in F.calendar_legend(s)] + \
                  [html.Span([html.I(className="ln dash acc"), tr("entrada do VIIRS (2012)")])]
        harmfig, harm_note = F.harmonization(m, repo.has_harm)
        fy = st["fy"] or (st["cal"][1] if st["cal"] and st["cal"][0] in ("cell", "year") else st["t1"] // 12)
        fy = min(max(fy, repo.y0 + 1), repo.y1)
        cumfig, call = F.cumulative(s, fy, repo.y0 + 1, repo.y1)
        anomfig = F.monthly_anomaly(s, fy, repo.y0 + 1, repo.y1)

        hm_fig, hm_note = F.satellite_monthly(m, repo.has_harm)
        chk_fig, chk_note = F.model_check(m)
        rank_title, rows = ranking(st)
        tl = F.timeline(s, st["t0"], st["t1"], ok)
        tl_total = sum(v for kk, v in s.items() if st["t0"] <= kk <= st["t1"] and ok(kk))
        return (crumbs, scope_name(st), chip_el, kpis,
                calfig, cal_leg, harmfig, dcc.Markdown(harm_note, dangerously_allow_html=True),
                cumfig, dcc.Markdown(call, dangerously_allow_html=True), tr("{fy} contra o histórico", fy=fy), anomfig,
                rank_title, rows, tl, f"{mlabel(st['t0'])} – {mlabel(st['t1'])}", tr("{n} focos", n=fmt(tl_total)),
                not st["playing"], tr("❚❚ Pausar") if st["playing"] else tr("▶ Reproduzir"),
                "main " + st["mode"], tr("Expandir mapa") if st["mode"] == "dash" else tr("Voltar ao painel"),
                hm_fig, dcc.Markdown(hm_note, dangerously_allow_html=True), chk_fig, dcc.Markdown(chk_note, dangerously_allow_html=True))

    def ranking(st):
        f = filtro(st)
        k, uid = st["kind"], st["uid"]
        if k == "all":
            df, kind, title = repo.territories("pais", f), "pais", tr("Países com mais focos")
            names = {u: geo.paises[u].nome for u in df["id"]}; areas = {u: geo.paises[u].area_km2 for u in df["id"]}
        elif k == "pais" and uid in repo.adm:
            df, kind, title = repo.territories("prov", f, uid), "prov", tr("Províncias com mais focos") if uid == "ARG" else tr("Estados/províncias com mais focos")
            names = {u: geo.provincias[u].nome for u in df["id"] if u in geo.provincias}; areas = {u: geo.provincias[u].area_km2 for u in names}
        elif k == "prov":
            df, kind, title = repo.territories("dep", f, uid), "dep", tr("Departamentos com mais focos") if country_of(st) == "ARG" else tr("Municípios com mais focos")
            names = {u: geo.departamentos[u].nome for u in df["id"] if u in geo.departamentos}; areas = {u: geo.departamentos[u].area_km2 for u in names}
        else:
            deg = 0.05 if k in ("dep", "shape") else 0.25
            g = repo.grid(f, deg)
            if g.empty:
                return tr("Células mais quentes"), [html.Li(tr("Nenhum foco com os filtros atuais."), className="note")]
            g = g.sort_values("n", ascending=False).head(10)
            mx = g["n"].max()
            rows = []
            for i, r in enumerate(g.itertuples()):
                lat, lon = (r.gy + 0.5) * deg, (r.gx + 0.5) * deg
                km2 = deg * 111.32 * np.cos(np.radians(lat)) * deg * 110.57
                pm = months_long()[int(r.pico_mes) - 1] if pd.notna(r.pico_mes) else "—"
                rows.append(html.Li(html.Button([html.Span(str(i + 1), className="n"),
                                                 html.Span([f"{abs(lat):.2f}°{'S' if lat < 0 else 'N'} {abs(lon):.2f}°{'W' if lon < 0 else 'E'}",
                                                            html.Small(tr("pico em {m}", m=pm)), html.Span(className="bar", style={"width": f"{r.n / mx * 100:.1f}%"})], className="nm"),
                                                 html.Span(fmt(r.n), className="val"), html.Span(fmt1(r.n / km2 * 1000), className="den")],
                                                id={"type": "rank", "k": "cell", "id": f"{r.gx}:{r.gy}:{deg}"}, n_clicks=0)))
            return tr("Células mais quentes ({d}°)", d=degs(deg)), rows
        df = df[df["id"].isin(names)].sort_values("n", ascending=False).head(12)
        if df.empty:
            return title, [html.Li(tr("Nenhum foco com os filtros atuais."), className="note")]
        mx = df["n"].max()
        rows = [html.Li(html.Button([html.Span(str(i + 1), className="n"),
                                     html.Span([names[r.id], html.Small(tr("pico em {m}", m=months_long()[int(r.pico_mes) - 1])) if pd.notna(r.pico_mes) else None,
                                                html.Span(className="bar", style={"width": f"{r.n / mx * 100:.1f}%"})], className="nm"),
                                     html.Span(fmt(r.n), className="val"), html.Span(fmt1(r.n / areas[r.id] * 1000), className="den")],
                                    id={"type": "rank", "k": kind, "id": r.id}, n_clicks=0, className="cur" if (k == kind and uid == r.id) else ""))
                for i, r in enumerate(df.itertuples())]
        return title, rows

    # ------------------------------------------------------------ map: the level of detail follows the zoom
    # zoom < 3.6 countries · < 5.6 provinces · < 7 departments · < 9 grid of cells · >= 9 individual hotspots
    LEVELS = [(3.6, "pais"), (5.6, "prov"), (7.0, "dep"), (9.0, "grid"), (99, "pts")]
    LEVEL_LBL = {"pais": "países", "prov": "províncias", "dep": "departamentos", "grid": "grade de focos", "pts": "focos individuais"}  # tr() at use
    MAP_PX = {"dash": (580, 560), "map": (900, 640)}

    def scope_key(st) -> str:
        return f"{st['kind']}:{st['uid']}:{len(st['shape'])}:{st['shape'][:1]}"

    def bbox_from(center, zoom, w, h):
        import math
        scale = 512 * 2 ** zoom
        dlon = 360 * w / scale
        y = math.log(math.tan(math.pi / 4 + math.radians(center["lat"]) / 2))
        dy = math.pi * 2 * h / scale / 2
        lat = lambda v: math.degrees(2 * math.atan(math.exp(v)) - math.pi / 2)  # noqa: E731
        return [center["lon"] - dlon / 2, lat(y - dy), center["lon"] + dlon / 2, lat(y + dy)]

    import shapely as _shp
    adm_shapes = {iso: _shp.geometry.shape(geo.paises[iso].feature["geometry"]) for iso in repo.adm if iso in geo.paises} if repo.ready else {}

    def adm_at(bbox) -> str | None:
        """Country with provinces/departments under the centre of the view (Argentina, Brazil, the Netherlands)."""
        c = _shp.Point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        hit = next((iso for iso, g in adm_shapes.items() if g.contains(c)), None)
        if hit:
            return hit
        near = [(g.distance(c), iso) for iso, g in adm_shapes.items()]
        return min(near)[1] if near and min(near)[0] < 1.0 else None  # just off the coast still counts

    def level_for(zoom, layer, bbox):
        lvl = next(name for lim, name in LEVELS if zoom < lim)
        here = adm_at(bbox)
        if not here and lvl in ("prov", "dep"):
            lvl = "pais" if zoom < 5.6 else "grid"  # provinces/departments only for the countries in data/geo
        if layer == "dens":
            return {"grid": "dep", "pts": "dep"}.get(lvl, lvl) if here else "pais"
        if layer == "grid":
            return "grid"
        if layer == "pts":
            return "pts"
        return lvl

    def deg_for(zoom):
        return 0.5 if zoom < 5 else 0.25 if zoom < 7 else 0.1 if zoom < 8 else 0.05

    @app.callback(Output("mapview", "data"), Input("map", "relayoutData"), State("st", "data"), State("mapview", "data"), prevent_initial_call=True)
    def on_view(rd, st, prev):
        if not rd or not any(k.startswith("map.") for k in rd):
            return no_update
        prev = prev if prev and prev.get("scope") == scope_key(st) else {}
        zoom = rd.get("map.zoom", prev.get("zoom"))
        center = rd.get("map.center", prev.get("center"))
        if zoom is None or center is None:
            return no_update
        der = rd.get("map._derived") or {}
        coords = der.get("coordinates")
        if coords:
            xs, ys = [c[0] for c in coords], [c[1] for c in coords]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        else:
            bbox = bbox_from(center, zoom, *MAP_PX[st["mode"]])
        bbox = [round(v, 1) for v in bbox]
        if prev and prev.get("bbox") == bbox and abs(prev.get("zoom", 0) - zoom) < 0.25:
            return no_update
        return {"scope": scope_key(st), "zoom": round(zoom, 2), "center": center, "bbox": bbox}

    @app.callback(Output("map", "figure"), Output("maplegend", "children"), Output("map-level", "children"),
                  Input("st", "data"), Input("mapview", "data"))
    def render_map(st, view):
        f = filtro(st)
        k, uid, layer = st["kind"], st["uid"], st["layer"]
        w, h = MAP_PX[st["mode"]]
        if view and view.get("scope") == scope_key(st):
            zoom, bbox = view["zoom"], view["bbox"]
            center, start_zoom = view["center"], view["zoom"]
        else:  # new selection: fly to it
            center, zoom = F.zoom_for(scope_bbox(st), w, h)
            start_zoom = zoom
            bbox = bbox_from(center, zoom, w, h)
        lvl = level_for(zoom, layer, bbox)
        traces, legend = [], []
        grey = [[0, "#eceae4"], [1, "#eceae4"]]

        def visible(b):
            return not (b[2] < bbox[0] or b[0] > bbox[2] or b[3] < bbox[1] or b[1] > bbox[3])

        def units_trace(level, units, df, name, highlight, opacity, line_w=0.6):
            dfi = df.set_index("id") if len(df) else pd.DataFrame(columns=["n", "pico_mes", "frp_max"])
            ids, z, cd = [], [], []
            for u in units:
                n = float(dfi["n"].get(u.id, 0)) if len(dfi) else 0.0
                d = n / max(u.area_km2, 1) * 1000
                pm = dfi["pico_mes"].get(u.id) if len(dfi) else None
                txt = (tr("<b>{u}</b><br>{n} focos · {d} por 1.000 km²", u=u.nome, n=fmt(n), d=fmt1(d))
                       + (tr("<br>Pico: {m}", m=months_long()[int(pm) - 1]) if pm is not None and pd.notna(pm) else "")
                       + tr("<br><i>clique para selecionar · aproxime para ver mais detalhes</i>"))
                ids.append(u.id); z.append(d if highlight else 0); cd.append([level, u.id, txt])
            vals = [v for v in z if v > 0]
            zmax = float(np.quantile(vals, 0.95)) if vals else 1
            fc = geo.fc[level] if level in ("pais", "prov") else geo.subset("dep", ids)
            traces.append(F.choropleth(fc, ids, z, cd, name, opacity=opacity, line_w=line_w, colorscale=None if highlight else grey, zmax=zmax))
            return zmax

        empty = pd.DataFrame(columns=["id", "n", "pico_mes", "frp_max"])
        tf = Filtro(kind="all", uid="all", t0=f.t0, t1=f.t1, cal=f.cal, sats=f.sats, serie=f.serie)  # map shows everything; the selection is outlined
        zmax = units_trace("pais", geo.paises.values(), repo.territories("pais", tf), "países", lvl == "pais", 0.75 if lvl == "pais" else 0.45)
        if lvl == "pais":
            legend = ramp_legend(zmax, tr("Focos por 1.000 km²"))
        if lvl in ("prov", "dep", "grid", "pts") and any(visible(geo.paises[i].bbox) for i in repo.adm if i in geo.paises):
            zp = units_trace("prov", geo.provincias.values(), repo.territories("prov", tf) if lvl == "prov" else empty, "províncias", lvl == "prov",
                             0.85 if lvl == "prov" else 0.35, line_w=1.0)
            if lvl == "prov":
                legend = ramp_legend(zp, tr("Focos por 1.000 km²"))
        if lvl == "dep":
            deps = [d for d in geo.departamentos.values() if visible(d.bbox)]
            zd = units_trace("dep", deps, repo.territories("dep", tf), "departamentos", True, 0.85, line_w=0.5)
            legend = ramp_legend(zd, tr("Focos por 1.000 km² (departamentos)"))
        if lvl in ("grid", "pts"):
            g = repo.grid_view(tf, deg_for(zoom), tuple(bbox))
            deg = g.attrs.get("deg", deg_for(zoom))
            while len(g) > 3000 and deg < 2:
                deg *= 2
                g = repo.grid_view(tf, deg, tuple(bbox))
            if len(g):
                gj = F.grid_geojson(g, deg)
                zmax_g = float(g["n"].quantile(0.97)) or 1
                cd = []
                for r in g.itertuples():
                    lat = (r.gy + 0.5) * deg
                    km2 = deg * 111.32 * np.cos(np.radians(lat)) * deg * 110.57
                    sats = " · ".join(f"{s_} {int(getattr(r, s_))}" for s_ in repo.sats if hasattr(r, s_) and getattr(r, s_))
                    pm = months_long()[int(r.pico_mes) - 1] if pd.notna(r.pico_mes) else "—"
                    cd.append(["cell", int(r.gx), int(r.gy), deg,
                               tr("<b>Célula de {g}° (~{a} km²)</b><br>{n} focos · pico em {m}<br>Último: {u} · FRP máx. {f} MW<br>{s}<br><i>clique para analisar a célula</i>",
                                  g=degs(deg), a=fmt(km2), n=fmt(r.n), m=pm, u=mlabel(int(r.ultimo_mi)), f=fmt1(r.frp_max), s=sats)])
                trace = F.choropleth(gj, [ft["id"] for ft in gj["features"]], g["n"].tolist(), cd, "grade", opacity=0.55 if lvl == "pts" else 0.8, line_w=0, zmax=zmax_g)
                trace.hovertemplate = "%{customdata[4]}<extra></extra>"
                traces.append(trace)
                legend = ramp_legend(zmax_g, tr("Focos por célula de {g}°", g=degs(deg)), per_area=False)
        if lvl == "pts":
            p, total = repo.points_view(tf, tuple(bbox))
            for sat, grp in p.groupby("satelite"):
                traces.append(go.Scattermap(lat=grp["lat"], lon=grp["lon"], mode="markers", name=sat,
                                            marker=dict(size=7, color=F.SAT_C.get(sat, "#888"), opacity=0.9),
                                            customdata=np.stack([np.full(len(grp), "pt"), grp["ts"].dt.strftime("%d/%m/%Y %H:%M"), grp["frp"].round(1),
                                                                 np.full(len(grp), sat), grp["sensor"]], 1),
                                            hovertemplate=tr("<b>Foco · %{customdata[3]} (%{customdata[4]})</b><br>%{customdata[1]} UTC<br>FRP %{customdata[2]} MW<br>%{lat:.4f}, %{lon:.4f}") + "<extra></extra>"))
            legend = legend + [html.Div([html.Span([html.I(className="dot", style={"background": c}), s_]) for s_, c in F.SAT_C.items() if s_ in repo.sats], className="legend")]
            if total > len(p):
                legend.append(html.Div(tr("Mostrando os {n} focos mais recentes de {t} na tela. Aproxime ou filtre o período para ver todos.", n=fmt(len(p)), t=fmt(total)), className="note"))
        if st.get("tool", "pan") != "pan":  # invisible lattice so box/lasso selection always fires
            gx, gy = np.meshgrid(np.linspace(bbox[0], bbox[2], 20), np.linspace(bbox[1], bbox[3], 20))
            traces.append(go.Scattermap(lon=gx.ravel(), lat=gy.ravel(), mode="markers", marker=dict(size=1, opacity=0), hoverinfo="skip", name="sel"))
        layers = []
        if k in ("pais", "prov", "dep"):
            u = geo.unit(k, uid)
            layers.append(dict(sourcetype="geojson", source={"type": "FeatureCollection", "features": [u.feature]}, type="line", color=F.ACCENT, line=dict(width=3)))
        if k == "shape":
            ring = st["shape"] + [st["shape"][0]]
            layers.append(dict(sourcetype="geojson", source={"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring}},
                               type="line", color=F.ACCENT, line=dict(width=2.5, dash=[2, 1])))
        fig = go.Figure(traces)
        fig.update_layout(map=dict(style="carto-positron", center=center, zoom=start_zoom, layers=layers),
                          margin=dict(l=0, r=0, t=0, b=0), showlegend=False, dragmode=st.get("tool", "pan"),
                          uirevision=scope_key(st), paper_bgcolor="#d9e2ea",
                          hoverlabel=dict(bgcolor=F.FG, font_color="#fff", font_size=12), clickmode="event", separators=F.separators())
        return fig, legend, tr("Detalhe: {l}", l=tr(LEVEL_LBL[lvl])) + (tr(" · automático pelo zoom") if layer == "auto" else "")

    def degs(deg) -> str:
        return F.num(deg, 3).rstrip("0").rstrip(",.")

    def ramp_legend(zmax, title, per_area=True):
        labels = [fmt1(zmax * (i + 1) / 6) if zmax * (i + 1) / 6 < 10 else fmt(zmax * (i + 1) / 6) for i in range(5)] + ["+"]
        return [html.Div(title, className="note"),
                html.Div([html.Span([html.I(style={"background": c}), lab]) for c, lab in zip(F.RAMP, labels)], className="mlr")]

    # ------------------------------------------------------------ CSV
    @app.callback(Output("download", "data"), Input("csv", "n_clicks"), State("st", "data"), prevent_initial_call=True)
    def download(n, st):
        df = repo.export(filtro(st))
        name = scope_name(st).replace(" ", "_").lower()
        return dcc.send_data_frame(df.to_csv, f"{tr('focos')}_{name}_{mlabel(st['t0']).replace('/', '-')}_{mlabel(st['t1']).replace('/', '-')}.csv", index=False)
