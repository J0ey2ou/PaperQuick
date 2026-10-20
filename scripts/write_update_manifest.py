"""Create the updater contract for an already assembled, public package folder."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_updates import allowed_file,version_tuple


def write_manifest(folder,version):
    folder=Path(folder).resolve();version_tuple(version)
    files={}
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.name=='update-manifest.json':continue
        name=path.relative_to(folder).as_posix()
        if not allowed_file(name):raise ValueError('Private or unexpected package file: '+name)
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if '文献直达.exe' not in files or 'version.json' not in files:raise ValueError('Main executable/version missing')
    if json.loads((folder/'version.json').read_text('utf-8-sig'))['version']!=version:raise ValueError('Version mismatch')
    manifest={'schema':1,'version':version,'files':files}
    (folder/'update-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    return manifest


if __name__=='__main__':
    result=write_manifest(sys.argv[1],sys.argv[2]);print(json.dumps({'version':result['version'],'files':len(result['files'])}))
