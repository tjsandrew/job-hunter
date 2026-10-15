"""Frozen local imports and one-transaction, idempotent review application."""
from copy import deepcopy
import logging
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from job_hunter.domain.models import Document, ProfileImport, ProfileItem, Upload, now_utc
from .. import services as bank
from ..schema import validate_item_data, Provenance
from . import (ImportFailure, extract_text, from_text, document_to_json_resume,
               heuristic_to_json_resume, json_resume_to_candidates, match_candidates,
               additive_merge, FakeModel, OllamaModel, BedrockModel, parse_with_model)
from .schema import validate_resume
from .docx import detect_resume_file, extract_docx


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def import_out(row):
    return {'id':str(row.id),'source_type':row.source_type,'status':row.status,'parser':row.parser,
            'profile_epoch':row.profile_epoch,'input_ref':row.input_ref,'candidates':row.candidates,
            'error_code':row.error_code,'created_at':row.created_at,'applied_at':row.applied_at,
            'result':row.applied_result}


def _get(db, import_id, lock=False):
    query=select(ProfileImport).where(ProfileImport.id==import_id,ProfileImport.user_id==bank._user_id(db))
    if lock: query=query.with_for_update()
    row=db.scalar(query)
    if row is None: raise bank.BankError(404,'NOT_FOUND','Resource not found')
    return row


def get_import(db,import_id):
    row=_get(db,import_id)
    output=import_out(row)
    if row.status=='ready':
        profile=bank._profile(db)
        output['candidates']=match_candidates(row.candidates,[bank.item_out(item) for item in bank._items(db)],profile.draft if profile else {},profile.revision if profile else 0)
        output['review_revision']=profile.bank_revision if profile else 0
    return output


def list_imports(db):
    rows=db.scalars(select(ProfileImport).where(ProfileImport.user_id==bank._user_id(db)).order_by(ProfileImport.created_at.desc()).limit(20)).all()
    return {'items':[{**import_out(row),'candidates':[]} for row in rows],'next_cursor':None}


def _flatten(value):
    if isinstance(value,str): return [value]
    if isinstance(value,dict): return [text for child in value.values() for text in _flatten(child)]
    if isinstance(value,list): return [text for child in value for text in _flatten(child)]
    return []


def _run(db,row,settings):
    try:
        if row.source_type=='upload':
            upload=db.scalar(select(Upload).where(Upload.id==row.upload_id,Upload.user_id==bank._user_id(db)))
            if upload is None: raise ImportFailure('SOURCE_DELETED','The source file is no longer available')
            data=Path(upload.file_path).read_bytes()
            if sha256(data).hexdigest()!=row.input_ref['sha256']: raise ImportFailure('SOURCE_CHANGED','The captured file changed')
            # Content decides the type: stored names and MIME types are not trusted.
            extracted=extract_text(data) if detect_resume_file(data)=='pdf' else extract_docx(data)
        elif row.source_type=='text':
            if row.input_payload is None: raise ImportFailure('INPUT_EXPIRED','The frozen input has expired')
            if sha256(row.input_payload.encode()).hexdigest()!=row.input_ref['sha256']: raise ImportFailure('SOURCE_CHANGED','Frozen text changed')
            extracted=from_text(row.input_payload,row.input_ref['sha256'])
        else:
            if row.input_payload is None: raise ImportFailure('INPUT_EXPIRED','The frozen input has expired')
            if sha256(canonical(row.input_payload)).hexdigest()!=row.input_ref['sha256']: raise ImportFailure('SOURCE_CHANGED','Frozen import input changed')
            resume=document_to_json_resume(row.input_payload) if row.source_type=='document' else validate_resume(deepcopy(row.input_payload))
            extracted=from_text('\n'.join(_flatten(row.input_payload)) or '{}',row.input_ref['sha256'])
        if row.source_type in ('upload','text'):
            model=None
            if settings.model_backend=='fake': model=FakeModel([heuristic_to_json_resume(extracted)])
            elif settings.model_backend=='ollama': model=OllamaModel(settings.ollama_url,settings.ollama_model)
            elif settings.model_backend=='bedrock': model=BedrockModel()
            resume,row.parser,row.error_code=parse_with_model(extracted,model,settings.model_backend)
        else: row.parser='document-v1' if row.source_type=='document' else 'json-resume-v1'
        candidates=json_resume_to_candidates(resume,extracted)
        current=bank._profile(db)
        row.candidates=match_candidates(candidates,[bank.item_out(item) for item in bank._items(db)], current.draft if current else {},current.revision if current else 0)
        row.status='ready'
    except (ImportFailure,ValueError,OSError) as exc:
        row.status='failed'; row.error_code=getattr(exc,'code','IMPORT_FAILED'); row.candidates=[]
        row.applied_result={'message':str(exc)}
    except Exception:
        # Third-party parsers can fail in unforeseen ways on hostile files; record a retryable failure, not a 500.
        logging.getLogger(__name__).exception('Profile import parsing failed')
        row.status='failed'; row.error_code='IMPORT_FAILED'; row.candidates=[]
        row.applied_result={'message':'This file could not be read. Try exporting it again as PDF or .docx.'}
    db.flush()
    return import_out(row)


