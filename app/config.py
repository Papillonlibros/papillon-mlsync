"""Configuracion central de la app intermedia (paths, server, sync)."""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # .../app
PROJECT_DIR = os.path.dirname(BASE_DIR)                       # raíz del proyecto

# Cargar credenciales/config desde .env (en la raíz del proyecto)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# Rutas al ERP (por defecto asume la app DENTRO de DBFS; se pueden fijar por .env
# con rutas absolutas para tener la app fuera de la carpeta del ERP).
DBF_DIR = os.environ.get("DBF_DIR", os.path.dirname(PROJECT_DIR))

# --- Mercado Libre ---
ML_APP_ID = os.environ.get("ML_APP_ID", "")
ML_CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET", "")
ML_REDIRECT_URI = os.environ.get("ML_REDIRECT_URI", "https://localhost:8000/ml/callback")
ML_SITE_ID = os.environ.get("ML_SITE_ID", "MLA")
ML_AUTH_HOST = "https://auth.mercadolibre.com.ar"
ML_API = "https://api.mercadolibre.com"

# Carpeta de portadas del ERP (una imagen EAN.jpg por articulo)
TAPAS_DIR = os.environ.get("TAPAS_DIR", os.path.join(os.path.dirname(DBF_DIR), "TAPAS"))

# Base propia de la app (lo que el ERP no guarda: publicados, ids de ML, ventas, log)
DB_PATH = os.path.join(PROJECT_DIR, "mlsync.db")

# Cada cuantos minutos se vuelca el catalogo del ERP (DBF) a SQLite
SYNC_INTERVAL_MIN = int(os.environ.get("MLSYNC_INTERVAL_MIN", "60"))

# Server (0.0.0.0 = accesible desde otras PCs de la red local)
HOST = os.environ.get("MLSYNC_HOST", "0.0.0.0")
PORT = int(os.environ.get("MLSYNC_PORT", "8000"))

# Encoding de los DBF del ERP (DOS Latin-America)
DBF_ENCODING = "cp850"
