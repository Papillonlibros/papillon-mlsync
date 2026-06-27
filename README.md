# Papillon · App intermedia ERP ↔ Mercado Libre

App interna que lee el catálogo del ERP (DBF) y servirá para revisar precios/stock,
elegir qué publicar en Mercado Libre, sincronizar y ver ventas.

## Stack
- **FastAPI** (backend + UI) · **SQLite** (base propia) · **HTMX** (UI sin build)
- Lee los DBF del ERP en **solo lectura** (encoding `cp850`). Nunca escribe en el ERP.

## Ubicación
La app vive en `C:\Users\Libra\ProyectoX` (fuera de la carpeta del ERP).
Apunta al ERP por ruta absoluta vía `.env` (`DBF_DIR`, `TAPAS_DIR`) — solo lectura.

## Cómo correrla
```powershell
cd C:\Users\Libra\ProyectoX
py -m pip install -r requirements.txt   # solo la primera vez
.\run.ps1
```
Abrir en el navegador: <http://localhost:8000>
Desde otra PC de la librería: `http://<IP-de-esta-PC>:8000`
(puede requerir habilitar el puerto 8000 en el Firewall de Windows).

## Estructura
- `app/config.py` — paths, puerto, intervalo de sync.
- `app/db.py` — esquema SQLite (`articulo`, `publicacion`, `sync_log`).
- `app/ingest.py` — vuelca ARTICU+STKLIS+STOCK_+STKCOD → SQLite (join por CODINT).
- `app/scheduler.py` — ingesta automática cada `MLSYNC_INTERVAL_MIN` minutos (def. 60).
- `app/main.py` — rutas y UI.
- `app/templates/`, `app/static/` — vistas y estilos.
- `mlsync.db` — base propia (se crea sola).

## Variables de entorno (opcionales)
- `MLSYNC_INTERVAL_MIN` — minutos entre ingestas automáticas (default 60).
- `MLSYNC_HOST` / `MLSYNC_PORT` — default `0.0.0.0` / `8000`.

## Pendiente (próximas fases)
- Conexión OAuth con Mercado Libre (credenciales de la app).
- Publicar / actualizar ítems, sincronizar stock y precio.
- Panel de ventas de ML para carga manual al ERP.
