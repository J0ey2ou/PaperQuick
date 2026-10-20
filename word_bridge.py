"""Small, local Word COM transport. No document is saved by this module."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class WordBridgeError(RuntimeError):
    pass


def bridge_path():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'word-integration' / 'WordBridge.exe'


def _call(request, timeout=90, executable=None):
    if os.name != 'nt':
        raise WordBridgeError('Word 引用目前支持 Windows 桌面版 Microsoft Word。')
    executable = Path(executable or bridge_path())
    if not executable.is_file():
        raise WordBridgeError('Word 引用组件尚未安装，请使用完整的软件安装包。')
    with tempfile.TemporaryDirectory(prefix='PaperQuickWord-') as directory:
        request_path = Path(directory) / 'request.json'
        response_path = Path(directory) / 'response.json'
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        try:
            result = subprocess.run([str(executable), str(request_path), str(response_path)],
                                    capture_output=True, timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise WordBridgeError('Word 暂时没有响应。请先检查文档中的引用是否已经插入；如果已经插入，请使用“更新全部引用”，不要重复插入。关闭 Word 中的对话框后再操作。') from exc
        except OSError as exc:
            raise WordBridgeError('无法启动 Word 引用组件，请重新打开软件。') from exc
        if not response_path.is_file():
            raise WordBridgeError('Word 未完成操作。请检查 Word 是否正在等待确认，再重试。')
        try:
            data = json.loads(response_path.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError) as exc:
            raise WordBridgeError('Word 的返回信息不完整，请检查文档后重试。') from exc
        if not isinstance(data, dict):
            raise WordBridgeError('Word 的返回信息不完整，请检查文档后重试。')
        if not data.get('ok'):
            raise WordBridgeError(data.get('error') or 'Word 未完成操作，请稍后重试。')
        if not isinstance(data.get('result'), dict):
            raise WordBridgeError('Word 的返回信息不完整，请检查文档后重试。')
        return data['result']


def snapshot():
    """Read only the active Word document, including PaperQuick field metadata."""
    return _call({'action': 'snapshot'})


def apply(snapshot, operations):
    """Apply one undoable batch after checking document, cursor and content.

    operations: insert={kind,payload,result_rtf}; updates=[{id,payload,result_rtf}];
    remove=[field_id]. Result is a fresh snapshot. Insertion requires a collapsed
    cursor outside any existing field; only main document text is supported.
    """
    if operations.get('append_bibliography') and 'append_bibliography' not in snapshot.get('capabilities', []):
        raise WordBridgeError('Word 引用组件版本较旧，请更新完整安装包后重新连接 Word，以同步生成文末参考文献表。')
    return _call({'action': 'apply', 'snapshot': snapshot, 'operations': operations})


def health():
    return _call({'action': 'health'})


def isolated_selftest(timeout=150, batches=None):
    """Create and close a dedicated, unsaved Word test document; never attach."""
    request = {'action': 'selftest'}
    if batches is not None:
        request['batches'] = batches
    return _call(request, timeout=timeout)