def start_import(db,body,settings):
    supplied=[key for key in ('upload_id','document_id','json_resume','text') if body.get(key) is not None]
    if len(supplied)!=1: raise bank.BankError(422,'INVALID_IMPORT_SOURCE','Choose exactly one import source')
    source=supplied[0]
    profile=bank._profile(db,create=True,lock=True)
    payload=None
    upload_id=document_id=None
    if source=='upload_id':
        upload_id=body[source]
        upload=db.scalar(select(Upload).where(Upload.id==upload_id,Upload.user_id==bank._user_id(db)))
        if upload is None: raise bank.BankError(404,'NOT_FOUND','Resource not found')
        if not upload.sha256: raise bank.BankError(422,'UPLOAD_NOT_READY','Finish uploading the file first')
        ref={'upload_id':str(upload_id),'sha256':upload.sha256}
        source_type='upload'
    else:
        if source=='document_id':
            document_id=body[source]
            document=db.scalar(select(Document).where(Document.id==document_id,Document.user_id==bank._user_id(db),Document.kind=='resume'))
            if document is None: raise bank.BankError(404,'NOT_FOUND','Resource not found')
            payload=deepcopy(document.content)
            ref={'document_id':str(document_id),'document_revision':document.revision}
            source_type='document'
        else:
            payload=deepcopy(body[source]); ref={}; source_type='json_resume' if source=='json_resume' else 'text'
        encoded=payload.encode() if source_type=='text' else canonical(payload)
        if len(encoded)>1024*1024: raise bank.BankError(422,'INPUT_TOO_LARGE','Import input must be at most 1 MiB')
        ref['sha256']=sha256(encoded).hexdigest()
    row=ProfileImport(user_id=bank._user_id(db),source_type=source_type,upload_id=upload_id,document_id=document_id,
                      input_ref=ref,input_payload=payload,profile_epoch=profile.profile_epoch,parser='pending')
    db.add(row); db.flush()
    return _run(db,row,settings)


def retry_import(db,import_id,settings):
    profile=bank._profile(db,create=True,lock=True)
    row=_get(db,import_id,True)
    if row.profile_epoch!=profile.profile_epoch: raise bank.BankError(409,'PROFILE_EPOCH_CHANGED','Profile data was deleted; start a new import')
    if row.status!='failed': raise bank.BankError(409,'IMPORT_NOT_RETRYABLE','Only failed imports can be retried')
    row.error_code=None; row.applied_result=None
    return _run(db,row,settings)


def discard_import(db,import_id):
    bank._profile(db,create=True,lock=True)
    row=_get(db,import_id,True)
    if row.status=='applied': raise bank.BankError(409,'IMPORT_ALREADY_APPLIED','This import has already been applied')
    row.status='discarded'; row.input_payload=None; row.candidates=[]; row.applied_result=None
    return import_out(row)


def _with_provenance(candidate,data,import_id):
    result=deepcopy(data)
    evidence=candidate.get('evidence',{})
    for field,value in list(result.items()):
        if field in ('bullets','provenance','legacy_fields','angles','tags'): continue
        existing=result.setdefault('provenance',{}).get(field)
        if existing:
            Provenance.model_validate(existing)
            # Supplied provenance only stays import-backed if the value still matches its evidence.
            if existing.get('origin')=='import' and not bank._evidence_matches(value,existing):
                result['provenance'][field]={**existing,'origin':'user'}
            continue
        quote=evidence.get(field)
        source={'origin':'import' if quote and bank._evidence_matches(value,{'evidence':quote}) else 'user','import_id':str(import_id),'evidence':quote}
        result['provenance'][field]=source
    for point in result.get('bullets',[]):
        if point.get('provenance'):
            Provenance.model_validate(point['provenance'])
            if not bank._evidence_matches(point['text'],point['provenance']): point['provenance']['origin']='user'
        else:
            quote=evidence.get('bullets',{}).get(point['id'])
            point['provenance']={'origin':'import' if quote and bank._evidence_matches(point['text'],{'evidence':quote}) else 'user','import_id':str(import_id),'evidence':quote}
    return result


