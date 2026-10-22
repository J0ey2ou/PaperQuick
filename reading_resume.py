"""Per-attachment reading positions stored with the local library configuration."""
from pathlib import Path
import math
import time
from library_core import Library


def number(value, default, minimum, maximum):
    try:value = float(value)
    except (TypeError, ValueError):return default
    return max(minimum, min(maximum, value)) if math.isfinite(value) else default


class ReadingResumeStore:
    def __init__(self, directory):self.directory = Path(directory)

    @staticmethod
    def normalize(value):
        if not isinstance(value, dict):return None
        if not value.get('paper') or not value.get('attachment'):return None
        return dict(paper=str(value['paper']), attachment=str(value['attachment']),
                    page=int(number(value.get('page'), 0, 0, 1000000)),
                    fraction=number(value.get('fraction'), 0, 0, 1),
                    x_fraction=number(value.get('x_fraction'), 0, 0, 1),
                    scale=number(value.get('scale'), 1.2, .3, 3),
                    continuous=bool(value.get('continuous', True)),
                    notes_visible=bool(value.get('notes_visible', True)),
                    split=number(value.get('split'), .75, .15, .9),
                    logical=bool(value.get('logical', False)),
                    paragraph=int(number(value.get('paragraph'), 0, 0, 10000000)),
                    updated=number(value.get('updated'), 0, 0, float('inf')))

    def save(self, paper, attachment, **position):
        value = self.normalize(dict(position, paper=paper, attachment=attachment, updated=time.time()))
        lib = Library(self.directory)
        try:
            record = lib.get(paper)
            if attachment not in {item['id'] for item in record['attachments']}:return None
            lib.set_setting('reading-position:' + attachment, value)
            lib.set_setting('reading-last', dict(paper=paper, attachment=attachment))
            lib.set_setting('reading-paper-last:' + paper, attachment)
            return value
        finally:lib.close()

    def get(self, attachment):
        if not isinstance(attachment, str) or not attachment:return None
        lib = Library(self.directory)
        try:
            value = self.normalize(lib.setting('reading-position:' + attachment, None))
            if not value:return None
            try:record = lib.get(value['paper'])
            except ValueError:return None
            if value['attachment'] not in {item['id'] for item in record['attachments']}:return None
            return value
        finally:lib.close()

    def last(self):
        lib = Library(self.directory)
        try:last = lib.setting('reading-last', None)
        finally:lib.close()
        return self.get(last['attachment']) if isinstance(last, dict) and last.get('attachment') else None

    def for_paper(self, paper):
        lib = Library(self.directory)
        try:attachment = lib.setting('reading-paper-last:' + paper, None)
        finally:lib.close()
        value = self.get(attachment) if isinstance(attachment, str) else None
        return value if value and value['paper'] == paper else None

    def clear(self, attachment):
        lib = Library(self.directory)
        try:
            with lib.db:
                lib.db.execute('DELETE FROM config WHERE key=?', ('reading-position:' + attachment,))
                last = lib.setting('reading-last', {})
                if isinstance(last, dict) and last.get('attachment') == attachment:
                    lib.db.execute("DELETE FROM config WHERE key='reading-last'")
        finally:lib.close()
