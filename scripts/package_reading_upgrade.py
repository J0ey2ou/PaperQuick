"""Package the tested v3.3 release; exclude libraries, notes and backups."""
from pathlib import Path
import hashlib,json,sys
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'scripts'))
from package_local_preview import application_files,write_archive
destination=BASE/'PaperQuick-v3.3-Windows.zip'
assert (BASE/'build/v33-final-bundle-check.json').is_file()
assert json.loads((BASE/'build/v33-final-bundle-check.json').read_text('utf-8'))['passed']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(BASE/'文献直达.exe')==sha(BASE/'release/PaperQuick.exe')
files=application_files();write_archive(destination,'PaperQuick-v3.3',files)
report={'package':str(destination),'bytes':destination.stat().st_size,'files':len(files),'executable_sha256':sha(BASE/'文献直达.exe'),'private_data_included':False}
(BASE/'build/v33-package-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
