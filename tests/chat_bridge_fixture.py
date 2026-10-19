"""Disposable backend for the no-window MV3 integration check; no user library."""
import hashlib,json,sys,tempfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'tests'),str(BASE/'build/vendor')]
from chat_bridge import ChatBridge
from library_core import Library
from test_reader import text_pdf
from PIL import Image

folder=BASE/'build/chat-integration';folder.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=folder) as temporary:
    root=Path(temporary);assert root.resolve().is_relative_to(folder.resolve())
    source=root/'fixture-paper.pdf';text_pdf(source)
    lib=Library(root/'store');rid=lib.import_pdf(source);other=lib.save({'title':'Other paper'})
    bridge=ChatBridge(lib.root)
    token=None
    try:
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('stop'):break
            if request.get('status'):
                print(json.dumps(bridge.status(token)),flush=True);continue
            quote=request.get('quote','Selected passage from the local fixture paper.')
            url=bridge.prepare(rid,quote=quote,image=Image.new('RGB',(36,24),'red') if request.get('image') else None)
            token=url.split('#paperquick=')[1].split('.',1)[1]
            files=bridge.payload(token)['files']
            print(json.dumps({'url':bridge.open_url(url) if request.get('local') else url,'files':files,'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                              'prompt':bridge.payload(token)['prompt']},ensure_ascii=True),flush=True)
    finally:bridge.close();lib.close()
