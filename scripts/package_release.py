"""Package a complete versioned build, retaining all public components."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,zipfile
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'scripts'))
from app_version import VERSION
from package_local_preview import application_files
from write_update_manifest import write_manifest

def main():
    built=BASE/'release'/('v'+VERSION)
    parser=argparse.ArgumentParser();parser.add_argument('--bundle-check',type=Path,default=BASE/'build'/('v'+VERSION.replace('.','')+'-bundle-check.json'));parser.add_argument('--prerelease',action='store_true');args=parser.parse_args()
    report=json.loads(args.bundle_check.read_text('utf-8'))
    assert report['passed'] and report['frozen'] and report['version']==VERSION
    files={p.relative_to(BASE).as_posix():p for p in application_files()}
    files['文献直达.exe']=built/'PaperQuick.exe'
    files['全局选词助手.exe']=built/'全局选词助手.exe' if (built/'全局选词助手.exe').is_file() else BASE/'全局选词助手.exe'
    assert all(p.is_file() for p in files.values())
    prefix=f'PaperQuick-v{VERSION}';stage=built/prefix;stage.mkdir(parents=True,exist_ok=True)
    for name,path in files.items():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    (stage/'version.json').write_text(json.dumps({'version':VERSION,'package':'complete','prerelease':args.prerelease},indent=2),'utf-8')
    notes=(BASE/'RELEASE_NOTES.md').read_text('utf-8').split('\n# PaperQuick',1)[0]
    upgrade=notes+'\n\n升级请保留原目录完整“本地文献库”、settings.json、shortcut.json。先从托盘正常退出主程序和选词助手，再覆盖程序文件。\n设置中可检查并下载后续版本；在退出后更新，下次启动生效。\n浏览器扩展文件更新后，请在扩展管理页重新加载，再刷新已有 ChatGPT 标签页。\n'
    (stage/'升级说明.txt').write_text(upgrade,'utf-8-sig')
    manifest=write_manifest(stage,VERSION)
    destination=built/f'{prefix}-Windows.zip';partial=destination.with_suffix('.zip.partial')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in [*manifest['files'],'update-manifest.json']:archive.write(stage/name,f'{prefix}/{name}')
    with zipfile.ZipFile(partial) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(manifest['files'])+1
        assert archive.read(f'{prefix}/文献直达.exe')==(built/'PaperQuick.exe').read_bytes()
        assert not any(x.endswith(('/settings.json','/shortcut.json','.sqlite')) or '/本地文献库/' in x for x in archive.namelist())
    partial.replace(destination)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    (built/'SHA256SUMS.txt').write_text(f'{digest}  {destination.name}\n',encoding='ascii')
    feed={'schema':1,'version':VERSION,'tag':'v'+VERSION,'prerelease':args.prerelease,'notes':notes,
          'package':{'name':destination.name,'url':'https://github.com/J0ey2ou/PaperQuick/releases/download/v'+VERSION+'/'+destination.name,'size':destination.stat().st_size,'sha256':digest}}
    (built/'update.json').write_text(json.dumps(feed,ensure_ascii=False,indent=2),'utf-8')
    (BASE/'build'/('v'+VERSION.replace('.','')+'-package-check.json')).write_text(json.dumps({'version':VERSION,'file':str(destination),'bytes':destination.stat().st_size,'sha256':digest,'files':len(manifest['files'])+1,'complete_package':True,'private_data_included':False},indent=2),'utf-8')
    print(destination.name,digest)

if __name__=='__main__':main()
