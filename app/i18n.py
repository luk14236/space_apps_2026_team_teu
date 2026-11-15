"""Portuguese / English interface. AI-assisted: written with Claude (Anthropic), reviewed by the team.

Portuguese is the source language: every visible text is written in Portuguese and wrapped in `tr()`, and the
English version comes from `EN` (app/i18n_en.py). The language lives in the `lang` cookie, set by /lang/<code>
(the PT | EN switch at the top of each page). Dash callbacks are HTTP requests too, so they read the same cookie.
"""
from __future__ import annotations

from urllib.parse import quote

from flask import has_request_context, request

from .i18n_en import EN

LANGS = ("pt", "en")
MONTHS = {"pt": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
          "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
MONTHS_LONG = {"pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
               "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]}


def lang() -> str:
    if has_request_context():
        v = request.args.get("lang") or request.cookies.get("lang")
        if v in LANGS:
            return v
    return "pt"


def tr(text: str, **kw) -> str:
    """Translate a Portuguese text (and fill {placeholders} when given)."""
    if lang() == "en":
        text = EN.get(text, text)
    return text.format(**kw) if kw else text


def months() -> list[str]:
    return MONTHS[lang()]


def months_long() -> list[str]:
    return MONTHS_LONG[lang()]


def num(n, decimals: int = 0) -> str:
    s = f"{n:,.{decimals}f}"  # 1,234.5
    return s if lang() == "en" else s.replace(",", "X").replace(".", ",").replace("X", ".")


def ordinal(n: int) -> str:
    if lang() == "pt":
        return f"{n}º"
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def switch_href(code: str, next_path: str) -> str:
    return f"/lang/{code}?next={quote(next_path)}"


def register_routes(server) -> None:
    from flask import redirect

    @server.route("/lang/<code>")
    def set_lang(code):
        nxt = request.args.get("next", "/")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        resp = redirect(nxt)
        if code in LANGS:
            https = request.is_secure or request.headers.get("X-Forwarded-Proto", "").startswith("https")
            # SameSite=None keeps it working when the Space is shown inside the huggingface.co iframe
            resp.set_cookie("lang", code, max_age=365 * 86400, samesite="None" if https else "Lax", secure=https)
        return resp
