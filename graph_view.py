"""Self-contained offline interactive graph; no CDN, API or AI."""
import json
from pathlib import Path

def write_graph(library, project=None, destination=None):
    destination = Path(destination or library.root / 'collection-graph.html')
    template = (Path(__file__).parent / 'graph_template.html').read_text('utf-8')
    from graph_style import DEFAULT,validate_style
    payload=library.graph(project);payload['highlight']=validate_style(library.setting('graph_style',DEFAULT))
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    destination.write_text(template.replace('__DATA__', data), 'utf-8')
    return destination
