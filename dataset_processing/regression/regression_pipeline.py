"""Modeling utilities for the MODIS-to-VIIRS monthly count regressions notebook."""

from __future__ import annotations

import math
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.optimize as opt
import scipy.stats as scipy_stats
import statsmodels.api as sm
from statsmodels.discrete.discrete_model import NegativeBinomial

FAMILIES = ("quasi_poisson", "nb2")
HYPOTHESES = ("exponencial", "potencial", "proporcional")
PAIRS = (("AQUA", "SNPP"), ("TERRA", "SNPP"))
EXPECTED_SENSOR = {"AQUA": "MODIS", "TERRA": "MODIS", "SNPP": "VIIRS", "NOAA20": "VIIRS"}
MODEL_TABLE = "modelos_equacoes"
MODEL_COLUMNS = [
    ("pais", "VARCHAR"), ("satelite_origem", "VARCHAR"), ("satelite_destino", "VARCHAR"),
    ("familia", "VARCHAR"), ("hipotese", "VARCHAR"), ("equacao", "VARCHAR"),
    ("beta0", "DOUBLE"), ("beta1", "DOUBLE"), ("c", "DOUBLE"), ("phi", "DOUBLE"),
    ("alpha", "DOUBLE"), ("inicio_periodo", "DATE"), ("fim_periodo", "DATE"),
    ("n_meses", "INTEGER"),
    ("x_min", "DOUBLE"), ("x_max", "DOUBLE"), ("rmse", "DOUBLE"), ("mae", "DOUBLE"),
    ("vies_medio", "DOUBLE"), ("maior_erro_absoluto", "DOUBLE"), ("meses_maior_erro", "VARCHAR"),
]
PRIMARY_KEY = ("pais", "satelite_origem", "satelite_destino")
ZERO_TOLERANCE = 1e-10


@dataclass
class PreparedPair:
    frame: pd.DataFrame
    absent_months: int
    window_start: pd.Timestamp | None
    window_end: pd.Timestamp | None
    source_count: int
    destination_count: int


@dataclass
class Fit:
    status: str
    reason: str
    family: str
    hypothesis: str
    model: Any = None
    beta0: float | None = None
    beta1: float | None = None
    c: float | None = None
    phi: float | None = None
    alpha: float | None = None
    predictions: np.ndarray | None = None
    design: np.ndarray | None = None
    offset: np.ndarray | None = None
    center: float | None = None
    scale: float | None = None
    x_scale: float | None = None
    n_estimation: int = 0
    loglike: float | None = None
    diagnostics: dict | None = None


def load_monthly_counts(database_path: str | Path) -> pd.DataFrame:
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Banco DuckDB não encontrado: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "focos_mensais" not in tables:
            raise ValueError("A tabela focos_mensais não existe no DuckDB informado.")
        rows = con.execute("""
            SELECT pais, make_date(ano, mes, 1) AS data, satelite, sensor, nfocos
            FROM focos_mensais
            WHERE nfocos IS NOT NULL
        """).fetchdf()
    finally:
        con.close()
    expected_cols = {"pais", "data", "satelite", "sensor", "nfocos"}
    if set(rows.columns) != expected_cols:
        raise ValueError(f"Colunas inesperadas em focos_mensais: {list(rows.columns)}")
    rows["data"] = pd.to_datetime(rows["data"])
    rows["nfocos"] = pd.to_numeric(rows["nfocos"], errors="raise")
    if rows[list(expected_cols)].isna().any().any():
        raise ValueError("focos_mensais contém valores nulos nas colunas requeridas.")
    if not np.isfinite(rows["nfocos"].to_numpy(dtype=float)).all():
        raise ValueError("Há contagens não finitas em focos_mensais.")
    if (rows["nfocos"] < 0).any() or not np.equal(rows["nfocos"], np.floor(rows["nfocos"])).all():
        raise ValueError("As contagens devem ser inteiras não negativas.")
    unexpected_satellites = set(rows["satelite"]) - set(EXPECTED_SENSOR)
    if unexpected_satellites:
        raise ValueError(f"Satélites não reconhecidos: {sorted(unexpected_satellites)}")
    unexpected_sensor = rows[rows.apply(lambda r: EXPECTED_SENSOR.get(r["satelite"]) != r["sensor"], axis=1)]
    if not unexpected_sensor.empty:
        raise ValueError("Há pares satélite/sensor inesperados:\n" + unexpected_sensor.head(10).to_string(index=False))
    key = ["pais", "data", "satelite", "sensor"]
    duplicated = rows.duplicated(key, keep=False)
    if duplicated.any():
        raise ValueError("Há duplicidade por país, mês, satélite e sensor:\n" + rows.loc[duplicated].head(10).to_string(index=False))
    rows["nfocos"] = rows["nfocos"].astype("int64")
    return rows.sort_values(key).reset_index(drop=True)


def coverage_summary(base: pd.DataFrame) -> pd.DataFrame:
    return (base.groupby(["satelite", "sensor"], as_index=False)
            .agg(primeiro_mes=("data", "min"), ultimo_mes=("data", "max"),
                 meses_com_registro=("data", "nunique"), linhas=("nfocos", "size")))


