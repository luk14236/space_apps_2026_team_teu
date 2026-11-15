import duckdb
import pandas as pd
import pytest
from pathlib import Path

from regression_pipeline import (
    build_harmonized_monthly,
    build_harmonized_weights,
    comparison_ranking,
    load_monthly_counts,
    save_selected_models,
)


def _model(country, origin, destination, c):
    return {
        "pais": country,
        "satelite_origem": origin,
        "satelite_destino": destination,
        "familia": "quasi_poisson",
        "hipotese": "potencial",
        "beta0": 0.0,
        "beta1": 1.0,
        "c": c,
        "status": "ok",
    }


def test_comparison_ranking_uses_mae_before_rmse():
    results = [
        {"status": "ok", "familia": "first", "mae": 2.0, "rmse": 1.0},
        {"status": "ok", "familia": "second", "mae": 1.0, "rmse": 3.0},
    ]

    assert comparison_ranking(results).familia.tolist() == ["second", "first"]


def test_comparison_ranking_returns_empty_when_all_models_fail():
    failed = [{"status": "failed", "familia": "broken", "mae": None, "rmse": None}]

    assert comparison_ranking(failed).empty
    assert comparison_ranking([]).empty


def test_harmonized_predictions_round_half_up():
    monthly = pd.DataFrame(
        [(2011, 1, "Argentina", "AQUA", "MODIS", 1)],
        columns=["ano", "mes", "pais", "satelite", "sensor", "nfocos"],
    )
    models = [_model("Argentina", origin, "SNPP", 1.25) for origin in ("AQUA", "TERRA")]

    result = build_harmonized_monthly(monthly, models)

    assert result.loc[result.satelite == "SNPP", "nfocos_harm"].iloc[0] == 3


def test_harmonization_prefers_aqua_falls_back_to_terra_and_preserves_observations():
    monthly = pd.DataFrame(
        [
            (2011, 1, "Argentina", "AQUA", "MODIS", 10),
            (2011, 1, "Argentina", "TERRA", "MODIS", 12),
            (2011, 2, "Argentina", "TERRA", "MODIS", 5),
            (2020, 2, "Argentina", "AQUA", "MODIS", 3),
            (2020, 2, "Argentina", "SNPP", "VIIRS", 7),
            (2020, 2, "Argentina", "NOAA20", "VIIRS", 9),
            (2020, 3, "Guiana Francesa", "AQUA", "MODIS", 11),
        ],
        columns=["ano", "mes", "pais", "satelite", "sensor", "nfocos"],
    )
    models = [
        _model(country, origin, "SNPP", c)
        for country in ("Argentina", "Guiana Francesa")
        for origin, c in (("AQUA", 2), ("TERRA", 4))
    ]

    result = build_harmonized_monthly(monthly, models)
    lookup = result.set_index(["ano", "mes", "pais", "satelite"])

    # Potential mean: c * (1 + x)^beta1. Before 2012, January prefers AQUA.
    assert lookup.loc[(2011, 1, "Argentina", "SNPP"), "nfocos_harm"] == 22
    assert lookup.loc[(2011, 1, "Argentina", "SNPP"), "nfocos"] is pd.NA
    # February 2011 has no AQUA, so it falls back to TERRA.
    assert lookup.loc[(2011, 2, "Argentina", "SNPP"), "nfocos_harm"] == 24
    assert lookup.loc[(2011, 1, "Argentina", "SNPP"), "modelo_harm"] == "AQUA->SNPP | quasi_poisson | potencial"
    assert lookup.loc[(2011, 2, "Argentina", "SNPP"), "modelo_harm"] == "TERRA->SNPP | quasi_poisson | potencial"
    # Since 2012, preserve observed SNPP in nfocos and keep the model estimate separate.
    assert lookup.loc[(2020, 2, "Argentina", "SNPP"), "nfocos"] == 7
    assert lookup.loc[(2020, 2, "Argentina", "SNPP"), "nfocos_harm"] == 8
    assert lookup.loc[(2020, 2, "Argentina", "SNPP"), "modelo_harm"] == "AQUA->SNPP | quasi_poisson | potencial"
    assert pd.isna(lookup.loc[(2020, 2, "Argentina", "NOAA20"), "nfocos_harm"])
    assert pd.isna(lookup.loc[(2020, 2, "Argentina", "NOAA20"), "modelo_harm"])
    # A post-2012 month without observed SNPP still receives a synthetic estimate.
    assert lookup.loc[(2020, 3, "Guiana Francesa", "SNPP"), "nfocos_harm"] == 24
    assert pd.isna(lookup.loc[(2020, 3, "Guiana Francesa", "SNPP"), "nfocos"])
    assert pd.isna(lookup.loc[(2020, 3, "Guiana Francesa", "AQUA"), "nfocos_harm"])
    assert result.loc[result.satelite.isin(("AQUA", "TERRA")), ["nfocos_harm", "modelo_harm"]].isna().all().all()
    assert int(result.nfocos.sum()) == int(monthly.nfocos.sum())
    assert len(result) == len(monthly) + 3
    rerun = build_harmonized_monthly(result, models)
    pd.testing.assert_frame_equal(rerun, result)

    weights = build_harmonized_weights(monthly, result).set_index(["ano", "mes", "pais", "satelite_origem"])
    assert weights.loc[(2011, 1, "Argentina", "AQUA"), "peso_harm"] == 2.2
    assert weights.loc[(2011, 2, "Argentina", "TERRA"), "peso_harm"] == 4.8
    # Spatial visualization stays on observed SNPP after 2012, not on the modeled total.
    assert weights.loc[(2020, 2, "Argentina", "SNPP"), "peso_harm"] == 1.0
    assert (2020, 2, "Argentina", "AQUA") not in weights.index
    assert (2020, 3, "Guiana Francesa", "AQUA") not in weights.index
    assert set(weights.index.get_level_values("satelite_origem")) == {"AQUA", "TERRA", "SNPP"}


