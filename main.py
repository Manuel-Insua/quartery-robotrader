"""
Punto de entrada del sistema de optimización GMVP.
Orquesta el pipeline completo en 5 etapas:
  1. Carga del estado de cartera (JSON)
  2. Ingesta y caché de precios históricos (yfinance + SQLite)
  3. Optimización de mínima varianza (Ledoit-Wolf + OSQP/SCS)
  4. Conciliación y cálculo de deltas operativos
  5. Generación del informe estructurado (SRRI, CNMV, órdenes)

Uso:
    cd spanish_portfolio_optimizer
    python main.py
"""

import logging
import sys
from pathlib import Path

# ── Logging antes de cualquier import de módulo propio ────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-28s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Garantiza que los submódulos encuentren config.py independientemente
# del directorio de trabajo desde el que se invoque el script
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BANDA_TOLERANCIA_ABS,
    BANDA_TOLERANCIA_REL,
    DIAS_HISTORICO,
    ESTADO_PATH,
    GDRIVE_CREDENTIALS_PATH,
    GDRIVE_SHEET_POSICIONES,
    GDRIVE_SPREADSHEET_ID,
    GDRIVE_TOKEN_PATH,
    MAX_PESO_ACTIVO,
    UNIVERSO_IBEX,
)
from data.gdrive import load_positions_from_sheets
from data.ingester import fetch_prices, get_current_prices
from mathematical.optimizer import optimize_min_variance
from presentation.output import ReportData, print_report
from reconciliation.engine import compute_deltas, compute_nav, load_cash_state


def _load_portfolio() -> tuple[float, dict, dict]:
    """
    Efectivo: estado_cartera.json (local).
    Posiciones: pestaña 'posiciones' de Google Sheets, filtrando Estado=Abierta.
    """
    # ── Efectivo desde JSON local ──────────────────────────────────────────────
    capital, metadata = load_cash_state(ESTADO_PATH)
    logger.info("Efectivo neto: %s EUR (fuente: %s)", f"{capital:,.2f}", ESTADO_PATH.name)

    # ── Posiciones desde Google Sheets ─────────────────────────────────────────
    try:
        positions = load_positions_from_sheets(
            GDRIVE_SPREADSHEET_ID,
            GDRIVE_SHEET_POSICIONES,
            GDRIVE_CREDENTIALS_PATH,
            GDRIVE_TOKEN_PATH,
        )
    except RuntimeError as exc:
        logger.critical(
            "No se pueden cargar posiciones desde Google Sheets: %s", exc
        )
        sys.exit(1)
    except ValueError as exc:
        logger.critical("Error al parsear la pestaña '%s': %s", GDRIVE_SHEET_POSICIONES, exc)
        sys.exit(1)
    except Exception as exc:
        logger.critical("Error inesperado al leer Google Sheets: %s", exc)
        sys.exit(1)

    return capital, positions, metadata


def main() -> None:
    # ── 1. Estado de la cartera ────────────────────────────────────────────────
    logger.info("━━━ [1/5] Cargando estado de cartera ━━━")
    try:
        capital, positions, metadata = _load_portfolio()
    except (FileNotFoundError, ValueError) as exc:
        logger.critical("Error al leer efectivo desde '%s': %s", ESTADO_PATH.name, exc)
        sys.exit(1)

    logger.info(
        "Efectivo neto: %s EUR  |  Posiciones activas: %s",
        f"{capital:,.2f}", list(positions.keys()),
    )

    # ── 2. Ingesta y caché de precios ──────────────────────────────────────────
    logger.info("━━━ [2/5] Ingesta y caché de precios históricos (%d días) ━━━", DIAS_HISTORICO)
    # El universo de optimización incluye siempre los activos ya en cartera
    universe = list(dict.fromkeys(UNIVERSO_IBEX + list(positions.keys())))

    try:
        prices_hist = fetch_prices(universe, DIAS_HISTORICO)
    except (ConnectionError, ValueError) as exc:
        logger.critical("Error en la ingesta de datos: %s", exc)
        sys.exit(1)

    available = prices_hist.columns.tolist()
    logger.info("%d activos con cobertura suficiente para optimización", len(available))

    logger.info("━━━ [2b/5] Obteniendo precios actuales de mercado ━━━")
    current_prices = get_current_prices(available)
    if not current_prices:
        logger.critical("No se pudieron obtener precios de mercado actuales.")
        sys.exit(1)

    # ── 3. Optimización GMVP ───────────────────────────────────────────────────
    logger.info("━━━ [3/5] Optimización GMVP (Ledoit-Wolf + OSQP → SCS) ━━━")
    # Solo optimiza sobre activos con precio actual disponible
    opt_tickers = [t for t in available if t in current_prices]
    if len(opt_tickers) < 2:
        logger.critical(
            "Solo %d activo(s) con precio actual. Se necesitan al menos 2.", len(opt_tickers)
        )
        sys.exit(1)

    try:
        weights, volatility = optimize_min_variance(prices_hist[opt_tickers], MAX_PESO_ACTIVO)
    except RuntimeError as exc:
        logger.critical("Fallo de optimización: %s", exc)
        sys.exit(1)

    # ── 4. Conciliación y deltas ───────────────────────────────────────────────
    logger.info("━━━ [4/5] Cálculo de NAV y delta operativo ━━━")
    nav = compute_nav(capital, positions, current_prices)
    orders = compute_deltas(
        weights, nav, positions, current_prices,
        BANDA_TOLERANCIA_ABS, BANDA_TOLERANCIA_REL,
    )
    logger.info(
        "NAV total: %s EUR  |  Órdenes generadas: %d  (COMPRAR: %d, VENDER: %d)",
        f"{nav:,.2f}",
        len(orders),
        sum(1 for v in orders.values() if v > 0),
        sum(1 for v in orders.values() if v < 0),
    )

    # ── 5. Informe de salida ───────────────────────────────────────────────────
    logger.info("━━━ [5/5] Generando informe ━━━")
    print_report(ReportData(
        nav=nav,
        capital_neto=capital,
        volatility=volatility,
        target_weights=weights,
        orders=orders,
        current_positions=positions,
        prices=current_prices,
        metadata=metadata,
    ))


if __name__ == "__main__":
    main()