def prepare_pair(
    base: pd.DataFrame,
    country: str,
    origin: str,
    destination: str,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> PreparedPair:
    origin_data = base[(base.pais == country) & (base.satelite == origin)][["data", "nfocos"]].rename(columns={"nfocos": "x"})
    destination_data = base[(base.pais == country) & (base.satelite == destination)][["data", "nfocos"]].rename(columns={"nfocos": "y"})
    if origin_data.empty or destination_data.empty:
        return PreparedPair(pd.DataFrame(columns=["data", "x", "y"]), 0, None, None, len(origin_data), len(destination_data))
    lower = max(origin_data.data.min(), destination_data.data.min())
    upper = min(origin_data.data.max(), destination_data.data.max())
    if start is not None:
        lower = max(lower, pd.Timestamp(start))
    if end is not None:
        upper = min(upper, pd.Timestamp(end))
    if lower > upper:
        return PreparedPair(pd.DataFrame(columns=["data", "x", "y"]), 0, None, None, len(origin_data), len(destination_data))
    origin_window = origin_data[(origin_data.data >= lower) & (origin_data.data <= upper)]
    destination_window = destination_data[(destination_data.data >= lower) & (destination_data.data <= upper)]
    calendar = pd.date_range(lower, upper, freq="MS")
    observed_union = set(origin_window.data) | set(destination_window.data)
    absent = max(0, len(calendar) - len(observed_union))
    frame = origin_window.merge(destination_window, on="data", how="inner").sort_values("data").reset_index(drop=True)
    frame = frame[["data", "x", "y"]]
    return PreparedPair(frame, absent, pd.Timestamp(lower), pd.Timestamp(upper), len(origin_window), len(destination_window))


def _invalid_fit(family: str, hypothesis: str, status: str, reason: str, **kwargs) -> Fit:
    return Fit(status=status, reason=reason, family=family, hypothesis=hypothesis, **kwargs)


def _design(x: np.ndarray, hypothesis: str) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    if hypothesis == "proporcional":
        if np.any(x <= 0):
            raise ValueError("hipótese proporcional incompatível: x contém zero e log(x) não é definido")
        return np.ones((len(x), 1)), np.log(x), 0.0, 1.0, 1.0
    if hypothesis == "potencial":
        u = np.log1p(x)
        x_scale = 1.0
    elif hypothesis == "exponencial":
        x_scale = 10000.0
        u = x / x_scale
    else:
        raise ValueError(f"Hipótese desconhecida: {hypothesis}")
    center = float(np.mean(u))
    scale = float(np.std(u, ddof=0))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("preditor sem variação para estimar inclinação")
    z = (u - center) / scale
    design = np.column_stack([np.ones(len(x)), z])
    if np.linalg.matrix_rank(design) != design.shape[1]:
        raise ValueError("matriz de desenho sem posto completo")
    return design, np.zeros(len(x)), center, scale, x_scale


def _convert_coefficients(params: np.ndarray, hypothesis: str, center: float, scale: float, x_scale: float):
    a0 = float(params[0])
    if hypothesis == "proporcional":
        beta0, beta1 = a0, None
    elif hypothesis == "potencial":
        a1 = float(params[1])
        beta0, beta1 = a0 - a1 * center / scale, a1 / scale
    else:
        a1 = float(params[1])
        beta0, beta1 = a0 - a1 * center / scale, a1 / (scale * x_scale)
    c = math.exp(beta0)
    if not math.isfinite(c) or not math.isfinite(beta0) or (beta1 is not None and not math.isfinite(beta1)):
        raise FloatingPointError("coeficientes convertidos não finitos")
    return beta0, beta1, c


def predict_equation(fit: Fit, x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if fit.hypothesis == "proporcional":
        return fit.c * x
    if fit.hypothesis == "potencial":
        return fit.c * np.power(1.0 + x, fit.beta1)
    return np.exp(fit.beta0 + fit.beta1 * x)


def _fit_quasi_poisson(y: np.ndarray, design: np.ndarray, offset: np.ndarray, hypothesis: str,
                       center: float, scale: float, x_scale: float, x: np.ndarray) -> Fit:
    k = design.shape[1]
    if len(y) <= k:
        return _invalid_fit("quasi_poisson", hypothesis, "dados_insuficientes", f"observações={len(y)}; parâmetros média={k}")
    if not np.any(y > 0):
        return _invalid_fit("quasi_poisson", hypothesis, "dados_insuficientes", "resposta toda zero não admite intercepto log finito")
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = sm.GLM(y, design, offset=offset, family=sm.families.Poisson()).fit(
                method="IRLS", scale="X2", maxiter=1000, tol=1e-10
            )
        fitted = np.asarray(result.fittedvalues, dtype=float)
        phi = float(np.sum((y - fitted) ** 2 / fitted) / (len(y) - k))
        if not result.converged:
            raise RuntimeError("IRLS não convergiu")
        if not np.isfinite(result.params).all() or not np.isfinite(fitted).all() or np.any(fitted <= 0):
            raise FloatingPointError("parâmetros/previsões inválidos")
        if not math.isfinite(phi) or phi <= 0 or not math.isclose(phi, float(result.scale), rel_tol=1e-5, abs_tol=1e-8):
            raise FloatingPointError(f"dispersão Pearson degenerada/inconsistente (phi={phi}, scale={result.scale})")
        beta0, beta1, c = _convert_coefficients(np.asarray(result.params), hypothesis, center, scale, x_scale)
        fit = Fit("ok", "", "quasi_poisson", hypothesis, model=result, beta0=beta0, beta1=beta1, c=c,
                  phi=phi, predictions=fitted, design=design, offset=offset, center=center, scale=scale,
                  x_scale=x_scale, n_estimation=len(y), diagnostics={"avisos": [str(w.message) for w in caught]})
        formula_predictions = predict_equation(fit, x)
        if not np.allclose(formula_predictions, fitted, rtol=1e-8, atol=1e-8):
            raise FloatingPointError("equação convertida não reproduz previsões GLM")
        if hypothesis == "proporcional":
            expected_c = float(y.sum() / x.sum())
            if not math.isclose(c, expected_c, rel_tol=1e-7, abs_tol=1e-9):
                raise FloatingPointError(f"identidade proporcional Quasi-Poisson falhou: c={c}; esperado={expected_c}")
        return fit
    except Exception as exc:
        return _invalid_fit("quasi_poisson", hypothesis, "falha_ajuste", f"{type(exc).__name__}: {exc}")


def _fit_nb2(y: np.ndarray, design: np.ndarray, offset: np.ndarray, hypothesis: str,
             center: float, scale: float, x_scale: float, x: np.ndarray, seed: int) -> Fit:
    k = design.shape[1]
    if len(y) <= k:
        return _invalid_fit("nb2", hypothesis, "dados_insuficientes", f"observações={len(y)}; parâmetros média={k}")
    if not np.any(y > 0):
        return _invalid_fit("nb2", hypothesis, "dados_insuficientes", "resposta toda zero não admite intercepto log finito")
    init_fit = _fit_quasi_poisson(y, design, offset, hypothesis, center, scale, x_scale, x)
    if init_fit.status != "ok":
        return _invalid_fit("nb2", hypothesis, "falha_ajuste", "inicialização Quasi-Poisson inválida: " + init_fit.reason)
    mu_q = np.asarray(init_fit.predictions)
    def nll_log_alpha(log_alpha):
        alpha = float(np.exp(log_alpha))
        size = 1.0 / alpha
        prob = size / (size + mu_q)
        values = scipy_stats.nbinom.logpmf(y, size, prob)
        return float(-np.sum(values)) if np.isfinite(values).all() else np.inf
    alpha_search = opt.minimize_scalar(nll_log_alpha, bounds=(-16, 3), method="bounded", options={"xatol": 1e-8, "maxiter": 1000})
    if not alpha_search.success or min(abs(alpha_search.x - (-16)), abs(alpha_search.x - 3)) < 1e-4:
        return _invalid_fit("nb2", hypothesis, "falha_ajuste", f"busca inicial de alpha falhou/atingiu limite: {alpha_search.message}")
    alpha_init = float(np.exp(alpha_search.x))
    start_beta = np.asarray(init_fit.model.params, dtype=float)
    base_ll = -nll_log_alpha(math.log(alpha_init))
    rng = np.random.default_rng(seed)
    starts = [np.r_[start_beta, alpha_init],
              np.r_[start_beta + rng.normal(0, 0.04, size=k), alpha_init],
              np.r_[start_beta, alpha_init * 0.7],
              np.r_[start_beta, alpha_init * 1.3]]
    candidates, failures = [], []
    model = NegativeBinomial(y, design, loglike_method="nb2", offset=offset)
    for method in ("bfgs", "lbfgs"):
        for start_params in starts:
            try:
                optimizer_options = {"gtol": 1e-8} if method == "bfgs" else {"pgtol": 1e-8, "factr": 1e7}
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    result = model.fit(start_params=start_params.copy(), method=method, maxiter=5000, disp=0,
                                       full_output=True, **optimizer_options)
                params = np.asarray(result.params, dtype=float)
                alpha = float(params[-1])
                beta_internal = params[:k]
                fitted = np.asarray(result.predict(exog=design, offset=offset), dtype=float)
                cov = np.asarray(result.cov_params(), dtype=float)
                retvals = getattr(result, "mle_retvals", {}) or {}
                converged = bool(retvals.get("converged", False))
                llf = float(result.llf)
                if (not converged or not np.isfinite(params).all() or alpha <= 0 or
                    not np.isfinite(fitted).all() or np.any(fitted <= 0) or
                    not math.isfinite(llf) or cov.shape != (k + 1, k + 1) or
                    not np.isfinite(cov).all() or np.any(np.diag(cov) <= 0)):
                    failures.append(f"{method}: solução/convergência/covariância inválida")
                    continue
                try:
                    eig = np.linalg.eigvalsh(cov)
                    covariance_pd = bool(np.all(eig > 0))
                except np.linalg.LinAlgError:
                    covariance_pd = False
                if not covariance_pd:
                    failures.append(f"{method}: covariância não positiva definida")
                    continue
                grad = retvals.get("gopt")
                if grad is not None:
                    grad = np.asarray(grad, dtype=float)
                    if not np.isfinite(grad).all() or np.max(np.abs(grad)) / max(len(y), 1) >= 1e-4:
                        failures.append(f"{method}: gradiente não atingiu tolerância")
                        continue
                if llf < base_ll - 1e-5:
                    failures.append(f"{method}: log-verossimilhança abaixo da inicialização")
                    continue
                beta0, beta1, c = _convert_coefficients(beta_internal, hypothesis, center, scale, x_scale)
                fit = Fit("ok", "", "nb2", hypothesis, model=result, beta0=beta0, beta1=beta1, c=c,
                          alpha=alpha, predictions=fitted, design=design, offset=offset, center=center,
                          scale=scale, x_scale=x_scale, n_estimation=len(y), loglike=llf,
                          diagnostics={"optimizer": method, "mle_retvals": _json_safe(retvals), "avisos": [str(w.message) for w in caught]})
                if not np.allclose(predict_equation(fit, x), fitted, rtol=1e-8, atol=1e-8):
                    failures.append(f"{method}: equação convertida não reproduz previsões")
                    continue
                candidates.append(fit)
            except Exception as exc:
                failures.append(f"{method}: {type(exc).__name__}: {exc}")
    if not candidates:
        return _invalid_fit("nb2", hypothesis, "falha_ajuste", "nenhuma tentativa NB2 válida; " + " | ".join(failures[-4:]))
    candidates.sort(key=lambda fit: fit.loglike, reverse=True)
    best = candidates[0]
    best.diagnostics["tentativas_validas"] = len(candidates)
    best.diagnostics["tentativas_falhas"] = failures
    return best


def fit_model(data: pd.DataFrame, family: str, hypothesis: str, seed: int = 20261112) -> Fit:
    if family not in FAMILIES:
        return _invalid_fit(family, hypothesis, "falha_ajuste", f"família desconhecida: {family}")
    if hypothesis not in HYPOTHESES:
        return _invalid_fit(family, hypothesis, "falha_ajuste", f"hipótese desconhecida: {hypothesis}")
    if data.empty:
        return _invalid_fit(family, hypothesis, "dados_insuficientes", "nenhum mês pareado")
    x = data.x.to_numpy(dtype=float)
    y = data.y.to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(x < 0) or np.any(y < 0):
        return _invalid_fit(family, hypothesis, "falha_ajuste", "contagens não finitas ou negativas")
    try:
        design, offset, center, scale, x_scale = _design(x, hypothesis)
    except ValueError as exc:
        status = "incompativel" if "incompatível" in str(exc) else "dados_insuficientes"
        return _invalid_fit(family, hypothesis, status, str(exc))
    if family == "quasi_poisson":
        return _fit_quasi_poisson(y, design, offset, hypothesis, center, scale, x_scale, x)
    return _fit_nb2(y, design, offset, hypothesis, center, scale, x_scale, x, seed)


def model_equation(fit: Fit, origin: str, destination: str) -> str | None:
    if fit.status != "ok":
        return None
    if fit.hypothesis == "proporcional":
        rhs = f"{fit.c:.12g} * {origin}"
    elif fit.hypothesis == "potencial":
        rhs = f"{fit.c:.12g} * (1 + {origin})**({fit.beta1:.12g})"
    else:
        rhs = f"exp({fit.beta0:.12g} + {fit.beta1:.12g} * {origin})"
    return f"{destination}_estimado = {rhs}"


def calculate_metrics(data: pd.DataFrame, fit: Fit) -> tuple[dict, pd.DataFrame]:
    if fit.status != "ok":
        return {}, pd.DataFrame()
    x = data.x.to_numpy(dtype=float)
    y = data.y.to_numpy(dtype=float)
    mu = np.asarray(fit.predictions, dtype=float)
    if not np.isfinite(mu).all():
        raise FloatingPointError("Previsões não finitas; métricas não calculadas.")
    residual = y - mu
    abs_resid = np.abs(residual)
    maximum = float(abs_resid.max())
    tied = abs_resid >= maximum - max(ZERO_TOLERANCE, abs(maximum) * ZERO_TOLERANCE)
    diagnostics = data[["data"]].copy()
    diagnostics["x"] = x
    diagnostics["y"] = y
    diagnostics["media_prevista"] = mu
    diagnostics["residuo_bruto"] = residual
    metrics = {"rmse": float(np.sqrt(np.mean(residual ** 2))), "mae": float(np.mean(abs_resid)),
               "vies_medio": float(np.mean(residual)), "maior_erro_absoluto": maximum,
               "meses_maior_erro": ",".join(diagnostics.loc[tied, "data"].dt.strftime("%Y-%m").tolist())}
    return metrics, diagnostics


def make_record(
    country: str, origin: str, destination: str,
    family: str, hypothesis: str, prepared: PreparedPair, fit: Fit,
    diagnostics: pd.DataFrame | None = None,
) -> dict:
    metrics = {}
    if fit.status == "ok" and diagnostics is not None and not diagnostics.empty:
        residual = diagnostics.residuo_bruto.to_numpy(dtype=float)
        abs_resid = np.abs(residual)
        maximum = float(abs_resid.max())
        tied = abs_resid >= maximum - max(ZERO_TOLERANCE, abs(maximum) * ZERO_TOLERANCE)
        metrics = {"rmse": float(np.sqrt(np.mean(residual ** 2))), "mae": float(np.mean(abs_resid)),
                   "vies_medio": float(np.mean(residual)), "maior_erro_absoluto": maximum,
                   "meses_maior_erro": ",".join(diagnostics.loc[tied, "data"].dt.strftime("%Y-%m").tolist())}
    dates = prepared.frame.data if not prepared.frame.empty else pd.Series(dtype="datetime64[ns]")
    row = {column: None for column, _ in MODEL_COLUMNS}
    row.update({"pais": country, "satelite_origem": origin, "satelite_destino": destination,
                "familia": family, "hipotese": hypothesis,
                "equacao": model_equation(fit, origin, destination), "beta0": fit.beta0,
                "beta1": fit.beta1, "c": fit.c, "phi": fit.phi, "alpha": fit.alpha,
                "inicio_periodo": dates.min().date() if not dates.empty else None,
                "fim_periodo": dates.max().date() if not dates.empty else None,
                "n_meses": len(prepared.frame),
                "x_min": float(prepared.frame.x.min()) if not prepared.frame.empty else None,
                "x_max": float(prepared.frame.x.max()) if not prepared.frame.empty else None,
                "rmse": metrics.get("rmse"), "mae": metrics.get("mae"),
                "vies_medio": metrics.get("vies_medio"),
                "maior_erro_absoluto": metrics.get("maior_erro_absoluto"),
                "meses_maior_erro": metrics.get("meses_maior_erro"),
                "status": fit.status, "motivo_status": fit.reason})
    return row


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (float, int, str, bool)) or value is None:
        return value
    return str(value)


MONTHLY_COLUMNS = ["ano", "mes", "pais", "satelite", "sensor", "nfocos", "nfocos_harm", "modelo_harm"]


def build_harmonized_monthly(monthly: pd.DataFrame, records: list[dict]) -> pd.DataFrame:
    """Estimate the SNPP-scale count wherever a MODIS observation exists.

    AQUA is preferred as the MODIS predictor; TERRA is used only when AQUA is
    absent for that country and month. Observed SNPP remains in ``nfocos`` and
    never gets copied into ``nfocos_harm``. A synthetic SNPP row is created
    when MODIS exists but no observed SNPP row exists, regardless of year.
    """
    required = {"ano", "mes", "pais", "satelite", "sensor", "nfocos"}
    if not required.issubset(monthly.columns):
        raise ValueError(f"Agregado mensal sem colunas necessárias: {sorted(required - set(monthly.columns))}")

    model_by_key = {}
    for record in records:
        key = (record["pais"], record["satelite_origem"], record["satelite_destino"])
        if key in model_by_key:
            raise ValueError(f"Modelo duplicado para {key}")
        if record.get("status", "ok") != "ok":
            raise ValueError(f"Modelo inválido para {key}: {record.get('motivo_status', record.get('status'))}")
        model_by_key[key] = record

    base = monthly[list(required)].copy()
    # Rebuild all synthetic VIIRS rows from scratch; only SNPP is harmonized.
    base = base[~(base.satelite.isin(("SNPP", "NOAA20")) & base.nfocos.isna())].copy()
    base = base.reset_index(drop=True)
    base["nfocos"] = pd.to_numeric(base["nfocos"], errors="raise").astype("Int64")
    base["nfocos_harm"] = pd.array([None] * len(base), dtype="Float64")
    base["modelo_harm"] = None

    modis = base[base.satelite.isin(("AQUA", "TERRA")) & base.nfocos.notna()]
    for (country, year, month), group in modis.groupby(["pais", "ano", "mes"], sort=False):
        source_rows = {row.satelite: int(row.nfocos) for row in group.itertuples()}
        origin = "AQUA" if "AQUA" in source_rows else "TERRA"
        x = source_rows[origin]
        key = (country, origin, "SNPP")
        model = model_by_key.get(key)
        if model is None:
            raise ValueError(f"Modelo ausente para previsão {country}: {origin}→SNPP")
        hypothesis = model["hipotese"]
        beta0 = float(model["beta0"])
        beta1 = model["beta1"]
        c = float(model["c"])
        if hypothesis == "proporcional":
            predicted = c * x
        elif hypothesis == "potencial":
            predicted = c * (1.0 + x) ** float(beta1)
        elif hypothesis == "exponencial":
            predicted = math.exp(beta0 + float(beta1) * x)
        else:
            raise ValueError(f"Hipótese de modelo desconhecida: {hypothesis}")
        if not math.isfinite(predicted) or predicted < 0:
            raise FloatingPointError(f"Previsão inválida para {country} {year}-{month:02d} {origin}→SNPP: {predicted}")
        predicted = math.floor(predicted + 0.5)

        target = (base.pais == country) & (base.ano == year) & (base.mes == month) & (base.satelite == "SNPP")
        label = f"{origin}->SNPP | {model['familia']} | {hypothesis}"
        if target.any():
            base.loc[target, "nfocos_harm"] = predicted
            base.loc[target, "modelo_harm"] = label
        else:
            base.loc[len(base)] = {
                "ano": int(year), "mes": int(month), "pais": country,
                "satelite": "SNPP", "sensor": "VIIRS", "nfocos": pd.NA,
                "nfocos_harm": predicted, "modelo_harm": label,
            }

    result = base[MONTHLY_COLUMNS].copy()
    result["ano"] = result.ano.astype("int32")
    result["mes"] = result.mes.astype("int8")
    result["nfocos"] = result.nfocos.astype("Int64")
    result["nfocos_harm"] = result.nfocos_harm.astype("Int64")
    return result.sort_values(["ano", "mes", "pais", "satelite", "sensor"], kind="mergesort").reset_index(drop=True)


def build_harmonized_weights(monthly: pd.DataFrame, harmonized: pd.DataFrame) -> pd.DataFrame:
    """Build spatial weights without replacing observed SNPP after 2012.

    Before 2012, the modeled total is spread over the selected MODIS source.
    From 2012 onward, every observed SNPP hotspot keeps weight 1. Modeled
    monthly estimates without observed SNPP therefore have no spatial weight.
    """
    targets = harmonized[(harmonized.nfocos_harm.notna()) & (harmonized.ano < 2012)][
        ["ano", "mes", "pais", "nfocos_harm", "modelo_harm"]
    ].copy()
    targets["satelite_origem"] = targets.modelo_harm.map(lambda label: label.split("->", 1)[0])
    if not targets.satelite_origem.isin(("AQUA", "TERRA")).all():
        raise ValueError("Há uma origem inválida em modelo_harm.")
    source = monthly[["pais", "ano", "mes", "satelite", "nfocos"]].copy()
    source = source[source.nfocos.notna()].rename(columns={"satelite": "satelite_origem", "nfocos": "nfocos_origem"})
    modeled = targets.merge(source, on=["pais", "ano", "mes", "satelite_origem"], how="left", validate="one_to_one")
    if modeled.nfocos_origem.isna().any() or (modeled.nfocos_origem <= 0).any():
        bad = modeled[modeled.nfocos_origem.isna() | (modeled.nfocos_origem <= 0)]
        raise ValueError("Não há focos de origem para distribuir nfocos_harm:\n" + bad.head(10).to_string(index=False))
    modeled["peso_harm"] = modeled.nfocos_harm.astype(float) / modeled.nfocos_origem.astype(float)

    observed = source[(source.satelite_origem == "SNPP") & (source.ano >= 2012)][
        ["pais", "ano", "mes", "satelite_origem"]
    ].copy()
    observed["peso_harm"] = 1.0
    weights = pd.concat([modeled, observed], ignore_index=True)
    return weights[["pais", "ano", "mes", "satelite_origem", "peso_harm"]]


def save_selected_models(
    database_path: str | Path,
    records: list[dict],
    countries: list[str],
    pairs: list[tuple[str, str]],
    monthly_csv_path: str | Path | None = None,
    raw_csv_path: str | Path | None = None,
) -> int:
    """Publish models, predictions and weights with rollback on handled failures."""
    if not records:
        raise ValueError("Nenhum modelo escolhido para persistir; tabela não será alterada.")
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    failed = [r for r in records if r.get("status", "ok") != "ok"]
    if failed:
        details = "; ".join(f"{r.get('pais')} {r.get('satelite_origem')}→{r.get('satelite_destino')}: {r.get('motivo_status')}" for r in failed[:8])
        raise ValueError(f"Há {len(failed)} ajustes inválidos; tabela existente preservada. {details}")
    expected_keys = {(country, origin, destination) for country in countries for origin, destination in pairs}
    record_keys = {(r["pais"], r["satelite_origem"], r["satelite_destino"]) for r in records}
    if len(record_keys) != len(records) or record_keys != expected_keys:
        missing = sorted(expected_keys - record_keys)
        unexpected = sorted(record_keys - expected_keys)
        raise ValueError(f"Conjunto de ajustes incompleto/duplicado; tabela existente preservada. Ausentes={missing}; inesperados={unexpected}")
    selected_specs = {(r["familia"], r["hipotese"]) for r in records}
    if len(selected_specs) != 1:
        raise ValueError("A tabela deve conter somente uma família e hipótese globais por execução.")
    columns_sql = ",\n".join(f'"{name}" {dtype}' + (" NOT NULL" if name in PRIMARY_KEY else "") for name, dtype in MODEL_COLUMNS)
    names = [name for name, _ in MODEL_COLUMNS]
    csv_path = Path(monthly_csv_path).expanduser().resolve() if monthly_csv_path is not None else path.parent / "focos_mensais_america_sul.csv"
    raw_path = Path(raw_csv_path).expanduser().resolve() if raw_csv_path is not None else path.parent / "focos_brutos_america_sul.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    temp_csv: Path | None = None
    raw_temp_csv: Path | None = None
    file_publications: list[tuple[Path, Path]] = []
    backups: dict[Path, Path] = {}
    published: set[Path] = set()
    database_committed = False
    commit_attempted = False
    con = None
    try:
        temp_fd, temp_name = tempfile.mkstemp(prefix=csv_path.name + ".", suffix=".part", dir=csv_path.parent)
        os.close(temp_fd)
        temp_csv = Path(temp_name)
        raw_fd, raw_temp_name = tempfile.mkstemp(prefix=raw_path.name + ".", suffix=".part", dir=raw_path.parent)
        os.close(raw_fd)
        raw_temp_csv = Path(raw_temp_name)
        file_publications = [(temp_csv, csv_path), (raw_temp_csv, raw_path)]
        con = duckdb.connect(str(path))
        monthly = con.execute("SELECT ano, mes, pais, satelite, sensor, nfocos FROM focos_mensais").fetchdf()
        raw_expected = con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        harmonized = build_harmonized_monthly(monthly, records)
        weights = build_harmonized_weights(monthly, harmonized)
        expected_nfocos_sum = int(monthly.nfocos.sum())
        if int(harmonized.nfocos.sum()) != expected_nfocos_sum:
            raise RuntimeError("A harmonização alterou a soma das contagens observadas.")
        harmonized.to_csv(temp_csv, index=False, na_rep="", float_format="%.17g")
        con.execute("SELECT 1").fetchall()  # Drain DuckDB's previous result before registering pandas frames.
        con.register("_harmonized_monthly", harmonized)
        con.register("_harmonized_weights", weights)

        con.execute("BEGIN TRANSACTION")
        con.execute(f"DROP TABLE IF EXISTS {MODEL_TABLE}")
        pk_sql = ", ".join(f'"{name}"' for name in PRIMARY_KEY)
        con.execute(f'CREATE TABLE {MODEL_TABLE} ({columns_sql}, PRIMARY KEY ({pk_sql}))')
        placeholders = ",".join(["?"] * len(names))
        statement = f'INSERT INTO {MODEL_TABLE} ({",".join(chr(34) + n + chr(34) for n in names)}) VALUES ({placeholders})'
        values = [[record.get(name) for name in names] for record in records]
        con.executemany(statement, values)
        actual_count = con.execute(f"SELECT count(*) FROM {MODEL_TABLE}").fetchone()[0]
        if actual_count != len(expected_keys):
            raise RuntimeError(f"Validação da substituição falhou: esperados {len(expected_keys)} registros, inseridos {actual_count}.")

        con.execute("""CREATE OR REPLACE TABLE focos_mensais AS
            SELECT ano::INTEGER AS ano, mes::INTEGER AS mes, pais::VARCHAR AS pais,
                   satelite::VARCHAR AS satelite, sensor::VARCHAR AS sensor,
                   nfocos::BIGINT AS nfocos, nfocos_harm::BIGINT AS nfocos_harm,
                   modelo_harm::VARCHAR AS modelo_harm
            FROM _harmonized_monthly""")

        raw_columns = {row[0] for row in con.execute("DESCRIBE focos_brutos").fetchall()}
        raw_projection = 'b.* EXCLUDE (peso_harm)' if "peso_harm" in raw_columns else "b.*"
        con.execute(f"""CREATE OR REPLACE TABLE focos_brutos AS
            SELECT {raw_projection}, coalesce(w.peso_harm, 0.0)::DOUBLE AS peso_harm
            FROM focos_brutos b
            LEFT JOIN _harmonized_weights w
              ON b.pais = w.pais
             AND year(b.data_hora_gmt) = w.ano
             AND month(b.data_hora_gmt) = w.mes
             AND upper(b.satelite) = w.satelite_origem""")
        raw_rows = con.execute("SELECT count(*) FROM focos_brutos").fetchone()[0]
        if raw_rows != raw_expected:
            raise RuntimeError("A aplicação de peso_harm alterou a quantidade de focos brutos.")
        bad_weight_sums = con.execute("""WITH weighted AS (
                SELECT pais, year(data_hora_gmt)::INTEGER AS ano,
                       month(data_hora_gmt)::INTEGER AS mes, sum(peso_harm) AS peso
                FROM focos_brutos GROUP BY ALL
            ), expected AS (
                SELECT pais, ano, mes, nfocos_harm::DOUBLE AS expected_weight
                FROM _harmonized_monthly
                WHERE ano < 2012 AND nfocos_harm IS NOT NULL
                UNION ALL
                SELECT pais, ano, mes, nfocos::DOUBLE AS expected_weight
                FROM _harmonized_monthly
                WHERE ano >= 2012 AND satelite = 'SNPP' AND nfocos IS NOT NULL
            )
            SELECT count(*) FROM expected e LEFT JOIN weighted w USING (pais, ano, mes)
            WHERE w.peso IS NULL OR abs(w.peso - e.expected_weight) > 1e-5""").fetchone()[0]
        if bad_weight_sums:
            raise RuntimeError(f"peso_harm não reproduz a referência espacial em {bad_weight_sums} país/mês.")
        raw_sql_path = str(raw_temp_csv.resolve()).replace("'", "''")
        con.execute(f"COPY (SELECT * FROM focos_brutos) TO '{raw_sql_path}' (FORMAT CSV, HEADER TRUE)")

        for temp_file, final_file in file_publications:
            if final_file.exists():
                backup_fd, backup_name = tempfile.mkstemp(prefix=final_file.name + ".", suffix=".backup", dir=final_file.parent)
                os.close(backup_fd)
                backup = Path(backup_name)
                backup.unlink()
                backups[final_file] = backup
                os.replace(final_file, backup)
            published.add(final_file)
            os.replace(temp_file, final_file)
        commit_attempted = True
        con.execute("COMMIT")
        database_committed = True
    except BaseException:
        rolled_back = False
        no_active_transaction = False
        if con is not None:
            try:
                con.execute("ROLLBACK")
                rolled_back = True
            except Exception as rollback_error:
                no_active_transaction = "no transaction is active" in str(rollback_error).lower()
        should_restore_files = not database_committed and not (commit_attempted and no_active_transaction)
        if should_restore_files:
            for _, final_file in reversed(file_publications):
                backup = backups.get(final_file)
                if backup is not None and backup.exists():
                    os.replace(backup, final_file)
                elif final_file in published:
                    final_file.unlink(missing_ok=True)
        elif commit_attempted and no_active_transaction:
            # COMMIT completed if a subsequent ROLLBACK reports no active transaction.
            database_committed = True
        raise
    finally:
        if con is not None:
            try:
                con.close()
            except BaseException:
                pass
        for temporary in (temp_csv, raw_temp_csv):
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except BaseException:
                    pass
        if database_committed:
            for backup in backups.values():
                try:
                    backup.unlink(missing_ok=True)
                except BaseException:
                    pass
    return len(records)


def plot_diagnostic(data: pd.DataFrame, fit: Fit, country: str, origin: str, destination: str,
                    family: str, hypothesis: str, period_text: str, kind: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    title = f"{country} | {origin} → {destination} | {family} | {hypothesis} | {period_text}"
    if fit.status != "ok" or data.empty:
        ax.text(0.5, 0.5, fit.reason or "Sem dados para ajuste", ha="center", va="center", wrap=True)
        ax.set_title(title)
        ax.axis("off")
        fig.tight_layout()
        return fig
    metrics, diagnostics = calculate_metrics(data, fit)
    if kind == "curva média":
        x = diagnostics.x.to_numpy(dtype=float)
        ax.scatter(x, diagnostics.y, s=22, alpha=0.65, label="Observado")
        grid = np.linspace(float(np.min(x)), float(np.max(x)), 400)
        ax.plot(grid, predict_equation(fit, grid), color="darkorange", lw=2, label="Média estimada")
        ax.set_xlabel(f"Contagem mensal {origin}")
        ax.set_ylabel(f"Contagem mensal {destination}")
        ax.legend()
    elif kind == "observado × previsto":
        predicted, observed = diagnostics.media_prevista.to_numpy(), diagnostics.y.to_numpy()
        ax.scatter(predicted, observed, s=22, alpha=0.65)
        bounds = [min(float(predicted.min()), float(observed.min())), max(float(predicted.max()), float(observed.max()))]
        ax.plot(bounds, bounds, "k--", lw=1, label="1:1")
        ax.set_xlim(bounds)
        ax.set_ylim(bounds)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("Média prevista")
        ax.set_ylabel("Observado")
        ax.legend()
        ax.text(0.02, 0.98, f"RMSE={metrics['rmse']:.4g}; MAE={metrics['mae']:.4g}", transform=ax.transAxes, va="top")
    else:
        ordered = diagnostics.sort_values("data")
        ax.axhline(0, color="black", lw=1)
        ax.scatter(ordered.data, ordered.residuo_bruto, s=22, alpha=0.7)
        ax.set_xlabel("Mês")
        ax.set_ylabel("Observado − previsto")
    ax.set_title(title)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def comparison_ranking(results: list[dict]) -> pd.DataFrame:
    table = pd.DataFrame(results)
    if table.empty:
        return table
    valid = table[(table.status == "ok") & table.mae.notna()].copy()
    return valid.sort_values(["mae", "rmse"], kind="mergesort").reset_index(drop=True)
