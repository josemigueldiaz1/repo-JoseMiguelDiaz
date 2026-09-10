<#
.SYNOPSIS
    Construye y sirve los grafos de OSRM para la Fase 2.

.DESCRIPTION
    Un servidor OSRM sirve UN solo perfil: el que se compilo en su grafo. Para comparar
    auto / pie / bicicleta hacen falta tres grafos y tres contenedores, cada uno en su
    puerto. Este script automatiza las cuatro etapas del flujo de OSRM:

        osrm-extract    lee el .osm.pbf y aplica el perfil Lua (la etapa lenta)
        osrm-partition  particiona el grafo para el algoritmo MLD
        osrm-customize  calcula los pesos de las celdas
        osrm-routed     levanta el servidor HTTP

    El directorio de trabajo va FUERA de OneDrive a proposito: los grafos compilados pesan
    varios GB por perfil y OneDrive intentaria sincronizarlos.

    NOTA DE CODIFICACION: este archivo se mantiene en ASCII puro a proposito. PowerShell 5.1
    lee los .ps1 con la pagina de codigos ANSI del sistema cuando no llevan BOM, asi que un
    guion largo o una tilde rompen el parseo del script entero con errores enganosos.

.PARAMETER Accion
    build   Compila el grafo (etapas extract + partition + customize)
    serve   Levanta el contenedor del servidor
    stop    Detiene y elimina los contenedores
    status  Muestra que contenedores corren y si responden

.PARAMETER Perfil
    car, foot, bike, o all (por defecto: car)

.EXAMPLE
    .\scripts\osrm.ps1 build car
    .\scripts\osrm.ps1 serve car
    .\scripts\osrm.ps1 status
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("build", "serve", "stop", "status")]
    [string]$Accion = "status",

    [Parameter(Position = 1)]
    [ValidateSet("car", "foot", "bike", "all")]
    [string]$Perfil = "car"
)

# OJO: NO usar "Stop" aqui. Las herramientas de OSRM escriben todo su progreso por stderr,
# y PowerShell 5.1 convierte cada linea de stderr de un ejecutable nativo en un ErrorRecord.
# Con "Stop", una compilacion perfectamente correcta abortaria en falso a los pocos segundos.
# El exito o fracaso real de cada etapa se comprueba con $LASTEXITCODE, que es lo fiable.
$ErrorActionPreference = "Continue"

# ------------------------------------------------------------------ parametros fijos
$IMAGEN    = "ghcr.io/project-osrm/osrm-backend"
$BASE      = "C:\osrm-hw2"                      # debe coincidir con [ruteo].directorio_osrm
$PBF_ORIG  = Join-Path $PSScriptRoot "..\data\raw\peru-latest.osm.pbf"
$PBF_NOM   = "peru-latest.osm.pbf"
$OSRM_NOM  = "peru-latest.osrm"
$MAX_TABLE = 4000                               # debe coincidir con [ruteo].max_table_size
$PRUEBA    = "-77.0300,-12.0464"                # Lima, para el chequeo de salud

$PERFILES = @{
    car  = @{ lua = "/opt/car.lua";     puerto = 5000 }
    foot = @{ lua = "/opt/foot.lua";    puerto = 5001 }
    bike = @{ lua = "/opt/bicycle.lua"; puerto = 5002 }
}

function Write-Paso($msg)  { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Aviso($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

function Test-Docker {
    docker version --format "{{.Server.Version}}" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "El motor de Docker no responde. Abre Docker Desktop y espera a que diga 'Engine running'."
    }
}

function Get-DirPerfil($p) { Join-Path $BASE $p }

function Test-Responde($puerto) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:$puerto/nearest/v1/driving/$PRUEBA" -TimeoutSec 10
        return ($r.code -eq "Ok")
    } catch { return $false }
}

