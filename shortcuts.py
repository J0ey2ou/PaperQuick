"""Shared shortcut validation and persistence for the desktop UI."""
import json
from pathlib import Path
import re

DEFAULT_SHORTCUT = "Ctrl + Alt + F"
MODIFIERS = {"Ctrl": 2, "Alt": 1, "Shift": 4}


def parse_shortcut(value):
    parts = [part.strip() for part in str(value).split("+")]
    if len(parts) < 3 or len(parts) > 4:
        raise ValueError("请使用至少两个修饰键，例如 Ctrl + Alt + J。")
    modifiers, key = parts[:-1], parts[-1].upper()
    if len(set(modifiers)) != len(modifiers) or any(x not in MODIFIERS for x in modifiers):
        raise ValueError("修饰键只能使用 Ctrl、Alt、Shift，且不能重复。")
    if re.fullmatch(r"[A-Z0-9]", key):
        code = ord(key)
    elif re.fullmatch(r"F(?:[1-9]|1[0-9]|2[0-4])", key):
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("主键请选择字母、数字或 F1–F24。")
    canonical = " + ".join([x for x in MODIFIERS if x in modifiers] + [key])
    return canonical, sum(MODIFIERS[x] for x in modifiers), code


def load_shortcut(directory):
    try:
        return parse_shortcut(json.loads((Path(directory) / "shortcut.json").read_text("utf-8-sig"))["shortcut"])[0]
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SHORTCUT


def save_shortcut(directory, value):
    canonical, _, _ = parse_shortcut(value)
    path = Path(directory) / "shortcut.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"shortcut": canonical}, ensure_ascii=False, indent=2), "utf-8")
    temp.replace(path)
    return canonical
