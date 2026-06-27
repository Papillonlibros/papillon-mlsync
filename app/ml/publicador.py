"""Publicador de libros a Mercado Libre: arma el payload, sube la portada,
publica (categoria MLA412445) y opcionalmente pausa. Registra el resultado."""
import os
import tempfile
import threading
import datetime
import dbfread
from PIL import Image

from .. import config, db
from . import client as ml

MIN_PX = 500  # ML exige minimo 500px de lado en la portada

# Estado del lote de publicacion en curso (para mostrar progreso en la UI)
_batch_lock = threading.Lock()
batch_status = {
    "running": False, "total": 0, "done": 0, "ok": 0, "fail": 0,
    "results": [], "started_at": None,
}

CATEGORY_BOOKS = "MLA412445"

# Articulos que en el ERP quedan al final del titulo ("PRINCIPITO EL")
_ARTICULOS = {"EL", "LA", "LOS", "LAS", "LO", "UN", "UNA", "UNOS", "UNAS"}
# Palabras que en Title Case van en minuscula (salvo al inicio)
_MINUS = {"de", "del", "la", "el", "los", "las", "y", "e", "o", "u",
          "en", "a", "con", "por", "para", "un", "una", "al"}

_editoriales = None


def editoriales() -> dict:
    """Mapa GRUPO_ -> nombre de editorial (tabla GRUPOS del ERP)."""
    global _editoriales
    if _editoriales is None:
        _editoriales = {}
        kw = dict(load=False, ignore_missing_memofile=True,
                  encoding=config.DBF_ENCODING, char_decode_errors="replace")
        for r in dbfread.DBF(os.path.join(config.DBF_DIR, "GRUPOS.DBF"), **kw):
            nombre = (r["DESCRI"] or "").strip()
            if nombre:
                _editoriales[r["GRUPO_"]] = nombre
    return _editoriales


def find_cover(ean: str):
    ean = (ean or "").strip()
    if not ean:
        return None
    for ext in (".jpg", ".JPG", ".jpeg", ".JPEG", ".png", ".PNG"):
        p = os.path.join(config.TAPAS_DIR, ean + ext)
        if os.path.exists(p):
            return p
    return None


def prepare_cover(path: str) -> str:
    """Devuelve una ruta a la portada lista para ML (>=500px, RGB JPEG).
    Si la imagen ya cumple, devuelve la original; si es chica, la agranda."""
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return path  # que ML decida; igual capturamos el error
    w, h = img.size
    if min(w, h) >= MIN_PX and img.mode == "RGB":
        return path
    if img.mode != "RGB":
        img = img.convert("RGB")
    if min(w, h) < MIN_PX:
        factor = 600 / min(w, h)  # apuntamos a 600px de lado corto
        img = img.resize((round(w * factor), round(h * factor)), Image.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="tapa_")
    os.close(fd)
    img.save(tmp, "JPEG", quality=90)
    return tmp


def clean_title(t: str) -> str:
    """'SABUESO DE LOS BASKERVILLE EL' -> 'El Sabueso De Los Baskerville'."""
    parts = (t or "").strip().split()
    if len(parts) > 1 and parts[-1].upper().strip(".,") in _ARTICULOS:
        parts = [parts[-1].strip(".,")] + parts[:-1]
    out = []
    for i, w in enumerate(parts):
        wl = w.lower()
        out.append(wl if (i > 0 and wl in _MINUS) else wl.capitalize())
    return " ".join(out)[:60]


