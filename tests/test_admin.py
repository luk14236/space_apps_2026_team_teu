"""Admin and deliveries tests on a temporary data folder. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
import io
import re
import tarfile
import time

import pytest

from app import config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ADMIN_USER", "u")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "p")
    from app.main import create_app
    app = create_app()
    return app.server.test_client(), tmp_path


def _csrf(c):
    page = c.get("/admin").get_data(as_text=True)
    m = re.search(r"name=csrf value=([0-9a-f]+)", page) or re.search(r"const CSRF='([0-9a-f]+)'", page)
    return m.group(1)


def _login(c, user="u", pw="p"):
    return c.post("/admin/login", data={"csrf": _csrf(c), "usuario": user, "senha": pw})


def _tar(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _upload(c, tok, data: bytes, name: str):
    return c.post("/admin/upload", data={"arquivos": (io.BytesIO(data), name)}, headers={"X-CSRF": tok}, content_type="multipart/form-data")


def _wait_idle(c):
    for _ in range(100):
        if not c.get("/admin/api/state").get_json()["job"]["running"]:
            return
        time.sleep(0.1)


def test_admin_requires_login(client):
    c, _ = client
    assert "Entrar no admin" in c.get("/admin").get_data(as_text=True)
    assert c.get("/admin/api/state").status_code == 403
    assert _login(c, pw="errada").headers["Location"].endswith("erro=1")
    assert _login(c).headers["Location"].endswith("/admin")
    assert c.get("/admin/api/state").status_code == 200


def test_admin_disabled_without_credentials(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    assert c.get("/admin").status_code == 403


def test_upload_archive_creates_delivery_with_only_allowed_csvs(client):
    c, data = client
    _login(c)
    tok = _csrf(c)
    pkg = _tar({"output/focos_brutos_x.csv": b"pais,data_hora_gmt\n", "output/focos_america_sul.duckdb": b"x",
                "../../evil/focos_mensais_y.csv": b"ano,mes\n"})
    assert _upload(c, tok, pkg, "dataset_v1.tar.gz").get_json()["ok"]
    _wait_idle(c)
    ents = c.get("/admin/api/state").get_json()["entregas"]
    assert len(ents) == 1 and sorted(a["nome"] for a in ents[0]["arquivos"]) == ["focos_brutos_x.csv", "focos_mensais_y.csv"]
    assert not (data / "evil").exists()


def test_new_delivery_replaces_old_but_keeps_history(client):
    c, _ = client
    _login(c)
    tok = _csrf(c)
    _upload(c, tok, _tar({"output/focos_brutos_x.csv": b"a\n"}), "v1.tar.gz")
    _wait_idle(c)
    time.sleep(1.1)
    _upload(c, tok, _tar({"output/focos_brutos_x.csv": b"b\n"}), "v2.tar.gz")
    _wait_idle(c)
    new, old = c.get("/admin/api/state").get_json()["entregas"]  # newest first
    assert new["nome"] == "v2.tar.gz" and new["ativa"]
    assert old["nome"] == "v1.tar.gz" and not old["ativa"] and old["substituida_por"] == new["id"]
    assert c.post("/admin/api/toggle", json={"id": old["id"]}, headers={"X-CSRF": tok}).status_code == 200
    assert c.get("/admin/api/state").get_json()["entregas"][1]["ativa"] is True


def test_rejects_bad_csrf_and_unknown_files(client):
    c, _ = client
    _login(c)
    assert c.post("/admin/upload", data={"arquivos": (io.BytesIO(b"x"), "focos_brutos.csv")}, headers={"X-CSRF": "wrong"},
                  content_type="multipart/form-data").status_code == 400
    assert _upload(c, _csrf(c), b"x", "notas.txt").get_json()["ok"] is False
    assert c.get("/admin/api/state").get_json()["entregas"] == []


def test_inbox_import_and_migration(client):
    c, data = client
    from app.pipeline import entregas
    (data / "entrada").mkdir()
    (data / "entrada" / "pacote.tar.gz").write_bytes(_tar({"output/focos_brutos_z.csv": b"a\n"}))
    assert [f["nome"] for f in entregas.inbox_files()] == ["pacote.tar.gz"]
    m = entregas.from_path(data / "entrada" / "pacote.tar.gz", "pasta", lambda s: None)
    assert m["arquivos"][0]["nome"] == "focos_brutos_z.csv"
    raw = data / "raw2"  # migration only runs while there are no deliveries yet
    raw.mkdir()
    (raw / "focos_brutos_q.csv").write_text("a\n")
    entregas.migrate_raw(raw, lambda s: None)
    assert (raw / "focos_brutos_q.csv").exists()
