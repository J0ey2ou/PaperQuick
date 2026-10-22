"""Export selected topic documents without changing the library or existing outputs."""
from dataclasses import dataclass
from pathlib import Path
import csv
import io
import json
import shutil
import zipfile

from library_core import attachment_kind, clean_name, display_name


class PackageCancelled(Exception):
    pass


@dataclass(frozen=True)
class PackageFile:
    id: str
    path: str
    name: str
    size: int
    state: str
    role: str
    url: str = ''


@dataclass(frozen=True)
class PackagePaper:
    id: str
    title: str
    metadata: dict
    files: tuple


@dataclass(frozen=True)
class PackagePlan:
    root: Path
    name: str
    papers: tuple


def _source(root, relative):
    path = Path(relative)
    if path.is_absolute() or not relative:
        raise ValueError('附件路径必须位于文献库内。')
    source = (root / path).resolve()
    if not source.is_relative_to(root):
        raise ValueError('附件路径超出了文献库。')
    return source


def prepare_package(library, project=None):
    """A summary-only snapshot includes descendants, regardless of UI filters."""
    root = library.root.resolve()
    name = library.project(project)['name'] if project else '全部文献'
    projects = {p['id']: p['name'] for p in library.projects()}
    papers = []
    for record in library.records(project, summary=True):
        files = []
        for index, attachment in enumerate(record['attachments']):
            relative = attachment.get('path') or ''
            kind = attachment_kind(attachment)
            state, size = '链接', 0
            if kind != 'link':
                try:
                    source = _source(root, relative)
                    size = source.stat().st_size
                    state = '可打包' if source.is_file() else '文件缺失'
                except ValueError:
                    state = '路径异常'
                except OSError:
                    state = '文件缺失'
            files.append(PackageFile(str(attachment.get('id') or index), relative,
                                     Path(relative or attachment.get('original') or '').name or attachment.get('label') or '链接附件',
                                     size, state, attachment.get('role', 'supplement'), attachment.get('url', '')))
        metadata = {key: record.get(key, '') for key in ('title', 'authors', 'year', 'doi', 'venue', 'tags', 'status', 'rating')}
        metadata['projects'] = [projects.get(pid, '') for pid in record['projects']]
        papers.append(PackagePaper(record['id'], display_name(record), metadata, tuple(files)))
    return PackagePlan(root, name, tuple(papers))


def export_package(plan, selection, directory, name, format='zip', progress=None, cancel=None):
    """selection maps included paper IDs to included local attachment IDs.

    Missing files and links remain visible in the inventory. Newly disappearing
    files fail the operation; only output created by this call is cleaned up.
    """
    if format not in ('zip', 'folder'):
        raise ValueError('请选择 ZIP 压缩包或文件夹。')
    selected = [p for p in plan.papers if p.id in selection]
    if not selected:
        raise ValueError('请至少勾选一篇文献。')
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError('请选择已存在的保存文件夹。')
    if directory.is_relative_to(plan.root):
        raise ValueError('请选择文献库之外的保存位置，避免重复归档。')
    name = clean_name(name.strip(), 64)
    suffix = '.zip' if format == 'zip' else ''
    if format == 'zip' and name.lower().endswith('.zip'):
        name = name[:-4] or '课题文献'
    tasks, inventory = [], []
    unavailable = 0
    for number, paper in enumerate(selected, 1):
        folder = f'{number:03d}_{clean_name(paper.title, 48)}'
        item = dict(id=paper.id, display_name=paper.title, **paper.metadata, files=[])
        for index, attachment in enumerate(paper.files, 1):
            included = attachment.id in selection[paper.id] and attachment.state == '可打包'
            extension = '.' + clean_name(Path(attachment.name).suffix[1:], 12) if Path(attachment.name).suffix else ''
            relative = f'{folder}/{index:02d}_{clean_name(Path(attachment.name).stem, 64)}{extension}'
            entry = dict(name=attachment.name, state='已打包' if included else ('未勾选' if attachment.state == '可打包' else attachment.state),
                         path=relative if included else '', url=attachment.url)
            item['files'].append(entry)
            if attachment.state in ('文件缺失', '路径异常'):
                unavailable += 1
            if included:
                tasks.append((attachment, relative))
        inventory.append(item)
    total = sum(a.size for a, _ in tasks)
    completed = 0
    output = None
    archive = None

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise PackageCancelled('已取消打包。')

    def report():
        if progress:
            progress(completed, total)

    try:
        check_cancel()
        # Exclusive creation preserves existing files even if another exporter
        # picks the same name between the existence check and creation.
        for attempt in range(10000):
            candidate = directory / f'{name}{" (" + str(attempt + 1) + ")" if attempt else ""}{suffix}'
            try:
                if format == 'zip':
                    archive = zipfile.ZipFile(candidate, 'x', compression=zipfile.ZIP_DEFLATED, allowZip64=True)
                else:
                    candidate.mkdir()
                output = candidate
                break
            except FileExistsError:
                output = None
        if output is None:
            raise ValueError('保存位置中有过多同名文件，请修改打包名称。')

        def write_text(relative, content, encoding='utf-8'):
            if archive is not None:
                archive.writestr(f'{name}/{relative}', content.encode(encoding))
            else:
                target = output / relative
                target.write_bytes(content.encode(encoding))

        report()
        for attachment, relative in tasks:
            check_cancel()
            source = _source(plan.root, attachment.path)
            if not source.is_file():
                raise FileNotFoundError(f'附件已不存在，请重新打开打包窗口：{attachment.name}')
            with source.open('rb') as stream:
                if archive is not None:
                    destination = archive.open(f'{name}/{relative}', 'w', force_zip64=True)
                else:
                    target = output / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    destination = target.open('xb')
                with destination:
                    while True:
                        check_cancel()
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)
                        completed += len(chunk)
                        report()
        check_cancel()
        write_text('打包清单.json', json.dumps(dict(schema=1, topic=plan.name, papers=inventory), ensure_ascii=False, indent=2))
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['文献', '作者', '年份', 'DOI', '课题', '已打包文件', '缺失或异常文件', '链接附件'])
        def cell(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for paper in inventory:
            writer.writerow([cell(value) for value in [paper['display_name'], paper['authors'], paper['year'], paper['doi'],
                             '；'.join(paper['projects']), sum(f['state'] == '已打包' for f in paper['files']),
                             sum(f['state'] in ('文件缺失', '路径异常') for f in paper['files']),
                             '；'.join(f['url'] for f in paper['files'] if f['url'])]])
        write_text('文献目录.csv', buffer.getvalue(), 'utf-8-sig')
        write_text('打包说明.txt', '按文献分别存放正文和补充附件。\n文献目录.csv 和打包清单.json 记录所选文献、文件及链接。\n链接只保存地址，不自动下载；缺失文件会在清单中标出。\n此包用于文件分享，不是完整文献库备份。\n')
        if archive is not None:
            archive.close()
            archive = None
        return dict(path=output, papers=len(selected), files=len(tasks), unavailable=unavailable)
    except BaseException:
        if archive is not None:
            archive.close()
        if output is not None:
            if format == 'zip':
                output.unlink(missing_ok=True)
            else:
                shutil.rmtree(output)
        raise
