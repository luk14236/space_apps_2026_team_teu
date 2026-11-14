"""Admin upload tests on a temporary raw folder. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
import io
import re
import tarfile

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
    c = app.server.test_client()
    return c, tmp_path / "raw"


def _csrf(c):
    page = c.get("/admin").get_data(as_text=True)
    return re.search(r"name=csrf value=([0-9a-f]+)", page).group(1)


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


def test_upload_archive_extracts_only_allowed_csvs(client):
    c, raw = client
    _login(c)
    tok = _csrf(c)
    pkg = _tar({"output/focos_brutos_x.csv": b"pais,data_hora_gmt\n", "output/focos_america_sul.duckdb": b"x",
                "../../evil/focos_mensais_y.csv": b"ano,mes\n"})
    r = c.post("/admin/upload", data={"csrf": tok, "arquivos": (io.BytesIO(pkg), "dataset_v1.tar.gz")},
               content_type="multipart/form-data")
    assert r.status_code == 302
    assert sorted(p.name for p in raw.iterdir()) == ["focos_brutos_x.csv", "focos_mensais_y.csv"]  # path stripped, .duckdb skipped


def test_upload_rejects_unknown_files_and_bad_csrf(client):
    c, raw = client
    _login(c)
    r = c.post("/admin/upload", data={"csrf": "wrong", "arquivos": (io.BytesIO(b"x"), "focos_brutos.csv")},
               content_type="multipart/form-data")
    assert r.status_code == 400
    tok = _csrf(c)
    c.post("/admin/upload", data={"csrf": tok, "arquivos": (io.BytesIO(b"x"), "notas.txt")},
           content_type="multipart/form-data")
    assert not raw.exists() or not any(raw.iterdir())


def test_toggle_keeps_file_out_of_processing(client):
    c, raw = client
    _login(c)
    raw.mkdir(parents=True)
    (raw / "focos_brutos_a.csv").write_text("pais\n")
    tok = _csrf(c)
    r = c.post("/admin/api/toggle", json={"name": "focos_brutos_a.csv"}, headers={"X-CSRF": tok})
    assert r.status_code == 200 and (raw / "focos_brutos_a.csv.off").exists()
    files = c.get("/admin/api/state").get_json()["files"]
    assert files[0]["name"] == "focos_brutos_a.csv" and files[0]["active"] is False
    assert c.post("/admin/api/process", json={}, headers={"X-CSRF": tok}).status_code == 400  # nothing active
    c.post("/admin/api/toggle", json={"name": "focos_brutos_a.csv"}, headers={"X-CSRF": tok})
    assert (raw / "focos_brutos_a.csv").exists()
