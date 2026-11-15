"""Every visible Portuguese text has an English version. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
import ast
import re
import string
from pathlib import Path

import pytest

from app import config
from app.i18n_en import EN

ROOT = Path(__file__).resolve().parents[1]
FILES = ["app/ui/figures.py", "app/ui/layout.py", "app/ui/callbacks.py", "app/ui/sala.py", "app/admin.py", "app/admin_page.py", "app/data/geo.py", "app/main.py"]


def literal_keys():
    keys = set()
    for f in FILES:
        for n in ast.walk(ast.parse((ROOT / f).read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("tr", "T") and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.add(a.value)
                elif isinstance(a, ast.Dict):
                    keys |= {v.value for v in a.values if isinstance(v, ast.Constant)}
    from app.admin_page import JS
    keys |= set(re.findall(r"(?<![A-Za-z])t\('((?:[^'\\]|\\.)*)'", JS))
    return keys


def dynamic_keys():
    """Texts that reach tr() through a variable."""
    from app.admin import PREP_STAGES
    from app.data.sala import LABEL
    from app.ui import sala as S
    keys = set(LABEL.values()) | set(S.WIN_L.values()) | set(S.PRESET_L.values()) | {x for t in S.WIDGETS.values() for x in t} | set(S.CLS_L)
    keys |= {s for _, _, s in PREP_STAGES}
    from app.data.geo import Geo
    keys |= {u.nome_pt for u in Geo(config.GEO_DIR).paises.values()}
    return keys


def fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


def test_every_text_has_english():
    missing = sorted((literal_keys() | dynamic_keys()) - set(EN) - {"{"})
    assert not missing, missing[:10]


def test_placeholders_match():
    bad = [k for k, v in EN.items() if "{" in k and fields(k) != fields(v)]
    assert not bad, bad[:5]


@pytest.fixture(scope="module")
def app():
    from app.main import create_app
    return create_app()


def test_switch_sets_cookie_and_returns(app):
    c = app.server.test_client()
    r = c.get("/lang/en?next=/sala")
    assert r.status_code == 302 and r.headers["Location"].endswith("/sala") and "lang=en" in r.headers["Set-Cookie"]
    assert c.get("/lang/en?next=//evil.com").headers["Location"].endswith("/")


@pytest.mark.skipif(not (config.PROCESSED_DIR / "dia_dep.parquet").exists(), reason="agregados diários ausentes")
def test_sala_renders_in_english(app):
    from plotly.io.json import to_json_plotly
    key = next(k for k in app.callback_map if "sala-kpis.children" in k)
    fn = app.callback_map[key]["callback"]
    fn = getattr(fn, "__wrapped__", fn)
    with app.server.test_request_context("/", headers={"Cookie": "lang=en"}):
        out = to_json_plotly(list(fn({"win": 7, "kind": "ar", "uid": "", "shape": [], "hl": None, "sort": ["score", -1]}, "pan")))
    assert "hotspots" in out and "Expected" in out and "focos em" not in out


def test_admin_login_in_english(app):
    c = app.server.test_client()
    c.set_cookie("lang", "en")
    page = c.get("/admin").get_data(as_text=True)
    assert "Sign in to admin" in page or "Admin disabled" in page
