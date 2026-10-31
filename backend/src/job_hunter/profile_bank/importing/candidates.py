"""Interchange mapping, evidence and deterministic candidate matching."""
from bisect import bisect_right
from copy import deepcopy
from difflib import SequenceMatcher
from uuid import NAMESPACE_URL, uuid5
import re

from ..schema import validate_item_data
from ..skills import infer_skill_category
from ..dates import normalize_date
from .schema import validate_resume
from .text import ImportFailure


FUZZY_LINE_LIMIT = 2000


def normalized(text):
    return ' '.join(re.findall(r'\w+', str(text).casefold()))


def evidence_for(value, source):
    if source is None or value in (None, '', [], {}):
        return None
    if isinstance(value, (dict,list)):
        return None
    query = normalized(value)
    if not query:
        return None
    lines = source.normalized_lines
    index, starts = source.normalized_index
    position = index.find(f' {query} ')
    if position >= 0:
        line = lines[bisect_right(starts, position) - 1][0]
        return {'source_sha256':source.source_sha256, 'page':line.page, 'text':line.text}
    # Fuzzy fallback only against lines of similar length, and only for bounded inputs.
    if len(query) < 12 or len(lines) > FUZZY_LINE_LIMIT:
        return None
    numbers = re.findall(r'\d+', query)
    for line, text in lines:
        if abs(len(text)-len(query)) <= len(query)*.1 and re.findall(r'\d+', text) == numbers \
                and SequenceMatcher(None,query,text).ratio() >= .94:
            return {'source_sha256':source.source_sha256, 'page':line.page, 'text':line.text}
    return None


def _points(values, seed):
    return [{'id':'b_'+uuid5(NAMESPACE_URL,f'{seed}/{index}').hex, 'text':value, 'tags':[], 'skills':[], 'alternatives':[]}
            for index,value in enumerate(values) if value.strip()]


def _dates(row):
    start, end = normalize_date(row.get('startDate')), normalize_date(row.get('endDate'))
    # A missing end date is unknown, never inferred to mean present.
    return {'start':start,'end':end,'current':False}


