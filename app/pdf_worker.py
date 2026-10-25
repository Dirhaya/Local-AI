"""PDF parsing worker: receives bytes via stdin; no document written to disk."""
import io
import json
import sys


def extract(data):
    from pypdf import PdfReader
    if len(data) > 20*1024*1024 or not data.lstrip().startswith(b'%PDF-'):
        raise ValueError('Upload a valid PDF up to 20 MB.')
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError('This PDF is password protected. Export an unlocked copy first.')
    if not 1 <= len(reader.pages) <= 500:
        raise ValueError('Upload 1–500 pages at a time. Split larger books by chapter.')
    pages, total, empty = [], 0, 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content and len(content.get_data()) > 8*1024*1024:
            raise ValueError(f'Page {number} is too complex. Export a simpler PDF.')
        text = (page.extract_text() or '').replace('\x00','').strip()
        total += len(text)
        if total > 1_000_000:
            raise ValueError('This PDF has too much text. Split it by chapter.')
        if len(text) < 20: empty += 1
        pages.append({'page':number, 'text':text})
    if total < 50:
        raise ValueError('No usable text found. This may be a scanned PDF. Use a searchable/OCR copy; OCR is not installed in this version.')
    return {'pages':pages, 'warning': f'{empty} page(s) had little extractable text. Check formulas and diagrams against the original.' if empty else 'Check extracted mathematical notation against the original PDF.'}


if __name__ == '__main__':
    try:
        print(json.dumps(extract(sys.stdin.buffer.read(20*1024*1024+1)), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc) if isinstance(exc,ValueError) else 'Could not parse this PDF. Export a fresh searchable copy.'}))
        sys.exit(1)
