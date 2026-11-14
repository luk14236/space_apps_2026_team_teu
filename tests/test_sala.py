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
    out = _render(app)({"win": win, "kind": kind, "uid": uid})
    assert len(out) == 16
    to_json_plotly(list(out))  # what Dash does before sending: fails on non-serializable values
    assert out[4]  # title


def test_metrics_consistent(app):
    from app.data.geo import Geo
    from app.data.repository import Repository
    from app.data.sala import Sala
    s = Sala(Repository(config.PROCESSED_DIR, Geo(config.GEO_DIR)))
    deps, provs = s.metrics(7)
    assert abs(deps["R"].sum() - provs["R"].sum()) < 1e-6  # provinces are the sum of their departments
    assert set(deps["status"]) <= {"crit", "alert", "watch", "ok", "below"}