def test_monthly_loader_excludes_synthetic_null_observations(tmp_path):
    path = tmp_path / "monthly.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("""CREATE TABLE focos_mensais (
            ano INTEGER, mes INTEGER, pais VARCHAR, satelite VARCHAR, sensor VARCHAR,
            nfocos BIGINT, nfocos_harm BIGINT, modelo_harm VARCHAR)""")
        con.execute("INSERT INTO focos_mensais VALUES (2020, 1, 'Argentina', 'AQUA', 'MODIS', 10, NULL, NULL)")
        con.execute("INSERT INTO focos_mensais VALUES (2020, 1, 'Argentina', 'SNPP', 'VIIRS', NULL, 22.0, 'AQUA->SNPP | quasi_poisson | potencial')")

    loaded = load_monthly_counts(path)
    assert len(loaded) == 1
    assert loaded.iloc[0].nfocos == 10


def test_save_selected_models_publishes_matching_csv_and_duckdb(tmp_path):
    database = tmp_path / "harmonized.duckdb"
    csv_path = tmp_path / "focos_mensais_america_sul.csv"
    raw_csv_path = tmp_path / "focos_brutos_america_sul.csv"
    with duckdb.connect(str(database)) as con:
        con.execute("""CREATE TABLE focos_brutos (
            pais VARCHAR, data_hora_gmt TIMESTAMP, latitude DOUBLE, longitude DOUBLE,
            satelite VARCHAR, sensor VARCHAR, frp DOUBLE, confidence VARCHAR,
            daynight VARCHAR, type INTEGER)""")
        con.execute("""INSERT INTO focos_brutos VALUES
            ('Argentina','2011-01-05 00:00:00',-34,-58,'AQUA','MODIS',1,'80','D',0),
            ('Argentina','2011-01-06 00:00:00',-34,-58,'AQUA','MODIS',1,'80','D',0),
            ('Argentina','2011-01-05 12:00:00',-34,-58,'TERRA','MODIS',1,'80','D',0),
            ('Argentina','2020-03-05 06:00:00',-34,-58,'AQUA','MODIS',1,'80','D',0),
            ('Argentina','2020-03-05 00:00:00',-34,-58,'SNPP','VIIRS',1,'n','D',0),
            ('Argentina','2020-03-06 00:00:00',-34,-58,'SNPP','VIIRS',1,'h','D',0),
            ('Argentina','2020-03-05 12:00:00',-34,-58,'NOAA20','VIIRS',1,'n','D',0)""")
        con.execute("""CREATE TABLE focos_mensais AS SELECT * FROM (VALUES
            (2011, 1, 'Argentina', 'AQUA', 'MODIS', 2::BIGINT),
            (2011, 1, 'Argentina', 'TERRA', 'MODIS', 1::BIGINT),
            (2020, 3, 'Argentina', 'AQUA', 'MODIS', 1::BIGINT),
            (2020, 3, 'Argentina', 'SNPP', 'VIIRS', 2::BIGINT),
            (2020, 3, 'Argentina', 'NOAA20', 'VIIRS', 1::BIGINT)
        ) AS t(ano,mes,pais,satelite,sensor,nfocos)""")
    csv_path.write_text("ano,mes,pais,satelite,sensor,nfocos\n2011,1,Argentina,AQUA,MODIS,2\n2011,1,Argentina,TERRA,MODIS,1\n2020,3,Argentina,AQUA,MODIS,1\n2020,3,Argentina,SNPP,VIIRS,2\n2020,3,Argentina,NOAA20,VIIRS,1\n", encoding="utf-8")
    raw_csv_path.write_text("pais,data_hora_gmt,latitude,longitude,satelite,sensor,frp,confidence,daynight,type\n", encoding="utf-8")
    models = [
        _model("Argentina", origin, destination, c)
        for origin, destination, c in (
            ("AQUA", "SNPP", 2),
            ("TERRA", "SNPP", 4),
        )
    ]
    for model in models:
        model.pop("status")  # Persisted model rows do not contain transient fit status.

    saved = save_selected_models(
        database,
        models,
        ["Argentina"],
        [("AQUA", "SNPP"), ("TERRA", "SNPP")],
        csv_path,
        raw_csv_path,
    )

    with duckdb.connect(str(database), read_only=True) as con:
        assert saved == 2
        assert con.execute("SELECT count(*) FROM modelos_equacoes").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0] == 7
        assert con.execute("SELECT sum(peso_harm) FROM focos_brutos WHERE satelite='AQUA'").fetchone()[0] == 6
        assert con.execute("SELECT sum(peso_harm) FROM focos_brutos WHERE satelite='SNPP'").fetchone()[0] == 2
        assert con.execute("SELECT sum(peso_harm) FROM focos_brutos WHERE satelite='NOAA20'").fetchone()[0] == 0
        assert con.execute("SELECT nfocos, nfocos_harm, modelo_harm FROM focos_mensais WHERE ano=2020 AND mes=3 AND satelite='SNPP'").fetchone() == (2, 4, "AQUA->SNPP | quasi_poisson | potencial")
        assert con.execute("SELECT count(*), count(*) FILTER (WHERE nfocos IS NULL), sum(nfocos) FROM focos_mensais").fetchone() == (6, 1, 7)
        assert con.execute(f"SELECT count(*) FROM ((SELECT * FROM focos_mensais) EXCEPT ALL (SELECT * FROM read_csv('{csv_path}', header=true)))").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*), sum(peso_harm) FROM read_csv('{raw_csv_path}', header=true)").fetchone() == (7, 8.0)


def test_save_selected_models_restores_files_on_keyboard_interrupt(tmp_path, monkeypatch):
    database = tmp_path / "harmonized.duckdb"
    monthly_csv = tmp_path / "monthly.csv"
    raw_csv = tmp_path / "raw.csv"
    monthly_csv.write_text("old monthly\n", encoding="utf-8")
    raw_csv.write_text("old raw\n", encoding="utf-8")
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE focos_brutos (pais VARCHAR, data_hora_gmt TIMESTAMP, satelite VARCHAR)")
        con.execute("INSERT INTO focos_brutos VALUES ('Argentina', '2011-01-01', 'AQUA')")
        con.execute("""CREATE TABLE focos_mensais AS SELECT * FROM (VALUES
            (2011, 1, 'Argentina', 'AQUA', 'MODIS', 1::BIGINT)
        ) AS t(ano,mes,pais,satelite,sensor,nfocos)""")

    models = [_model("Argentina", origin, "SNPP", 1) for origin in ("AQUA", "TERRA")]
    real_replace = __import__("os").replace
    interrupted = False

    def interrupt_raw_publication(source, destination):
        nonlocal interrupted
        if not interrupted and Path(destination) == raw_csv and str(source).endswith(".part"):
            interrupted = True
            real_replace(source, destination)
            raise KeyboardInterrupt
        return real_replace(source, destination)

    monkeypatch.setattr("regression_pipeline.os.replace", interrupt_raw_publication)

    with pytest.raises(KeyboardInterrupt):
        save_selected_models(
            database, models, ["Argentina"], [("AQUA", "SNPP"), ("TERRA", "SNPP")],
            monthly_csv, raw_csv,
        )

    assert monthly_csv.read_text(encoding="utf-8") == "old monthly\n"
    assert raw_csv.read_text(encoding="utf-8") == "old raw\n"
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM focos_mensais").fetchone()[0] == 1
        assert "modelos_equacoes" not in {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.backup"))
