# Carga los datos FICTICIOS de ejemplo en las cuatro bases (demostracion).
#
# Uso, desde la raiz del repositorio y con el sistema levantado:
#   powershell -ExecutionPolicy Bypass -File .\scripts\cargar_datos_demo.ps1
#
# Se puede repetir las veces que haga falta: cada archivo vacia sus tablas
# antes de llenarlas. La clave de todas las cuentas de ejemplo es Tutorias2026.

$raiz = Split-Path -Parent $PSScriptRoot
$bases = @(
    @{ servicio = "identity_db"; archivo = "identity.sql" },
    @{ servicio = "catalog_db";  archivo = "catalog.sql" },
    @{ servicio = "tutoring_db"; archivo = "tutoring.sql" },
    @{ servicio = "payment_db";  archivo = "payments.sql" }
)

Push-Location $raiz
try {
    foreach ($b in $bases) {
        $origen = Join-Path "data\seeds\demo" $b.archivo
        if (-not (Test-Path $origen)) {
            Write-Host "-- $($b.archivo) no esta en esta rama: se omite" -ForegroundColor Yellow
            continue
        }
        Write-Host "== $($b.servicio)  <-  $origen" -ForegroundColor Cyan
        docker compose cp $origen "$($b.servicio):/tmp/$($b.archivo)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo copiar $origen. Esta levantado $($b.servicio)? (docker compose ps)" -ForegroundColor Red
            exit 1
        }
        # Usuario y base salen de las variables del propio contenedor.
        docker compose exec -T $b.servicio sh -c "psql -U `$POSTGRES_USER -d `$POSTGRES_DB -v ON_ERROR_STOP=1 -q -f /tmp/$($b.archivo)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Fallo la carga de $($b.archivo): copia el error de arriba." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Listo. Clave de todas las cuentas de ejemplo: Tutorias2026" -ForegroundColor Green
}
finally {
    Pop-Location
}