def json_resume_to_candidates(resume, text=None):
    validate_resume(resume)
    metadata = resume.get('meta',{}).get('jobHunter')
    candidates = []
    if metadata is not None:
        if not isinstance(metadata,dict) or metadata.get('schemaVersion') != 1 or not isinstance(metadata.get('items'),list) or not isinstance(metadata.get('basics'),dict):
            raise ImportFailure('INVALID_BANK_METADATA','Invalid Job Hunter metadata')
        basics = deepcopy(metadata['basics'])
        originals = metadata['items']
        if not all(isinstance(raw,dict) and isinstance(raw.get('kind'),str) and isinstance(raw.get('data'),dict)
                   and isinstance(raw.get('tags',[]),list) for raw in originals):
            raise ImportFailure('INVALID_BANK_METADATA','Invalid Job Hunter metadata items')
    else:
        row = resume.get('basics',{})
        basics = {key:row[source] for key,source in [('name','name'),('headline','label'),('email','email'),('phone','phone'),('summary','summary')] if source in row}
        if row.get('location',{}).get('city'): basics['location'] = row['location']['city']
        if 'profiles' in row: basics['links'] = deepcopy(row['profiles'])
        originals = []
        for field,kind in [('work','experience'),('education','education'),('projects','project'),('skills','skill'),('certificates','certification'),('awards','award'),('volunteer','volunteering')]:
            for index,row in enumerate(resume.get(field,[])):
                data = _dates(row) if kind != 'skill' else {}
                source_dates=resume.get('meta',{}).get('jobHunterDates',{}).get(field,{}).get(str(index))
                if source_dates and kind!='skill': data.update(source_dates)
                data['bullets'] = _points(row.get('courses' if kind=='education' else 'highlights',[]),f'{kind}/{index}/{text.source_sha256 if text else "json"}')
                if kind == 'experience': data.update(title=row.get('position') or 'Unspecified role',organisation=row.get('name',''),location=row.get('location',''),summary=row.get('summary',''),skills=[])
                elif kind == 'education': data.update(qualification=row.get('area') or row.get('studyType') or 'Unspecified qualification',institution=row.get('institution',''),grade=row.get('score',''))
                elif kind == 'project': data.update(name=row.get('name') or 'Untitled project',role=', '.join(row.get('roles',[])),url=row.get('url',''),summary=row.get('description',''),skills=row.get('keywords',[]))
                elif kind == 'skill': data.update(name=row.get('name') or 'Unnamed skill',category=infer_skill_category(row.get('name','')),level=row.get('level',''))
                elif kind == 'certification': data.update(name=row.get('name') or 'Unnamed certificate',issuer=row.get('issuer',''),url=row.get('url',''),start=normalize_date((row.get('date') or '')[:7]))
                elif kind == 'award': data.update(title=row.get('title') or 'Unnamed award',awarder=row.get('awarder',''),summary=row.get('summary',''),start=normalize_date((row.get('date') or '')[:7]))
                else: data.update(title=row.get('position') or 'Volunteer',organisation=row.get('organization',''),summary=row.get('summary',''),skills=[])
                originals.append({'kind':kind,'data':data,'tags':[]})
    allowed = {'name','display_name','headline','email','phone','location','summary','links'}
    if set(basics)-allowed:
        raise ImportFailure('INVALID_BANK_METADATA','Unsupported basics in the export metadata')
    candidates.append({'candidate_id':'basics','kind':'basics','data':basics,
                       'basics_provenance':deepcopy(metadata.get('basicsProvenance',{})) if metadata else {}})
    for index,raw in enumerate(originals):
        try:
            validate_item_data(raw['kind'],raw['data'])
        except (ValueError,KeyError) as exc:
            raise ImportFailure('INVALID_PROFILE_ITEM','An extracted item is invalid or exceeds profile limits') from exc
        data = deepcopy(raw['data'])
        candidates.append({'candidate_id':f'item_{index}', 'kind':raw['kind'], 'data':data,
                           'tags':deepcopy(raw.get('tags',[])), 'source_item_id':raw.get('id'),
                           'parent_source_id':raw.get('parent_id')})
    unsorted = resume.get('meta',{}).get('jobHunterUnsorted',[])
    if not isinstance(unsorted,list) or not all(isinstance(raw,dict) and isinstance(raw.get('bullets',[]),list)
                                                and all(isinstance(point,dict) and isinstance(point.get('text'),str) for point in raw.get('bullets',[]))
                                                for raw in unsorted):
        raise ImportFailure('INVALID_JSON_RESUME','Unsorted entries must be objects with text points')
    for index,raw in enumerate(unsorted):
        data = {'title':raw.get('title') or 'Unsorted', 'heading':raw.get('heading',''), 'summary':raw.get('summary',''), 'dates_text':raw.get('dates_text',''), 'bullets':deepcopy(raw.get('bullets',[]))}
        for point_index,point in enumerate(data['bullets']):
            point.setdefault('id','b_'+uuid5(NAMESPACE_URL,f'unsorted/{index}/{point_index}').hex)
            point.setdefault('alternatives',[])
        validate_item_data('custom',data)
        candidates.append({'candidate_id':f'unsorted_{index}','kind':'custom','data':data,'tags':[],'unsorted':True})
    if len(candidates)>401:
        raise ImportFailure('CANDIDATE_LIMIT','Import a smaller resume (at most 400 items)')
    for candidate in candidates:
        data = candidate['data']
        # Derived or normalised values (dates, inferred categories, lists) never appear verbatim in the source.
        candidate['evidence'] = {field:evidence_for(value,text) for field,value in data.items()
                                 if field not in ('bullets','provenance','legacy_fields','angles','tags') and field not in DERIVED_FIELDS}
        candidate['evidence']['bullets'] = {point['id']:evidence_for(point['text'],text) for point in data.get('bullets',[])}
    return candidates


DERIVED_FIELDS = {'start','end','current','dates_text','category','level','skills'}


def _core(value):
    """Organisation/institution core: drop parentheticals and anything after a location separator."""
    text = re.sub(r'\([^)]*\)', ' ', str(value or ''))
    return normalized(re.split(r'\s[·|•–—,]\s|,', text)[0])


def _identity(kind,data):
    keys = {'experience':('organisation','title'), 'education':('institution','qualification'),
            'project':('name',), 'skill':('name',), 'certification':('issuer','name'), 'award':('awarder','title'),
            'volunteering':('organisation','title'),'custom':('title','heading')}[kind]
    return tuple(_core(data.get(key,'')) if key in ('organisation','institution','issuer','awarder') else normalized(data.get(key,''))
                 for key in keys)


def _same_start(left,right):
    # Compare by year, and only when both sides have one: "2023" and "2023-07" are the same job.
    a, b = (left or {}).get('start'), (right or {}).get('start')
    return not a or not b or str(a)[:4] == str(b)[:4]


