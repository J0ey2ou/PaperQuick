$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compilerPath)) {
    $compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
& $compilerPath /nologo /target:winexe /platform:anycpu "/out:$projectDir\word-integration\WordBridge.exe" /reference:Microsoft.CSharp.dll /reference:System.Web.Extensions.dll /reference:System.Core.dll "$projectDir\word-integration\WordBridge.cs"
if ($LASTEXITCODE -ne 0) { throw 'Word bridge build failed' }
Write-Output 'Built word-integration/WordBridge.exe'
