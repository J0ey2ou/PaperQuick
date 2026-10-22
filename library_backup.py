"""Consistent library snapshots and strictly validated, non-destructive restores."""
from pathlib import Path, PurePosixPath
from contextlib import closing
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile

MANIFEST = 'backup-manifest.json'
EXCLUDED_DIRS = frozenset(('cache', 'staging', '.updates', '.tasks', '__pycache__'))
EXCLUDED_FILES = frozenset(('library.sqlite-wal', 'library.sqlite-shm', 'library.sqlite-journal',
                            '.paperquick-tasks.json', 'collection-graph.html'))
CHUNK = 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 ** 3


def _load_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('清单包含重复的 JSON 字段。')
            result[key] = value
        return result
    def invalid_number(value):
        raise ValueError('清单包含无效的数值：' + value)
    return json.loads(content, object_pairs_hook=pairs, parse_constant=invalid_number)


def _check_space(directory, size):
    if size + 16 * 1024 * 1024 > shutil.disk_usage(directory).free:
        raise ValueError('目标磁盘空间不足，请选择有足够空间的位置。')


def _check(context):
    if context is not None:
        context.check_cancelled()


def _report(context, done, total, message):
    if context is not None:
        context.progress(done, total, message)


def _safe_name(name):
    """One canonical portable path; reject Windows aliases even on other systems."""
    if not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name or '\x00' in name:
        raise ValueError('备份包含不安全的文件路径。')
    parts = name.split('/')
    if any(not part or part in ('.', '..') or part[-1:] in (' ', '.') or
           any(ord(char) < 32 or char in '<>:"|?*' for char in part) or
           re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)
           for part in parts):
        raise ValueError(f'备份路径不合法：{name}')
    return PurePosixPath(*parts).as_posix()


def _regular(path):
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not path.is_symlink() and not (
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _inventory(root):
    files = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        base = Path(directory)
        kept = []
        for name in directories:
            child = base / name
            relative = child.relative_to(root)
            if relative.parts[0] in EXCLUDED_DIRS:
                continue
            info = child.lstat()
            if child.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                raise ValueError(f'文献库包含链接目录，无法安全备份：{relative}')
            kept.append(name)
        directories[:] = kept
        for name in names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative == 'library.sqlite' or relative in EXCLUDED_FILES or relative.startswith('.paperquick-tasks.json.'):
                continue
            _safe_name(relative)
            if relative == MANIFEST or not _regular(path):
                raise ValueError(f'文献库包含无法备份的文件：{relative}')
            info = path.stat()
            files[relative] = (info.st_size, info.st_mtime_ns)
    return files


def _attachments(db, existing):
    missing = []
    existing = {name.casefold() for name in existing}
    columns = {row[1] for row in db.execute('PRAGMA table_info(attachments)')}
    if not {'id', 'path'}.issubset(columns):
        raise ValueError('备份不是有效的文献库：缺少附件信息。')
    query = 'SELECT id,path' + (',kind' if 'kind' in columns else ",''") + ' FROM attachments'
    for attachment_id, relative, kind in db.execute(query):
        if kind == 'link' or not relative:
            continue
        relative = _safe_name(str(relative).replace('\\', '/'))
        if relative.casefold() not in existing:
            missing.append({'id': str(attachment_id), 'path': relative, 'reason': '附件文件缺失'})
    return missing


def _verify_database(path, existing):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('文献库数据库完整性检查失败。')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'papers', 'projects', 'attachments'}.issubset(tables):
            raise ValueError('备份中缺少文献库数据表。')
        return _attachments(db, existing)


def create_backup(directory, output, context=None):
    root, output = Path(directory).resolve(), Path(output).resolve()
    if not (root / 'library.sqlite').is_file():
        raise ValueError('请选择包含 library.sqlite 的文献库。')
    if not output.parent.is_dir() or output.exists() or output.is_relative_to(root):
        raise ValueError('请将备份保存到文献库之外的新 ZIP 文件，不能覆盖已有文件。')
    _check(context)
    files = _inventory(root)
    with tempfile.TemporaryDirectory(prefix='.paperquick-backup-', dir=output.parent) as temporary:
        stage = Path(temporary)
        snapshot = stage / 'library.sqlite'
        source = sqlite3.connect((root / 'library.sqlite').as_uri() + '?mode=ro', uri=True, timeout=30)
        try:
            version = source.execute('PRAGMA data_version').fetchone()[0]
            _report(context, 0, max(len(files), 1), '正在创建数据库一致性快照')
            destination = sqlite3.connect(snapshot)
            try:
                source.backup(destination, pages=256, progress=lambda *_: _check(context), sleep=.05)
            finally:
                destination.close()
            missing = _verify_database(snapshot, set(files))
            entries = []
            total = sum(size for size, _ in files.values()) + snapshot.stat().st_size
            done = 0
            archive = stage / 'snapshot.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
                for relative in ['library.sqlite', *sorted(files)]:
                    _check(context)
                    path = snapshot if relative == 'library.sqlite' else root / relative
                    if not _regular(path) or not path.resolve().is_relative_to(stage if relative == 'library.sqlite' else root):
                        raise ValueError(f'文件位置发生变化，请重新备份：{relative}')
                    before = path.stat()
                    digest, size = hashlib.sha256(), 0
                    with path.open('rb') as stream, bundle.open(relative, 'w', force_zip64=True) as target:
                        while chunk := stream.read(CHUNK):
                            _check(context)
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                            done += len(chunk)
                            _report(context, done, total, f'正在备份：{relative}')
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != before.st_size:
                        raise RuntimeError(f'文件在备份时发生变化，请重试：{relative}')
                    entries.append(dict(path=relative, size=size, sha256=digest.hexdigest()))
                if _inventory(root) != files or source.execute('PRAGMA data_version').fetchone()[0] != version:
                    raise RuntimeError('文献库在备份时发生变化，本次备份未发布，请稍后重试。')
                manifest = dict(schema=1, type='PaperQuickLibraryBackup', created=time.time(), files=entries,
                                missing_attachments=missing, excluded=sorted(EXCLUDED_DIRS | EXCLUDED_FILES))
                bundle.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
            _check(context)
            # Windows rename is atomic on the same volume and refuses overwrite.
            # Elsewhere, a hard link gives the same no-overwrite guarantee.
            if os.name == 'nt':
                os.rename(archive, output)
            else:
                os.link(archive, output)
            return dict(path=str(output), files=len(entries), missing_attachments=missing,
                        warnings=[f"{item['path']}：附件缺失" for item in missing])
        finally:
            source.close()


