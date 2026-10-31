# Construit la Table de montage :
#   dist\TableDeMontage\                    le dossier de l'application (TableDeMontage.exe, lanceur.exe, bin\ffmpeg.exe)
#   dist\TableDeMontage-portable.zip        la version portable (avec portable.txt : données à côté de l'exe)
#   dist\TableDeMontage-setup-<version>.exe l'installateur, si Inno Setup 6 est installé
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"
$version = & $python -c "from tablemontage import VERSION; print(VERSION)"
Write-Host "Table de montage $version"

& $python -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
& $python -m PyInstaller --noconfirm --clean TableDeMontage.spec

# ffmpeg et ffprobe à côté de l'exe (ceux du PATH)
$app = "dist\TableDeMontage"
New-Item -ItemType Directory -Force "$app\bin" | Out-Null
foreach ($outil in "ffmpeg", "ffprobe") {
    $source = (Get-Command $outil -ErrorAction SilentlyContinue).Source
    if ($source) { Copy-Item $source "$app\bin\" -Force } else { Write-Warning "$outil introuvable dans le PATH : à copier dans $app\bin" }
}
Copy-Item README.md "$app\" -Force

# version portable
Set-Content "$app\portable.txt" "Présence de ce fichier : les aperçus et préférences sont rangés dans le dossier « donnees »." -Encoding utf8
Compress-Archive -Path "$app\*" -DestinationPath "dist\TableDeMontage-portable.zip" -Force
Remove-Item "$app\portable.txt"

# installateur
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) { & $iscc "/DVersion=$version" setup.iss } else { Write-Host "Inno Setup 6 non installé : pas d'installateur (https://jrsoftware.org/isinfo.php)." }