# ------------------------------------------------------------------------------ build
function Invoke-Build($p) {
    $cfg = $PERFILES[$p]
    $dir = Get-DirPerfil $p
    Write-Paso "Compilando grafo OSRM - perfil '$p' (Lua: $($cfg.lua))"

    if (-not (Test-Path $PBF_ORIG)) {
        throw "No se encuentra el extracto OSM en $PBF_ORIG. Corre primero: python run_pipeline.py --phase 1 --with-osm"
    }

    New-Item -ItemType Directory -Force $dir | Out-Null
    $pbf = Join-Path $dir $PBF_NOM
    if (-not (Test-Path $pbf)) {
        Write-Host "    copiando extracto OSM a $dir ..."
        Copy-Item $PBF_ORIG $pbf
    } else {
        Write-Ok "extracto ya presente"
    }

    $listo = Join-Path $dir "$OSRM_NOM.mldgr"
    if (Test-Path $listo) {
        Write-Ok "el grafo de '$p' ya esta compilado. Borra $dir para rehacerlo."
        return
    }

    $vol = "$($dir):/data"
    $t0 = Get-Date

    Write-Host "    [1/3] osrm-extract  (la etapa lenta; medido: ~2 min para el Peru)..."
    docker run --rm -v $vol $IMAGEN osrm-extract -p $cfg.lua "/data/$PBF_NOM"
    if ($LASTEXITCODE -ne 0) { throw "osrm-extract fallo para el perfil '$p' (codigo $LASTEXITCODE)" }

    Write-Host "    [2/3] osrm-partition ..."
    docker run --rm -v $vol $IMAGEN osrm-partition "/data/$OSRM_NOM"
    if ($LASTEXITCODE -ne 0) { throw "osrm-partition fallo para el perfil '$p' (codigo $LASTEXITCODE)" }

    Write-Host "    [3/3] osrm-customize ..."
    docker run --rm -v $vol $IMAGEN osrm-customize "/data/$OSRM_NOM"
    if ($LASTEXITCODE -ne 0) { throw "osrm-customize fallo para el perfil '$p' (codigo $LASTEXITCODE)" }

    $min = ((Get-Date) - $t0).TotalMinutes
    Write-Ok ("grafo '{0}' compilado en {1:N1} min" -f $p, $min)
}

# ------------------------------------------------------------------------------ serve
function Invoke-Serve($p) {
    $cfg = $PERFILES[$p]
    $dir = Get-DirPerfil $p
    $nombre = "osrm-$p"

    if (-not (Test-Path (Join-Path $dir "$OSRM_NOM.mldgr"))) {
        throw "El grafo de '$p' no esta compilado. Corre primero: .\scripts\osrm.ps1 build $p"
    }

    docker rm -f $nombre 2>$null | Out-Null
    Write-Paso "Levantando servidor OSRM '$p' en el puerto $($cfg.puerto)"
    docker run -d --name $nombre -p "$($cfg.puerto):5000" -v "$($dir):/data" $IMAGEN `
        osrm-routed --algorithm mld --max-table-size $MAX_TABLE "/data/$OSRM_NOM" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "no se pudo levantar el contenedor '$nombre'" }

    foreach ($i in 1..10) {
        Start-Sleep -Seconds 3
        if (Test-Responde $cfg.puerto) {
            Write-Ok "responde en http://localhost:$($cfg.puerto)"
            return
        }
    }
    Write-Aviso "el contenedor arranco pero aun no responde; revisa con: docker logs $nombre"
}

# ------------------------------------------------------------------------ stop/status
function Invoke-Stop {
    Write-Paso "Deteniendo contenedores OSRM"
    foreach ($p in @("car", "foot", "bike")) {
        $n = "osrm-$p"
        $existe = docker ps -aq -f "name=^$n$"
        if ($existe) { docker rm -f $n | Out-Null; Write-Ok "$n eliminado" }
    }
}

function Invoke-Status {
    Write-Paso "Estado de OSRM"
    Write-Host ("    {0,-6} {1,-7} {2,-11} {3,-9} {4}" -f "perfil", "puerto", "contenedor", "responde", "grafo")
    foreach ($p in @("car", "foot", "bike")) {
        $cfg = $PERFILES[$p]
        $n = "osrm-$p"
        $corriendo = docker ps -q -f "name=^$n$" -f "status=running"
        $estado = if ($corriendo) { "corriendo" } else { "detenido" }
        $resp = "-"
        if ($corriendo) { $resp = if (Test-Responde $cfg.puerto) { "SI" } else { "NO" } }
        $grafo = if (Test-Path (Join-Path (Get-DirPerfil $p) "$OSRM_NOM.mldgr")) { "compilado" } else { "SIN COMPILAR" }
        Write-Host ("    {0,-6} {1,-7} {2,-11} {3,-9} {4}" -f $p, $cfg.puerto, $estado, $resp, $grafo)
    }
}

# ------------------------------------------------------------------------------- main
Test-Docker
$objetivo = if ($Perfil -eq "all") { @("car", "foot", "bike") } else { @($Perfil) }

switch ($Accion) {
    "build"  { foreach ($p in $objetivo) { Invoke-Build $p };  Invoke-Status }
    "serve"  { foreach ($p in $objetivo) { Invoke-Serve $p };  Invoke-Status }
    "stop"   { Invoke-Stop }
    "status" { Invoke-Status }
}
