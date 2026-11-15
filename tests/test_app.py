"""Smoke tests on the processed data. AI-assisted: written with Claude (Anthropic), reviewed by the team.

Skipped when data/processed is missing (run scripts/prepare_data.py first).
"""
import copy

import pytest
from plotly.io.json import to_json_plotly

from app import config

pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "meta.json").exists(), reason="dados processados ausentes")


@pytest.fixture(scope="module")
def app_and_repo():
    from app.data.geo import Geo
    from app.data.repository import Repository
    from app.main import create_app
    app = create_app()
    repo = Repository(config.PROCESSED_DIR, Geo(config.GEO_DIR))
    return app, repo


def _callback(app, output_id):
    key = next(k for k in app.callback_map if output_id in k)
    fn = app.callback_map[key]["callback"]
    return getattr(fn, "__wrapped__", fn)


def _states(repo):
    from app.ui.layout import initial_state
    base = initial_state(repo)
    prov = repo.territories("prov", __import__("app.data.repository", fromlist=["Filtro"]).Filtro()).sort_values("n").iloc[-1]["id"]
    dep = repo.geo.deps_of[prov][0]
    out = {"argentina": base}
    for name, upd in {"america_do_sul": {"kind": "all", "uid": "all"}, "provincia": {"kind": "prov", "uid": prov},
                      "departamento": {"kind": "dep", "uid": dep}, "brasil": {"kind": "pais", "uid": "BRA", "t0": repo.mi1 - 11},
                      "area": {"kind": "shape", "uid": "", "shape": [[-65, -32], [-64, -32], [-64, -31], [-65, -31]], "t0": repo.mi1 - 23},
                      "so_modis_mapa": {"serie": "modis", "mode": "map", "cal": ["month", 9]}}.items():
        st = copy.deepcopy(base)
        st.update(upd)
        out[name] = st
    return out


@pytest.mark.parametrize("scope", ["argentina", "america_do_sul", "provincia", "departamento", "brasil", "area", "so_modis_mapa"])
def test_render_every_scope(app_and_repo, scope):
    app, repo = app_and_repo
    st = _states(repo)[scope]
    panel = _callback(app, "crumbs.children")(st)
    assert panel[1]  # scope title
    to_json_plotly(list(panel))
    fig, legend, level = _callback(app, "map.figure")(st, None)
    assert len(fig.data) >= 1
    to_json_plotly([fig, legend, level])


@pytest.mark.parametrize("zoom,expected", [(3, "países"), (5, "províncias"), (6.5, "departamentos"), (8, "grade"), (10, "focos individuais")])
def test_map_level_follows_zoom(app_and_repo, zoom, expected):
    app, repo = app_and_repo
    st = _states(repo)["argentina"]
    on_view = _callback(app, "mapview.data")
    view = on_view({"map.zoom": zoom, "map.center": {"lon": -60.5, "lat": -27.5}}, st, None)
    fig, legend, level = _callback(app, "map.figure")(st, view)
    assert expected in level
    to_json_plotly([fig, legend])


def test_monthly_matches_total(app_and_repo):
    _, repo = app_and_repo
    from app.data.repository import Filtro
    assert repo.monthly(Filtro(kind="all", uid="all"))["raw"].sum() == repo.meta["total_focos"]


@pytest.mark.parametrize("center", [(-55.0, -12.0), (5.6, 52.3)], ids=["brasil", "holanda"])
@pytest.mark.parametrize("zoom,expected", [(5, "províncias"), (6.5, "departamentos"), (8, "grade"), (10, "focos individuais")])
def test_zoom_drill_down_in_brazil_and_netherlands(app_and_repo, center, zoom, expected):
    """Brazil and the Netherlands have the same drill-down as Argentina (states/provinces, municipalities, fine grid)."""
    app, repo = app_and_repo
    st = _states(repo)["argentina"]
    view = _callback(app, "mapview.data")({"map.zoom": zoom, "map.center": {"lon": center[0], "lat": center[1]}}, st, None)
    fig, legend, level = _callback(app, "map.figure")(st, view)
    assert expected in level
    to_json_plotly([fig, legend])


@pytest.mark.parametrize("kind,uid", [("pais", "NLD"), ("prov", "BR-MT"), ("prov", "NL-GE")])
def test_render_brazil_and_netherlands(app_and_repo, kind, uid):
    app, repo = app_and_repo
    st = copy.deepcopy(_states(repo)["argentina"])
    st.update(kind=kind, uid=uid)
    panel = _callback(app, "crumbs.children")(st)
    to_json_plotly(list(panel))
    assert panel[13]  # ranking rows
