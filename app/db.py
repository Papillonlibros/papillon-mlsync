"""Acceso a la base propia SQLite y creacion del esquema."""
import sqlite3
from . import config

SCHEMA = """
-- Snapshot del catalogo del ERP (se reescribe en cada ingesta)
CREATE TABLE IF NOT EXISTS articulo (
    codint         TEXT PRIMARY KEY,
    ean            TEXT,
    isbn           TEXT,
    titulo         TEXT,
    autor          TEXT,
    precio         REAL,
    oferta         REAL,
    stock_total    INTEGER,
    reservado      INTEGER,
    stock_disp     INTEGER,
    marca          TEXT,
    grupo          INTEGER,
    linea          INTEGER,
    rubro          INTEGER,
    estado         TEXT,
    discon         TEXT,
    proveedor      TEXT,
    fecmod_precio  TEXT,
    actualizado_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_art_stock ON articulo(stock_disp);
CREATE INDEX IF NOT EXISTS idx_art_titulo ON articulo(titulo);

-- Estado propio: que se publica y su relacion con Mercado Libre
CREATE TABLE IF NOT EXISTS publicacion (
    codint       TEXT PRIMARY KEY,
    publicar     INTEGER DEFAULT 0,
    ml_item_id   TEXT,
    ml_status    TEXT,
    precio_ml    REAL,
    last_sync_at TEXT,
    sync_error   TEXT
);

-- Token OAuth de Mercado Libre (una sola fila, id=1)
CREATE TABLE IF NOT EXISTS ml_token (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    access_token  TEXT,
    refresh_token TEXT,
    user_id       TEXT,
    expires_at    TEXT,
    actualizado   TEXT
);

-- Historial de sincronizaciones (ingesta y, mas adelante, push a ML)
CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo       TEXT,
    inicio     TEXT,
    fin        TEXT,
    registros  INTEGER,
    estado     TEXT,
    detalle    TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
