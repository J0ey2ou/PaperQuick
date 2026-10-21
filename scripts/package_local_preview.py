"""Build public v3.2 and WeChat packages from an explicit file allowlist.

Run after rebuilding the application and producing the release screenshots.
Use --check to validate inputs without writing either ZIP archive.
"""
from argparse import ArgumentParser
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import zipfile

BASE = Path(__file__).resolve().parents[1]
VERSION = '3.2'
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico'}
ROOT_FILES = (
    '文献直达.exe', '全局选词助手.exe', '打开文献库.bat', 'README.md',
    'CONTRIBUTING.md', 'RELEASE_NOTES.md', '使用说明.md', '本地文献库使用说明.md',
    '右键插件安装.html', '推送文案.html', '推送文案.txt', '推送文案.md',
)
EXTENSION_FILES = (
    'app.ico', 'background.js', 'chat-background.js', 'chat-content.js', 'chat-launch.js', 'ai-sites.js', 'ai-web-content.js', 'engine.js', 'icon128.png', 'icon16.png',
    'icon48.png', 'manifest.json', 'package.json', 'page-reader.js',
    'results.html', 'results.js', 'style.css',
)
VENDOR_FILES = (
    'AGPL-3.0.txt', 'ATTRIBUTION.txt', 'CC-BY-SA-3.0-LEGALCODE.txt',
    'CITEPROC-LICENSE', 'citeproc.js', 'CPAL-1.0.txt', 'CSL-LOCALES-LICENSE',
    'CSL-STYLES-LICENSE', 'manifest.json', 'NODE-LICENSE',
)
REQUIRED_DOCS = ('word-citations.md', 'v3.2-local.md', 'documents-and-attachments.md')
REQUIRED_IMAGES = ('word-citations-preview.png', 'v32-attachments.png',
                   'v32-conversion.png', 'v32-summary.png')
MEDIA_ROOT_FILES = ('推送文案.html', '推送文案.txt', '推送文案.md')


def checked_files(files):
    """Reject private, outside-workspace and unintended executable payloads."""
    checked = {}
    for path in files:
        path = Path(path).resolve()
        if not path.is_relative_to(BASE):
            raise ValueError(f'Outside public source directory: {path}')
        relative = path.relative_to(BASE)
        parts = {part.lower() for part in relative.parts}
        if parts & {'build', '.git', '.codex', '.agents', '本地文献库', 'staging', 'settings.json', 'shortcut.json'}:
            raise ValueError(f'Private file cannot be packaged: {relative}')
        if any(part.endswith('.data') for part in parts) or path.suffix.lower() in {'.pdf', '.doc', '.docx', '.enl', '.sqlite', '.db', '.log', '.pdb'}:
            raise ValueError(f'User document or runtime data cannot be packaged: {relative}')
        if path.suffix.lower() == '.exe' and relative.as_posix() not in {'文献直达.exe', '全局选词助手.exe'}:
            raise ValueError(f'Only application executables belong outside the bundled runtime: {relative}')
        if not path.is_file():
            raise FileNotFoundError(f'Missing public package input: {relative}')
        checked[relative.as_posix()] = path
    return [checked[key] for key in sorted(checked)]


def application_files():
    files = [BASE / name for name in ROOT_FILES]
    files += [BASE / 'browser-extension' / name for name in EXTENSION_FILES]
    files += [BASE / 'docs' / name for name in REQUIRED_DOCS]
    files += list((BASE / 'docs').glob('*.md'))
    files += [BASE / 'docs' / 'images' / name for name in REQUIRED_IMAGES]
    files += [p for p in (BASE / 'docs' / 'images').rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    files += [p for p in (BASE / 'assets').glob('*') if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    # Node and both compiled helpers already live inside the application EXE.
    # Keep accessible licenses, upstream source, styles/locales and attribution.
    files += [BASE / 'word-integration' / 'vendor' / name for name in VENDOR_FILES]
    files += [BASE / 'word-integration' / name for name in ('cite_runner.js', 'WordBridge.cs', 'DocumentConverter.cs')]
    files += list((BASE / 'word-integration' / 'styles').glob('*.csl'))
    files += list((BASE / 'word-integration' / 'locales').glob('*.xml'))
    for optional in ('LICENSE', 'LICENSE.txt', 'LICENSE.md'):
        if (BASE / optional).is_file():
            files.append(BASE / optional)
    return checked_files(files)


class ImageSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'img':
            self.sources += [value for key, value in attrs if key.lower() == 'src' and value]


def media_files():
    files = [BASE / name for name in MEDIA_ROOT_FILES]
    parser = ImageSources()
    parser.feed((BASE / '推送文案.html').read_text('utf-8'))
    markdown = (BASE / '推送文案.md').read_text('utf-8')
    sources = parser.sources + re.findall(r'!\[[^\]]*\]\(([^)]+)\)', markdown)
    for source in sources:
        source = source.strip().strip('<>')
        parsed = urlsplit(source)
        if parsed.scheme in {'data', 'http', 'https'}:
            continue
        if parsed.scheme or parsed.netloc:
            raise ValueError('Unsupported image location in public copy')
        path = (BASE / unquote(parsed.path)).resolve()
        if not (path.is_relative_to(BASE / 'docs' / 'images') or path.is_relative_to(BASE / 'assets')):
            raise ValueError(f'WeChat image must belong to public images/assets: {source}')
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f'Unsupported WeChat image type: {source}')
        files.append(path)
    return checked_files(files)


def write_archive(destination, prefix, files):
    partial = destination.with_suffix('.zip.partial')
    try:
        with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, (Path(prefix) / path.relative_to(BASE)).as_posix())
        with zipfile.ZipFile(partial) as archive:
            failure = archive.testzip()
            if failure:
                raise ValueError(f'Archive verification failed: {failure}')
            expected = {(Path(prefix) / path.relative_to(BASE)).as_posix() for path in files}
            if set(archive.namelist()) != expected:
                raise ValueError('Archive contents differ from the public allowlist')
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate source files only; do not create ZIPs')
    args = parser.parse_args()
    application, media = application_files(), media_files()
    if args.check:
        print(f'Public inputs verified: {len(application)} application files; {len(media)} WeChat files. No archives written.')
        return
    app_zip = BASE / f'PaperQuick-v{VERSION}-Windows.zip'
    media_zip = BASE / 'PaperQuick-WeChat-Materials.zip'
    write_archive(app_zip, f'PaperQuick-v{VERSION}', application)
    write_archive(media_zip, 'PaperQuick-WeChat-Materials', media)
    print(f'Created {app_zip.name} ({len(application)} public files)')
    print(f'Created {media_zip.name} ({len(media)} public files)')
    print('Personal libraries, documents, settings, build files and logs are excluded.')


if __name__ == '__main__':
    main()
