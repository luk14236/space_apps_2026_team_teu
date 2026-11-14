"""Situation room smoke tests. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
import pytest
from plotly.io.json import to_json_plotly

from app import config

pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "dia_dep.parquet").exists(), reason="agregados diários ausentes")


@pytest.fixture(scope="module")
def app():
    from app.main import create_app
    return create_app()


def _render(app):
    key = next(k for k in app.callback_map if "sala-kpis.children" in k)
    fn = app.callback_map[key]["callback"]
    return getattr(fn, "__wrapped__", fn)


@pytest.mark.parametrize("kind,uid", [("ar", ""), ("prov", "AR-P"), ("dep", None)])
@pytest.mark.parametrize("win", [1, 7, 30])
def test_render_sala(app, kind, uid, win):
    from app.data.geo import Geo
    if uid is None:
        uid = Geo(config.GEO_DIR).deps_of["AR-X"][0]
    out = _render(app)({"win": win, "kind": kind, "uid": uid, "shape": [], "hl": None, "sort": ["score", -1]}, "pan")
    assert len(out) == 22
    to_json_plotly(list(out))  # what Dash does before sending: fails on non-serializable values
    assert out[4]  # title


@pytest.mark.parametrize("extra", [{"kind": "shape", "uid": "", "shape": [[-65, -32], [-64, -32], [-64, -31], [-65, -31]]},
                                   {"kind": "dep", "uid": None, "hl": [-645, -312, 0.1]},
                                   {"sort": ["nome", 1]}, {"sort": ["frp", -1]}])
def test_render_sala_variants(app, extra):
    from app.data.geo import Geo
    st = {"win": 7, "kind": "ar", "uid": "", "shape": [], "hl": None, "sort": ["score", -1]}
    st.update(extra)
    if st["uid"] is None:
        st["uid"] = Geo(config.GEO_DIR).deps_of["AR-X"][0]
    to_json_plotly(list(_render(app)(st, "select")))


def test_layout_presets_and_edit(app):
    key = next(k for k in app.callback_map if "w-map.className" in k)
    fn = app.callback_map[key]["callback"]
    fn = getattr(fn, "__wrapped__", fn)
    from app.ui.sala import PRESETS, WIDGETS
    out = fn({"preset": "resp", "layout": PRESETS["resp"]}, True)
    n = len(WIDGETS)
    classes, styles = out[:n], out[n:2 * n]
    assert sum(1 for s_ in styles if s_.get("display") == "none") == n - len(PRESETS["resp"])
    assert any("s-XL" in c for c in classes)
    to_json_plotly(list(out))


def test_metrics_consistent(app):
    from app.data.geo import Geo
    from app.data.repository import Repository
    from app.data.sala import Sala
    s = Sala(Repository(config.PROCESSED_DIR, Geo(config.GEO_DIR)))
    deps, provs = s.metrics(7)
    assert abs(deps["R"].sum() - provs["R"].sum()) < 1e-6  # provinces are the sum of their departments
    assert set(deps["status"]) <= {"crit", "alert", "watch", "ok", "below"}
