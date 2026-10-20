"""GitHub release updates, verified staging and rollback without touching user data."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

REPO = 'J0ey2ou/PaperQuick'
API = 'https://api.github.com/repos/' + REPO + '/releases?per_page=30'
UPDATE_FEED = 'https://github.com/' + REPO + '/releases/latest/download/update.json'
MAX_PACKAGE = 512 * 1024 * 1024
ROOT_FILES = {'文献直达.exe','全局选词助手.exe','打开文献库.bat','README.md','CONTRIBUTING.md','RELEASE_NOTES.md',
              '使用说明.md','本地文献库使用说明.md','右键插件安装.html','推送文案.html','推送文案.txt','推送文案.md',
              'LICENSE','LICENSE.txt','LICENSE.md','version.json','升级说明.txt'}


def version_tuple(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)(?:\.(\d+))?',str(value))
    if not match:raise ValueError('无法识别发布版本号。')
    return tuple(int(n or 0) for n in match.groups())


def _asset_url(url):
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='github.com' or not parsed.path.startswith('/'+REPO+'/releases/download/') or parsed.query or parsed.fragment:
        raise ValueError('更新文件地址不属于开发者的 GitHub 发布页。')
    return url


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        from urllib.parse import urlsplit
        parsed=urlsplit(newurl)
        if parsed.scheme!='https' or parsed.hostname not in {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'} or parsed.username or parsed.password:
            raise ValueError('更新下载被重定向到未授权地址。')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _open(url):
    request=urllib.request.Request(url,headers={'User-Agent':'PaperQuick-updater/1','Accept':'application/vnd.github+json' if url==API else 'application/octet-stream'})
    return urllib.request.build_opener(ReleaseRedirect()).open(request,timeout=30)


def select_release(releases, current, preview=False):
    candidates=[]
    for release in releases:
        if release.get('draft') or (release.get('prerelease') and not preview):continue
        try:version=version_tuple(release.get('tag_name',''))
        except ValueError:continue
        if version<=version_tuple(current):continue
        tag=release['tag_name'];name='PaperQuick-'+tag+'-Windows.zip'
        asset=next((a for a in release.get('assets',[]) if a.get('name')==name and a.get('state')=='uploaded'),None)
        if not asset or not re.fullmatch(r'sha256:[a-f0-9]{64}',asset.get('digest') or ''):continue
        if not 0<int(asset.get('size',0))<=MAX_PACKAGE:continue
        try:url=_asset_url(asset['browser_download_url'])
        except (ValueError,KeyError):continue
        candidates.append({'version':tag.lstrip('v'),'tag':tag,'url':url,'sha256':asset['digest'][7:],
                           'size':int(asset['size']),'notes':str(release.get('body') or '')[:20000]})
    return max(candidates,key=lambda r:version_tuple(r['version']),default=None)


def manifest_release(data,current,preview=False):
    if not isinstance(data,dict) or data.get('schema')!=1:raise ValueError('更新清单格式不正确。')
    version=str(data.get('version',''));version_tuple(version)
    package=data.get('package',{});name='PaperQuick-v'+version+'-Windows.zip'
    if data.get('tag')!='v'+version or package.get('name')!=name:raise ValueError('更新清单版本与安装包不匹配。')
    release={'tag_name':'v'+version,'prerelease':bool(data.get('prerelease')),'body':data.get('notes',''),
             'assets':[{'name':name,'state':'uploaded','size':package.get('size',0),
                        'digest':'sha256:'+str(package.get('sha256','')),'browser_download_url':package.get('url','')}]}
    if select_release([release],'0.0.0',True) is None:raise ValueError('更新清单缺少有效的校验信息或下载地址。')
    return select_release([release],current,preview)


def check_update(current, preview=False):
    def public_manifest():
        with _open(UPDATE_FEED) as response:data=response.read(1024*1024+1)
        if len(data)>1024*1024:raise ValueError('更新清单过大。')
        return manifest_release(json.loads(data),current,preview)
    # Stable clients need no anonymous GitHub API quota or access token.
    if not preview:
        import urllib.error
        try:return public_manifest()
        except (urllib.error.URLError,TimeoutError):pass
    try:
        with _open(API) as response:data=response.read(4*1024*1024+1)
    except OSError as exc:
        if not preview:raise ValueError('暂时无法检查更新，请检查网络后重试。') from exc
        raise ValueError('预览版接口暂不可用或已限流；可取消“接收预览版”检查正式版本。') from exc
    if len(data)>4*1024*1024:raise ValueError('更新列表过大，请稍后重试。')
    releases=json.loads(data)
    if not isinstance(releases,list):raise ValueError('暂时无法获取版本列表。')
    return select_release(releases,current,preview)


def allowed_file(name):
    path=PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or any(p in ('..','.','') for p in name.split('/')):return False
    if len(path.parts)==1:return name in ROOT_FILES
    if path.parts[0] not in {'assets','docs','browser-extension','word-integration'}:return False
    return not any(p.startswith('.') or p.lower() in {'settings.json','shortcut.json','本地文献库'} for p in path.parts)


def hash_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def stage_archive(archive_path, install_root, release):
    root=Path(install_root).resolve();archive_path=Path(archive_path).resolve()
    if archive_path.parent.parent.name!='.updates' or archive_path.parent.parent.parent!=root:
        raise ValueError('更新下载不在程序的暂存目录中。')
    if hash_file(archive_path)!=release['sha256']:raise ValueError('下载文件校验失败，未安装。请重新检查更新。')
    stage=archive_path.parent;content=stage/'package';prefix='PaperQuick-v'+release['version']+'/'
    with zipfile.ZipFile(archive_path) as archive:
        infos=archive.infolist()
        if len(infos)>5000 or sum(i.file_size for i in infos)>2*1024*1024*1024:raise ValueError('更新包大小异常。')
        manifest=json.loads(archive.read(prefix+'update-manifest.json'))
        if manifest.get('schema')!=1 or manifest.get('version')!=release['version']:raise ValueError('更新清单版本不匹配。')
        files=manifest.get('files',{})
        if not isinstance(files,dict) or '文献直达.exe' not in files or 'version.json' not in files:raise ValueError('更新包缺少主程序或版本信息。')
        names=[i.filename for i in infos]
        if len(names)!=len(set(names)):raise ValueError('更新包包含重复路径。')
        for info in infos:
            name=info.filename
            if not name.startswith(prefix) or stat.S_ISLNK(info.external_attr>>16):raise ValueError('更新包包含不安全路径。')
            relative=name[len(prefix):]
            if relative=='update-manifest.json':continue
            if info.is_dir():continue
            if not allowed_file(relative) or relative not in files:raise ValueError('更新包包含未声明或个人数据文件。')
        for name,sha in files.items():
            if not allowed_file(name) or not re.fullmatch('[a-f0-9]{64}',str(sha)):raise ValueError('更新清单包含不安全路径。')
            data=archive.read(prefix+name)
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('更新包文件校验失败：'+name)
            target=content/name
            if not target.resolve().is_relative_to(content.resolve()):raise ValueError('更新文件超出暂存目录。')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    if json.loads((content/'version.json').read_text('utf-8-sig')).get('version')!=release['version']:raise ValueError('安装包版本不匹配。')
    plan={'schema':1,'root':str(root),'version':release['version'],'files':files,'pid':os.getpid()}
    plan_path=stage/'plan.json';plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf-8');return plan_path


def download_update(root,release,progress=lambda done,total:None):
    root=Path(root).resolve()
    # Reuse a complete verified download after a failed or deferred installation.
    cached=sorted((root/'.updates').glob('*/download.zip'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]
    for candidate in cached:
        if candidate.stat().st_size==release['size'] and hash_file(candidate)==release['sha256']:
            progress(release['size'],release['size']);return stage_archive(candidate,root,release)
    stage=root/'.updates'/uuid.uuid4().hex;stage.mkdir(parents=True)
    package=stage/'download.zip';done=0
    with _open(_asset_url(release['url'])) as response,package.open('wb') as stream:
        while True:
            block=response.read(256*1024)
            if not block:break
            done+=len(block)
            if done>release['size'] or done>MAX_PACKAGE:raise ValueError('下载大小不符合发布清单。')
            stream.write(block);progress(done,release['size'])
    if done!=release['size']:raise ValueError('下载尚未完整，请重试。')
    return stage_archive(package,root,release)


def launch_installer(plan_path):
    if not getattr(sys,'frozen',False):raise ValueError('源码运行模式仅支持检查更新；请使用完整安装包自动更新。')
    helper=Path(plan_path).parent/'updater.exe';shutil.copy2(sys.executable,helper)
    subprocess.Popen([str(helper),'--apply-update',str(plan_path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=str(helper.parent))


def apply_staged(plan_path, replace=os.replace):
    """Install only public files, atomically roll back a failed batch, never kill apps."""
    plan_path=Path(plan_path).resolve();stage=plan_path.parent;plan=json.loads(plan_path.read_text('utf-8'))
    root=Path(plan['root']).resolve()
    if stage.parent.name!='.updates' or stage.parent.parent!=root or plan.get('schema')!=1:raise ValueError('更新暂存位置不正确。')
    version_tuple(plan['version']);files=plan['files'];prepared=[];written=[];validated=[]
    if not isinstance(files,dict) or '文献直达.exe' not in files or 'version.json' not in files:raise ValueError('更新清单缺少主程序或版本。')
    for name,sha in files.items():
        if not allowed_file(name):raise ValueError('拒绝覆盖个人数据或未知文件。')
        source=stage/'package'/name;target=root/name
        if source.resolve()!=source or target.resolve()!=target or not source.is_relative_to(stage/'package') or not target.is_relative_to(root):
            raise ValueError('更新路径包含链接或超出程序目录。')
        if hash_file(source)!=sha:raise ValueError('暂存文件发生变化，请重新下载。')
        validated.append((source,target,stage/'backup'/name))
    try:
        for source,target,backup in validated:
            if target.exists():backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.update-'+uuid.uuid4().hex)
            prepared.append((temporary,target,backup));shutil.copy2(source,temporary)
        for temporary,target,backup in prepared:
            replace(temporary,target);written.append((target,backup))
    except Exception:
        for target,backup in reversed(written):
            if backup.exists():os.replace(backup,target)
            else:target.unlink(missing_ok=True)
        raise
    finally:
        for temporary,_,_ in prepared:temporary.unlink(missing_ok=True)
    result={'version':plan['version'],'state':'installed','files':len(written),'user_data_modified':False}
    (root/'.updates'/'latest-result.json').write_text(json.dumps(result,ensure_ascii=False),'utf-8');return result


def installer_main(plan_path):
    plan_path=Path(plan_path).resolve()
    try:
        plan=json.loads(plan_path.read_text('utf-8'))
        # Hold a process handle so PID reuse cannot mistake another process for the parent.
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p;kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,int(plan['pid']))
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,24*60*60*1000)!=0:raise ValueError('等待原程序退出超时，已保留下载文件。')
            finally:kernel.CloseHandle(handle)
        elif ctypes.get_last_error()!=87:raise ValueError('无法确认原程序已退出，已保留下载文件。')
        for attempt in range(12):
            try:return apply_staged(plan_path)
            except PermissionError:
                if attempt==11:raise
                time.sleep(5)
    except Exception as exc:
        report={'state':'failed','error':str(exc),'user_data_modified':False}
        (plan_path.parent/'result.json').write_text(json.dumps(report,ensure_ascii=False),'utf-8')
        return report
