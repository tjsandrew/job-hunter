"""Safe .docx import: content detection, zip/XML hardening and extraction (fictional data only)."""
from hashlib import sha256
from io import BytesIO
import os
import socket
import zipfile

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from job_hunter.profile_bank.importing import heuristic_to_json_resume, text as text_module
from job_hunter.profile_bank.importing.docx import (DOCX_CONTENT_TYPE, _read_document, declared_file_problem,
                                                   detect_resume_file, extract_docx, validate_docx)
from job_hunter.profile_bank.importing.text import ImportFailure
from tests.test_profile_importing import pdf_fixture


def save(document):
    output = BytesIO(); document.save(output); return output.getvalue()


def make_docx(layout='single', numbered_bullets=False):
    document = Document()
    header = document.sections[0].header
    header.paragraphs[0].text = 'Jordan Example'
    header.add_paragraph('jordan@example.invalid')
    if layout == 'single':
        blocks = [document]
    else:
        table = document.add_table(rows=1, cols=2)
        blocks = [table.cell(0, 0), table.cell(0, 1)]
    left, right = blocks[0], blocks[-1]
    left.add_paragraph('Experience', style='Heading 1')
    left.add_paragraph('Backend Engineer | Fictional Labs 2023 – Present')
    for line in ('Built Python APIs', 'Reduced query latency'):
        bullet = left.add_paragraph(line, style=None if numbered_bullets else 'List Bullet')
        if numbered_bullets:
            numbering = bullet._p.get_or_add_pPr().get_or_add_numPr()
            numbering.get_or_add_ilvl().val = 0; numbering.get_or_add_numId().val = 3
    right.add_paragraph('Skills', style='Heading 1')
    right.add_paragraph('Python, SQL | Docker')
    return save(document)


def rebuild(data, replace=None, add=None, remove=()):
    """Copy a package, optionally swapping/adding/removing parts (names may be unsafe on purpose)."""
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename in remove:
                continue
            target.writestr(info.filename, (replace or {}).get(info.filename, source.read(info)))
        for name, blob in (add or {}).items():
            target.writestr(name, blob)
    return output.getvalue()


def failure(data, fn=detect_resume_file):
    with pytest.raises(ImportFailure) as raised:
        fn(data)
    return raised.value


def test_docx_with_header_headings_and_list_styles_yields_resume_facts():
    source = extract_docx(make_docx())
    assert [line.text for line in source.lines][:2] == ['Jordan Example', 'jordan@example.invalid']
    assert '• Built Python APIs' in source.text and {line.page for line in source.lines} == {1}
    resume = heuristic_to_json_resume(source)
    assert resume['basics'] == {'name': 'Jordan Example', 'email': 'jordan@example.invalid'}
    work = resume['work'][0]
    assert work['position'] == 'Backend Engineer' and work['name'] == 'Fictional Labs'
    assert work['highlights'] == ['Built Python APIs', 'Reduced query latency']
    assert {skill['name'] for skill in resume['skills']} == {'Python', 'SQL', 'Docker'}


def test_source_hash_is_of_the_original_bytes():
    data = make_docx()
    assert extract_docx(data).source_sha256 == sha256(data).hexdigest()


def test_two_column_table_layout_is_read_cell_by_cell():
    resume = heuristic_to_json_resume(extract_docx(make_docx('table')))
    assert resume['basics']['name'] == 'Jordan Example'
    assert resume['work'][0]['highlights'] == ['Built Python APIs', 'Reduced query latency']
    assert {skill['name'] for skill in resume['skills']} == {'Python', 'SQL', 'Docker'}


def test_numbering_properties_count_as_bullets_but_headings_do_not():
    document = Document()
    heading = document.add_paragraph('Experience', style='Heading 1')
    numbering = heading._p.get_or_add_pPr().get_or_add_numPr()
    numbering.get_or_add_ilvl().val = 0; numbering.get_or_add_numId().val = 2
    document.add_paragraph('Backend Engineer | Fictional Labs 2023 – Present')
    item = document.add_paragraph('Shipped a synthetic feature')
    numbering = item._p.get_or_add_pPr().get_or_add_numPr()
    numbering.get_or_add_ilvl().val = 0; numbering.get_or_add_numId().val = 2
    off = document.add_paragraph('Not a bullet')
    numbering = off._p.get_or_add_pPr().get_or_add_numPr()
    numbering.get_or_add_ilvl().val = 0; numbering.get_or_add_numId().val = 0
    lines = [line.text for line in extract_docx(save(document)).lines]
    assert lines == ['Experience', 'Backend Engineer | Fictional Labs 2023 – Present', '• Shipped a synthetic feature', 'Not a bullet']


