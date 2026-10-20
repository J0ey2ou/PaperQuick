"""Render optional metadata fields without placeholder words or orphan separators."""
import re
import string

MISSING = {'unknown', 'untitled', 'none', 'n/a', '未知作者', '未知年份', '未知期刊', '无doi', '未命名'}


def optional_name(template, values, fallback='未命名文献'):
    parts = list(string.Formatter().parse(template))
    output = []; previous_missing = False
    for literal, field, _, _ in parts:
        if field is None:
            if not previous_missing:
                output.append(literal)
            continue
        value = str(values.get(field) or '').strip()
        if not value or value.casefold() in MISSING:
            previous_missing = True
            continue
        if previous_missing:
            literal = literal.lstrip(')]）】')
            literal = re.sub(r'^[^\W_]+', '', literal)
        if not output:
            literal = literal.lstrip(' _-–—·,，;；:：/\\()（）[]【】')
        output.extend((literal, value)); previous_missing = False
    result = ''.join(output)
    # Remove an opening bracket whose optional value was omitted at the end.
    for left, right in [('(', ')'), ('（', '）'), ('[', ']'), ('【', '】')]:
        if result.count(left) > result.count(right):
            result = result.rstrip(' _-–—·,，;；:：' + left)
    return result.strip(' _-–—·,，;；') or fallback
