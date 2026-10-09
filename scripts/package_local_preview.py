"""Package an explicit public file allowlist; never include a personal library."""
from pathlib import Path
import zipfile
base=Path(__file__).resolve().parents[1]
files=[base/name for name in ('文献直达.exe','全局选词助手.exe','打开文献库.bat','README.md','CONTRIBUTING.md','RELEASE_NOTES.md','使用说明.md','本地文献库使用说明.md','右键插件安装.html','推送文案.html','推送文案.txt')]
files.extend(p for p in (base/'browser-extension').rglob('*') if p.is_file())
files.extend(p for p in (base/'docs'/'images').rglob('*') if p.is_file())
files.extend(p for p in (base/'assets').rglob('*') if p.is_file())
destination=base/'PaperQuick-v3.1-Windows.zip'
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        if not file.is_file():raise FileNotFoundError(file)
        archive.write(file,Path('PaperQuick-v3.1')/file.relative_to(base))
with zipfile.ZipFile(destination) as archive:
    assert not any('.enl' in n or '.sqlite' in n or '本地文献库/' in n for n in archive.namelist())
print('Public v3.1 package created; no user library, PDF or sync data included.')
