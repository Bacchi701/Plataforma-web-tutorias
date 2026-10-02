# Demostracion en vivo: cada base rechaza lo que el anexo A prohibe.
#
# Uso, desde la raiz del repositorio, con el sistema levantado y los datos
# de ejemplo cargados:
#   powershell -ExecutionPolicy Bypass -File .\scripts\probar_restricciones.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\probar_restricciones.ps1 tutoring
#
# Cada intento debe terminar en ERROR (salvo el que dice "debe ACEPTARSE").
# Todo corre en una transaccion que se deshace: los datos quedan intactos.

param([string]$solo = "")

$raiz = Split-Path -Parent $PSScriptRoot
$bases = @(
    @{ nombre = "identity"; servicio = "identity_db" },
    @{ nombre = "catalog";  servicio = "catalog_db" },
    @{ nombre = "tutoring"; servicio = "tutoring_db" },
    @{ nombre = "payments"; servicio = "payment_db" }
)

Push-Location $raiz
try {
    foreach ($b in $bases) {
        if ($solo -and $solo -ne $b.nombre) { continue }
        $origen = Join-Path "data\seeds\demo\restricciones" "$($b.nombre).sql"
        Write-Host ""
        Write-Host "################ $($b.servicio)" -ForegroundColor Cyan
        docker compose cp $origen "$($b.servicio):/tmp/restricciones.sql"
        if ($LASTEXITCODE -ne 0) { exit 1 }
        docker compose exec -T $b.servicio sh -c "psql -U `$POSTGRES_USER -d `$POSTGRES_DB -q -f /tmp/restricciones.sql 2>&1"
    }
}
finally {
    Pop-Location
}
