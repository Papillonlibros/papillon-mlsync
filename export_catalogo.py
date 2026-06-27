"""
Exporta el catalogo del ERP (Papillon Libros) a un CSV limpio uniendo:
  ARTICU (titulo/autor/categoria) + STKLIS (precio) + STOCK_ (stock) + STKCOD (EAN/ISBN)
Clave de join: CODINT. Encoding de los DBF: cp850.

Uso:
    py _mlsync/export_catalogo.py                # exporta todo a _mlsync/catalogo.csv
    py _mlsync/export_catalogo.py --con-stock    # solo articulos con stock > 0
"""
import csv
import os
import sys
import dbfread

DBF_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo.csv")
KW = dict(load=False, ignore_missing_memofile=True,
          encoding="cp850", char_decode_errors="replace")


def tabla(nombre):
    return dbfread.DBF(os.path.join(DBF_DIR, nombre), **KW)


def s(v):
    """Normaliza a string recortado."""
    return (v or "").strip() if isinstance(v, str) else (v if v is not None else "")


def main():
    solo_stock = "--con-stock" in sys.argv

    print("Leyendo precios (STKLIS)...")
    precio = {}
    for r in tabla("STKLIS.DBF"):
        c = r["CODINT"]
        if c not in precio:
            precio[c] = (r["PRECIO"] or 0, r["OFERTA"] or 0)

    print("Leyendo stock (STOCK_)...")
    stock = {}
    for r in tabla("STOCK_.DBF"):
        stock[r["CODINT"]] = (r["CANTID"] or 0, r["RESERV"] or 0)

    print("Leyendo codigos EAN/ISBN (STKCOD)...")
    codigos = {}
    for r in tabla("STKCOD.DBF"):
        c = r["CODINT"]
        if c not in codigos and s(r["EAN___"]):
            codigos[c] = (s(r["EAN___"]), s(r["ISBN__"]), s(r["PROCOD"]))

    print("Leyendo articulos (ARTICU) y escribiendo CSV...")
    n = 0
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["CODINT", "EAN", "ISBN", "TITULO", "AUTOR",
                    "PRECIO", "OFERTA", "STOCK_TOTAL", "RESERVADO", "STOCK_DISP",
                    "MARCA", "GRUPO", "LINEA", "RUBRO", "ESTADO", "DISCON", "PROVEEDOR"])
        for a in tabla("ARTICU.DBF"):
            c = a["CODINT"]
            p, of = precio.get(c, (0, 0))
            cant, resv = stock.get(c, (0, 0))
            ean, isbn, pro = codigos.get(c, ("", "", ""))
            disp = (cant or 0) - (resv or 0)
            if solo_stock and disp <= 0:
                continue
            w.writerow([s(c), ean, isbn, s(a["DESCRI"]), s(a["AUTOR1"]),
                        p, of, cant, resv, disp,
                        s(a["MARCA_"]), a["GRUPO_"], a["LINEA_"], a["RUBRO_"],
                        s(a["ESTADO"]), s(a["DISCON"]), pro or s(a["PROCOD"])])
            n += 1
    print(f"Listo: {n} articulos -> {OUT}")


if __name__ == "__main__":
    main()
