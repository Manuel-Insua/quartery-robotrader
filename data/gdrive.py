"""
Integración con Google Drive para carga del estado de cartera.
Lee estado_cartera.json desde la carpeta Drive configurada (documentación/bancos/stocks/),
con fallback automático al archivo local si Drive no está disponible o las
credenciales no están configuradas.
"""

import io
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_FILE_NAME = "estado_cartera.json"


def _get_credentials(credentials_path: Path, token_path: Path):
    """
    Retorna credenciales OAuth2 válidas para la Drive API.
    En el primer uso abre el flujo de consentimiento en el navegador.
    En usos posteriores reutiliza el token guardado en disco.
    """
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


def load_from_drive(
    folder_id: str,
    credentials_path: Path,
    token_path: Path,
) -> dict:
    """
    Descarga estado_cartera.json desde la carpeta Drive especificada y
    lo devuelve como diccionario Python.

    Primer uso: abre el navegador para el consentimiento OAuth2.
    Usos posteriores: usa el token guardado localmente (token.json).

    Raises:
        RuntimeError: si credentials.json no existe.
        FileNotFoundError: si el archivo no existe en la carpeta Drive.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError(
            "Dependencias de Google Drive no instaladas.\n"
            "Ejecuta: pip install google-api-python-client google-auth-oauthlib"
        ) from exc

    if not credentials_path.exists():
        raise RuntimeError(
            f"Credenciales de Google Drive no encontradas: '{credentials_path}'\n"
            "Pasos para configurar:\n"
            "  1. Abre https://console.cloud.google.com/\n"
            "  2. Crea un proyecto y habilita la Drive API\n"
            "  3. Crea credenciales OAuth 2.0 (tipo: aplicación de escritorio)\n"
            "  4. Descarga credentials.json y colócalo en el directorio del proyecto"
        )

    creds = _get_credentials(credentials_path, token_path)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    query = (
        f"name = '{_FILE_NAME}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )
    results = (
        service.files()
        .list(q=query, fields="files(id, name, modifiedTime)", pageSize=1)
        .execute()
    )
    files = results.get("files", [])

    if not files:
        raise FileNotFoundError(
            f"'{_FILE_NAME}' no encontrado en la carpeta Drive (id={folder_id}).\n"
            "Sube el archivo a Google Drive en la ruta: documentación/bancos/stocks/"
        )

    file_id = files[0]["id"]
    modified = files[0].get("modifiedTime", "desconocida")
    logger.info(
        "Descargando %s desde Google Drive (última modificación: %s)", _FILE_NAME, modified
    )

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return json.loads(buffer.getvalue().decode("utf-8"))
