"""Page layout. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
from __future__ import annotations

from dash import dcc, html

from ..data.repository import Repository
from ..i18n import lang, switch_href, tr

SAT_LABEL = {"TERRA": "Terra · MODIS", "AQUA": "Aqua · MODIS", "SNPP": "S-NPP · VIIRS", "NOAA20": "NOAA-20 · VIIRS", "NOAA21": "NOAA-21 · VIIRS"}


def initial_state(repo: Repository) -> dict:
    return {"kind": "pais", "uid": "ARG", "shape": [], "t0": repo.mi0, "t1": repo.mi1, "cal": [], "sats": list(repo.sats),
            "serie": "harm" if repo.has_harm else "raw", "layer": "auto", "mode": "dash", "fy": None, "tool": "pan", "playing": False}


def lang_switch(path: str) -> html.Div:
    """PT | EN switch: a plain link that stores the choice in a cookie and comes back to the same page."""
    cur = lang()
    return html.Div(className="langsw", title=tr("Idioma / Language"), children=[
        html.A(code.upper(), href=switch_href(code, path), className="on" if code == cur else "", lang=code,
               **{"aria-current": "true" if code == cur else "false"}) for code in ("pt", "en")])


def nav(active: str):
    """Navigation between the two public pages. The admin page is intentionally not linked."""
    if active == "sala":
        return html.Nav(className="nav", children=[html.A(tr("← Calendário de Focos"), href="/", className="navlink"), lang_switch("/sala")])
    return html.Nav(className="nav", children=[
        html.A([html.Span(className="pulse"), tr("Sala de Situação ↗")], href="/sala", target="_blank", rel="noopener",
               className="sala-btn", title=tr("Abre a sala de situação numa aba separada")), lang_switch("/")])


def root_layout() -> html.Div:
    return html.Div([dcc.Location(id="url"), dcc.Store(id="doc"), html.Div(id="doc-sink", hidden=True), html.Div(id="page")])


def empty_layout() -> html.Div:
    return html.Div(className="app", children=[
        html.Header(className="top", children=[html.Div(className="brand", children=[html.H1(tr("Calendário de Focos"))]), nav("cal")]),
        html.Main(className="empty", children=[html.Section(className="sec", children=[
            html.H2(tr("Ainda não há dados processados")),
            html.P(tr("Envie a entrega do time de dados (CSV ou .tar.gz) ou baixe os focos do NASA FIRMS pela área de admin. "
                      "O painel aparece aqui assim que o processamento terminar.")),
            html.P(tr("Peça a quem administra o sistema para carregar os dados."), className="note")])]),
    ])


def harm_legend(has_harm: bool) -> list:
    from .figures import MODIS_C, RAMP, VIIRS_C
    sw = lambda c, t: html.Span([html.I(className="sw", style={"background": c}), t])  # noqa: E731
    ln = lambda c, t, dash=False: html.Span([html.I(className="lnk", style={"borderTop": f"2px {'dashed' if dash else 'solid'} {c}"}), t])  # noqa: E731
    if has_harm:
        return [sw(RAMP[3], tr("barras: série harmonizada")), ln(VIIRS_C, tr("tracejado: bruta (todos os satélites, sem peso)"), True),
                ln(MODIS_C, tr("azul: só MODIS"))]
    return [sw(MODIS_C, "MODIS"), sw(VIIRS_C, "VIIRS"), ln(MODIS_C, tr("azul: só MODIS"))]


def card(id_, *children, cls="sec"):
    return html.Section(children, id=id_, className=cls)


def build_layout(repo: Repository) -> html.Div:
    meta = repo.meta
    graph_cfg = {"displaylogo": False, "displayModeBar": False}
    serie_opts = [{"label": tr("Harmonizada"), "value": "harm", "disabled": not repo.has_harm},
                  {"label": tr("Só MODIS"), "value": "modis"}, {"label": tr("Bruta"), "value": "raw"}]
    period = tr("{a} a {b}", a=meta['inicio'][:7].replace('-', '/'), b=meta['fim'][:7].replace('-', '/'))
    return html.Div(className="app", children=[
        dcc.Store(id="st", data=initial_state(repo)),
        dcc.Interval(id="tick", interval=700, disabled=True),
        dcc.Download(id="download"),
        html.Header(className="top", children=[
            html.Div(className="brand", children=[
                html.H1(tr("Calendário de Focos")),
                html.Small(tr("MODIS + VIIRS · América do Sul · {p} · NASA FIRMS", p=period)),
            ]),
            nav("cal"),
            html.Span(tr("{n} avisos nos dados", n=len(meta['avisos'])), className="warn", title="\n".join(meta["avisos"])) if meta["avisos"] else None,
            html.Div(className="controls", children=[
                html.Button([html.Span("⤢ "), html.Span(tr("Expandir mapa"), id="viewlbl")], id="viewbtn", className="vbtn ghost", n_clicks=0),
                dcc.Dropdown(id="search", options=repo.geo.search_options(), placeholder=tr("Buscar país, província ou departamento"),
                             className="search", clearable=True, searchable=True),
                dcc.RadioItems(id="serie", options=serie_opts, value=initial_state(repo)["serie"], className="seg", inline=True),
            ]),
        ]),
        html.Div(id="main", className="main dash", children=[
            html.Div(id="mapcard", className="mapcard", children=[
                html.Div(className="maptools", children=[
                    dcc.RadioItems(id="tool", options=[{"label": tr("✋ Navegar"), "value": "pan"}, {"label": tr("▭ Retângulo"), "value": "select"},
                                                       {"label": tr("⬠ Polígono"), "value": "lasso"}], value="pan", className="seg small", inline=True),
                    html.Button(tr("Limpar área"), id="clear-shape", className="mini", n_clicks=0),
                    dcc.Dropdown(id="layer", options=[{"label": tr("Detalhe pelo zoom"), "value": "auto"}, {"label": tr("Coroplético"), "value": "dens"},
                                                      {"label": tr("Grade de focos"), "value": "grid"}, {"label": tr("Focos individuais"), "value": "pts"}],
                                 value="auto", clearable=False, className="layer"),
                ]),
                dcc.Store(id="mapview"),
                dcc.Graph(id="map", className="mapgraph", config={"scrollZoom": True, "displaylogo": False, "doubleClick": False,
                                                                  "modeBarButtonsToRemove": ["toImage"]}),
                html.Div([html.Span(id="map-level", className="lvl"), html.Div(id="maplegend", className="maplegend")], className="mapfoot"),
                html.Div(className="sats", children=[html.Span(tr("Satélites"), className="eyebrow"),
                                                     dcc.Checklist(id="sats", options=[{"label": SAT_LABEL.get(s, s), "value": s} for s in repo.sats],
                                                                   value=list(repo.sats), inline=True, className="satlist")]),
                html.Div(className="timeline", children=[
                    html.Div(className="tl-head", children=[
                        html.Span(id="tl-range", className="rng"), html.Span(id="tl-total", className="tot"),
                        html.Span(className="btns", children=[
                            html.Button(tr("Tudo"), id={"type": "preset", "p": "all"}, className="mini", n_clicks=0),
                            html.Button(tr("5 anos"), id={"type": "preset", "p": "5y"}, className="mini", n_clicks=0),
                            html.Button(tr("12 meses"), id={"type": "preset", "p": "12m"}, className="mini", n_clicks=0),
                            html.Button(tr("▶ Reproduzir"), id="play", className="mini play", n_clicks=0)]),
                    ]),
                    dcc.Graph(id="timeline", config=graph_cfg | {"displayModeBar": False}),
                    html.P(tr("Arraste sobre as barras para escolher o período."), className="note"),
                ]),
            ]),
            card("sec-scope", html.Nav(id="crumbs", className="crumbs"), html.H2(id="scope-title"), html.Div(id="chips", className="chips")),
            card("sec-kpis", html.Div(id="kpis", className="kpis")),
            card("sec-cal", html.Span(tr("Calendário de atividade"), className="eyebrow"), html.H3(tr("Quando os focos acontecem")),
                 html.P(tr("Cada célula é um mês. Clique numa célula, numa barra de mês (em cima) ou de ano (à direita) para filtrar o mapa."), className="sub"),
                 dcc.Graph(id="cal", config=graph_cfg), html.Div(id="cal-legend", className="legend")),
            card("sec-harm", html.Span(tr("Harmonização"), className="eyebrow"), html.H3(tr("O degrau de 2012")),
                 html.Div(harm_legend(repo.has_harm), className="legend"),
                 dcc.Graph(id="harm", config=graph_cfg), html.P(id="harm-note", className="note")),
            card("sec-cum", html.Div(className="head-row", children=[
                    html.Div([html.Span(tr("Anomalia"), className="eyebrow"), html.H3(id="cum-title")]),
                    html.Label([tr("Ano em foco") + " ", dcc.Dropdown(id="fy", options=[{"label": str(y), "value": y} for y in range(repo.y1, repo.y0, -1)],
                                                              value=repo.y1, clearable=False, className="fy")], className="note fyl")]),
                 html.Div(id="cum-call", className="callout"), dcc.Graph(id="cum", config=graph_cfg),
                 html.Div(className="legend", children=[html.Span([html.I(className="sw band1"), tr("mín–máx")]), html.Span([html.I(className="sw band2"), "p25–p75"]),
                                                        html.Span([html.I(className="ln dash"), tr("mediana")]), html.Span([html.I(className="ln acc"), tr("ano em foco")])]),
                 dcc.Graph(id="anom", config=graph_cfg), html.P(tr("Barras: cada mês do ano em foco contra a mediana daquele mês. Clique para ver no mapa."), className="note")),
            card("sec-rank", html.Span(tr("Ranking"), className="eyebrow"), html.H3(id="rank-title"), html.Ol(id="rank", className="rank"),
                 html.P(tr("Clique numa linha para descer um nível. A coluna cinza é a densidade (focos por 1.000 km²)."), className="note")),
            card("sec-exp", html.Span(tr("Exportar"), className="eyebrow"), html.H3(tr("Focos da seleção")),
                 html.Button(tr("Baixar CSV"), id="csv", className="btn primary", n_clicks=0),
                 html.P(tr("Até 200 mil focos mais recentes da área e período selecionados."), className="note")),
            html.Footer(id="sec-foot", className="foot", children=[
                html.Strong(tr("Fontes")),
                html.Span([tr("Focos: NASA FIRMS (MODIS C6.1, VIIRS 375 m), entregues pelo time de dados. "
                              "Limites: Natural Earth (países) e geoBoundaries (províncias e departamentos da Argentina).")]),
                html.Span(tr("Uso de IA: partes do código foram escritas com auxílio do Claude (Anthropic) e revisadas pelo time."), className="note"),
            ]),
        ]),
        html.Div(id="toast", className="toast"),
    ])
