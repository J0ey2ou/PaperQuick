$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
Set-Location -LiteralPath $projectDir
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python tests/gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'GUI tests failed' }
python tests/make_icons.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compilerPath /nologo /target:winexe "/out:$projectDir\全局选词助手.exe" "/win32icon:$projectDir\browser-extension\app.ico" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "$projectDir\selection-helper\SelectionAssistant.cs"
if ($LASTEXITCODE -ne 0) { throw 'Selection helper build failed' }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PaperQuick --icon "$projectDir\browser-extension\app.ico" --distpath "$projectDir\release" --workpath "$projectDir\build" --specpath "$projectDir\build" "$projectDir\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath "$projectDir\release\PaperQuick.exe" -Destination "$projectDir\文献直达.exe" -Force
Write-Output 'Built 文献直达.exe'