def build_payload(art, listing_type="gold_special", picture_id=None) -> dict:
    ean = (art["ean"] or "").strip()
    titulo = clean_title(art["titulo"])
    autor = (art["autor"] or "").strip()
    attrs = [
        {"id": "BOOK_TITLE", "value_name": titulo},
        {"id": "AUTHOR", "value_name": autor or "Anónimo"},
        {"id": "GTIN", "value_name": ean},
    ]
    edi = editoriales().get(art["grupo"])
    if edi:
        attrs.append({"id": "BOOK_PUBLISHER", "value_name": edi})
    payload = {
        "category_id": CATEGORY_BOOKS,
        "price": float(art["precio"]),
        "currency_id": "ARS",
        "available_quantity": int(art["stock_disp"]),
        "buying_mode": "buy_it_now",
        "condition": "new",
        "listing_type_id": listing_type,
        "family_name": titulo,
        "attributes": attrs,
    }
    if picture_id:
        payload["pictures"] = [{"id": picture_id}]
    return payload


def _registrar(codint, item_id, status, error):
    conn = db.get_conn()
    try:
        conn.execute(
            """INSERT INTO publicacion (codint, publicar, ml_item_id, ml_status, last_sync_at, sync_error)
               VALUES (?, 1, ?, ?, ?, ?)
               ON CONFLICT(codint) DO UPDATE SET
                 ml_item_id=excluded.ml_item_id, ml_status=excluded.ml_status,
                 last_sync_at=excluded.last_sync_at, sync_error=excluded.sync_error""",
            (codint, item_id, status,
             datetime.datetime.now().isoformat(timespec="seconds"), error),
        )
        conn.commit()
    finally:
        conn.close()


def publish_one(art, listing_type="gold_special", pausar=True) -> dict:
    """Publica un articulo. art = fila de la tabla `articulo`."""
    ean = (art["ean"] or "").strip()
    cover = find_cover(ean)
    if not cover:
        _registrar(art["codint"], None, "error", "sin portada en TAPAS")
        return {"ok": False, "codint": art["codint"], "error": "sin portada en TAPAS"}
    try:
        listo = prepare_cover(cover)
        pic = ml.upload_picture(listo)
        if listo != cover:
            try:
                os.remove(listo)
            except OSError:
                pass
        payload = build_payload(art, listing_type, pic["id"])
        item = ml.api_post("/items", payload)
        item_id = item["id"]
        status = item.get("status", "active")
        if pausar and status != "paused":
            try:
                ml.api_put(f"/items/{item_id}", {"status": "paused"})
                status = "paused"
            except ml.MLError:
                pass
        _registrar(art["codint"], item_id, status, None)
        return {"ok": True, "codint": art["codint"], "item_id": item_id,
                "status": status, "permalink": item.get("permalink"),
                "title": item.get("title")}
    except ml.MLError as e:
        _registrar(art["codint"], None, "error", f"{e.status}: {e.body[:400]}")
        return {"ok": False, "codint": art["codint"], "error": f"{e.status}: {e.body[:200]}"}
    except Exception as e:
        _registrar(art["codint"], None, "error", str(e))
        return {"ok": False, "codint": art["codint"], "error": str(e)}


def run_batch(codints, listing_type="gold_special", pausar=True):
    """Publica una lista de codints en segundo plano, actualizando batch_status."""
    if not _batch_lock.acquire(blocking=False):
        return False
    batch_status.update(running=True, total=len(codints), done=0, ok=0, fail=0,
                        results=[], started_at=datetime.datetime.now().isoformat(timespec="seconds"))
    try:
        for codint in codints:
            conn = db.get_conn()
            art = conn.execute("SELECT * FROM articulo WHERE codint=?", (codint,)).fetchone()
            conn.close()
            if not art:
                res = {"ok": False, "codint": codint, "error": "artículo no encontrado"}
                titulo = codint
            else:
                res = publish_one(art, listing_type, pausar)
                titulo = clean_title(art["titulo"])
            batch_status["done"] += 1
            batch_status["ok" if res["ok"] else "fail"] += 1
            batch_status["results"].append({
                "codint": codint, "ok": res["ok"], "titulo": titulo,
                "item_id": res.get("item_id"), "error": res.get("error"),
            })
    finally:
        batch_status["running"] = False
        _batch_lock.release()
    return True
