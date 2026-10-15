"""Conservative original heuristics: unknown content remains reviewable."""
from copy import deepcopy
import re

from ..dates import normalize_dates
from .text import ExtractedText

HEADINGS = {'experience':'work', 'work experience':'work', 'professional experience':'work', 'work history':'work',
            'education':'education', 'projects':'projects', 'skills':'skills', 'technical skills':'skills',
            'summary':'summary', 'profile':'summary', 'professional summary':'summary',
            'certifications':'certificates', 'certificates':'certificates', 'awards':'awards', 'volunteering':'volunteer'}
# Only real month names may precede a year, so "Fictional Labs 2023" keeps "Labs" in the employer.
MONTH = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?'
DATE_RANGE = re.compile(rf'((?:{MONTH}\s+)?(?:19|20)\d{{2}}(?:-\d{{2}})?\s*(?:–|—|\s-\s|\bto\b)\s*(?:(?:{MONTH}\s+)?(?:19|20)\d{{2}}(?:-\d{{2}})?|Present|Current|Now))', re.I)
# Heading keywords, checked in order; matched only on short lines so prose isn't mistaken for a heading.
HEADING_KEYWORDS = (('work', ('experience', 'employment', 'work history', 'career history')),
                    ('education', ('education', 'qualification', 'academic')),
                    ('projects', ('project',)),
                    ('skills', ('skill', 'technologies', 'tech stack', 'competenc')),
                    ('certificates', ('certif', 'licen')),
                    ('awards', ('award', 'honour', 'honor', 'achievement')),
                    ('volunteer', ('volunteer',)),
                    ('summary', ('summary', 'profile', 'about me', 'objective')))


def _date_fields(text):
    parsed = normalize_dates(text)
    return {key: parsed[field] for key, field in [('startDate','start'),('endDate','end')] if parsed.get(field)}


def _section_kind(title):
    key = title.casefold().strip().rstrip(':')
    if key in HEADINGS:
        return HEADINGS[key]
    if not key or len(key) > 40 or len(key.split()) > 4 or re.search(r'\d|[.,;|@]', key):
        return None
    return next((kind for kind, words in HEADING_KEYWORDS if any(word in key for word in words)), None)


def document_to_json_resume(content):
    basics = {key: deepcopy(content[key]) for key in ('name','phone','summary') if isinstance(content.get(key), str) and content[key]}
    # Studio fields are free text; only a well-formed email is carried, so a draft typo can't block the import.
    if isinstance(content.get('email'), str) and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', content['email'].strip()):
        basics['email'] = content['email'].strip()
    if content.get('location'):
        basics['location'] = {'city': content['location']}
    result = {'basics': basics, 'work': [], 'education': [], 'projects': [], 'skills': [], 'meta': {'jobHunterUnsorted': [], 'jobHunterDates': {}}}
    for section in content.get('sections', []):
        kind = _section_kind(section.get('title',''))
        for entry in section.get('entries', []):
            heading, sub = entry.get('heading',''), entry.get('subheading','')
            points = deepcopy(entry.get('bullets', []))
            dates = _date_fields(entry.get('dates',''))
            if kind in ('work','education','projects'):
                result['meta']['jobHunterDates'].setdefault(kind,{})[str(len(result[kind]))]=normalize_dates(entry.get('dates',''))
            organisation, _, place = (part.strip() for part in sub.partition(' · '))
            if kind == 'work' and heading:
                result['work'].append({'position':heading,'name':organisation, **({'location':place} if place else {}), 'highlights':points, **dates})
            elif kind == 'education' and heading:
                result['education'].append({'area':heading,'institution':sub,'courses':points, **dates})
            elif kind == 'projects' and heading:
                result['projects'].append({'name':heading,'description':sub,'highlights':points, **dates})
            elif kind == 'skills':
                names = points or [heading]
                for name in names:
                    for skill in re.split(r'[,|·•;]', re.sub(r'^[^:]{1,30}:\s*', '', name)):
                        if skill.strip():
                            result['skills'].append({'name':skill.strip()})
            else:
                result['meta']['jobHunterUnsorted'].append({'title':section.get('title','Custom section'), 'heading':heading,
                    'summary':sub,'dates_text':entry.get('dates',''), 'bullets':[{'text':point} for point in points]})
    return result


def heuristic_to_json_resume(source: ExtractedText):
    result = {'basics': {}, 'work': [], 'education': [], 'projects': [], 'skills': [],
              'meta': {'jobHunterUnsorted': [], 'jobHunterDates': {}}}
    section, current = None, None
    for line in source.lines:
        text = line.text.strip()
        heading = _section_kind(text)
        if heading:
            section, current = heading, None
            continue
        if re.search(r'(?i)ignore previous instructions|system prompt|assistant:|execute command', text):
            result['meta']['jobHunterUnsorted'].append({'title':'Unclassified source text','summary':text,'bullets':[]})
            continue
        if section is None:
            email = re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
            if email: result['basics']['email'] = email[0]
            elif re.match(r'^\+?\d[\d ()-]{7,}$',text): result['basics']['phone'] = text
            elif 'name' not in result['basics'] and re.fullmatch(r'[\w .\-]{2,80}',text) and not re.search(r'\d',text): result['basics']['name'] = text
            elif 'label' not in result['basics']: result['basics']['label'] = text
            continue
        if section == 'summary':
            result['basics']['summary'] = '\n'.join(filter(None,[result['basics'].get('summary'),text]))
            continue
        if section == 'skills':
            for skill in re.split(r'[,|•·;]',text):
                skill = re.sub(r'^\w+:\s*','',skill).strip(' -')
                if skill: result['skills'].append({'name':skill})
            continue
        if section not in ('work','education','projects'):
            result['meta']['jobHunterUnsorted'].append({'title':section,'summary':text,'bullets':[]})
            continue
        bullet = re.match(r'^[•▪●*-]\s+(.+)$',text)
        if bullet:
            if current is not None:
                current.setdefault('courses' if section == 'education' else 'highlights',[]).append(bullet[1])
            else:
                result['meta']['jobHunterUnsorted'].append({'title':section,'summary':text,'bullets':[]})
            continue
        date_match = DATE_RANGE.search(text)
        if date_match and text == date_match[0] and current is not None:
            current.update(_date_fields(text))
            result['meta']['jobHunterDates'].setdefault(section,{})[str(len(result[section])-1)]=normalize_dates(text)
            continue
        without_dates = text[:date_match.start()].strip(' |·,–') if date_match else text
        parts = re.split(r'\s+[|·]\s+|\s+at\s+|\s+—\s+',without_dates,maxsplit=1)
        if current is not None and len(parts) == 1 and not date_match:
            key = 'name' if section == 'work' else 'institution' if section == 'education' else 'description'
            if not current.get(key): current[key] = text
            else: current.setdefault('courses' if section == 'education' else 'highlights',[]).append(text)
            continue
        if section == 'work': current = {'position':parts[0], 'name':parts[1] if len(parts)>1 else '', 'highlights':[]}
        elif section == 'education': current = {'area':parts[0], 'institution':parts[1] if len(parts)>1 else '', 'courses':[]}
        else: current = {'name':parts[0], 'description':parts[1] if len(parts)>1 else '', 'highlights':[]}
        if date_match:
            current.update(_date_fields(date_match[0]))
            result['meta']['jobHunterDates'].setdefault(section,{})[str(len(result[section]))]=normalize_dates(date_match[0])
        result[section].append(current)
    return result
