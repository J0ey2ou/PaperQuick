"""Atomic local preferences; keep unknown keys during upgrades."""
import json
import os
from pathlib import Path
import tempfile


def load_preferences(path):
    try:
        result=json.loads(Path(path).read_text('utf-8-sig'))
        return result if isinstance(result,dict) else {}
    except (OSError,ValueError):return {}


def save_preferences(path,changes):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    values=load_preferences(path);values.update(changes)
    fd,temporary=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(values,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return values
