"""Safe Word (.docx) detection and text extraction.

A .docx is a ZIP of XML parts, so the package is inspected with ``zipfile`` (entry count, sizes, ratios, paths,
encryption, content types, macros) before python-docx ever opens it. python-docx parses XML with lxml and
``resolve_entities=False``; this module additionally refuses any part carrying a DOCTYPE/ENTITY declaration, never
follows external relationships and never touches image parts. Extracted text is data, never instructions.
"""
from hashlib import sha256
from io import BytesIO
import re
import struct
import time
import zipfile

from . import text as _text
from .text import ExtractedText, ImportFailure, SourceLine

PDF_CONTENT_TYPE = 'application/pdf'
DOCX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
CONTENT_TYPES = {'pdf': PDF_CONTENT_TYPE, 'docx': DOCX_CONTENT_TYPE}
MAIN_DOCUMENT_TYPE = DOCX_CONTENT_TYPE + '.main+xml'

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ENTRIES = 200
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_RATIO = 100
# Tiny parts may legitimately exceed 100:1 (an empty relationships file), so the ratio only guards real payloads.
RATIO_FLOOR_BYTES = 16 * 1024
MAX_DOCUMENT_XML_BYTES = 5 * 1024 * 1024
MAX_CONTENT_TYPES_BYTES = 1024 * 1024
MAX_TABLE_DEPTH = 4

LEGACY_DOC_MESSAGE = 'Legacy Word (.doc) files are not supported. Save it as PDF or .docx and upload again.'
UNSUPPORTED_MESSAGE = 'Unsupported file type. Upload a PDF or a Word (.docx) resume.'
MACRO_MESSAGE = 'Macro-enabled Word files (.docm) are not supported. Save it as PDF or .docx without macros and upload again.'

OLE_MAGIC = b'\xd0\xcf\x11\xe0'
ZIP_MAGIC = b'PK\x03\x04'


def _declared_entry_count(data):
    """Entry count from the end-of-central-directory record, so a huge directory is refused before parsing it."""
    tail = data[-(22 + 65535):]
    index = tail.rfind(b'PK\x05\x06')
    if index < 0 or len(tail) - index < 22:
        return None
    return struct.unpack('<H', tail[index + 10:index + 12])[0]


def _unsafe_name(name):
    parts = re.split(r'[\\/]', name)
    return (not name or '\x00' in name or name.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', name) is not None
            or '..' in parts)


def _safe_parser():
    from lxml import etree
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                           huge_tree=False, remove_comments=True, remove_pis=True)


def _read_limited(archive, info, limit):
    with archive.open(info) as handle:
        blob = handle.read(limit + 1)
    if len(blob) > limit:
        raise ImportFailure('DOCX_ZIP_BOMB', 'This Word file expands to more data than allowed')
    return blob


