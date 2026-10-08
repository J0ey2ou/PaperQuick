"""Measure public example queries; no clipboard or user browser access."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_finder import find_papers, automatic_target

report = []
for query in ['10.1038/s41586-021-03819-2', 'Highly accurate protein structure prediction with AlphaFold', 'arXiv:1706.03762']:
    start = time.monotonic()
    first = []
    opened = []

    def partial(result):
        elapsed = round(time.monotonic() - start, 3)
        if not first:
            first.append(elapsed)
        if not opened and automatic_target(result):
            opened.append(elapsed)

    try:
        result = find_papers(query, on_result=partial)
        row = dict(query=query, first_link_seconds=first[0] if first else None,
                   automatic_open_ready_seconds=opened[0] if opened else None,
                   total_seconds=round(time.monotonic() - start, 3),
                   title=result.papers[0].title, papers=len(result.papers), notes=result.notes)
    except Exception as exc:
        row = dict(query=query, error=str(exc), total_seconds=round(time.monotonic() - start, 3))
    report.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
Path('speed-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
