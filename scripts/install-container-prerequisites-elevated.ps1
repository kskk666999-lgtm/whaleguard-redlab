[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Write-Error "This repository file is intentionally not an elevated entry point. Run INSTALL_WHALEGUARD_DOCKER.bat; it passes a parser-validated, in-memory command to UAC so the administrator process never loads user-writable project code."
exit 1
