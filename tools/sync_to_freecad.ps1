<#
Copies PipeHarness/ into one or more FreeCAD Mod/ folders for local testing.
A plain copy (not a symlink) is used deliberately, so it works even when the
repo lives on a cloud-synced drive (OneDrive/Google Drive/etc.) that handles
NTFS symlinks/junctions poorly. Re-run this after every source change and
reload the workbench (or restart FreeCAD).

By default it deploys into FreeCAD's per-user addon Mod/ folder
(%APPDATA%\FreeCAD\<version>\Mod) - the same location FreeCAD's own Addon
Manager installs workbenches into. To also deploy into a portable install's
own Mod/ folder (or any other target), pass the paths explicitly, e.g.:

    ./sync_to_freecad.ps1 -FreeCADModPaths @(
        "D:\FreeCAD-portable\Mod",
        "$env:APPDATA\FreeCAD\v1-1\Mod"
    )
#>
param(
    [string[]]$FreeCADModPaths = @(
        "$env:APPDATA\FreeCAD\v1-1\Mod"
    )
)

$source = Join-Path $PSScriptRoot "..\PipeHarness"

foreach ($modPath in $FreeCADModPaths) {
    $dest = Join-Path $modPath "PipeHarness"
    robocopy $source $dest /MIR /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Error "robocopy failed with exit code $LASTEXITCODE for '$dest'"
        continue
    }
    Write-Host "Synced '$source' -> '$dest'"
}
