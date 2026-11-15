"""Plotly figures for the dashboard. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..i18n import lang, months, months_long, num, ordinal, tr

FG, MUTED, LINE, SURF = "#1a1f25", "#5b6570", "#d9dde2", "#ffffff"
ACCENT, ACCENT_SOFT = "#c2410c", "rgba(194,65,12,.18)"
GOOD, CRIT = "#23704a", "#b42318"
MODIS_C, VIIRS_C = "#3c6db3", "#e07a1f"
RAMP = ["#fbeec9", "#f7cf7f", "#ef9a45", "#d9582a", "#a3261d", "#5c0f18"]
RAMP_SCALE = [[0, "#eef0f3"], [0.0001, RAMP[0]], [0.2, RAMP[1]], [0.4, RAMP[2]], [0.6, RAMP[3]], [0.8, RAMP[4]], [1, RAMP[5]]]
SAT_C = {"TERRA": "#3c6db3", "AQUA": "#11897d", "SNPP": "#e07a1f", "NOAA20": "#b8336a", "NOAA21": "#7a5cc8"}
FONT = dict(family="IBM Plex Sans, system-ui, sans-serif", size=11, color=MUTED)


def fmt(n) -> str:
    return num(n)


def fmt1(n) -> str:
    return num(n, 1)


def fmtk(n) -> str:
    return fmt(n / 1000) + "k" if n >= 10000 else (fmt1(n / 1000) + "k" if n >= 1000 else fmt(n))


def separators() -> str:
    """Decimal and thousands separators for numbers inside Plotly hovers and axes."""
    return ".," if lang() == "en" else ",."


def base_layout(fig: go.Figure, height: int, **kw) -> go.Figure:
    opts = dict(height=height, margin=dict(l=40, r=10, t=8, b=26), paper_bgcolor=SURF, plot_bgcolor=SURF,
                font=FONT, showlegend=False, hoverlabel=dict(bgcolor=FG, font_color=SURF, font_size=12, bordercolor=FG),
                dragmode=False, separators=separators())
    fig.update_layout(**(opts | kw))
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=LINE, tickfont=dict(family="IBM Plex Mono, monospace", size=10))
    fig.update_yaxes(gridcolor=LINE, zeroline=False, tickfont=dict(family="IBM Plex Mono, monospace", size=10))
    return fig


# ------------------------------------------------------------------ calendar (Greenpeace style, with margins)
def calendar(m: pd.DataFrame, values: pd.Series, t0: int, t1: int, cal: tuple, viirs_year: int = 2012) -> go.Figure:
    y0, y1 = int(m["ano"].min()), int(m["ano"].max())
    years = list(range(y0, y1 + 1))
    z = np.full((len(years), 12), np.nan)
    for mi, v in values.items():
        z[mi // 12 - y0, mi % 12] = v
    inrange = (values.index >= t0) & (values.index <= t1)
    vr = values[inrange]
    month_mean = [vr[vr.index % 12 == k].mean() if (vr.index % 12 == k).any() else 0 for k in range(12)]
    year_tot = [vr[vr.index // 12 == y].sum() for y in years]
    zmax = float(np.nanquantile(z[z > 0], 0.97)) if np.any(z > 0) else 1
    med = [np.nanmedian(z[:, k]) for k in range(12)]
    ML = months_long()
    txt = [[tr("<b>{m} de {y}</b><br>{n} focos<br>{p}% vs. mediana do mês", m=ML[k], y=y, n=fmt(z[i, k]),
               p=f"{'+' if z[i, k] >= med[k] else ''}{fmt((z[i, k] - med[k]) / med[k] * 100) if med[k] else 0}")
            if not np.isnan(z[i, k]) else "" for k in range(12)] for i, y in enumerate(years)]

    fig = make_subplots(rows=2, cols=2, column_widths=[0.8, 0.2], row_heights=[0.12, 0.88], shared_xaxes="columns",
                        shared_yaxes="rows", horizontal_spacing=0.02, vertical_spacing=0.015)
    fig.add_trace(go.Bar(x=list(range(1, 13)), y=month_mean, marker_color=ACCENT, opacity=0.85,
                         customdata=[["month", k + 1, m] for k, m in enumerate(months())],
                         hovertemplate=tr("<b>%{customdata[2]}</b> média de %{y:,.0f} focos/mês<br>clique para filtrar") + "<extra></extra>"), 1, 1)
    fig.add_trace(go.Heatmap(z=z, x=list(range(1, 13)), y=years, colorscale=RAMP_SCALE, zmin=0, zmax=zmax, showscale=False, xgap=1.5, ygap=1.5,
                             text=txt, hovertemplate="%{text}<extra></extra>", customdata=[[["cell", y, k + 1] for k in range(12)] for y in years]), 2, 1)
    fig.add_trace(go.Bar(x=year_tot, y=years, orientation="h", marker_color=ACCENT, opacity=0.85, customdata=[["year", y] for y in years],
                         hovertemplate=tr("<b>%{y}</b>: %{x:,.0f} focos no período<br>clique para filtrar") + "<extra></extra>"), 2, 2)
    base_layout(fig, 560)
    fig.update_layout(margin=dict(l=40, r=8, t=6, b=24), bargap=0.25)
    fig.update_xaxes(tickvals=list(range(1, 13)), ticktext=months(), side="bottom", row=2, col=1, showticklabels=True)
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, showgrid=False, row=2, col=2)
    fig.update_yaxes(autorange="reversed", dtick=1, showgrid=False, row=2, col=1)
    fig.update_yaxes(showticklabels=False, showgrid=False, row=1, col=1)
    fig.update_yaxes(showgrid=False, row=2, col=2)
    shapes = [dict(type="line", xref="x3", yref="y3", x0=0.5, x1=12.5, y0=viirs_year - 0.5, y1=viirs_year - 0.5,
                   line=dict(color=ACCENT, width=1.6, dash="dash"))]
    for y in years:  # dim years outside the selected period
        if y * 12 + 11 < t0 or y * 12 > t1:
            shapes.append(dict(type="rect", xref="x3", yref="y3", x0=0.5, x1=12.5, y0=y - 0.5, y1=y + 0.5, fillcolor="rgba(255,255,255,.65)", line_width=0))
    if cal and cal[0] == "cell":
        shapes.append(dict(type="rect", xref="x3", yref="y3", x0=cal[2] - 0.5, x1=cal[2] + 0.5, y0=cal[1] - 0.5, y1=cal[1] + 0.5, line=dict(color=FG, width=2.5)))
    elif cal and cal[0] == "month":
        shapes.append(dict(type="rect", xref="x3", yref="y3", x0=cal[1] - 0.5, x1=cal[1] + 0.5, y0=y0 - 0.5, y1=y1 + 0.5, line=dict(color=FG, width=2)))
    elif cal and cal[0] == "year":
        shapes.append(dict(type="rect", xref="x3", yref="y3", x0=0.5, x1=12.5, y0=cal[1] - 0.5, y1=cal[1] + 0.5, line=dict(color=FG, width=2)))
    fig.update_layout(shapes=shapes)
    return fig


def calendar_legend(values: pd.Series) -> list[tuple[str, str]]:
    v = values[values > 0]
    zmax = float(v.quantile(0.97)) if len(v) else 1
    return [(RAMP[i], "≤" + fmtk(zmax * (i + 1) / 6) if i < 5 else "+") for i in range(6)]


# ------------------------------------------------------------------ anomaly (EFFIS style)
def cumulative(values: pd.Series, fy: int, y_first_full: int, y_last: int) -> tuple[go.Figure, str]:
    def cum(y):
        a = [values.get(y * 12 + k, np.nan) for k in range(12)]
        return np.nancumsum(a) if not np.all(np.isnan(a)) else np.full(12, np.nan)
    hist = np.array([cum(y) for y in range(y_first_full, y_last + 1) if y != fy])
    cur = cum(fy)
    mn, mx = np.nanmin(hist, 0), np.nanmax(hist, 0)
    p25, p50, p75 = (np.nanquantile(hist, q, 0) for q in (0.25, 0.5, 0.75))
    x = months()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=mx, mode="lines", line_width=0, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=mn, mode="lines", fill="tonexty", fillcolor="rgba(91,101,112,.13)", line_width=0, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p75, mode="lines", line_width=0, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p25, mode="lines", fill="tonexty", fillcolor=ACCENT_SOFT, line_width=0, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=p50, mode="lines", line=dict(color=MUTED, width=1.5, dash="dash"), hovertemplate=tr("mediana: %{y:,.0f}") + "<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=cur, mode="lines+markers", line=dict(color=ACCENT, width=3), marker=dict(size=6, color=ACCENT),
                             customdata=np.stack([mn, mx, p50], 1),
                             hovertemplate=tr("<b>{fy} até %{{x}}</b><br>%{{y:,.0f}} acumulados<br>mediana %{{customdata[2]:,.0f}} · faixa %{{customdata[0]:,.0f}}–%{{customdata[1]:,.0f}}", fy=fy) + "<extra></extra>"))
    base_layout(fig, 250)
    last = int(np.nanmax(np.where(~np.isnan(cur))[0])) if np.any(~np.isnan(cur)) else 11
    at = hist[:, last]
    rank = int((at > cur[last]).sum()) + 1
    d = (cur[last] - p50[last]) / p50[last] * 100 if p50[last] else 0
    pc = int(round((at < cur[last]).mean() * 100))
    call = tr("<b>{fy}</b> até {m}: <b>{n}</b> focos, {d}% contra a mediana. É o <b>{rank}</b> maior acumulado em {tot} temporadas (percentil {pc}).",
              fy=fy, m=months_long()[last], n=fmt(cur[last]), d=f"{'+' if d >= 0 else ''}{fmt(d)}", rank=ordinal(rank), tot=len(at) + 1, pc=pc)
    return fig, call


def monthly_anomaly(values: pd.Series, fy: int, y_first_full: int, y_last: int) -> go.Figure:
    pct, txt = [], []
    for k in range(12):
        v = values.get(fy * 12 + k, np.nan)
        hist = [values.get(y * 12 + k, np.nan) for y in range(y_first_full, y_last + 1) if y != fy]
        med = np.nanmedian(hist) if hist else np.nan
        p = (v - med) / med * 100 if med and not np.isnan(v) else np.nan
        pct.append(p)
        txt.append(tr("<b>{m} de {y}</b><br>{v} focos · mediana {med}<br>{p}%<br>clique para ver no mapa", m=months_long()[k], y=fy,
                      v=fmt(v) if not np.isnan(v) else "—", med=fmt(med) if not np.isnan(med) else "—", p=f"{'+' if p >= 0 else ''}{fmt(p)}")
                   if not np.isnan(p) else "")
    cols = [CRIT if (p or 0) > 0 else GOOD for p in pct]
    fig = go.Figure(go.Bar(x=months(), y=pct, marker_color=cols, opacity=0.9, text=txt, hovertemplate="%{text}<extra></extra>",
                           customdata=[["cell", fy, k + 1] for k in range(12)]))
    base_layout(fig, 150)
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor=MUTED)
    return fig


# ------------------------------------------------------------------ harmonization
def harmonization(m: pd.DataFrame, has_harm: bool, viirs_year: int = 2012) -> tuple[go.Figure, str]:
    y = m.groupby("ano")[["raw", "modis", "viirs", "harm"]].sum(min_count=1)
    fig = go.Figure()
    if has_harm and y["harm"].notna().any():
        fig.add_trace(go.Bar(x=y.index, y=y["harm"], marker_color=RAMP[3], name=tr("Harmonizada"), hovertemplate=tr("%{x}: %{y:,.0f} harmonizados") + "<extra></extra>"))
        fig.add_trace(go.Scatter(x=y.index, y=y["raw"], line=dict(color=VIIRS_C, width=2, dash="dash"), name=tr("Bruta"), hovertemplate=tr("bruta %{y:,.0f}") + "<extra></extra>"))
    else:
        fig.add_trace(go.Bar(x=y.index, y=y["modis"], marker_color=MODIS_C, name="MODIS", hovertemplate="%{x} · MODIS: %{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Bar(x=y.index, y=y["viirs"], marker_color=VIIRS_C, name="VIIRS", hovertemplate="%{x} · VIIRS: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=y.index, y=y["modis"], line=dict(color=MODIS_C, width=2), name=tr("Só MODIS"), hovertemplate=tr("só MODIS %{y:,.0f}") + "<extra></extra>"))
    base_layout(fig, 230, barmode="stack")
    fig.add_vline(x=viirs_year - 0.5, line=dict(color=ACCENT, dash="dash", width=1.5))
    fig.add_annotation(x=viirs_year - 0.4, y=1, yref="paper", text=tr("VIIRS entra"), showarrow=False, xanchor="left", font=dict(color=ACCENT, size=10))
    r0, r1 = y["raw"].get(viirs_year - 1, 0), y["raw"].get(viirs_year, 0)
    jump = (r1 - r0) / r0 * 100 if r0 else 0
    note = tr("De {a} para {b} a soma bruta salta <b>{j}%</b>, só pela entrada do VIIRS.", a=viirs_year - 1, b=viirs_year, j=f"{'+' if jump >= 0 else ''}{fmt(jump)}")
    if not has_harm:
        note += " " + tr("A série harmonizada aparece aqui quando o time de dados entregar a coluna <code>peso_harm</code>.")
    return fig, note


# ------------------------------------------------------------------ monthly series by satellite (SNPP scale)
CAL_YEARS = (2013, 2019)  # overlap used for the provisional estimate (before the Terra/Aqua orbit drift)


def ratios(m: pd.DataFrame, base: str) -> dict:
    """S-NPP / `base` ratio per calendar month over CAL_YEARS ("glob" = all months together)."""
    ov = m[(m["ano"] >= CAL_YEARS[0]) & (m["ano"] <= CAL_YEARS[1])]
    tot_b = ov[base].sum()
    glob = ov["snpp"].sum() / tot_b if tot_b else np.nan
    out = {mes: (g["snpp"].sum() / g[base].sum() if g[base].sum() >= 30 else glob) for mes, g in ov.groupby("mes")}
    return {k: (v if np.isfinite(v) else glob) for k, v in out.items()} | {"glob": glob}


def provisional_harm(m: pd.DataFrame) -> pd.Series | None:
    """Estimate in S-NPP scale while `peso_harm` is missing: S-NPP where it exists (NOAA-20 after it ends); before it,
    Aqua (same ~13:30 overpass) times the S-NPP/Aqua ratio of the same calendar month in CAL_YEARS, and Terra alone
    (before Aqua existed) times the S-NPP/Terra ratio. Ratios fall back to the all-months value when counts are small."""
    snpp, aqua, terra, noaa20 = (m[c] for c in ("snpp", "aqua", "terra", "noaa20"))
    if snpp.sum() == 0:
        return None
    ka, kt = ratios(m, "aqua"), ratios(m, "terra")
    first = snpp[snpp > 0].index.min()
    est = pd.Series(np.nan, index=m.index)
    for mi in m.index:
        mes = mi % 12 + 1
        if mi >= first:
            est[mi] = snpp[mi] if snpp[mi] > 0 or noaa20[mi] == 0 else noaa20[mi]
        elif aqua[mi] > 0:
            est[mi] = aqua[mi] * ka.get(mes, ka["glob"])
        elif terra[mi] > 0:
            est[mi] = terra[mi] * kt.get(mes, kt["glob"])
    return est


def satellite_monthly(m: pd.DataFrame, has_harm: bool) -> tuple[go.Figure, str]:
    x = pd.to_datetime({"year": m.index // 12, "month": m.index % 12 + 1, "day": 1})
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=m["aqua"].where(m["aqua"].cumsum() > 0), mode="lines", line=dict(color="#11897d", width=1), opacity=0.75, name=tr("AQUA observado"),
                             hovertemplate=tr("AQUA observado: %{y:,.0f}") + "<extra></extra>"))
    if has_harm and m["harm"].notna().any():
        harm, lbl, note = m["harm"], tr("Harmonizado completo (escala SNPP)"), tr(
            "Linha laranja: soma do <code>peso_harm</code> entregue pelo time de dados, na escala de um satélite VIIRS (S-NPP), exibida apenas antes do início das observações S-NPP.")
    else:
        harm, lbl = provisional_harm(m), tr("Harmonizado (escala SNPP) · estimativa provisória")
        note = tr("Linha laranja provisória até chegar o <code>peso_harm</code>: antes do S-NPP, Aqua × razão S-NPP/Aqua do mesmo mês em {a}–{b} "
                  "(Terra × razão S-NPP/Terra antes do Aqua existir). A linha termina quando começam as observações S-NPP.", a=CAL_YEARS[0], b=CAL_YEARS[1])
    # The harmonized line ends at the first month with observed S-NPP.
    # This changes only the chart, not the source data or monthly aggregates.
    first_snpp = m.index[m["snpp"] > 0]
    if harm is not None and len(first_snpp):
        harm = harm.where(m.index < first_snpp[0])
    if harm is not None:
        fig.add_trace(go.Scatter(x=x, y=harm, mode="lines", line=dict(color="#ff8c00", width=2.2), name=lbl,
                                 hovertemplate=tr("harmonizado: %{y:,.0f}") + "<extra></extra>"))
    sn = m["snpp"].where(m["snpp"] > 0)
    fig.add_trace(go.Scatter(x=x, y=sn, mode="lines+markers", line=dict(color="#3c6ef0", width=1.4), marker=dict(size=4), name=tr("SNPP observado"),
                             hovertemplate=tr("SNPP observado: %{y:,.0f}") + "<extra></extra>"))
    base_layout(fig, 340, showlegend=True, hovermode="x unified",
                legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=FG), bgcolor="rgba(0,0,0,0)"))
    fig.update_layout(margin=dict(l=50, r=10, t=30, b=30))
    first = m.index[m["snpp"] > 0]
    if len(first):
        x0 = pd.Timestamp(year=int(first[0] // 12), month=int(first[0] % 12 + 1), day=1)
        fig.add_vline(x=x0, line=dict(color=MUTED, dash="dash", width=1.2))
        fig.add_annotation(x=x0, y=1, yref="paper", text=tr("Início do período SNPP observado"), showarrow=False, xanchor="left",
                           font=dict(color=MUTED, size=10))
    fig.update_yaxes(title=dict(text=tr("focos por mês"), font=dict(size=10)))
    return fig, note


def model_check(m: pd.DataFrame) -> tuple[go.Figure, str]:
    """Validation: S-NPP estimated from Aqua (same ratios as the provisional series) against S-NPP observed, 2012 onwards."""
    sel = m[(m["snpp"] > 0) & (m["aqua"] > 0)]
    sel = sel[sel["ano"] < sel["ano"].max()] if len(sel) and (sel["ano"] == sel["ano"].max()).sum() < 12 else sel  # full years only
    fig = go.Figure()
    if len(sel) < 12:
        base_layout(fig, 300)
        return fig, tr("Sem meses suficientes com S-NPP e Aqua ao mesmo tempo nesta área.")
    ka = ratios(m, "aqua")
    est = pd.Series([a * ka.get(mi % 12 + 1, ka["glob"]) for mi, a in sel["aqua"].items()], index=sel.index)
    obs = sel["snpp"]
    x = pd.to_datetime({"year": sel.index // 12, "month": sel.index % 12 + 1, "day": 1})
    fig.add_trace(go.Scatter(x=x, y=est, mode="lines+markers", line=dict(color="#ff8c00", width=2), marker=dict(size=4),
                             name=tr("SNPP estimado pelo modelo"), hovertemplate=tr("estimado: %{y:,.0f}") + "<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=obs, mode="lines+markers", line=dict(color="#3c6ef0", width=1.4), marker=dict(size=4),
                             name=tr("SNPP observado"), hovertemplate=tr("observado: %{y:,.0f}") + "<extra></extra>"))
    base_layout(fig, 320, showlegend=True, hovermode="x unified",
                legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=FG), bgcolor="rgba(0,0,0,0)"))
    fig.update_layout(margin=dict(l=50, r=10, t=30, b=30))
    fig.update_yaxes(title=dict(text=tr("focos por mês"), font=dict(size=10)))
    out = sel["ano"] > CAL_YEARS[1]  # years not used to fit the ratios
    r = float(np.corrcoef(est, obs)[0, 1]) if obs.std() and est.std() else float("nan")
    tot_err = (est[out].sum() - obs[out].sum()) / obs[out].sum() * 100 if out.any() and obs[out].sum() else float("nan")
    y0, y1 = int(sel["ano"].min()), int(sel["ano"].max())
    note = tr("{a}–{b}: correlação mensal <b>{r}</b> entre estimado e observado. Nos anos fora do ajuste ({c}–{b}), o total estimado difere "
              "<b>{e}%</b> do observado. Razões ajustadas em {f}–{g}.", a=y0, b=y1, r=num(r, 2), c=CAL_YEARS[1] + 1,
              e=f"{'+' if tot_err >= 0 else ''}{num(tot_err, 1)}", f=CAL_YEARS[0], g=CAL_YEARS[1])
    return fig, note


# ------------------------------------------------------------------ timeline (brush)
def timeline(values: pd.Series, t0: int, t1: int, cal_ok) -> go.Figure:
    x = values.index.to_numpy()
    on = [(t0 <= k <= t1) and cal_ok(k) for k in x]
    labels = [tr("{m} de {y}", m=months_long()[k % 12], y=k // 12) for k in x]
    fig = go.Figure(go.Bar(x=x, y=values.to_numpy(), marker_color=[ACCENT if o else "#c9cfd6" for o in on], marker_line_width=0,
                           customdata=labels, hovertemplate=tr("%{customdata}: %{y:,.0f} focos") + "<extra></extra>"))
    years = range(x.min() // 12 + 1, x.max() // 12 + 1)
    base_layout(fig, 110, dragmode="select", selectdirection="h", bargap=0.1)
    fig.update_layout(margin=dict(l=8, r=8, t=4, b=20), newselection=dict(line=dict(color=ACCENT)))
    fig.update_xaxes(tickvals=[y * 12 for y in years if y % 5 == 0], ticktext=[str(y) for y in years if y % 5 == 0], range=[x.min() - 0.5, x.max() + 0.5])
    fig.update_yaxes(visible=False, fixedrange=True)
    fig.add_vrect(x0=t0 - 0.5, x1=t1 + 0.5, fillcolor=ACCENT_SOFT, line_width=1, line_color=ACCENT, layer="below")
    return fig


# ------------------------------------------------------------------ map
def zoom_for(bbox, width_px: int = 700, height_px: int = 560) -> tuple[dict, float]:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    def merc(lat):
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    dx = max(x1 - x0, 0.05) / 360
    dy = max(merc(y1) - merc(y0), 0.001) / (2 * math.pi)
    z = math.log2(min(width_px / 512 / dx, height_px / 512 / dy)) - 0.2  # MapLibre uses 512 px tiles
    return {"lon": cx, "lat": cy}, max(1.5, min(13, z))


def choropleth(fc: dict, ids, z, custom, name: str, opacity=0.85, line_w=0.6, colorscale=None, zmax=None):
    return go.Choroplethmap(geojson=fc, locations=list(ids), z=list(z), featureidkey="id", colorscale=colorscale or RAMP_SCALE,
                            zmin=0, zmax=zmax, showscale=False, marker_opacity=opacity, marker_line_width=line_w, marker_line_color="#8f877b",
                            customdata=custom, hovertemplate="%{customdata[2]}<extra></extra>", name=name)


def grid_geojson(df: pd.DataFrame, deg: float) -> dict:
    feats = []
    for gx, gy in zip(df["gx"], df["gy"]):
        x0, y0 = gx * deg, gy * deg
        feats.append({"type": "Feature", "id": f"{gx}:{gy}", "properties": {},
                      "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + deg, y0], [x0 + deg, y0 + deg], [x0, y0 + deg], [x0, y0]]]}})
    return {"type": "FeatureCollection", "features": feats}