def apply_import(db,import_id,decisions,expected_profile_epoch):
    profile=bank._profile(db,create=True,lock=True)
    # The row is deliberately hard-deleted with profile data; the client-held
    # epoch permits a stale review to get an explicit fence error even then.
    if profile.profile_epoch!=expected_profile_epoch: raise bank.BankError(409,'PROFILE_EPOCH_CHANGED','Your profile data was deleted since this review began. Start a new import.')
    row=_get(db,import_id,True)
    if row.profile_epoch!=profile.profile_epoch: raise bank.BankError(409,'PROFILE_EPOCH_CHANGED','Start a new import after deleting profile data')
    if row.status=='applied': return row.applied_result
    if row.status!='ready': raise bank.BankError(409,'IMPORT_NOT_READY','This import is not ready to apply')
    candidates={candidate['candidate_id']:candidate for candidate in row.candidates}
    if len(decisions)!=len({decision['candidate_id'] for decision in decisions}) or any(decision['candidate_id'] not in candidates for decision in decisions):
        raise bank.BankError(422,'INVALID_IMPORT_DECISIONS','Use each known candidate at most once')
    counts={'added':0,'merged':0,'skipped':len(candidates)-len(decisions),'basics_updated':0}
    conflicts=[]; target_map={}; parents=[]
    original_revision=profile.bank_revision
    for decision in decisions:
        candidate=candidates[decision['candidate_id']]
        action=decision['action']
        if action=='skip': counts['skipped']+=1; continue
        data=deepcopy(decision.get('data') if decision.get('data') is not None else candidate['data'])
        if candidate['kind']=='basics':
            accepted=decision.get('accepted_fields') or []
            if not set(accepted)<=set(candidate['data']): raise bank.BankError(422,'INVALID_BASICS_FIELDS','Choose fields from the basics candidate')
            if accepted:
                expected=decision.get('expected_revision')
                if expected is None: expected=candidate['match']['basics_revision']
                if profile.revision!=expected: bank._conflict()
                updated={**profile.draft,**{field:data[field] for field in accepted}}
                bank.update_basics(db,updated,expected)
                provenance=deepcopy(profile.basics_provenance or {})
                for field in accepted:
                    quote=candidate['evidence'].get(field)
                    original=candidate.get('basics_provenance',{}).get(field)
                    if original:
                        Provenance.model_validate(original)
                        provenance[field]=deepcopy(original)
                        if data[field]!=candidate['data'].get(field) and not bank._evidence_matches(data[field],original): provenance[field]['origin']='user'
                    else:
                        provenance[field]={'origin':'import' if quote and bank._evidence_matches(data[field],{'evidence':quote}) else 'user','import_id':str(row.id),'evidence':quote}
                profile.basics_provenance=provenance
                counts['basics_updated']+=len(accepted)
            continue
        data=_with_provenance(candidate,data,row.id)
        if action=='add':
            out=bank.create_item(db,candidate['kind'],data,candidate.get('tags',[]))
            counts['added']+=1
            item=bank._item(db,UUID(out['id']))
            item.origin='import'; item.import_id=row.id
        elif action=='merge':
            if decision.get('target_item_id') is None or decision.get('expected_revision') is None:
                raise bank.BankError(422,'MERGE_TARGET_REQUIRED','Merge needs a target and its expected revision')
            item=bank._item(db,decision['target_item_id'],True)
            if item.kind!=candidate['kind']: raise bank.BankError(422,'INVALID_MERGE_KIND','Merge into an item of the same kind')
            if item.revision!=decision['expected_revision']: bank._conflict()
            merged,fields=additive_merge(item.data,data)
            out=bank.update_item(db,item.id,item.revision,{'data':merged,'tags':list(dict.fromkeys([*item.tags,*candidate.get('tags',[])]))})
            if fields: conflicts.append({'candidate_id':candidate['candidate_id'],'fields':fields})
            counts['merged']+=1
        else: raise bank.BankError(422,'INVALID_IMPORT_ACTION','Choose add, merge or skip')
        source_id=candidate.get('source_item_id')
        if source_id: target_map[source_id]=UUID(out['id'])
        if candidate.get('parent_source_id'): parents.append((UUID(out['id']),candidate['parent_source_id']))
    for item_id,parent_source in parents:
        parent_id=target_map.get(parent_source)
        if parent_id is None:
            try: parent_id=bank._item(db,UUID(parent_source)).id
            except (bank.BankError,ValueError):
                conflicts.append({'candidate_id':str(item_id),'fields':{'parent_id':{'existing':None,'incoming':'Parent was not accepted; project kept standalone'}}})
                continue
        item=bank._item(db,item_id,True)
        if item.parent_id is None:
            bank._parent(db,item.kind,parent_id); item.parent_id=parent_id
        elif item.parent_id!=parent_id:
            conflicts.append({'candidate_id':str(item_id),'fields':{'parent_id':{'existing':str(item.parent_id),'incoming':str(parent_id)}}})
    # One import apply is one bank edit, despite using shared validated writers.
    profile.bank_revision=original_revision+1
    row.status='applied'; row.applied_at=now_utc(); row.input_payload=None
    row.applied_result={'import_id':str(row.id),'counts':counts,'conflicts':conflicts,'bank_revision':profile.bank_revision}
    db.flush()
    return deepcopy(row.applied_result)
