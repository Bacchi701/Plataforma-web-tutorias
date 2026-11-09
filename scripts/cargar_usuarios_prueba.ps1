# Carga 500 usuarios de prueba FICTICIOS en identity_db y tutoring_db, para
# medir la busqueda de tutores (HU-34, RNF-02).
#
# Uso, desde la raiz del repositorio, con el sistema levantado y despues de
# cargar los datos de ejemplo (scripts\cargar_datos_demo.ps1):
#   powershell -ExecutionPolicy Bypass -File .\scripts\cargar_usuarios_prueba.ps1
#
# Se puede repetir las veces que haga falta: cada archivo borra la carga
# anterior, y solo esa, y la vuelve a crear. Volver a cargar los datos de
# ejemplo borra esta carga. Las cuentas son carga.001 a carga.500@duocuc.cl,
# todas con la clave Tutorias2026.

$raiz = Split-Path -Parent $PSScriptRoot
$bases = @(
    @{ servicio = "identity_db"; archivo = "identity.sql" },
    @{ servicio = "tutoring_db"; archivo = "tutoring.sql" }
)

Push-Location $raiz
try {
    foreach ($b in $bases) {
        $origen = Join-Path "data\seeds\carga" $b.archivo
        if (-not (Test-Path $origen)) {
            Write-Host "No encuentro $origen en esta rama." -ForegroundColor Red
            exit 1
        }
        Write-Host "== $($b.servicio)  <-  $origen" -ForegroundColor Cyan
        docker compose cp $origen "$($b.servicio):/tmp/carga_$($b.archivo)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "No se pudo copiar $origen. Esta levantado $($b.servicio)? (docker compose ps)" -ForegroundColor Red
            exit 1
        }
        # Usuario y base salen de las variables del propio contenedor.
        docker compose exec -T $b.servicio sh -c "psql -U `$POSTGRES_USER -d `$POSTGRES_DB -v ON_ERROR_STOP=1 -q -f /tmp/carga_$($b.archivo)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Fallo la carga de $($b.archivo): copia el error de arriba." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Listo: 500 usuarios de prueba cargados (carga.001 a carga.500@duocuc.cl, clave Tutorias2026)." -ForegroundColor Green
}
finally {
    Pop-Location
}
