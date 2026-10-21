"""Build native macOS .app archives. Does not launch the app or run any tests."""
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from app_version import VERSION


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    if sys.platform!='darwin':raise SystemExit('Build this package on a macOS runner; cross-compiling is not supported.')
    architecture=platform.machine()
    if architecture not in ('arm64','x86_64'):raise SystemExit('Unsupported macOS architecture')
    os.chdir(BASE)
    build=BASE/'build'/('macos-'+architecture);build.mkdir(parents=True,exist_ok=True)
    word=build/'word-integration';word.mkdir(exist_ok=True)
    for name in ('styles','locales'):shutil.copytree(BASE/'word-integration'/name,word/name,dirs_exist_ok=True)
    shutil.copy2(BASE/'word-integration/cite_runner.js',word/'cite_runner.js')
    vendor=word/'vendor';vendor.mkdir(exist_ok=True)
    for path in (BASE/'word-integration/vendor').iterdir():
        if path.is_file() and path.suffix.lower() in ('.js','.json','.txt','') and path.name!='node':shutil.copy2(path,vendor/path.name)
    node=shutil.which('node')
    if not node:raise SystemExit('Node is required to bundle offline citation formatting')
    # Creating a bundle icon is a packaging operation, never a screenshot.
    from PIL import Image
    icon=build/'PaperQuick.icns'
    Image.open(BASE/'assets/app.ico').convert('RGBA').resize((1024,1024)).save(icon,format='ICNS')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--name','PaperQuick',
             '--osx-bundle-identifier','com.paperquick.desktop','--target-architecture',architecture,
             '--icon',str(icon),'--distpath',str(build/'dist'),'--workpath',str(build/'pyinstaller'),'--specpath',str(build),
             '--hidden-import','pypdf','--hidden-import','pypdfium2','--hidden-import','keyring.backends.macOS',
             '--collect-all','pypdfium2','--collect-all','pypdfium2_raw',
             '--add-binary',node+':word-integration/vendor',
             '--add-data',str(word)+':word-integration']
    for name in ('assets','browser-extension','docs','graph_template.html','右键插件安装.html','README.md','RELEASE_NOTES.md'):
        source=BASE/name;destination=name if source.is_dir() else '.'
        command+=['--add-data',str(source)+':'+destination]
    command.append(str(BASE/'macos_entry.py'))
    subprocess.run(command,check=True)
    app=build/'dist/PaperQuick.app'
    plist=app/'Contents/Info.plist'
    values=plistlib.loads(plist.read_bytes());values.update(CFBundleShortVersionString=VERSION,CFBundleVersion=VERSION,
        CFBundleDisplayName='PaperQuick 文献直达',NSHighResolutionCapable=True,LSMinimumSystemVersion='12.0')
    plist.write_bytes(plistlib.dumps(values))
    # Ad-hoc signature only. No Apple Developer certificate/notarization is claimed.
    subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(app)],check=True)
    release=BASE/'release'/('v'+VERSION+'-macos');release.mkdir(parents=True,exist_ok=True)
    name=f'PaperQuick-v{VERSION}-macOS-{architecture}'
    folder=release/name;folder.mkdir(exist_ok=True)
    shutil.copytree(app,folder/'PaperQuick.app',symlinks=True,dirs_exist_ok=True)
    for source,target in [('docs/macos-preview.md','Mac安装说明.md'),('docs/ai-reading.md','AI阅读说明.md')]:shutil.copy2(BASE/source,folder/target)
    metadata={'version':VERSION,'platform':'macos','architecture':architecture,'package':'complete','prerelease':True,
              'tested':False,'notarized':False,'signing':'ad-hoc','build_revision':os.environ.get('GITHUB_SHA','local')}
    (folder/'version.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
    files={};symlinks={}
    for path in sorted(folder.rglob('*')):
        relative=path.relative_to(folder).as_posix()
        if path.is_symlink():symlinks[relative]=os.readlink(path)
        elif path.is_file():files[relative]=sha(path)
    manifest={'schema':1,**metadata,'files':files,'symlinks':symlinks}
    (folder/'update-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    archive=release/(name+'.zip')
    subprocess.run(['/usr/bin/ditto','-c','-k','--keepParent','--norsrc',str(folder),str(archive)],check=True)
    checksum=sha(archive)
    (release/('SHA256SUMS-'+architecture+'.txt')).write_text(checksum+'  '+archive.name+'\n','ascii')
    feed={'schema':1,'version':VERSION,'platform':'macos','architecture':architecture,'prerelease':True,
          'notes':'Mac 试用构建，按用户要求仅打包，未运行应用或功能测试；未 Apple 公证。',
          'package':{'name':archive.name,'url':'https://github.com/J0ey2ou/PaperQuick/releases/download/v'+VERSION+'-macos.1/'+archive.name,'size':archive.stat().st_size,'sha256':checksum}}
    (release/('update-macos-'+architecture+'.json')).write_text(json.dumps(feed,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'archive':str(archive),'sha256':checksum,'architecture':architecture,'tested':False}))


if __name__=='__main__':main()
