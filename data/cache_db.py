"""
Capa de persistencia local SQLite.
Tabla asset_prices con PK compuesta (date, ticker) actúa como caché
de series temporales para evitar peticiones redundantes a Yahoo Finance.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd


def _ensure_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS asset_prices (
                date    TEXT NOT NULL,
                ticker  TEXT NOT NULL,
                close   REAL NOT NULL,
                PRIMARY KEY (date, ticker)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticker_date "
            "ON asset_prices (ticker, date)"
        )
        conn.commit()


@contextmanager
def _connection(db_path: Path):
    _ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_last_cached_date(db_path: Path, ticker: str) -> str | None:
    """Fecha máxima cacheada para el ticker, o None si no existe entrada."""
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM asset_prices WHERE ticker = ?", (ticker,)
        ).fetchone()
    return row[0] if row and row[0] else None


def get_cached_prices(db_path: Path, ticker: str, start_date: str) -> pd.DataFrame:
    """
    Devuelve DataFrame con columnas [close] e índice datetime
    para el ticker desde start_date.
    """
    with _connection(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM asset_prices "
            "WHERE ticker = ? AND date >= ? ORDER BY date ASC",
            conn,
            params=(ticker, start_date),
        )
    if df.empty:
        return pd.DataFrame(columns=["close"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def save_prices(db_path: Path, ticker: str, series: pd.Series) -> None:
    """Persiste una serie de precios (índice=datetime, valores=float) en SQLite."""
    rows = [
        (idx.strftime("%Y-%m-%d"), ticker, float(val))
        for idx, val in series.items()
        if pd.notna(val)
    ]
    if not rows:
        return
    with _connection(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO asset_prices (date, ticker, close) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
