"""Bounded PDF/text extraction with page and line evidence."""
from dataclasses import dataclass
from functools import cached_property
import time
from hashlib import sha256
from io import BytesIO
import re


class ImportFailure(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SourceLine:
    page: int
    text: str
    x0: float = 0
    top: float = 0


MAX_TEXT_CHARS = 120000
EXTRACT_SECONDS = 20


@dataclass(frozen=True, eq=False)
class ExtractedText:
    lines: tuple[SourceLine, ...]
    source_sha256: str

    @property
    def text(self):
        return '\n'.join(line.text for line in self.lines)

    @cached_property
    def normalized_lines(self):
        # Computed once per source so evidence matching doesn't re-normalise every line per field.
        return [(line, ' '.join(re.findall(r'\w+', line.text.casefold()))) for line in self.lines]

    @cached_property
    def normalized_index(self):
        """One searchable string (' line \\n line ') plus each line's start offset, for C-speed lookups."""
        starts, parts, offset = [], [], 0
        for _, text in self.normalized_lines:
            part = f' {text} \n'
            starts.append(offset); parts.append(part); offset += len(part)
        return ''.join(parts), starts


def from_text(text, source_sha256=None):
    if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
        raise ImportFailure('INPUT_TOO_LARGE', 'Pasted text must be at most 1 MiB')
    if not text.strip():
        raise ImportFailure('EMPTY_TEXT', 'No readable text was supplied')
    return ExtractedText(tuple(SourceLine(1, line.strip(), top=index) for index, line in enumerate(text.splitlines()) if line.strip()), source_sha256 or sha256(text.encode()).hexdigest())


def extract_text(pdf: bytes):
    import pdfplumber
    from pypdf import PdfReader
    if not pdf.startswith(b'%PDF-') or len(pdf) > 10 * 1024 * 1024:
        raise ImportFailure('INVALID_PDF', 'Upload a valid PDF of at most 10 MiB')
    try:
        reader = PdfReader(BytesIO(pdf))
        if reader.is_encrypted:
            raise ImportFailure('ENCRYPTED_PDF', 'Encrypted PDFs are not supported')
        if len(reader.pages) > 20:
            raise ImportFailure('PAGE_LIMIT_EXCEEDED', 'PDFs may have at most 20 pages')
        lines = []
        deadline = time.monotonic() + EXTRACT_SECONDS
        total_chars = 0
        with pdfplumber.open(BytesIO(pdf)) as document:
            for page_number, page in enumerate(document.pages, 1):
                # Bound work per page before word grouping: oversized or slow pages stop the import early.
                if time.monotonic() > deadline:
                    raise ImportFailure('EXTRACTION_TIMEOUT', 'This PDF took too long to read; try a simpler export')
                total_chars += len(page.chars)
                if total_chars > MAX_TEXT_CHARS * 2:
                    raise ImportFailure('TEXT_LIMIT_EXCEEDED', 'This PDF has too much text; split it into smaller resumes')
                rows = {}
                for word in page.extract_words():
                    rows.setdefault(round(word['top'] / 3) * 3, []).append(word)
                chunks = []
                for top, words in sorted(rows.items()):
                    words.sort(key=lambda word: word['x0'])
                    group = []
                    for word in words:
                        if group and word['x0'] - group[-1]['x1'] > 65:
                            chunks.append(SourceLine(page_number, ' '.join(value['text'] for value in group), group[0]['x0'], top))
                            group = []
                        group.append(word)
                    if group:
                        chunks.append(SourceLine(page_number, ' '.join(value['text'] for value in group), group[0]['x0'], top))
                # Separate sustained side columns, while retaining header lines.
                right = [line for line in chunks if line.x0 > page.width * .52]
                if len(right) >= 3 and any(re.fullmatch(r'(?i)(skills|education|projects)', line.text.strip()) for line in right):
                    chunks.sort(key=lambda line: (line.x0 > page.width * .52, line.top, line.x0))
                lines.extend(chunks)
        if sum(len(line.text) for line in lines) > MAX_TEXT_CHARS:
            raise ImportFailure('TEXT_LIMIT_EXCEEDED', 'This PDF has too much text; split it into smaller resumes')
        if not lines:
            raise ImportFailure('OCR_REQUIRED', 'No readable PDF text; paste facts manually or use a text-based PDF')
        return ExtractedText(tuple(lines), sha256(pdf).hexdigest())
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure('INVALID_OR_CORRUPT_PDF', 'The PDF could not be read') from exc
