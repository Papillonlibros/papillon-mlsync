"""Ingesta: vuelca el catalogo del ERP (DBF) al snapshot SQLite.

Lee ARTICU + STKLIS (precio) + STOCK_ (stock) + STKCOD (EAN/ISBN), une por CODINT
y reescribe la tabla `articulo`. Solo lectura sobre los DBF del ERP.
"""
import os
import threading
import datetime
import dbfread
from dbfread import FieldParser

from . import config, db

_lock = threading.Lock()


class _TolerantParser(FieldParser):
    """Parser de DBF tolerante a campos corruptos.

    Algunos DBF del ERP (p. ej. La Red del Libro) tienen registros sueltos con
    bytes basura en campos numéricos o de fecha. El parser estándar aborta toda
    la ingesta ante el primer valor ilegible; este devuelve None en su lugar
    (el resto del código ya trata None como 0/"" vía `or 0` y `_s`).
    """

    def parse(self, field, data):
        try:
            return super().parse(field, data)
        except (ValueError, TypeError, ArithmeticError):
            return None

# Estado en memoria para mostrar en la UI
status = {
    "running": False,
    "last_ok": None,
    "last_count": 0,
    "last_error": None,
}

_KW = dict(load=False, ignore_missing_memofile=True,
           encoding=config.DBF_ENCODING, char_decode_errors="replace",
           parserclass=_TolerantParser)


def _dbf(nombre):
    return dbfread.DBF(os.path.join(config.DBF_DIR, nombre), **_KW)


def _s(v):
    return v.strip() if isinstance(v, str) else (v if v is not None else "")


def _ean13_check(d12):
    """Digito verificador (str) de los 12 primeros digitos de un EAN-13."""
    suma = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(d12))
    return str((10 - suma % 10) % 10)


def _ean13_valido(e):
    """True si e es un EAN-13 numerico con digito verificador correcto."""
    return len(e) == 13 and e.isdigit() and _ean13_check(e[:12]) == e[12]


def _isbn10_valido(c):
    """True si c (10 caracteres) es un ISBN-10 con verificador valido (0-9 o X)."""
    if len(c) != 10 or not c[:9].isdigit():
        return False
    chk = c[9]
    if not (chk.isdigit() or chk in "Xx"):
        return False
    val = 10 if chk in "Xx" else int(chk)
    suma = sum((i + 1) * int(c[i]) for i in range(9)) + 10 * val
    return suma % 11 == 0


def _ean_desde_codigo(codigo):
    """Deriva el EAN-13 desde ARTICU.CODIGO.

    En La Red del Libro el EAN del catalogo no esta en STKCOD sino en
    ARTICU.CODIGO, que guarda el ISBN-10 del libro (p. ej. '0545010225').
    Se convierte a EAN-13: 978 + los 9 digitos del nucleo + verificador
    recalculado. Se acepta solo si CODIGO es un ISBN-10 valido (o, en su
    defecto, si '978'+CODIGO ya forma un EAN-13 valido); asi se descartan los
    codigos internos que no son ISBN. Devuelve '' si no aplica.
    """
    c = _s(codigo)
    if _isbn10_valido(c):
        d12 = "978" + c[:9]
        return d12 + _ean13_check(d12)
    if len(c) == 10 and c.isdigit() and _ean13_valido("978" + c):
        return "978" + c
    return ""


def _log(tipo, inicio, fin, registros, estado, detalle):
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO sync_log (tipo,inicio,fin,registros,estado,detalle) VALUES (?,?,?,?,?,?)",
            (tipo, inicio.isoformat(timespec="seconds"),
             fin.isoformat(timespec="seconds"), registros, estado, detalle),
        )
        conn.commit()
    finally:
        conn.close()


def run_ingest(tipo="manual"):
    """Ejecuta una ingesta completa. Devuelve dict con el resultado."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "ya hay una ingesta en curso"}

    status["running"] = True
    status["last_error"] = None
    inicio = datetime.datetime.now()
    try:
        # 1) Precios
        precio = {}
        for r in _dbf("STKLIS.DBF"):
            c = r["CODINT"]
            if c not in precio:
                precio[c] = (r["PRECIO"] or 0, r["OFERTA"] or 0, r["FECMOD"])

        # 2) Reservas por articulo. El stock TOTAL se toma de ARTICU.STKTOT
        #    (mas completo que STOCK_: en La Red ~13.500 articulos tienen
        #    STKTOT>0 vs ~7.000 con fila en STOCK_, y coinciden donde ambos
        #    existen). STOCK_ aporta solo lo reservado (sumando sus filas, una
        #    por ubicacion).
        reservado = {}
        for r in _dbf("STOCK_.DBF"):
            reservado[r["CODINT"]] = reservado.get(r["CODINT"], 0) + (r["RESERV"] or 0)

        # 3) Codigos (EAN/ISBN) - primer registro con EAN no vacio
        codigos = {}
        for r in _dbf("STKCOD.DBF"):
            c = r["CODINT"]
            if c not in codigos and _s(r["EAN___"]):
                codigos[c] = (_s(r["EAN___"]), _s(r["ISBN__"]), _s(r["PROCOD"]))

        # 4) Articulos -> filas para insertar
        now = datetime.datetime.now().isoformat(timespec="seconds")
        rows = []
        for a in _dbf("ARTICU.DBF"):
            c = a["CODINT"]
            p, of, fm = precio.get(c, (0, 0, None))
            try:
                total = int(a["STKTOT"] or 0)
            except (TypeError, ValueError):
                total = 0
            resv = int(reservado.get(c, 0) or 0)
            ean, isbn, pro = codigos.get(c, ("", "", ""))
            # Fallback La Red: si STKCOD no trae EAN, reconstruir desde ARTICU.CODIGO
            if not ean:
                ean = _ean_desde_codigo(a["CODIGO"])
                if ean and not isbn:
                    isbn = ean
            disp = max(0, total - resv)
            rows.append((
                _s(c), ean, isbn, _s(a["DESCRI"]), _s(a["AUTOR1"]),
                float(p or 0), float(of or 0),
                total, resv, disp,
                _s(a["MARCA_"]), a["GRUPO_"], a["LINEA_"], a["RUBRO_"],
                _s(a["ESTADO"]), _s(a["DISCON"]), pro or _s(a["PROCOD"]),
                fm.isoformat() if fm else None, now,
            ))

        # 5) Reescribir tabla en una transaccion
        conn = db.get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM articulo")
            conn.executemany(
                """INSERT OR REPLACE INTO articulo
                   (codint,ean,isbn,titulo,autor,precio,oferta,stock_total,reservado,
                    stock_disp,marca,grupo,linea,rubro,estado,discon,proveedor,
                    fecmod_precio,actualizado_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        fin = datetime.datetime.now()
        _log(tipo, inicio, fin, len(rows), "ok", None)
        status.update(running=False,
                      last_ok=fin.isoformat(timespec="seconds"),
                      last_count=len(rows), last_error=None)
        return {"count": len(rows), "segundos": (fin - inicio).total_seconds()}

    except Exception as e:
        fin = datetime.datetime.now()
        _log(tipo, inicio, fin, 0, "error", str(e))
        status.update(running=False, last_error=str(e))
        raise
    finally:
        status["running"] = False
        _lock.release()
