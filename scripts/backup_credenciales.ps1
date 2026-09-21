# Copia de seguridad de los archivos con credenciales de Maira, FUERA del repositorio.
#
# Ejecutar SIEMPRE antes de tocar el .env (a mano, con un script o con una herramienta):
#   powershell -ExecutionPolicy Bypass -File scripts\backup_credenciales.ps1
#
# Cada ejecucion crea una carpeta nueva con fecha y hora; nunca sobrescribe ni borra copias
# anteriores. Las copias quedan en texto plano en tu perfil de usuario: protegen frente a
# sobrescrituras y borrados, NO frente a la perdida del disco. Los valores irrecuperables
# (secretos de Azure, tokens) deben guardarse ademas en un gestor de contrasenas.
param(
    [string]$Destino = (Join-Path $env:USERPROFILE "Documents\backups-credenciales-maira")
)
$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$archivos = @(".env", "MAIRA_LEXGUARDIAN_CONEXIONES.env")

$carpeta = Join-Path $Destino (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Force -Path $carpeta | Out-Null

foreach ($a in $archivos) {
    $origen = Join-Path $raiz $a
    if (Test-Path $origen) {
        Copy-Item -LiteralPath $origen -Destination (Join-Path $carpeta $a)
        $bytes = (Get-Item -LiteralPath $origen).Length
        Write-Host ("copiado: {0} ({1} bytes)" -f $a, $bytes)
    } else {
        Write-Host ("no existe, se omite: {0}" -f $a)
    }
}
Write-Host "Copia guardada en: $carpeta"
