$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
Set-Location -LiteralPath $projectDir
$env:PYTHONPATH = "$projectDir\build\vendor;$env:PYTHONPATH"
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python tests/gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'GUI tests failed' }
python tests/library_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Library GUI tests failed' }
python tests/navigation_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Navigation GUI tests failed' }
python tests/reader_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Reader GUI tests failed' }
python tests/reader_routes_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'PDF routing tests failed' }
python tests/download_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Download flow tests failed' }
python tests/exploration_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Graph and annotation tests failed' }
python tests/runtime_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop runtime tests failed' }
python tests/v31_gui_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Reading recap, themes and renaming tests failed' }
python tests/make_icons.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compilerPath /nologo /target:winexe "/out:$projectDir\全局选词助手.exe" "/win32icon:$projectDir\browser-extension\app.ico" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "$projectDir\selection-helper\SelectionAssistant.cs"
if ($LASTEXITCODE -ne 0) { throw 'Selection helper build failed' }
$env:PYTHONPATH = "$projectDir\build\vendor;$env:PYTHONPATH"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PaperQuick --paths "$projectDir\build\vendor" --hidden-import pypdf --hidden-import pypdfium2 --collect-all pypdfium2 --collect-all pypdfium2_raw --add-data "$projectDir\graph_template.html;." --add-data "$projectDir\assets;assets" --icon "$projectDir\assets\app.ico" --distpath "$projectDir\release" --workpath "$projectDir\build" --specpath "$projectDir\build" "$projectDir\app.py"
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath "$projectDir\release\PaperQuick.exe" -Destination "$projectDir\文献直达.exe" -Force
Write-Output 'Built 文献直达.exe'
