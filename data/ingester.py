"""
Módulo de ingesta de datos de mercado.
Único punto de contacto con Yahoo Finance: gestiona rate limiting,
cabeceras User-Agent, ajuste por dividendos/splits y caché SQLite incremental.
"""

import logging
import random
import time
import warnings
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

from config import (
    BANDA_TOLERANCIA_ABS,  # noqa: F401 – re-exportado para conveniencia
    DB_PATH,
    DIAS_HISTORICO,
    MAX_FFILL_DIAS,
    MIN_COBERTURA,
    SLEEP_MAX_S,
    SLEEP_MIN_S,
)
from data.cache_db import get_cached_prices, get_last_cached_date, save_prices

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _make_session() -> requests.Session:
    """
    Sesión HTTP con cabeceras de navegador dinámicas.
    Intenta curl_cffi (mejor anti-fingerprint) y cae a requests estándar.
    """
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore
        return cffi_requests.Session(impersonate="chrome")
    except ImportError:
        pass

    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return session


def _start_date_for_window(dias: int) -> str:
    """Fecha de inicio con buffer 1.5× para absorber fines de semana y festivos."""
    return (datetime.today() - timedelta(days=int(dias * 1.50))).strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.today().strftime("%Y-%m-%d")


def _download_ticker(
    ticker: str,
    start: str,
    end: str,
    session: requests.Session,
) -> pd.Series | None:
    """
    Descarga el precio de cierre completamente ajustado (dividendos + splits)
    para un único ticker. El retardo preventivo evita el rate limiting por IP.
    """
    time.sleep(random.uniform(SLEEP_MIN_S, SLEEP_MAX_S))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t = yf.Ticker(ticker, session=session)
            hist = t.history(start=start, end=end, auto_adjust=True, timeout=12)

        if hist.empty or "Close" not in hist.columns:
            return None

        series = hist["Close"].copy()
        # Eliminar timezone para homogeneizar con el índice del caché
        if hasattr(series.index, "tz") and series.index.tz is not None:
            series.index = series.index.tz_localize(None)
        return series.rename(ticker)

    except Exception as exc:
        logger.warning("Descarga fallida [%s]: %s", ticker, exc)
        return None


def fetch_prices(tickers: list[str], dias: int = DIAS_HISTORICO) -> pd.DataFrame:
    """
    Devuelve DataFrame de precios ajustados (columnas=tickers, índice=fecha).

    Pipeline:
    1. Para cada ticker, comprueba última fecha cacheada en SQLite.
    2. Descarga solo el periodo incremental que falta desde Yahoo Finance.
    3. Aplica ffill para precios estancados (stale prices) de activos ilíquidos.
    4. Descarta activos con cobertura inferior al umbral MIN_COBERTURA.
    """
    start_global = _start_date_for_window(dias)
    today = _today()
    session = _make_session()

    series_map: dict[str, pd.Series] = {}
    skipped: list[str] = []

    for ticker in tickers:
        last_cached = get_last_cached_date(DB_PATH, ticker)
        needs_fetch = last_cached is None or last_cached < today

        if needs_fetch:
            # Descarga incremental: solo desde la última fecha cacheada
            fetch_from = (
                last_cached if (last_cached and last_cached >= start_global)
                else start_global
            )
            logger.info("[FETCH] %-12s desde %s", ticker, fetch_from)
            fresh = _download_ticker(ticker, fetch_from, today, session)
            if fresh is not None and not fresh.empty:
                save_prices(DB_PATH, ticker, fresh)
            else:
                logger.warning("[WARN]  %-12s sin datos en Yahoo Finance", ticker)
        else:
            logger.info("[CACHE] %-12s (hasta %s)", ticker, last_cached)

        cached = get_cached_prices(DB_PATH, ticker, start_global)
        if cached.empty:
            skipped.append(ticker)
        else:
            series_map[ticker] = cached["close"].rename(ticker)

    if not series_map:
        raise ValueError("No se obtuvieron datos de precio para ningún activo del universo.")

    if skipped:
        logger.warning("Activos sin datos: %s", skipped)

    prices = pd.concat(series_map.values(), axis=1)

    # ffill limitado: cubre festivos locales y huecos breves de iliquidez
    prices = prices.ffill(limit=MAX_FFILL_DIAS)

    # Filtrado de liquidez: rechaza activos por debajo del umbral de cobertura
    min_rows = int(len(prices) * MIN_COBERTURA)
    valid = prices.columns[prices.count() >= min_rows].tolist()
    dropped = [t for t in prices.columns if t not in valid]
    if dropped:
        logger.warning(
            "Activos descartados por cobertura insuficiente (<%d%%): %s",
            int(MIN_COBERTURA * 100), dropped,
        )
    if len(valid) < 2:
        raise ValueError(
            f"Se necesitan al menos 2 activos con datos completos. "
            f"Solo hay {len(valid)} tras el filtrado de liquidez."
        )

    return prices[valid].dropna()


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """
    Último precio disponible por ticker.
    Intenta fast_info (menor latencia); si falla, usa history de 5 días.
    """
    session = _make_session()
    prices: dict[str, float] = {}
    failed: list[str] = []

    for ticker in tickers:
        time.sleep(random.uniform(SLEEP_MIN_S, SLEEP_MAX_S))
        price: float | None = None

        try:
            fi = yf.Ticker(ticker, session=session).fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            if price:
                price = float(price)
        except Exception:
            pass

        if not price or price <= 0:
            try:
                hist = yf.Ticker(ticker, session=session).history(
                    period="5d", auto_adjust=True
                )
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass

        if price and price > 0:
            prices[ticker] = price
        else:
            failed.append(ticker)

    if failed:
        logger.warning("Precio actual no disponible: %s", failed)

    return prices