def validate_docx(data: bytes):
    """Raise ImportFailure unless ``data`` is a structurally safe, non-macro WordprocessingML package."""
    if len(data) > MAX_FILE_BYTES:
        raise ImportFailure('UPLOAD_TOO_LARGE', 'Upload a file of at most 10 MiB')
    if not data.startswith(ZIP_MAGIC):
        raise ImportFailure('UNSUPPORTED_FILE', UNSUPPORTED_MESSAGE)
    declared = _declared_entry_count(data)
    if declared is None:
        raise ImportFailure('INVALID_DOCX', 'The Word document could not be read; export it again as .docx')
    if declared > MAX_ENTRIES:
        raise ImportFailure('DOCX_TOO_MANY_ENTRIES', f'This Word file has more than {MAX_ENTRIES} parts')
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError) as exc:
        raise ImportFailure('INVALID_DOCX', 'The Word document could not be read; export it again as .docx') from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ImportFailure('DOCX_TOO_MANY_ENTRIES', f'This Word file has more than {MAX_ENTRIES} parts')
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise ImportFailure('INVALID_DOCX', 'This Word file has duplicate parts and cannot be read safely')
        total = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ImportFailure('DOCX_ENCRYPTED', 'Encrypted or password-protected Word files are not supported')
            if _unsafe_name(info.filename):
                raise ImportFailure('DOCX_UNSAFE_PATH', 'This Word file contains an unsafe part path')
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ImportFailure('DOCX_ZIP_BOMB', 'This Word file expands to more data than allowed')
            if info.file_size >= RATIO_FLOOR_BYTES and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise ImportFailure('DOCX_ZIP_BOMB', 'This Word file is compressed suspiciously well and was refused')
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ImportFailure('INVALID_DOCX', 'This Word file uses an unsupported compression method')
        lowered = {name.casefold() for name in names}
        if any(name.endswith('vbaproject.bin') for name in lowered):
            raise ImportFailure('MACRO_ENABLED', MACRO_MESSAGE)
        if '[content_types].xml' not in lowered or 'word/document.xml' not in lowered:
            raise ImportFailure('UNSUPPORTED_FILE', UNSUPPORTED_MESSAGE)
        by_name = {info.filename: info for info in infos}
        if '[Content_Types].xml' not in by_name or 'word/document.xml' not in by_name:
            raise ImportFailure('INVALID_DOCX', 'The Word document could not be read; export it again as .docx')
        if by_name['word/document.xml'].file_size > MAX_DOCUMENT_XML_BYTES:
            raise ImportFailure('DOCX_PART_TOO_LARGE', 'The main Word document part is too large to import')
        # Bytes are scanned for DOCTYPE/ENTITY before any XML parser sees them (Word never writes either).
        for info in infos:
            if not info.filename.lower().endswith(('.xml', '.rels')):
                continue
            blob = _read_limited(archive, info, MAX_UNCOMPRESSED_BYTES)
            if blob.startswith((b'\xff\xfe', b'\xfe\xff')) or b'\x00' in blob[:4]:
                raise ImportFailure('DOCX_UNSAFE_XML', 'This Word file uses an unsupported text encoding')
            if b'<!DOCTYPE' in blob or b'<!ENTITY' in blob:
                raise ImportFailure('DOCX_UNSAFE_XML', 'This Word file contains unsafe XML declarations and was refused')
        types = _read_limited(archive, by_name['[Content_Types].xml'], MAX_CONTENT_TYPES_BYTES)
        try:
            from lxml import etree
            root = etree.fromstring(types, _safe_parser())
        except Exception as exc:
            raise ImportFailure('INVALID_DOCX', 'The Word document could not be read; export it again as .docx') from exc
    overrides, defaults = {}, {}
    for node in root:
        tag = node.tag.rsplit('}', 1)[-1] if isinstance(node.tag, str) else ''
        if tag == 'Override':
            overrides[(node.get('PartName') or '').casefold()] = node.get('ContentType') or ''
        elif tag == 'Default':
            defaults[(node.get('Extension') or '').casefold()] = node.get('ContentType') or ''
    if any('macroenabled' in value.casefold() or 'vbaproject' in value.casefold()
           for value in [*overrides.values(), *defaults.values()]):
        raise ImportFailure('MACRO_ENABLED', MACRO_MESSAGE)
    main_type = overrides.get('/word/document.xml', defaults.get('xml', ''))
    if main_type != MAIN_DOCUMENT_TYPE:
        raise ImportFailure('UNSUPPORTED_FILE', UNSUPPORTED_MESSAGE)


def detect_resume_file(data: bytes) -> str:
    """Return 'pdf' or 'docx' from the content itself; the filename and MIME type are never trusted."""
    if data.startswith(b'%PDF-'):
        if len(data) > MAX_FILE_BYTES:
            raise ImportFailure('UPLOAD_TOO_LARGE', 'Upload a file of at most 10 MiB')
        return 'pdf'
    if data.startswith(OLE_MAGIC):
        if 'EncryptedPackage'.encode('utf-16-le') in data[:MAX_FILE_BYTES]:
            raise ImportFailure('DOCX_ENCRYPTED', 'Password-protected Word files are not supported. Remove the password, or save it as PDF or .docx, and upload again.')
        raise ImportFailure('LEGACY_DOC', LEGACY_DOC_MESSAGE)
    if data.startswith(ZIP_MAGIC):
        validate_docx(data)
        return 'docx'
    raise ImportFailure('UNSUPPORTED_FILE', UNSUPPORTED_MESSAGE)


