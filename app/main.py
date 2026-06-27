"""App intermedia Papillon <-> Mercado Libre (FastAPI + SQLite + HTMX)."""
import os
import re
import threading

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, db, ingest, scheduler
from .ml import client as ml
from .ml import publicador as pub

app = FastAPI(title="Papillon - Sync Mercado Libre")
templates = Jinja2Templates(directory=os.path.join(config.BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(config.BASE_DIR, "static")), name="static")

PAGE_SIZE = 50


@app.on_event("startup")
def _startup():
    db.init_db()
    scheduler.start()
    # Primera ingesta si la base esta vacia (en segundo plano)
    conn = db.get_conn()
    try:
        vacio = conn.execute("SELECT COUNT(*) c FROM articulo").fetchone()["c"] == 0
    finally:
        conn.close()
    if vacio and not ingest.status["running"]:
        threading.Thread(target=lambda: ingest.run_ingest(tipo="inicial"), daemon=True).start()


# ----------------------------- helpers -----------------------------

def _build_query(q: str, filtro: str):
    where = []
    params = []
    if q:
        where.append("(a.titulo LIKE ? OR a.autor LIKE ? OR a.ean LIKE ? OR a.codint LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if filtro == "stock":
        where.append("a.stock_disp > 0")
    elif filtro == "publicable":
        where.append("a.stock_disp > 0 AND (a.ean LIKE '978%' OR a.ean LIKE '979%')")
    elif filtro == "publicados":
        where.append("p.publicar = 1")
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    return sql_where, params


# ----------------------------- rutas -----------------------------

@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/catalogo")


@app.get("/catalogo", response_class=HTMLResponse)
def catalogo(request: Request, q: str = "", filtro: str = "stock", page: int = 1):
    page = max(1, page)
    sql_where, params = _build_query(q, filtro)
    conn = db.get_conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) c FROM articulo a "
            f"LEFT JOIN publicacion p ON p.codint=a.codint {sql_where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT a.*, COALESCE(p.publicar,0) AS publicar, p.ml_item_id, p.ml_status
                FROM articulo a LEFT JOIN publicacion p ON p.codint=a.codint
                {sql_where}
                ORDER BY a.titulo
                LIMIT ? OFFSET ?""",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        arts = conn.execute("SELECT COUNT(*) c FROM articulo").fetchone()["c"]
    finally:
        conn.close()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return templates.TemplateResponse(request, "catalogo.html", {
        "rows": rows, "q": q, "filtro": filtro, "arts": arts,
        "page": page, "pages": pages, "total": total, "status": ingest.status,
        "conectado": ml.is_connected(),
    })


@app.get("/estado", response_class=HTMLResponse)
def estado(request: Request):
    conn = db.get_conn()
    try:
        arts = conn.execute("SELECT COUNT(*) c FROM articulo").fetchone()["c"]
    finally:
        conn.close()
    return templates.TemplateResponse(request, "_estado.html", {
        "status": ingest.status, "arts": arts,
    })


@app.post("/ingest", response_class=HTMLResponse)
def ingest_now(request: Request):
    if not ingest.status["running"]:
        threading.Thread(target=lambda: ingest.run_ingest(tipo="manual"), daemon=True).start()
    return estado(request)


# ----------------------------- Mercado Libre -----------------------------

@app.get("/ml", response_class=HTMLResponse)
def ml_panel(request: Request, msg: str = "", err: str = ""):
    info = None
    if ml.is_connected():
        try:
            u = ml.me()
            info = {"nick": u.get("nickname"), "id": u.get("id"),
                    "email": u.get("email"), "site": u.get("site_id")}
        except Exception as e:
            err = err or f"Token guardado pero la API falló: {e}"
    return templates.TemplateResponse(request, "ml.html", {
        "conectado": ml.is_connected(), "info": info,
        "auth_url": ml.auth_url(), "redirect_uri": config.ML_REDIRECT_URI,
        "app_id": config.ML_APP_ID, "msg": msg, "err": err,
    })


@app.get("/ml/conectar")
def ml_conectar():
    return RedirectResponse(ml.auth_url())


@app.get("/ml/callback", response_class=HTMLResponse)
def ml_callback(code: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/ml?err=ML devolvió: {error}")
    try:
        ml.exchange_code(code)
        return RedirectResponse("/ml?msg=Conectado correctamente con Mercado Libre")
    except Exception as e:
        return RedirectResponse(f"/ml?err={e}")


@app.post("/ml/codigo")
def ml_codigo(code: str = Form(...)):
    try:
        ml.exchange_code(ml.extract_code(code))
        return RedirectResponse("/ml?msg=Conectado correctamente con Mercado Libre", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/ml?err={e}", status_code=303)


# ----------------------------- Portadas / Publicación en lote -----------------------------

_EAN_RE = re.compile(r"^[0-9A-Za-z\-]{1,20}$")


@app.get("/tapa/{ean}")
def tapa(ean: str):
    if not _EAN_RE.match(ean):
        return Response(status_code=404)
    for ext in (".jpg", ".JPG", ".jpeg", ".JPEG", ".png", ".PNG"):
        p = os.path.join(config.TAPAS_DIR, ean + ext)
        if os.path.exists(p):
            return FileResponse(p)
    return Response(status_code=404)


class PublicarReq(BaseModel):
    codints: list[str]


@app.post("/ml/publicar-lote")
def publicar_lote(req: PublicarReq):
    if not ml.is_connected():
        return JSONResponse({"error": "Mercado Libre no está conectado"}, status_code=400)
    if pub.batch_status["running"]:
        return JSONResponse({"error": "Ya hay una publicación en curso"}, status_code=409)
    codints = [c for c in req.codints][:300]
    if not codints:
        return JSONResponse({"error": "No seleccionaste ningún libro"}, status_code=400)
    threading.Thread(target=lambda: pub.run_batch(codints), daemon=True).start()
    return {"started": True, "total": len(codints)}


@app.get("/ml/publicar-estado")
def publicar_estado():
    return pub.batch_status


@app.post("/publicar", response_class=HTMLResponse)
def toggle_publicar(request: Request, codint: str = Form(...)):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT publicar FROM publicacion WHERE codint=?", (codint,)).fetchone()
        nuevo = 0 if (row and row["publicar"]) else 1
        conn.execute(
            "INSERT INTO publicacion (codint, publicar) VALUES (?, ?) "
            "ON CONFLICT(codint) DO UPDATE SET publicar=excluded.publicar",
            (codint, nuevo),
        )
        conn.commit()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "_publicar_btn.html", {
        "codint": codint, "publicar": nuevo,
    })
