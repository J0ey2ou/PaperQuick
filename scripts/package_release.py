"""Package a complete versioned build, retaining all public components."""
from pathlib import Path
import hashlib,json,sys,zipfile
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'scripts'))
from app_version import VERSION
from package_local_preview import application_files

def main():
    built=BASE/'release'/('v'+VERSION)
    report=json.loads((BASE/'build/v34-bundle-check.json').read_text('utf-8'))
    assert report['passed'] and report['frozen'] and report['version']==VERSION
    files={p.relative_to(BASE).as_posix():p for p in application_files()}
    files['文献直达.exe']=built/'PaperQuick.exe'
    files['全局选词助手.exe']=built/'全局选词助手.exe'
    assert all(p.is_file() for p in files.values())
    short='.'.join(VERSION.split('.')[:2]);prefix=f'PaperQuick-v{short}'
    destination=BASE/f'{prefix}-Windows.zip';partial=destination.with_suffix('.zip.partial')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):archive.write(path,f'{prefix}/{name}')
        archive.writestr(f'{prefix}/version.json',json.dumps({'version':VERSION,'package':'complete'},indent=2))
    with zipfile.ZipFile(partial) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(files)+1
        assert archive.read(f'{prefix}/文献直达.exe')==(built/'PaperQuick.exe').read_bytes()
        assert not any(x.endswith(('/settings.json','/shortcut.json','.sqlite')) or '/本地文献库/' in x for x in archive.namelist())
    partial.replace(destination)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    (BASE/'build/v34-SHA256SUMS.txt').write_text(f'{digest}  {destination.name}\n',encoding='ascii')
    (BASE/'build/v34-package-check.json').write_text(json.dumps({'version':VERSION,'file':destination.name,'bytes':destination.stat().st_size,'sha256':digest,'files':len(files)+1,'complete_package':True,'private_data_included':False},indent=2),'utf-8')
    print(destination.name,digest)

if __name__=='__main__':main()
