"""Atomic local preferences; keep unknown keys during upgrades."""
import json
import os
from pathlib import Path
import tempfile
import uuid


class PreferenceValues(dict):
    """A normal preference mapping with a startup recovery notice."""
    def __init__(self, values=(), warning='', recovered=False, error=None):
        super().__init__(values)
        self.warning=warning;self.recovered=recovered;self.error=error


def _read_preferences(path):
    result=json.loads(path.read_text('utf-8-sig'))
    if not isinstance(result,dict):raise ValueError('设置文件必须是对象。')
    return result


def load_preferences(path):
    path=Path(path)
    try:
        return PreferenceValues(_read_preferences(path))
    except (OSError,ValueError) as error:
        backup=path.with_name(path.name+'.bak')
        try:
            return PreferenceValues(_read_preferences(backup),
                warning='设置文件无法读取，已恢复上一次有效设置；原文件保留。',recovered=True,error=error)
        except (OSError,ValueError):
            if isinstance(error,FileNotFoundError):return PreferenceValues()
            return PreferenceValues(warning='设置文件无法读取且没有有效备份；原文件已保留，请恢复设置后再保存。当前使用默认设置。',error=error)


def save_preferences(path,changes):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    values=load_preferences(path)
    if values.error and not values.recovered:
        raise OSError('设置文件无法读取，已保留原文件以供恢复，未覆盖。') from values.error
    if values.recovered and path.exists():
        # Preserve malformed content before healing it from a valid backup.
        damaged=path.with_name(path.name+'.corrupt-'+uuid.uuid4().hex)
        with damaged.open('xb') as stream:stream.write(path.read_bytes())
    elif path.exists():
        _atomic_preferences(path.with_name(path.name+'.bak'),values)
    values.update(changes)
    if not path.exists() and not values.recovered:
        _atomic_preferences(path.with_name(path.name+'.bak'),values)
    _atomic_preferences(path,values)
    return PreferenceValues(values)


def _atomic_preferences(path,values):
    fd,temporary=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(values,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