def _read_manifest(bundle, max_total_bytes, expected_type='PaperQuickLibraryBackup',
                   required_files=('library.sqlite',), manifest_name=MANIFEST):
    infos = bundle.infolist()
    if len(infos) > 250001:
        raise ValueError('备份文件数量超过安全上限。')
    by_name, folded = {}, set()
    for info in infos:
        name = _safe_name(info.filename)
        if info.orig_filename != info.filename or name.casefold() in folded or info.is_dir() or info.flag_bits & 1 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
            raise ValueError('备份包含重复路径、链接或不支持的条目。')
        folded.add(name.casefold())
        by_name[name] = info
    if manifest_name not in by_name or by_name[manifest_name].file_size > 16 * 1024 * 1024:
        raise ValueError('备份清单缺失或过大。')
    manifest = _load_json(bundle.read(manifest_name))
    if not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1 or manifest.get('type') != expected_type or not isinstance(manifest.get('files'), list):
        raise ValueError('备份格式无法识别。')
    expected, size = {}, 0
    for entry in manifest['files']:
        if not isinstance(entry, dict):
            raise ValueError('备份清单文件条目必须为对象。')
        name = _safe_name(entry.get('path'))
        if name == manifest_name or name in expected or type(entry.get('size')) is not int or entry['size'] < 0 or not re.fullmatch('[a-fA-F0-9]{64}', str(entry.get('sha256', ''))):
            raise ValueError('备份清单的文件信息无效。')
        info = by_name.get(name)
        if info is None or info.file_size != entry['size']:
            raise ValueError(f'备份文件缺失或大小不符：{name}')
        expected[name] = entry
        size += entry['size']
        if size > max_total_bytes:
            raise ValueError('备份解压后大小超过安全上限。')
    if set(by_name) != set(expected) | {manifest_name} or not set(required_files).issubset(expected):
        raise ValueError('备份内容与清单不一致。')
    for name in expected:
        if any(parent.as_posix().casefold() in folded for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
            raise ValueError('备份包含冲突的文件与目录路径。')
    return manifest, expected, size


def restore_backup(archive, destination, context=None, max_total_bytes=MAX_TOTAL_BYTES):
    archive, destination = Path(archive).resolve(), Path(destination).resolve()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('恢复目标必须是尚不存在的新文件夹，现有文献库不会被覆盖。')
    _check(context)
    with zipfile.ZipFile(archive) as bundle:
        manifest, entries, total = _read_manifest(bundle, max_total_bytes)
        _check_space(destination.parent, total)
        with tempfile.TemporaryDirectory(prefix='.paperquick-restore-', dir=destination.parent) as temporary:
            stage = Path(temporary) / 'library'
            stage.mkdir()
            done = 0
            for relative, entry in entries.items():
                _check(context)
                target = stage.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with bundle.open(relative) as stream, target.open('xb') as output:
                    while chunk := stream.read(CHUNK):
                        _check(context)
                        size += len(chunk)
                        if size > entry['size']:
                            raise ValueError(f'备份文件超过声明大小：{relative}')
                        digest.update(chunk)
                        output.write(chunk)
                        done += len(chunk)
                        _report(context, done, total, f'正在恢复：{relative}')
                if size != entry['size'] or digest.hexdigest() != entry['sha256'].lower():
                    raise ValueError(f'备份文件校验失败：{relative}')
            missing = _verify_database(stage / 'library.sqlite', set(entries))
            declared_items = manifest.get('missing_attachments', [])
            if not isinstance(declared_items, list) or not all(isinstance(item, dict) and isinstance(item.get('id'), str) and isinstance(item.get('path'), str) for item in declared_items):
                raise ValueError('缺失附件清单格式不正确。')
            declared = {(item['id'], item['path']) for item in declared_items}
            if {(item['id'], item['path']) for item in missing} != declared:
                raise ValueError('备份附件不完整，且与清单中的缺失附件记录不一致。')
            _check(context)
            if destination.exists():
                raise FileExistsError('恢复目标已存在，请选择新的文件夹。')
            os.rename(stage, destination)  # On Windows rename refuses an existing destination.
            return dict(path=str(destination), files=len(entries), missing_attachments=missing,
                        warnings=[f"{item['path']}：原备份中附件缺失" for item in missing])
