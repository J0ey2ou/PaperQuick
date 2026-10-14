"""Source-preserving Word export and local PDF-to-DOCX conversion."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from xml.sax.saxutils import escape
import zipfile


class DocumentConversionError(RuntimeError):
    pass


WORD_SUFFIXES = {'.doc', '.docx'}


def converter_path():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'word-integration' / 'DocumentConverter.exe'


def can_convert(source, output_suffix):
    suffix = str(output_suffix).lower()
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    source_suffix = Path(source).suffix.lower()
    return (source_suffix in WORD_SUFFIXES and suffix == '.pdf') or (source_suffix == '.pdf' and suffix == '.docx')


def conversion_notice(source, output_suffix, mode='text'):
    if Path(source).suffix.lower() == '.pdf':
        if mode == 'appearance':
            return '将每页 PDF 作为图片放入 Word，方便保持页面外观和逐页比对。页面内文字不能直接编辑；原 PDF 会保留。不需要安装 Word。'
        return '提取 PDF 文字生成可编辑的 Word 文档。图表、公式和复杂排版不会完整还原；没有文字的页面会保留为图片。扫描件请选“保留页面外观”。原 PDF 会保留，不需要安装 Word。'
    return '通过本机 Microsoft Word 生成 PDF，原 Word 文件会保留。首次转换可能需要稍等片刻。'


def _timeout(value):
    try:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise DocumentConversionError('转换等待时间必须是正数。') from exc
    return max(1., min(value, 1800.))


def _call(request, timeout=120):
    if os.name != 'nt':
        raise DocumentConversionError('Word 导入与转 PDF 需要 Windows 桌面版 Microsoft Word；PDF 转 Word 可直接使用。')
    executable = converter_path()
    if not executable.is_file():
        raise DocumentConversionError('文档转换组件不完整，请使用完整的软件安装包。')
    timeout = _timeout(timeout)
    request = dict(request, timeout_seconds=timeout)
    with tempfile.TemporaryDirectory(prefix='PaperQuickConvert-') as directory:
        request_path = Path(directory) / 'request.json'
        response_path = Path(directory) / 'response.json'
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        try:
            subprocess.run([str(executable), str(request_path), str(response_path)],
                           capture_output=True, timeout=timeout + 15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError('转换等待时间较长，已停止本次转换。请稍后重试，或先用 Word 检查文件是否能正常打开。') from exc
        except OSError as exc:
            raise DocumentConversionError('无法启动文档转换，请重新打开软件后重试。') from exc
        try:
            data = json.loads(response_path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError) as exc:
            raise DocumentConversionError('转换未完成，请用 Microsoft Word 检查文件是否能正常打开。') from exc
        if not data.get('ok'):
            error = DocumentConversionError(data.get('error') or '转换未完成，请检查文件后重试。')
            error.detail = data.get('detail', '')
            raise error
        result = data.get('result')
        if not isinstance(result, dict):
            raise DocumentConversionError('转换结果不完整，请重试。')
        return result


def health():
    """Check installation without opening Word or touching any document."""
    if os.name != 'nt':
        return {'installed': False, 'helper': converter_path().is_file(), 'message': '需要 Windows 桌面版 Microsoft Word。'}
    if not converter_path().is_file():
        return {'installed': False, 'helper': False, 'message': '文档转换组件不完整。'}
    result = _call({'action': 'health'}, timeout=10)
    result['helper'] = True
    return result


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _valid_result(path):
    path = Path(path)
    try:
        if path.suffix.lower() == '.pdf':
            from pypdf import PdfReader
            with path.open('rb') as stream:
                if not stream.read(1024).lstrip().startswith(b'%PDF-'):
                    return False
                stream.seek(0)
                return len(PdfReader(stream, strict=False).pages) > 0
        with zipfile.ZipFile(path) as archive:
            return {'[Content_Types].xml', 'word/document.xml'}.issubset(archive.namelist()) and archive.testzip() is None
    except Exception:
        return False


def _publish_exclusive(staged, destination):
    # On Windows rename is atomic and refuses replacement. Hard linking provides
    # the same no-replace guarantee when tests run on POSIX.
    try:
        if os.name == 'nt':
            os.rename(staged, destination)
        else:
            os.link(staged, destination)
            Path(staged).unlink()
    except FileExistsError as exc:
        raise DocumentConversionError('这个位置已有同名文件，请换一个文件名。') from exc


def convert_document(source, destination, timeout=120, mode='text'):
    """Create a new PDF/DOCX; never modify the input or replace an existing file."""
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    timeout = _timeout(timeout)
    if not source.is_file():
        raise DocumentConversionError('找不到原文件，请重新选择。')
    if not can_convert(source, destination.suffix):
        raise DocumentConversionError('支持 Word（.doc / .docx）转 PDF，以及 PDF 转 Word（.docx）。')
    if source.suffix.lower() == '.pdf' and mode not in {'text', 'appearance'}:
        raise DocumentConversionError('请选择“可编辑文字”或“保留页面外观”。')
    if destination.exists() or destination.is_symlink():
        raise DocumentConversionError('这个位置已有同名文件，请换一个文件名。')
    if not destination.parent.is_dir():
        raise DocumentConversionError('保存文件夹不存在，请重新选择保存位置。')
    staged = destination.parent / ('.paperquick-convert-' + uuid.uuid4().hex + destination.suffix.lower())
    before = _hash(source)
    try:
        if source.suffix.lower() == '.pdf':
            _pdf_to_docx(source, staged, timeout, mode)
        else:
            _call({'action': 'convert', 'source': str(source), 'destination': str(staged)}, timeout=timeout)
        if not staged.is_file() or not _valid_result(staged):
            raise DocumentConversionError('没有得到完整的转换文件，请用 Word 检查原文件后重试。')
        if _hash(source) != before:
            raise DocumentConversionError('转换期间原文件发生了变化，请保存原文件后重新转换。')
        _publish_exclusive(staged, destination)
        return destination
    except DocumentConversionError:
        raise
    except OSError as exc:
        raise DocumentConversionError('无法保存转换文件。请检查文件夹权限和可用空间。') from exc
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def _xml_text(text):
    return escape(''.join(c for c in str(text) if c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF))


def _page_section(width, height, last=False):
    # Word supports pages up to 22 inches. Keep unusually large PDF pages in
    # proportion instead of creating invalid OOXML page sizes.
    scale = min(1., 1584 / max(width, height))
    w, h = round(width * scale * 20), round(height * scale * 20)
    properties = ('<w:sectPr><w:type w:val="nextPage"/><w:pgSz w:w="%d" w:h="%d"/>'
                  '<w:pgMar w:top="240" w:right="240" w:bottom="240" w:left="240" w:header="0" w:footer="0"/>'
                  '</w:sectPr>') % (w, h)
    if last:
        return properties
    return '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/>' + properties + '</w:pPr><w:r><w:rPr><w:sz w:val="2"/></w:rPr></w:r></w:p>'


def _image_paragraph(image_id, width, height):
    scale = min(1., 1584 / max(width, height))
    available_w, available_h = width * scale - 24, height * scale - 32
    fit = min(available_w / width, available_h / height)
    cx, cy = round(width * fit * 12700), round(height * fit * 12700)
    return ('<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{id}" name="PDF page {id}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="{id}" name="page-{id}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="image{id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>').format(id=image_id, cx=cx, cy=cy)


def _pdf_to_docx(source, destination, timeout, mode):
    """Write real editable OOXML or page images, without Word, OCR or a service."""
    from pypdf import PdfReader
    deadline = time.monotonic() + timeout
    def check_time():
        if time.monotonic() >= deadline:
            raise DocumentConversionError('这份文档转换时间较长，本次未保存结果。请尝试减少页数后再转换。')
    try:
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise DocumentConversionError('这份 PDF 已加密，请先使用有权访问的解密副本。')
        if not reader.pages:
            raise DocumentConversionError('这份 PDF 没有可转换的页面。')
        texts = []
        dimensions = []
        for page in reader.pages:
            check_time()
            width, height = float(page.cropbox.width), float(page.cropbox.height)
            if int(page.get('/Rotate', 0)) % 180:
                width, height = height, width
            if not (math.isfinite(width) and math.isfinite(height) and width > 24 and height > 32):
                raise DocumentConversionError('PDF 页面尺寸不适合转换为 Word。')
            dimensions.append((width, height))
            texts.append((page.extract_text() or '').strip() if mode == 'text' else '')
        if mode == 'text' and not any(texts):
            raise DocumentConversionError('没有找到可提取的文字，这可能是扫描件。请选择“保留页面外观”导出；此功能不包含文字识别。')
        body, relationships = [], []
        with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
            for index, ((width, height), text) in enumerate(zip(dimensions, texts)):
                check_time()
                if mode == 'appearance' or not text:
                    from pdf_reader_core import render_page
                    image = render_page(source, index, scale=2.)
                    try:
                        output = io.BytesIO()
                        image.save(output, format='PNG')
                        archive.writestr('word/media/page-%d.png' % (index + 1), output.getvalue())
                    finally:
                        image.close()
                    relationships.append('<Relationship Id="image%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/page-%d.png"/>' % (index + 1, index + 1))
                    body.append(_image_paragraph(index + 1, width, height))
                else:
                    # Explicit lines keep citation numbers and the PDF's reading
                    # order visible; no invented headings or reconstructed tables.
                    runs = '<w:br/>'.join('<w:t xml:space="preserve">%s</w:t>' % _xml_text(line) for line in text.splitlines())
                    body.append('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr>' + runs + '</w:r></w:p>')
                body.append(_page_section(width, height, last=index == len(dimensions) - 1))
            archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="document" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            archive.writestr('word/_rels/document.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(relationships) + '</Relationships>')
            archive.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>' + ''.join(body) + '</w:body></w:document>')
        check_time()
    except DocumentConversionError:
        raise
    except Exception as exc:
        raise DocumentConversionError('无法读取这份 PDF，请确认文件完整且未加密。') from exc


@contextmanager
def _cache_lock(path, timeout):
    """OS file locks release even if the process crashes; no stale lock guessing."""
    deadline = time.monotonic() + timeout
    with open(path, 'a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        acquired = False
        while not acquired:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise DocumentConversionError('这份 Word 文件正在准备预览，请稍后再试。')
                time.sleep(.08)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def preview_pdf(source, cache_dir, timeout=120):
    """Return the original PDF, or a content-addressed local Word preview PDF."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise DocumentConversionError('找不到原文件，请重新选择。')
    if source.suffix.lower() == '.pdf':
        return source
    if source.suffix.lower() not in WORD_SUFFIXES:
        raise DocumentConversionError('阅读预览支持 PDF、Word .doc 和 .docx。')
    timeout = _timeout(timeout)
    cache_dir = Path(cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = _hash(source)
    key = hashlib.sha256(('word-preview-v2-markup:' + source.suffix.lower() + ':' + digest).encode()).hexdigest()
    destination = cache_dir / (key + '.pdf')
    with _cache_lock(cache_dir / (key + '.lock'), timeout):
        if destination.is_file() and _valid_result(destination):
            return destination
        # A corrupt prior cache is moved aside, preserving it for diagnosis.
        if destination.exists():
            destination.rename(cache_dir / (key + '.invalid-' + uuid.uuid4().hex + '.pdf'))
        result = convert_document(source, destination, timeout=timeout)
        if _hash(source) != digest:
            # The source changed between choosing a key and starting conversion.
            result.unlink(missing_ok=True)
            raise DocumentConversionError('Word 文件刚刚发生了变化，请重新打开预览。')
        return result
