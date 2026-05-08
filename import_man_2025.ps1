chcp 65001 | Out-Null
$env:PYTHONUTF8 = "1"

$root = "C:\Users\rhod_\Documents\Bonus Engine Support\Input Files Original\2025"

if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "Path doesn't exist: $root" -ForegroundColor Red
    Write-Host "`nListing 'Input Files Original' instead:"
    Get-ChildItem -LiteralPath "C:\Users\rhod_\Documents\Bonus Engine Support\Input Files Original" -Directory | Select-Object Name
    throw "Adjust the path and re-run"
}

Write-Host "=== Subdirectories under $root ===" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $root -Directory | Select-Object Name

$manDir = Get-ChildItem -LiteralPath $root -Directory | Where-Object { $_.Name -like "*Mẫn*" -or $_.Name -like "*Man*" } | Select-Object -First 1
if (-not $manDir) {
    Write-Host "`nMẫn directory not found in $root" -ForegroundColor Red
    throw "Adjust path"
}
Write-Host "`nFound Mẫn dir: $($manDir.FullName)" -ForegroundColor Green

Write-Host "`n=== Files in Mẫn dir ===" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $manDir.FullName -Filter *.xlsx | Select-Object Name

Write-Host "`n=== Running importer ===" -ForegroundColor Cyan
python -m backend.importer.cli "$($manDir.FullName)" 2>&1 | Tee-Object -FilePath "logs\import_man_2025.log"
