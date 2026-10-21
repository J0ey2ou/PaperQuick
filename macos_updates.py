"""Architecture-specific Mac release updates, installed only after normal exit."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from urllib.request import Request,urlopen
from urllib.error import URLError,HTTPError
from app_updates import API,_asset_url,version_tuple,hash_file

ARCH='arm64' if platform.machine()=='arm64' else 'x86_64'
FEED='https://github.com/J0ey2ou/PaperQuick/releases/latest/download/update-macos-'+ARCH+'.json'


def _json(url):
    with urlopen(Request(url,headers={'User-Agent':'PaperQuick-macOS'}),timeout=25) as response:raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('更新清单过大。')
    return json.loads(raw)


def check_update(current,preview=False):
    try:
        data=_json(FEED)
        if data.get('schema')!=1 or data.get('platform')!='macos' or data.get('architecture')!=ARCH:raise ValueError('Mac 更新清单不匹配。')
        if data.get('prerelease') and not preview:return None
        package=data['package'];version=data['version'];version_tuple(version)
        if version_tuple(version)<=version_tuple(current):return None
        if not re.fullmatch(r'[a-f0-9]{64}',package.get('sha256','')) or not 0<int(package['size'])<=512*1024*1024:raise ValueError('Mac 更新校验信息无效。')
        return {'version':version,'url':_asset_url(package['url']),'sha256':package['sha256'],'size':package['size'],'notes':data.get('notes','')}
    except (URLError,TimeoutError):pass
    releases=_json(API);candidates=[]
    if not isinstance(releases,list):raise ValueError('暂时无法获取 GitHub Mac 更新列表。')
    for release in releases:
        if release.get('draft') or release.get('prerelease') and not preview:continue
        match=re.fullmatch(r'v(\d+\.\d+\.\d+)(?:-macos\.\d+)?',release.get('tag_name',''))
        if not match or version_tuple(match[1])<=version_tuple(current):continue
        name='PaperQuick-v'+match[1]+'-macOS-'+ARCH+'.zip'
        asset=next((a for a in release.get('assets',[]) if a['name']==name and a.get('state')=='uploaded'),None)
        if not asset or not re.fullmatch(r'sha256:[a-f0-9]{64}',asset.get('digest') or ''):continue
        if not 0<int(asset.get('size',0))<=512*1024*1024:continue
        candidates.append({'version':match[1],'url':_asset_url(asset['browser_download_url']),'sha256':asset['digest'][7:],'size':asset['size'],'notes':release.get('body','')})
    return max(candidates,key=lambda r:version_tuple(r['version']),default=None)


def download_update(directory,release,progress=lambda *args:None):
    stage=Path(directory)/'.updates'/('mac-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    archive=stage/'download.zip';written=0;expected=int(release['size'])
    if not 0<expected<=512*1024*1024:raise ValueError('更新包大小无效。')
    with urlopen(Request(_asset_url(release['url']),headers={'User-Agent':'PaperQuick-macOS'}),timeout=40) as response,archive.open('wb') as output:
        for block in iter(lambda:response.read(256*1024),b''):
            written+=len(block)
            if written>expected:raise ValueError('更新包大小超出清单。')
            output.write(block);progress(written,expected)
    if written!=expected or hash_file(archive)!=release['sha256']:raise ValueError('更新包校验失败，未安装。')
    prefix='PaperQuick-v'+release['version']+'-macOS-'+ARCH+'/'
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(infos)>20000 or sum(i.file_size for i in infos)>3*1024*1024*1024:raise ValueError('更新包内容异常。')
        for info in infos:
            p=PurePosixPath(info.filename)
            if not info.filename.startswith(prefix) or p.is_absolute() or '..' in p.parts or '\\' in info.filename:raise ValueError('更新包路径无效。')
            if (info.external_attr>>16)&0o170000==0o120000:
                target=z.read(info).decode('utf-8')
                resolved=(stage/'content'/Path(info.filename).parent/target).resolve()
                if not resolved.is_relative_to((stage/'content'/prefix).resolve()):raise ValueError('更新包链接越界。')
        manifest=json.loads(z.read(prefix+'update-manifest.json'))
        if manifest.get('schema')!=1 or manifest.get('version')!=release['version'] or manifest.get('architecture')!=ARCH:raise ValueError('更新包版本或架构不匹配。')
    content=stage/'content';content.mkdir()
    subprocess.run(['/usr/bin/ditto','-x','-k',str(archive),str(content)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    folder=content/prefix
    files=manifest.get('files',{});links=manifest.get('symlinks',{})
    if 'PaperQuick.app/Contents/MacOS/PaperQuick' not in files:raise ValueError('更新包缺少 Mac 主程序。')
    for name,sha in files.items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or hash_file(path)!=sha:raise ValueError('更新包内容校验失败。')
    for name,target in links.items():
        path=folder/name
        if not path.is_symlink() or os.readlink(path)!=target or not path.resolve().is_relative_to(folder.resolve()):raise ValueError('更新包链接校验失败。')
    plan=stage/'plan.json';plan.write_text(json.dumps({'app':str(folder/'PaperQuick.app'),'stage':str(stage),'version':release['version']}),'utf-8')
    return plan


def launch_installer(plan_path):
    plan_path=Path(plan_path).resolve();plan=json.loads(plan_path.read_text('utf-8'))
    target=next((p for p in Path(sys.executable).resolve().parents if p.suffix=='.app'),None)
    source=Path(plan['app']).resolve();stage=plan_path.parent
    if not target or target.name!='PaperQuick.app' or target.is_symlink():raise ValueError('请先将 PaperQuick.app 安装到可写目录再更新。')
    if not source.is_relative_to(stage) or not source.is_dir() or not os.access(target.parent,os.W_OK):raise ValueError('更新暂存已损坏或应用目录不可写；可将应用移至用户 Applications 目录。')
    prepared=target.parent/('.PaperQuick-next-'+uuid.uuid4().hex+'.app')
    backup=target.parent/('.PaperQuick-backup-'+uuid.uuid4().hex+'.app')
    subprocess.run(['/usr/bin/ditto',str(source),str(prepared)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    helper=stage/'after-exit.sh'
    helper.write_text('''#!/bin/sh
set -eu
pid="$1"; target="$2"; prepared="$3"; backup="$4"; receipt="$5"
while kill -0 "$pid" 2>/dev/null; do sleep 1; done
if [ ! -d "$target" ] || [ ! -d "$prepared" ] || [ -e "$backup" ]; then exit 1; fi
if /bin/mv "$target" "$backup"; then
  if /bin/mv "$prepared" "$target"; then printf 'installed\\n' > "$receipt";
  else /bin/mv "$backup" "$target"; printf 'rolled_back\\n' > "$receipt"; exit 1; fi
fi
''','utf-8')
    subprocess.Popen(['/bin/sh',str(helper),str(os.getpid()),str(target),str(prepared),str(backup),str(stage/'result.txt')],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
