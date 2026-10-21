$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
$sdkVersion='1.0.4258.31'
$sdkDir=Join-Path $projectDir 'build/webview2-sdk'
if (-not (Test-Path -LiteralPath (Join-Path $sdkDir 'Microsoft.Web.WebView2.WinForms.dll'))) {
    $packagePath=Join-Path $projectDir 'build/webview2.nupkg'
    Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg" -OutFile $packagePath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[System.IO.Compression.ZipFile]::OpenRead($packagePath)
    New-Item -ItemType Directory -Force -Path $sdkDir | Out-Null
    try {
        foreach ($name in @('lib/net462/Microsoft.Web.WebView2.Core.dll','lib/net462/Microsoft.Web.WebView2.WinForms.dll','runtimes/win-x64/native/WebView2Loader.dll')) {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry($name),(Join-Path $sdkDir ([System.IO.Path]::GetFileName($name))),$true)
        }
    } finally {$archive.Dispose()}
}
$outputDir=Join-Path $projectDir 'embedded-browser'
foreach ($name in @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll')) {Copy-Item -LiteralPath (Join-Path $sdkDir $name) -Destination (Join-Path $outputDir $name)}
$compilerPath=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $compilerPath /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.Core.dll ("/reference:"+(Join-Path $sdkDir 'Microsoft.Web.WebView2.Core.dll')) ("/reference:"+(Join-Path $sdkDir 'Microsoft.Web.WebView2.WinForms.dll')) ("/out:"+(Join-Path $outputDir 'EmbeddedChat.exe')) (Join-Path $outputDir 'EmbeddedChat.cs')
if ($LASTEXITCODE -ne 0) {throw 'Embedded chat component build failed'}