def test_external_links_are_never_followed(monkeypatch):
    document = Document()
    paragraph = document.add_paragraph('Portfolio ')
    relation = document.part.relate_to('http://127.0.0.1:9/never-fetched', RT.HYPERLINK, is_external=True)
    link = OxmlElement('w:hyperlink'); link.set(qn('r:id'), relation)
    run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'example.invalid/portfolio'
    run.append(text); link.append(run); paragraph._p.append(link)
    def forbidden(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    assert extract_docx(save(document)).text == 'Portfolio example.invalid/portfolio'


def test_empty_and_overlong_documents_are_refused(monkeypatch):
    assert failure(save(Document()), extract_docx).code == 'NO_READABLE_TEXT'
    data = make_docx()
    monkeypatch.setattr(text_module, 'MAX_TEXT_CHARS', 30)
    assert failure(data, extract_docx).code == 'TEXT_LIMIT_EXCEEDED'
    monkeypatch.undo()
    monkeypatch.setattr(text_module, 'EXTRACT_SECONDS', -1)
    assert failure(data, extract_docx).code == 'EXTRACTION_TIMEOUT'


def test_deeply_nested_tables_are_refused():
    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    for _ in range(6):
        cell = cell.add_table(rows=1, cols=1).cell(0, 0)
    cell.add_paragraph('deep')
    assert failure(save(document), extract_docx).code == 'DOCX_TOO_COMPLEX'


# ---- content detection -------------------------------------------------------------------------------------

def test_type_is_decided_by_content_not_name():
    docx, pdf = make_docx(), pdf_fixture()
    # A .docx saved as "resume.pdf" (or the reverse) is still recognised by its bytes.
    assert detect_resume_file(docx) == 'docx' and detect_resume_file(pdf) == 'pdf'
    assert declared_file_problem('resume.docx', DOCX_CONTENT_TYPE) == 'docx'
    assert declared_file_problem('resume.pdf', 'application/pdf') == 'pdf'


def test_legacy_doc_and_other_formats_are_refused_with_guidance():
    legacy = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 512
    error = failure(legacy)
    assert error.code == 'LEGACY_DOC' and 'Save it as PDF or .docx' in str(error)
    encrypted = legacy + 'EncryptedPackage'.encode('utf-16-le')
    assert failure(encrypted).code == 'DOCX_ENCRYPTED'
    assert failure(b'{\\rtf1\\ansi Jordan Example}').code == 'UNSUPPORTED_FILE'
    odt = BytesIO()
    with zipfile.ZipFile(odt, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('content.xml', '<office:document-content/>')
    assert failure(odt.getvalue()).code == 'UNSUPPORTED_FILE'
    assert failure(b'plain text resume').code == 'UNSUPPORTED_FILE'
    assert failure(b'PK\x03\x04 not really a zip').code in ('INVALID_DOCX',)


@pytest.mark.parametrize('name,type_,code', [
    ('resume.doc', 'application/msword', 'LEGACY_DOC'),
    ('resume.doc', 'application/pdf', 'LEGACY_DOC'),
    ('resume.docm', 'application/vnd.ms-word.document.macroEnabled.12', 'MACRO_ENABLED'),
    ('resume.rtf', 'application/rtf', 'UNSUPPORTED_FILE'),
    ('resume.odt', 'application/vnd.oasis.opendocument.text', 'UNSUPPORTED_FILE'),
    ('resume.pdf', DOCX_CONTENT_TYPE, 'UNSUPPORTED_FILE'),
    ('resume.docx', '', 'UNSUPPORTED_FILE'),
])
def test_declared_names_and_types_are_screened(name, type_, code):
    assert declared_file_problem(name, type_)[0] == code


# ---- package hardening -------------------------------------------------------------------------------------

def test_macro_enabled_documents_are_rejected():
    base = make_docx()
    assert failure(rebuild(base, add={'word/vbaProject.bin': b'\xd0\xcf\x11\xe0'})).code == 'MACRO_ENABLED'
    with zipfile.ZipFile(BytesIO(base)) as archive:
        types = archive.read('[Content_Types].xml').decode()
    macro = types.replace(DOCX_CONTENT_TYPE + '.main+xml', 'application/vnd.ms-word.document.macroEnabled.main+xml')
    assert macro != types
    assert failure(rebuild(base, {'[Content_Types].xml': macro.encode()})).code == 'MACRO_ENABLED'


def test_high_compression_ratio_entry_is_rejected():
    bomb = rebuild(make_docx(), add={'word/media/blob.bin': b'\x00' * (20 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024 and failure(bomb).code == 'DOCX_ZIP_BOMB'


def test_total_size_limit_applies_below_the_upload_limit():
    # Highly compressible but ratio-safe: repeated pseudo-text compresses ~10:1, 30 MiB uncompressed in 3 MiB.
    chunk = (b'abcdefghij' * 100 + os.urandom(100)) * 300
    extras = {f'word/media/part{i}.bin': chunk for i in range(2 + 25 * 1024 * 1024 // len(chunk))}
    data = rebuild(make_docx(), add=extras)
    assert len(data) < 10 * 1024 * 1024 and failure(data).code == 'DOCX_ZIP_BOMB'


def test_too_many_entries_are_rejected():
    data = rebuild(make_docx(), add={f'customXml/item{i}.xml': b'<a/>' for i in range(201)})
    assert failure(data).code == 'DOCX_TOO_MANY_ENTRIES'


def test_oversized_main_document_part_is_rejected():
    document = b'<w:document xmlns:w="x"><!--' + os.urandom(3 * 1024 * 1024).hex().encode() + b'--></w:document>'
    assert len(document) > 5 * 1024 * 1024
    assert failure(rebuild(make_docx(), {'word/document.xml': document})).code == 'DOCX_PART_TOO_LARGE'


@pytest.mark.parametrize('name', ['../evil.xml', 'word/../../evil.xml', '/etc/passwd', 'C:/evil.xml', 'word\\..\\evil.xml'])
def test_unsafe_entry_paths_are_rejected(name):
    assert failure(rebuild(make_docx(), add={name: b'<a/>'})).code == 'DOCX_UNSAFE_PATH'


def test_encrypted_entries_are_rejected():
    data = bytearray(rebuild(make_docx(), add={'word/secret.xml': b'<a/>'}))
    position = data.rindex(b'PK\x01\x02', 0, data.index(b'word/secret.xml', data.rindex(b'PK\x01\x02')))
    assert data[position + 46:position + 46 + 15] == b'word/secret.xml'
    data[position + 8] |= 0x1  # general-purpose flag bit 0 = encrypted
    assert failure(bytes(data)).code == 'DOCX_ENCRYPTED'


def test_duplicate_part_names_are_rejected():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        data = rebuild(make_docx(), add={'word/document.xml': b'<w:document xmlns:w="x"/>'})
    assert failure(data).code == 'INVALID_DOCX'


def test_missing_wordprocessingml_parts_are_not_a_word_document():
    sheet = BytesIO()
    with zipfile.ZipFile(sheet, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr('xl/workbook.xml', '<workbook/>')
    assert failure(sheet.getvalue()).code == 'UNSUPPORTED_FILE'
    assert failure(rebuild(make_docx(), remove=('word/document.xml',))).code == 'UNSUPPORTED_FILE'
    template = rebuild(make_docx(), {'[Content_Types].xml': zipfile.ZipFile(BytesIO(make_docx())).read('[Content_Types].xml')
                                     .replace(b'document.main+xml', b'template.main+xml')})
    assert failure(template).code == 'UNSUPPORTED_FILE'


def test_doctype_and_entities_are_refused_and_never_resolved(tmp_path):
    secret = tmp_path / 'secret.txt'; secret.write_text('TOP-SECRET-MARKER')
    base = make_docx()
    with zipfile.ZipFile(BytesIO(base)) as archive:
        original = archive.read('word/document.xml').decode()
    declaration = f'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "file://{secret}">]>'
    hostile = original.split('?>', 1)[1].replace('<w:t>', '<w:t>&xxe;', 1) if '?>' in original else original
    hostile = declaration + hostile
    data = rebuild(base, {'word/document.xml': hostile.encode()})
    assert failure(data).code == 'DOCX_UNSAFE_XML' and failure(data, extract_docx).code == 'DOCX_UNSAFE_XML'
    # Even past the byte screen, the parser itself must not expand the entity (python-docx: resolve_entities=False).
    lines = _read_document(data)
    assert 'TOP-SECRET-MARKER' not in ' '.join(line.text for line in lines)


def test_billion_laughs_is_refused_quickly():
    laugh = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
             '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
             '<w:body><w:p><w:r><w:t>&c;</w:t></w:r></w:p></w:body></w:document>')
    assert failure(rebuild(make_docx(), {'word/document.xml': laugh.encode()}), extract_docx).code == 'DOCX_UNSAFE_XML'
