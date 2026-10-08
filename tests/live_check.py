"""真实接口检查；默认不运行，不保存用户查询或邮箱。"""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_finder import find_papers, LookupError

queries = [
    "10.1038/s41586-021-03819-2",
    "Attention Is All You Need",
    "https://arxiv.org/abs/1706.03762",
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC8371605/",
]
results = []
for query in queries:
    started = time.monotonic()
    try:
        result = find_papers(query)
        summary = {"input": query, "seconds": round(time.monotonic() - started, 1), "papers": [{"title": p.title, "doi": p.doi, "match": p.match, "links": [{"kind": x.kind, "url": x.url, "source": x.source} for x in p.links]} for p in result.papers], "notes": result.notes}
        if query.startswith("10."):
            assert result.papers[0].doi == query
            assert "AlphaFold" in result.papers[0].title
            assert any(link.kind in ("pdf", "fulltext") for link in result.papers[0].links)
        elif "Attention" in query or "arxiv.org" in query:
            assert any("Attention Is All You Need" in p.title for p in result.papers)
            assert any("arxiv.org/pdf/1706.03762" in link.url for p in result.papers for link in p.links)
        else:
            assert result.papers[0].doi == "10.1038/s41586-021-03819-2"
        summary["passed"] = True
    except (LookupError, AssertionError) as exc:
        summary = {"input": query, "error": str(exc), "passed": False}
    results.append(summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
Path("live-check.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(0 if all(x["passed"] for x in results) else 1)
