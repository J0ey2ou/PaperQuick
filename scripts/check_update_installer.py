"""Run the frozen updater against a disposable fake installation, never the desktop."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_updates import stage_archive


def main():
    executable=Path(sys.argv[1]).resolve();report=Path(sys.argv[2]).resolve()
    base=Path(__file__).resolve().parents[1]/'build'/'update-installer-checks';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        root=Path(temporary).resolve();stage=root/'.updates'/'fixture';stage.mkdir(parents=True)
        source={'文献直达.exe':b'MZ fictional new program - never execute','README.md':b'New fixture notes','version.json':b'{"version":"9.0.0"}'}
        (root/'文献直达.exe').write_bytes(b'Old fixture program')
        (root/'settings.json').write_bytes(b'Keep settings');(root/'本地文献库').mkdir();(root/'本地文献库/note.txt').write_bytes(b'Keep personal note')
        manifest={'schema':1,'version':'9.0.0','files':{name:hashlib.sha256(data).hexdigest() for name,data in source.items()}}
        archive=stage/'download.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for name,data in source.items():z.writestr('PaperQuick-v9.0.0/'+name,data)
            z.writestr('PaperQuick-v9.0.0/update-manifest.json',json.dumps(manifest))
        plan_path=stage_archive(archive,root,{'version':'9.0.0','sha256':hashlib.sha256(archive.read_bytes()).hexdigest()})
        # The updater waits only for a disposable process owned by this check.
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)'],creationflags=flags)
        plan=json.loads(plan_path.read_text('utf-8'));plan['pid']=child.pid;plan_path.write_text(json.dumps(plan),'utf-8')
        helper=stage/'updater.exe';shutil.copy2(executable,helper)
        process=subprocess.Popen([str(helper),'--apply-update',str(plan_path)],creationflags=flags,cwd=stage)
        try:
            process.wait(timeout=90);child.wait(timeout=10)
            result=json.loads((root/'.updates/latest-result.json').read_text('utf-8'))
            assert result['state']=='installed'
            assert all((root/name).read_bytes()==data for name,data in source.items())
            assert (root/'settings.json').read_bytes()==b'Keep settings'
            assert (root/'本地文献库/note.txt').read_bytes()==b'Keep personal note'
            assert (stage/'backup/文献直达.exe').read_bytes()==b'Old fixture program'
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
            if child.poll() is None:child.wait(timeout=10)
    report.write_text(json.dumps({'passed':True,'frozen_installer':True,'background_only':True,'user_processes_touched':False,'checks':['wait for owned process exit','replace public files','preserve library and settings','keep previous executable backup']},indent=2),'utf-8')
    print(report.read_text('utf-8'))


if __name__=='__main__':main()
