"""
Integración con Google Sheets para carga de posiciones abiertas.
Lee la pestaña 'posiciones' de 'Seguimiento Stocks', filtra Estado='Abierta',
agrega N_Valores por ticker (sufijo .MC) y calcula precio_coste medio ponderado.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_REQUIRED_COLS = {"Valor", "N_Valores", "P_Compra", "Estado"}


def _get_credentials(credentials_path: Path, token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("Token OAuth2 guardado en '%s'", token_path)

    return creds


def _parse_es_float(s: str) -> float:
    """Convierte número en formato español (1.605,24) a float (1605.24)."""
    return float(s.strip().replace(".", "").replace(",", "."))


def load_positions_from_sheets(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_path: Path,
    token_path: Path,
) -> dict[str, dict]:
    """
    Lee la pestaña sheet_name, filtra filas con Estado='Abierta',
    agrega N_Valores por ticker y calcula precio_coste medio ponderado.

    Primer uso: abre navegador para consentimiento OAuth2.
    Usos posteriores: reutiliza token.json.

    Returns:
        {ticker: {"cantidad": int, "precio_coste": float}}

    Raises:
        RuntimeError: si credentials.json no existe o dependencias no instaladas.
        ValueError: si la cabecera no se encuentra en la pestaña.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Dependencias de Google no instaladas.\n"
            "Ejecuta: pip install google-api-python-client google-auth-oauthlib"
        ) from exc

    if not credentials_path.exists():
        raise RuntimeError(
            f"Credenciales no encontradas: '{credentials_path}'\n"
            "Pasos para configurar:\n"
            "  1. Abre https://console.cloud.google.com/\n"
            "  2. Crea un proyecto y habilita la Sheets API\n"
            "  3. Crea credenciales OAuth 2.0 (tipo: aplicación de escritorio)\n"
            "  4. Descarga credentials.json y colócalo junto a main.py"
        )

    creds = _get_credentials(credentials_path, token_path)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_name)
        .execute()
    )
    rows = result.get("values", [])

    # Localizar la fila de cabeceras buscando las columnas requeridas
    header_idx, col = None, {}
    for i, row in enumerate(rows):
        if _REQUIRED_COLS.issubset(set(row)):
            header_idx = i
            col = {name: idx for idx, name in enumerate(row)}
            break

    if header_idx is None:
        raise ValueError(
            f"Cabeceras no encontradas en la pestaña '{sheet_name}'. "
            f"Columnas requeridas: {_REQUIRED_COLS}"
        )

    total_shares: dict[str, int] = {}
    weighted_cost: dict[str, float] = {}

    for row in rows[header_idx + 1:]:
        try:
            estado = row[col["Estado"]].strip()
        except IndexError:
            continue
        if estado != "Abierta":
            continue

        try:
            ticker = row[col["Valor"]].strip() + ".MC"
            n = int(row[col["N_Valores"]])
            p = _parse_es_float(row[col["P_Compra"]])
        except (ValueError, IndexError):
            continue

        prev = total_shares.get(ticker, 0)
        total_shares[ticker] = prev + n
        weighted_cost[ticker] = (
            (weighted_cost.get(ticker, 0.0) * prev + p * n) / total_shares[ticker]
        )

    posiciones = {
        ticker: {
            "cantidad": shares,
            "precio_coste": round(weighted_cost[ticker], 4),
        }
        for ticker, shares in total_shares.items()
    }

    logger.info(
        "Posiciones leídas desde Sheets '%s' (%d tickers abiertos): %s",
        sheet_name, len(posiciones), list(posiciones.keys()),
    )
    return posiciones
