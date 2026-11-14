"""Page layout. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
from __future__ import annotations

from dash import dcc, html

from ..data.repository import Repository

SAT_LABEL = {"TERRA": "Terra · MODIS", "AQUA": "Aqua · MODIS", "SNPP": "S-NPP · VIIRS", "NOAA20": "NOAA-20 · VIIRS", "NOAA21": "NOAA-21 · VIIRS"}


def initial_state(repo: Repository) -> dict:
    return {"kind": "pais", "uid": "ARG", "shape": [], "t0": repo.mi0, "t1": repo.mi1, "cal": [], "sats": list(repo.sats),
            "serie": "harm" if repo.has_harm else "raw", "layer": "auto", "mode": "dash", "fy": None, "tool": "pan", "playing": False}


def nav(active: str):
    """Navigation between the two public pages. The admin page is intentionally not linked."""
    if active == "sala":
        return html.Nav(className="nav", children=[html.A("← Calendário de Focos", href="/", className="navlink")])
    return html.Nav(className="nav", children=[
        html.A([html.Span(className="pulse"), "Sala de Situação ↗"], href="/sala", target="_blank", rel="noopener",
               className="sala-btn", title="Abre a sala de situação numa aba separada")])


def root_layout() -> html.Div:
    return html.Div([dcc.Location(id="url"), html.Div(id="page")])


def empty_layout() -> html.Div:
    return html.Div(className="app", children=[
        html.Header(className="top", children=[html.Div(className="brand", children=[html.H1("Calendário de Focos")]), nav("cal")]),
        html.Main(className="empty", children=[html.Section(className="sec", children=[
            html.H2("Ainda não há dados processados"),
            html.P("Envie a entrega do time de dados (CSV ou .tar.gz) ou baixe os focos do NASA FIRMS pela área de admin. "
                   "O painel aparece aqui assim que o processamento terminar."),
            html.P("Peça a quem administra o sistema para carregar os dados.", className="note")])]),
    ])


def card(id_, *children, cls="sec"):
    return html.Section(children, id=id_, className=cls)


def build_layout(repo: Repository) -> html.Div:
    meta = repo.meta
    graph_cfg = {"displaylogo": False, "displayModeBar": False}
    serie_opts = [{"label": "Harmonizada", "value": "harm", "disabled": not repo.has_harm},
                  {"label": "Só MODIS", "value": "modis"}, {"label": "Bruta", "value": "raw"}]
    period = f"{meta['inicio'][:7].replace('-', '/')} a {meta['fim'][:7].replace('-', '/')}"
    return html.Div(className="app", children=[
        dcc.Store(id="st", data=initial_state(repo)),
        dcc.Interval(id="tick", interval=700, disabled=True),
        dcc.Download(id="download"),
        html.Header(className="top", children=[
            html.Div(className="brand", children=[
                html.H1("Calendário de Focos"),
                html.Small(f"MODIS + VIIRS · América do Sul · {period} · NASA FIRMS"),
            ]),
            nav("cal"),
            html.Span(f"{len(meta['avisos'])} avisos nos dados", className="warn", title="\n".join(meta["avisos"])) if meta["avisos"] else None,
            html.Div(className="controls", children=[
                html.Button([html.Span("⤢ "), html.Span("Expandir mapa", id="viewlbl")], id="viewbtn", className="vbtn ghost", n_clicks=0),
                dcc.Dropdown(id="search", options=repo.geo.search_options(), placeholder="Buscar país, província ou departamento",
                             className="search", clearable=True, searchable=True),
                dcc.RadioItems(id="serie", options=serie_opts, value=initial_state(repo)["serie"], className="seg", inline=True),
            ]),
        ]),
        html.Div(id="main", className="main dash", children=[
            html.Div(id="mapcard", className="mapcard", children=[
                html.Div(className="maptools", children=[
                    dcc.RadioItems(id="tool", options=[{"label": "✋ Navegar", "value": "pan"}, {"label": "▭ Retângulo", "value": "select"},
                                                       {"label": "⬠ Polígono", "value": "lasso"}], value="pan", className="seg small", inline=True),
                    html.Button("Limpar área", id="clear-shape", className="mini", n_clicks=0),
                    dcc.Dropdown(id="layer", options=[{"label": "Detalhe automático", "value": "auto"}, {"label": "Coroplético", "value": "dens"},
                                                      {"label": "Grade de focos", "value": "grid"}, {"label": "Focos individuais", "value": "pts"}],
                                 value="auto", clearable=False, className="layer"),
                ]),
                dcc.Loading(dcc.Graph(id="map", className="mapgraph", config={"scrollZoom": True, "displaylogo": False,
                                                                               "modeBarButtonsToRemove": ["toImage"]}), type="dot", color="#c2410c"),
                html.Div(id="maplegend", className="maplegend"),
                html.Div(className="sats", children=[html.Span("Satélites", className="eyebrow"),
                                                     dcc.Checklist(id="sats", options=[{"label": SAT_LABEL.get(s, s), "value": s} for s in repo.sats],
                                                                   value=list(repo.sats), inline=True, className="satlist")]),
                html.Div(className="timeline", children=[
                    html.Div(className="tl-head", children=[
                        html.Span(id="tl-range", className="rng"), html.Span(id="tl-total", className="tot"),
                        html.Span(className="btns", children=[
                            html.Button("Tudo", id={"type": "preset", "p": "all"}, className="mini", n_clicks=0),
                            html.Button("5 anos", id={"type": "preset", "p": "5y"}, className="mini", n_clicks=0),
                            html.Button("12 meses", id={"type": "preset", "p": "12m"}, className="mini", n_clicks=0),
                            html.Button("▶ Reproduzir", id="play", className="mini play", n_clicks=0)]),
                    ]),
                    dcc.Graph(id="timeline", config=graph_cfg | {"displayModeBar": False}),
                    html.P("Arraste sobre as barras para escolher o período.", className="note"),
                ]),
            ]),
            card("sec-scope", html.Nav(id="crumbs", className="crumbs"), html.H2(id="scope-title"), html.Div(id="chips", className="chips")),
            card("sec-kpis", html.Div(id="kpis", className="kpis")),
            card("sec-cal", html.Span("Calendário de atividade", className="eyebrow"), html.H3("Quando os focos acontecem"),
                 html.P("Cada célula é um mês. Clique numa célula, numa barra de mês (em cima) ou de ano (à direita) para filtrar o mapa.", className="sub"),
                 dcc.Graph(id="cal", config=graph_cfg), html.Div(id="cal-legend", className="legend")),
            card("sec-harm", html.Span("Harmonização", className="eyebrow"), html.H3("O degrau de 2012"),
                 dcc.Graph(id="harm", config=graph_cfg), html.P(id="harm-note", className="note")),
            card("sec-cum", html.Div(className="head-row", children=[
                    html.Div([html.Span("Anomalia", className="eyebrow"), html.H3(id="cum-title")]),
                    html.Label(["Ano em foco ", dcc.Dropdown(id="fy", options=[{"label": str(y), "value": y} for y in range(repo.y1, repo.y0, -1)],
                                                              value=repo.y1, clearable=False, className="fy")], className="note fyl")]),
                 html.Div(id="cum-call", className="callout"), dcc.Graph(id="cum", config=graph_cfg),
                 html.Div(className="legend", children=[html.Span([html.I(className="sw band1"), "mín–máx"]), html.Span([html.I(className="sw band2"), "p25–p75"]),
                                                        html.Span([html.I(className="ln dash"), "mediana"]), html.Span([html.I(className="ln acc"), "ano em foco"])]),
                 dcc.Graph(id="anom", config=graph_cfg), html.P("Barras: cada mês do ano em foco contra a mediana daquele mês. Clique para ver no mapa.", className="note")),
            card("sec-rank", html.Span("Ranking", className="eyebrow"), html.H3(id="rank-title"), html.Ol(id="rank", className="rank"),
                 html.P("Clique numa linha para descer um nível. A coluna cinza é a densidade (focos por 1.000 km²).", className="note")),
            card("sec-exp", html.Span("Exportar", className="eyebrow"), html.H3("Focos da seleção"),
                 html.Button("Baixar CSV", id="csv", className="btn primary", n_clicks=0),
                 html.P("Até 200 mil focos mais recentes da área e período selecionados.", className="note")),
            html.Footer(id="sec-foot", className="foot", children=[
                html.Strong("Fontes"),
                html.Span(["Focos: NASA FIRMS (MODIS C6.1, VIIRS 375 m), entregues pelo time de dados. "
                           "Limites: Natural Earth (países) e geoBoundaries (províncias e departamentos da Argentina)."]),
                html.Span("Uso de IA: partes do código foram escritas com auxílio do Claude (Anthropic) e revisadas pelo time.", className="note"),
            ]),
        ]),
        html.Div(id="toast", className="toast"),
    ])
