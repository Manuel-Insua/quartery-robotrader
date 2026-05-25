from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Rutas ─────────────────────────────────────────────────────────────────────
DB_PATH = BASE_DIR / "data" / "spanish_market_cache.db"
ESTADO_PATH = BASE_DIR / "estado_cartera.json"   # copia local / fallback

# ── Google Sheets ──────────────────────────────────────────────────────────────
# Fuente de posiciones: Mi Drive / 01. Documentación / Bancos / Stocks / Seguimiento Stocks
GDRIVE_SPREADSHEET_ID: str = "17Ge2Rur8HIkhYDSdgwfTJeAdCfCbylwTikZEI6wOCqE"
GDRIVE_SHEET_POSICIONES: str = "posiciones"
GDRIVE_CREDENTIALS_PATH: Path = BASE_DIR / "credentials.json"
GDRIVE_TOKEN_PATH: Path = BASE_DIR / "token.json"

# ── Universo IBEX 35 ──────────────────────────────────────────────────────────
UNIVERSO_IBEX: list[str] = [
    "ACS.MC", "ACX.MC", "ANA.MC", "BBVA.MC", "BKT.MC",
    "CABK.MC", "CLNX.MC", "COL.MC", "ELE.MC", "ENG.MC",
    "FER.MC", "GRF.MC", "IAG.MC", "IBE.MC", "IDR.MC",
    "ITX.MC", "LOG.MC", "MAP.MC", "NTGY.MC", "PHM.MC",
    "RED.MC", "REP.MC", "ROVI.MC", "SAB.MC", "SAN.MC",
    "SOL.MC", "TEF.MC", "UNI.MC", "VIS.MC",
]

# ── Parámetros de estimación ──────────────────────────────────────────────────
# 3 años bursátiles: equilibrio entre significación estadística y representatividad
# de la estructura de riesgo actual (recomendación del doc. de referencia)
DIAS_HISTORICO: int = 756

# ── Restricciones de optimización (Jagannathan-Ma, 2003) ─────────────────────
MAX_PESO_ACTIVO: float = 0.20   # 20 % máximo: fuerza diversificación implícita
MIN_PESO_ACTIVO: float = 0.0    # Long-only: sin ventas en corto

# ── Calidad de datos ──────────────────────────────────────────────────────────
MIN_COBERTURA: float = 0.80     # Umbral mínimo de días con datos (80 %)
MAX_FFILL_DIAS: int = 3         # Máximo de días consecutivos de interpolación ffill
                                # (stale prices microstructure filter)

# ── Rate limiting (Yahoo Finance) ─────────────────────────────────────────────
SLEEP_MIN_S: float = 0.25
SLEEP_MAX_S: float = 0.50
THROTTLE_DELAY_S: float = 0.35

# ── Bandas de tolerancia de rebalanceo ────────────────────────────────────────
# Protocolo mixto calendario + bandas dinámicas (evita churning por comisiones)
BANDA_TOLERANCIA_ABS: float = 0.05   # 5 % absoluto (posiciones grandes)
BANDA_TOLERANCIA_REL: float = 0.25   # 25 % relativo (posiciones pequeñas)
