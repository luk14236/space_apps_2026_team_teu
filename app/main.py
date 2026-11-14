"""Entry point: python -m app.main  (AI-assisted: written with Claude (Anthropic), reviewed by the team)."""
from __future__ import annotations

from dash import Dash, Input, Output

from . import config
from .admin import create_blueprint
from .data.geo import Geo
from .data.repository import Repository
from .ui.callbacks import register
from .ui.layout import build_layout, empty_layout, root_layout
from .ui.sala import register_sala, sala_layout


def create_app() -> Dash:
    geo = Geo(config.GEO_DIR)
    repo = Repository(config.PROCESSED_DIR, geo)  # empty until data/processed exists; /admin can build it
    app = Dash(__name__, title="Calendário de Focos", update_title=None, suppress_callback_exceptions=True)
    app.server.secret_key = config.SECRET_KEY
    app.server.register_blueprint(create_blueprint(lambda: repo))
    app.layout = root_layout

    @app.callback(Output("page", "children"), Input("url", "pathname"))
    def route(path):
        if path == "/sala":
            return sala_layout(repo)
        return build_layout(repo) if repo.ready else empty_layout()

    register(app, repo)
    register_sala(app, repo)
    return app


app = create_app()
server = app.server  # for gunicorn: gunicorn app.main:server

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
