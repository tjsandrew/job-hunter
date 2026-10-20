"""Synthetic layout regressions; no personal resume fixtures."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from job_hunter.profile_bank.importing import extract_text, heuristic_to_json_resume, json_resume_to_candidates
from job_hunter.profile_bank.importing.schema import validate_resume


def structured_pdf():
    output = BytesIO(); pdf = Canvas(output)
    font = Path(__file__).parents[1] / 'src/job_hunter/preparation/fonts/lmroman-regular.ttf'
    pdfmetrics.registerFont(TTFont('SyntheticImport', str(font))); pdf.setFont('SyntheticImport', 10)
    rows = [(40,790,'Jordan Example'), (36,765,'Education'),
            (36,744,'•'),(47,741,'Example University'),(520,741,'Singapore'),
            (47,725,'Master of Computing'),(450,725,'Aug 2025 – Present'),
            (36,704,'•'),(47,701,'Example University'),(520,701,'Singapore'),
            (47,685,'Bachelor of Science;'),(450,685,'Aug 2019 – Jan 2024'),
            (47,672,'Bachelor of Business'),(60,657,'- Dean’s List'),
            (36,632,'Professional Experience'),
            (36,612,'•'),(47,609,'Fictional Labs'),(520,609,'Singapore'),
            (47,593,'Research Engineer'),(450,593,'Jan 2024 – Present'),
            (60,578,'- Built reproducible pipelines with testing'),(71,564,'and documented release procedures.'),
            (60,548,'- Improved latency with SQL indexes.'),
            (36,528,'•'),(47,525,'Harbour Analytics'),(520,525,'Singapore'),
            (47,509,'Analytics Intern'),(450,509,'May 2022 – Jul 2022'),
            (60,494,'- Created reporting dashboards.'),
            (36,469,'Selected Projects'),(36,449,'•'),(47,446,'Forecasting Study'),
            (47,430,'Undergraduate Researcher'),(540,430,'2023'),
            (60,415,'- Compared forecasting models'),(71,401,'at multiple prediction horizons.'),
            (36,376,'Technical Skills'),
            (36,356,'• Programming / Data: Python, R, SQL (PostgreSQL)'),
            (36,336,'• Analytics / Methods: Econometrics (DiD, event studies), time series'),
            (36,316,'• Data Workflow: R, Git'),
            (36,291,'Additional'),(36,271,'• Languages: English, Malay')]
    for x,y,text in rows: pdf.drawString(x,y,text)
    pdf.save(); return output.getvalue()


def test_nested_bullets_dates_and_wrapped_lines_stay_with_their_entries():
    data = structured_pdf(); source = extract_text(data); parsed = heuristic_to_json_resume(source)
    validate_resume(parsed)
    assert len(parsed['work']) == 2 and len(parsed['education']) == 2 and len(parsed['projects']) == 1
    first, second = parsed['work']
    assert (first['position'], first['name'], first['location']) == ('Research Engineer', 'Fictional Labs', 'Singapore')
    assert first['highlights'] == ['Built reproducible pipelines with testing and documented release procedures.', 'Improved latency with SQL indexes.']
    assert second['position'] == 'Analytics Intern' and second['startDate'] == '2022-05'
    assert parsed['education'][1]['area'] == 'Bachelor of Science; Bachelor of Business'
    assert parsed['projects'][0]['highlights'] == ['Compared forecasting models at multiple prediction horizons.']
    assert parsed['projects'][0]['startDate'] == '2023'
    skills = [item['name'] for item in parsed['skills']]
    assert skills == ['Python', 'R', 'SQL (PostgreSQL)', 'Econometrics (DiD, event studies)', 'time series', 'Git']
    assert len(parsed['meta']['jobHunterUnsorted']) == 1
    candidates = json_resume_to_candidates(parsed, source)
    work = next(item for item in candidates if item['kind'] == 'experience')
    for point in work['data']['bullets']:
        evidence = work['evidence']['bullets'][point['id']]
        assert evidence['source_sha256'] == sha256(data).hexdigest() and evidence['page'] == 1
    assert work['data']['current'] is True