def match_candidates(candidates, items, basics=None, basics_revision=0):
    result = deepcopy(candidates)
    for candidate in result:
        if candidate['kind']=='basics':
            candidate['match'] = {'status':'update','basics_revision':basics_revision,
                'conflicts':{field:{'existing':(basics or {}).get(field), 'incoming':value} for field,value in candidate['data'].items() if (basics or {}).get(field) not in (None,'',[]) and (basics or {}).get(field)!=value}}
            continue
        matches = [item for item in items if item['kind']==candidate['kind'] and not item.get('archived_at') and
                   ((_identity(item['kind'],item['data'])==_identity(candidate['kind'],candidate['data']) and _same_start(item['data'],candidate['data']))
                    or item['id']==candidate.get('source_item_id'))]
        options = [{'item_id':item['id'],'item_revision':item['revision'], 'label':item['data'].get('title') or item['data'].get('name') or item['data'].get('qualification') or item['kind']} for item in matches]
        if len(matches)>1: candidate['match']={'status':'ambiguous','options':options}
        elif matches:
            old = matches[0]['data']
            same = {normalized(point['text']) for point in old.get('bullets',[])} == {normalized(point['text']) for point in candidate['data'].get('bullets',[])}
            candidate['match'] = {'status':'duplicate' if same else 'update', **options[0]}
        else: candidate['match']={'status':'new'}
    return result


DATE_FIELDS = ('start','end','current','dates_text')


def _has_dates(data):
    return bool(data.get('start') or data.get('end') or data.get('current') is True or data.get('dates_text'))


def _merge_dates(result, incoming, conflicts):
    """Dates merge as one unit, so a merge can never make an entry both current and ended, or end before it starts.

    No dates on file: take the incoming dates whole. No incoming dates: keep the ones on file. Both, and different: keep
    the ones on file and report each differing field as a conflict."""
    if not _has_dates(incoming):
        return
    if not _has_dates(result):
        for field in DATE_FIELDS:
            if field in incoming: result[field] = deepcopy(incoming[field])
        return
    for field in DATE_FIELDS:
        old, new = result.get(field), incoming.get(field)
        if field == 'current': old, new = bool(old), bool(new)
        elif new in (None, ''): continue
        if old != new: conflicts[field] = {'existing': result.get(field), 'incoming': deepcopy(incoming.get(field))}


def additive_merge(existing, incoming):
    """Never replace nonempty facts, IDs or existing wording metadata."""
    result, conflicts = deepcopy(existing), {}
    _merge_dates(result, incoming, conflicts)
    for field,value in incoming.items():
        if field in ('bullets','provenance','legacy_fields','angles',*DATE_FIELDS): continue
        current = result.get(field)
        if current in (None,'',[],{}): result[field]=deepcopy(value)
        elif field in ('skills','tags') and isinstance(value,list): result[field]=list(dict.fromkeys([*current,*value]))
        elif current!=value and value not in (None,'',[],{}): conflicts[field]={'existing':current,'incoming':deepcopy(value)}
    points = result.setdefault('bullets',[])
    for point in incoming.get('bullets',[]):
        found = next((old for old in points if normalized(old['text'])==normalized(point['text'])),None)
        if found is None:
            new = deepcopy(point)
            if any(old['id']==new['id'] for old in points): new['id']='b_'+uuid5(NAMESPACE_URL,new['id']+new['text']).hex
            points.append(new)
        else:
            for field in ('tags','skills'): found[field]=list(dict.fromkeys([*found.get(field,[]),*point.get(field,[])]))
            alternatives = found.setdefault('alternatives',[])
            wordings = {normalized(found['text']),*(normalized(version['text']) for version in alternatives)}
            for version in point.get('alternatives',[]):
                if normalized(version['text']) not in wordings:
                    new=deepcopy(version)
                    if any(old['id']==new['id'] for old in alternatives) or new['id']==found['id']: new['id']='v_'+uuid5(NAMESPACE_URL,new['id']+new['text']).hex
                    alternatives.append(new); wordings.add(normalized(version['text']))
    for field,provenance in incoming.get('provenance',{}).items():
        if field not in existing or existing[field] in (None,'',[],{}): result.setdefault('provenance',{})[field]=deepcopy(provenance)
    for field in ('angles','legacy_fields'):
        if not result.get(field) and incoming.get(field): result[field]=deepcopy(incoming[field])
    return result, conflicts
