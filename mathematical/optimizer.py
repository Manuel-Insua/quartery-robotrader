"""
Motor matemático de optimización de cartera.
Implementa la Cartera de Mínima Varianza Global (GMVP) con:
  - Estimador de covarianza Ledoit-Wolf (correlación constante)
  - Solver primario OSQP con redundancia SCS
  - Restricciones long-only y límite de concentración máxima
"""

import logging
import warnings

import pandas as pd
from pypfopt import EfficientFrontier, risk_models

logger = logging.getLogger(__name__)


def _compute_ledoit_wolf_cov(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Matriz de covarianza Ledoit-Wolf de correlación constante (anualizada).

    El objetivo de correlación constante estabiliza los pesos de la GMVP
    reduciendo el "efecto maximizador de errores" de la covarianza muestral
    en mercados con activos de liquidez fragmentada como el Mercado Continuo.
    Cae a covarianza muestral solo si el estimador de encogimiento falla.
    """
    try:
        cov = risk_models.risk_matrix(
            prices,
            method="ledoit_wolf_constant_correlation",
            frequency=252,
        )
        logger.info("Covarianza Ledoit-Wolf (corr. constante) calculada. δ óptimo analítico.")
        return cov
    except Exception as exc:
        logger.warning(
            "Ledoit-Wolf falló (%s). Fallback a covarianza muestral.", exc
        )
        return risk_models.risk_matrix(prices, method="sample_cov", frequency=252)


def optimize_min_variance(
    prices: pd.DataFrame,
    max_weight: float = 0.20,
) -> tuple[dict[str, float], float]:
    """
    Calcula los pesos de la GMVP y la volatilidad anualizada esperada.

    Cadena de solvers:
      1. OSQP (ADMM): primario, optimizado para QP convexo.
      2. SCS  (cono homogéneo): fallback, robusto bajo condiciones numéricas débiles.

    Args:
        prices:     DataFrame de precios ajustados (índice=fecha, columnas=tickers).
        max_weight: Límite máximo de asignación por activo (teorema Jagannathan-Ma).

    Returns:
        Tupla (pesos_limpios, volatilidad_anualizada).
    """
    cov_matrix = _compute_ledoit_wolf_cov(prices)

    for solver in ("OSQP", "SCS"):
        try:
            ef = EfficientFrontier(
                expected_returns=None,          # GMVP pura: solo minimiza varianza
                cov_matrix=cov_matrix,
                weight_bounds=(0.0, max_weight),
                solver=solver,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ef.min_volatility()

            weights = dict(ef.clean_weights())
            # portfolio_performance devuelve (retorno_esperado, volatilidad, sharpe)
            # Con expected_returns=None, retorno y sharpe son NaN
            _, volatility, _ = ef.portfolio_performance(verbose=False)

            logger.info(
                "GMVP optimizada con solver %s. Vol. anualizada=%.4f (%.2f%%)",
                solver, volatility, volatility * 100,
            )
            return weights, float(volatility)

        except Exception as exc:
            logger.warning("Solver %s falló: %s. Intentando siguiente...", solver, exc)

    raise RuntimeError(
        "Todos los solvers (OSQP, SCS) fallaron. "
        "Verifique la calidad y dimensionalidad de los datos históricos."
    )
