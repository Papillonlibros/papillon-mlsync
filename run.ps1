# Lanza la app intermedia Papillon <-> Mercado Libre
# Uso:  .\run.ps1
$env:PYTHONUTF8 = "1"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $proj
Write-Host "Abriendo en http://localhost:8000  (y accesible en la red por http://<IP-de-esta-PC>:8000)"
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir $proj
