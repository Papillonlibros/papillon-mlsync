"""Conector con Mercado Libre: OAuth (token + refresh) y llamadas a la API."""
import os
import datetime
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from .. import config, db


class MLError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"ML {status}: {body}")


# --------------------------- token storage ---------------------------

def _save_token(data: dict):
    now = datetime.datetime.now()
    expires_at = now + datetime.timedelta(seconds=int(data.get("expires_in", 21600)))
    conn = db.get_conn()
    try:
        conn.execute(
            """INSERT INTO ml_token (id, access_token, refresh_token, user_id, expires_at, actualizado)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 access_token=excluded.access_token,
                 refresh_token=COALESCE(excluded.refresh_token, ml_token.refresh_token),
                 user_id=excluded.user_id,
                 expires_at=excluded.expires_at,
                 actualizado=excluded.actualizado""",
            (data["access_token"], data.get("refresh_token"),
             str(data.get("user_id", "")), expires_at.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def get_token_row():
    conn = db.get_conn()
    try:
        return conn.execute("SELECT * FROM ml_token WHERE id=1").fetchone()
    finally:
        conn.close()


def is_connected() -> bool:
    return get_token_row() is not None


# --------------------------- OAuth flow ---------------------------

def auth_url() -> str:
    q = urlencode({
        "response_type": "code",
        "client_id": config.ML_APP_ID,
        "redirect_uri": config.ML_REDIRECT_URI,
    })
    return f"{config.ML_AUTH_HOST}/authorization?{q}"


def extract_code(texto: str) -> str:
    """Acepta el code pelado o una URL completa de callback y devuelve el code."""
    texto = (texto or "").strip()
    if texto.startswith("http"):
        qs = parse_qs(urlparse(texto).query)
        return (qs.get("code", [""])[0]).strip()
    return texto


def exchange_code(code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "client_id": config.ML_APP_ID,
        "client_secret": config.ML_CLIENT_SECRET,
        "code": code,
        "redirect_uri": config.ML_REDIRECT_URI,
    }
    r = httpx.post(f"{config.ML_API}/oauth/token", data=data,
                   headers={"Accept": "application/json"}, timeout=20)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    tok = r.json()
    _save_token(tok)
    return tok


def refresh() -> dict:
    row = get_token_row()
    if not row or not row["refresh_token"]:
        raise RuntimeError("No hay refresh_token; hay que reconectar con Mercado Libre.")
    data = {
        "grant_type": "refresh_token",
        "client_id": config.ML_APP_ID,
        "client_secret": config.ML_CLIENT_SECRET,
        "refresh_token": row["refresh_token"],
    }
    r = httpx.post(f"{config.ML_API}/oauth/token", data=data, timeout=20)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    tok = r.json()
    _save_token(tok)
    return tok


def valid_access_token() -> str:
    row = get_token_row()
    if not row:
        raise RuntimeError("Mercado Libre no está conectado.")
    expires_at = datetime.datetime.fromisoformat(row["expires_at"])
    if datetime.datetime.now() >= expires_at - datetime.timedelta(minutes=10):
        return refresh()["access_token"]
    return row["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {valid_access_token()}"}


# --------------------------- API calls ---------------------------

def me() -> dict:
    r = httpx.get(f"{config.ML_API}/users/me", headers=_headers(), timeout=20)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    return r.json()


def api_get(path: str, **params):
    r = httpx.get(f"{config.ML_API}{path}", headers=_headers(), params=params, timeout=30)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    return r.json()


def api_post(path: str, payload: dict):
    r = httpx.post(f"{config.ML_API}{path}", headers=_headers(), json=payload, timeout=60)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    return r.json()


def api_put(path: str, payload: dict):
    r = httpx.put(f"{config.ML_API}{path}", headers=_headers(), json=payload, timeout=60)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    return r.json()


def validate_item(payload: dict):
    """Valida un item sin publicarlo. Devuelve (ok, causas)."""
    r = httpx.post(f"{config.ML_API}/items/validate", headers=_headers(),
                   json=payload, timeout=60)
    if r.status_code in (200, 201, 204):
        return True, []
    try:
        return False, r.json().get("cause", [])
    except Exception:
        return False, [{"message": r.text}]


def upload_picture(filepath: str) -> dict:
    """Sube una imagen local a ML y devuelve {'id': ...} para referenciar en el item."""
    with open(filepath, "rb") as f:
        files = {"file": (os.path.basename(filepath), f, "image/jpeg")}
        r = httpx.post(f"{config.ML_API}/pictures/items/upload",
                       headers=_headers(), files=files, timeout=120)
    if r.status_code >= 400:
        raise MLError(r.status_code, r.text)
    return r.json()
