# Point d'entrée historique: délégation au lanceur unique corrigé.
$launcher = Join-Path (Split-Path -Parent $PSScriptRoot) "REPRODUIRE_TOUT.ps1"
& $launcher @args
