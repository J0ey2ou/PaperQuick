param([string]$Python='python',[switch]$SkipTests)
$ErrorActionPreference='Stop'
$projectDir=$PSScriptRoot
Set-Location -LiteralPath $projectDir
$env:PYTHONPATH="$projectDir\build\vendor;$env:PYTHONPATH"
$version=& $Python -c 'from app_version import VERSION; print(VERSION)'
if ($LASTEXITCODE -ne 0) { throw 'Version read failed' }
$releaseDirectory=Join-Path $projectDir "release\v$version"
New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
New-Item -ItemType Directory -Force -Path "$projectDir\build\test-temp" | Out-Null
$env:TMP="$projectDir\build\test-temp"
$env:TEMP=$env:TMP
if (-not (Test-Path -LiteralPath "$projectDir\word-integration\vendor\node.exe")) {
    & $Python scripts/prepare_word_assets.py
    if ($LASTEXITCODE -ne 0) { throw 'Word citation assets preparation failed' }
}
& "$projectDir\scripts\build_word_bridge.ps1"
& "$projectDir\scripts\build_document_converter.ps1"
if (-not $SkipTests) {
    & $Python scripts/test_background.py
    if ($LASTEXITCODE -ne 0) { throw 'Background verification failed' }
}
$compilerPath=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compilerPath /nologo /target:winexe "/out:$releaseDirectory\全局选词助手.exe" "/win32icon:$projectDir\browser-extension\app.ico" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "$projectDir\selection-helper\SelectionAssistant.cs"
if ($LASTEXITCODE -ne 0) { throw 'Selection helper build failed' }
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name PaperQuick --paths "$projectDir\build\vendor" --hidden-import pypdf --hidden-import pypdfium2 --collect-all pypdfium2 --collect-all pypdfium2_raw --add-data "$projectDir\graph_template.html;." --add-data "$projectDir\assets;assets" --add-data "$projectDir\word-integration;word-integration" --icon "$projectDir\assets\app.ico" --distpath "$releaseDirectory" --workpath "$projectDir\build\v$version" --specpath "$projectDir\build" "$projectDir\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Write-Output "Build ready at $releaseDirectory. Running applications and installed files have not been changed."
