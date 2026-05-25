"""
Motor de conciliación de cartera.
Vincula el estado financiero real del inversor con la asignación teórica
óptima para producir órdenes operativas netas (deltas enteros de acciones).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_portfolio_state(path: Path) -> tuple[float, dict[str, int], dict]:
    """
    Parsea estado_cartera.json y devuelve (capital_neto_eur, posiciones, metadata).

    Capital neto = efectivo.disponible − efectivo.reserva_gastos.
    Posiciones acepta tanto enteros simples {"SAN.MC": 500} como
    objetos enriquecidos {"SAN.MC": {"cantidad": 500, "precio_coste": 3.85}}.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Archivo de estado no encontrado: '{path}'\n"
            "Formato mínimo requerido:\n"
            '  {\n'
            '    "efectivo": {"disponible": 10000, "reserva_gastos": 0},\n'
            '    "posiciones": {"SAN.MC": 100}\n'
            '  }'
        )

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido en '{path}': {exc}") from exc

    efectivo = data.get("efectivo", {})
    disponible = efectivo.get("disponible")
    if disponible is None or not isinstance(disponible, (int, float)):
        raise ValueError("'efectivo.disponible' debe ser un número positivo en euros.")

    reserva = float(efectivo.get("reserva_gastos", 0.0))
    capital_neto = float(disponible) - reserva

    if capital_neto < 0:
        raise ValueError(
            f"Capital neto negativo ({capital_neto:.2f} EUR): "
            "'efectivo.disponible' debe superar 'efectivo.reserva_gastos'."
        )

    posiciones_raw = data.get("posiciones", {})
    if not isinstance(posiciones_raw, dict):
        raise ValueError("'posiciones' debe ser un objeto JSON {ticker: cantidad}.")

    positions: dict[str, int] = {}
    for ticker, val in posiciones_raw.items():
        qty = int(val["cantidad"]) if isinstance(val, dict) else int(val)
        if qty > 0:
            positions[ticker] = qty

    return capital_neto, positions, data.get("metadata", {})


def compute_nav(
    capital: float,
    positions: dict[str, int],
    prices: dict[str, float],
) -> float:
    """
    V_total = E + Σ(q_i · P_i)

    Donde E es el efectivo neto, q_i las acciones de cada posición
    y P_i el último precio de mercado disponible.
    """
    market_value = sum(
        qty * prices.get(ticker, 0.0)
        for ticker, qty in positions.items()
    )
    return capital + market_value


def compute_current_weights(
    positions: dict[str, int],
    prices: dict[str, float],
    nav: float,
) -> dict[str, float]:
    """Peso actual de cada posición: w_i = (q_i · P_i) / V_total."""
    if nav <= 0:
        return {}
    return {
        ticker: (qty * prices.get(ticker, 0.0)) / nav
        for ticker, qty in positions.items()
    }


def compute_deltas(
    target_weights: dict[str, float],
    nav: float,
    current_positions: dict[str, int],
    prices: dict[str, float],
    banda_abs: float = 0.05,
    banda_rel: float = 0.25,
) -> dict[str, int]:
    """
    Delta operativo: Δq_i = int(V_total · w*_i / P_i) − q_i_actual

    Aplica bandas de tolerancia dinámicas para minimizar costes de rotación:
    - Omite el activo si |Δw_i| < banda_abs  (5% absoluto, posiciones grandes)
    - Omite el activo si |Δw_i / w*_i| < banda_rel  (25% relativo, posiciones pequeñas)

    Returns:
        {ticker: delta_acciones}  — positivo=COMPRAR, negativo=VENDER.
        Los activos con delta=0 quedan excluidos del dict.
    """
    current_weights = compute_current_weights(current_positions, prices, nav)
    orders: dict[str, int] = {}

    for ticker, w_star in target_weights.items():
        price = prices.get(ticker, 0.0)
        if price <= 0:
            continue

        w_current = current_weights.get(ticker, 0.0)
        delta_w = w_star - w_current

        # Filtro de bandas de tolerancia
        within_abs = abs(delta_w) < banda_abs
        within_rel = w_star > 0 and abs(delta_w / w_star) < banda_rel
        if within_abs or within_rel:
            continue

        ideal_shares = int(nav * w_star / price)
        current_shares = current_positions.get(ticker, 0)
        delta_shares = ideal_shares - current_shares

        if delta_shares != 0:
            orders[ticker] = delta_shares

    # Liquidación total de posiciones eliminadas por el optimizador
    for ticker, qty in current_positions.items():
        if ticker not in target_weights and qty > 0:
            logger.info("Posición %s eliminada del universo óptimo → VENDER %d", ticker, qty)
            orders[ticker] = -qty

    return orders