def declared_file_problem(filename: str, content_type: str):
    """Pre-upload check of the declared name/MIME type. Returns (code, message) to refuse, or the kind to accept."""
    name = filename.lower()
    if name.endswith('.doc') or content_type == 'application/msword':
        return 'LEGACY_DOC', LEGACY_DOC_MESSAGE
    if name.endswith(('.docm', '.dotm')) or 'macroenabled' in content_type.lower():
        return 'MACRO_ENABLED', MACRO_MESSAGE
    if content_type == PDF_CONTENT_TYPE and name.endswith('.pdf'):
        return 'pdf'
    if content_type == DOCX_CONTENT_TYPE and name.endswith('.docx'):
        return 'docx'
    return 'UNSUPPORTED_FILE', UNSUPPORTED_MESSAGE


_CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​⁠﻿]')
_SPACES = re.compile('[ \t\xa0 -  　]+')
_BULLET = re.compile(r'^[•▪●◦*\-–]\s')


def _lines(paragraph_text):
    for raw in re.split(r'[\r\n]+', paragraph_text):
        line = _SPACES.sub(' ', _CONTROL.sub('', raw)).strip()
        if line:
            yield line


def _numbered(properties):
    numbering = getattr(properties, 'numPr', None) if properties is not None else None
    if numbering is None:
        return None
    number = numbering.numId
    return not (number is not None and number.val == 0)


def _is_list(paragraph):
    style = paragraph.style
    name = (style.name or '') if style is not None else ''
    if name.startswith(('Heading', 'Title')):
        return False  # numbered headings stay headings so section detection still works
    state = _numbered(paragraph._p.pPr)
    if state is not None:
        return state
    if name.startswith('List'):
        return True
    for _ in range(10):
        if style is None:
            return False
        state = _numbered(style.element.pPr)
        if state is not None:
            return state
        style = style.base_style
    return False


class _Collector:
    def __init__(self):
        self.lines = []
        self.chars = 0
        self.deadline = time.monotonic() + _text.EXTRACT_SECONDS

    def check(self):
        if time.monotonic() > self.deadline:
            raise ImportFailure('EXTRACTION_TIMEOUT', 'This document took too long to read; try a simpler export')

    def add(self, line):
        self.chars += len(line)
        if self.chars > _text.MAX_TEXT_CHARS:
            raise ImportFailure('TEXT_LIMIT_EXCEEDED', 'This document has too much text; split it into smaller resumes')
        self.lines.append(SourceLine(1, line, top=len(self.lines)))

    def paragraph(self, paragraph):
        self.check()
        bullet = _is_list(paragraph)
        for index, line in enumerate(_lines(paragraph.text)):
            self.add(f'• {line}' if bullet and index == 0 and not _BULLET.match(line) else line)

    def container(self, container, depth=0):
        from docx.table import Table
        for block in container.iter_inner_content():
            if isinstance(block, Table):
                self.table(block, depth + 1)
            else:
                self.paragraph(block)

    def table(self, table, depth):
        from docx.table import _Cell
        if depth > MAX_TABLE_DEPTH:
            raise ImportFailure('DOCX_TOO_COMPLEX', 'This Word file has deeply nested tables; export it as PDF instead')
        # Row by row, cell by cell, straight from the XML so merged cells are read once.
        for row in table._tbl.tr_lst:
            self.check()
            for cell in row.tc_lst:
                self.container(_Cell(cell, table), depth)


def _read_document(data: bytes):
    """Collect lines from an already validated package (header text first, then body in document order)."""
    from docx import Document
    document = Document(BytesIO(data))
    headers = _Collector()
    headers.deadline = time.monotonic() + _text.EXTRACT_SECONDS
    for section in document.sections:
        for header in (section.header, section.first_page_header):
            if header.is_linked_to_previous:
                continue
            headers.container(header)
    seen, header_lines = set(), []
    for line in headers.lines:
        if line.text not in seen:
            seen.add(line.text); header_lines.append(line.text)
    body = _Collector()
    for line in header_lines:
        body.add(line)
    body.container(document)
    return body.lines


def extract_docx(data: bytes) -> ExtractedText:
    validate_docx(data)
    try:
        lines = _read_document(data)
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure('INVALID_OR_CORRUPT_DOCX', 'The Word document could not be read') from exc
    if not lines:
        raise ImportFailure('NO_READABLE_TEXT', 'No readable text was found in this Word document')
    return ExtractedText(tuple(lines), sha256(data).hexdigest())
