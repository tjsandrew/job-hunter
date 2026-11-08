import { useState } from 'react';
import { HttpError } from '../api';
import { Icon, Pill } from '../ui';
import type { ImportCandidate, ImportDecision, ImportEvidence, ImportResult, ProfileImport, ProfilePoint } from '../types';
import './import.css';

const labels: Record<string,string> = {name:'Name',headline:'Headline',email:'Email',phone:'Phone',location:'Location',summary:'Summary',links:'Links',title:'Title',organisation:'Organisation',qualification:'Qualification',institution:'Institution',grade:'Grade',role:'Role',url:'Link',issuer:'Issuer',awarder:'Awarded by',heading:'Heading',category:'Category',level:'Level',start:'Start date',end:'End date',current:'Current',skills:'Skills',dates_text:'Original date text'};
const hidden=new Set(['bullets','provenance','legacy_fields','angles','tags']);
const norm=(value:string)=>value.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu)?.join(' ') || '';
const title=(candidate:ImportCandidate)=>String(candidate.data.title || candidate.data.name || candidate.data.qualification || candidate.data.heading || candidate.kind);
// A point whose wording was cleared counts as deleted; the server rejects blank points.
function withoutBlankPoints(decision:ImportDecision):ImportDecision {
  const bullets=decision.data?.bullets;
  return Array.isArray(bullets) ? {...decision,data:{...decision.data,bullets:bullets.filter(point=>typeof point?.text!=='string' || point.text.trim())}} : decision;
}
function display(value:unknown) { return typeof value==='string' ? value : value == null ? '' : JSON.stringify(value); }
function initial(candidate:ImportCandidate):ImportDecision {
  const match=candidate.match;
  const action=candidate.kind==='basics' ? 'merge' : match.status==='update' && match.item_id ? 'merge' : match.status==='new' ? 'add' : 'skip';
  return {candidate_id:candidate.candidate_id,action,target_item_id:match.item_id,expected_revision:candidate.kind==='basics' ? match.basics_revision : match.item_revision,
    data:structuredClone(candidate.data),accepted_fields:candidate.kind==='basics' ? Object.keys(candidate.data).filter(field=>!match.conflicts?.[field] && candidate.data[field]!=null && display(candidate.data[field])!=='') : undefined};
}

export function ImportReview({record,onApply,onClose,onDiscard,onReload}: {record:ProfileImport;onApply:(decisions:ImportDecision[])=>Promise<ImportResult>;onClose:()=>void;onDiscard:()=>Promise<void>;onReload:()=>Promise<void>}) {
  const [decisions,setDecisions]=useState<Record<string,ImportDecision>>(()=>Object.fromEntries(record.candidates.map(candidate=>[candidate.candidate_id,initial(candidate)])));
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const change=(id:string,changes:Partial<ImportDecision>)=>setDecisions(current=>({...current,[id]:{...current[id],...changes}}));
  const accepted=Object.values(decisions).filter(decision=>decision.action!=='skip' && (decision.candidate_id!=='basics' || !!decision.accepted_fields?.length)).length;
  const ambiguous=record.candidates.some(candidate=>decisions[candidate.candidate_id].action==='merge' && candidate.kind!=='basics' && !decisions[candidate.candidate_id].target_item_id);
  const apply=async()=>{
    setBusy(true);setError('');
    try {await onApply(Object.values(decisions).map(withoutBlankPoints).map(decision=>decision.candidate_id==='basics' && !decision.accepted_fields?.length ? {...decision,action:'skip' as const} : decision));}
    catch(cause) {setError(cause instanceof HttpError && cause.status===409 ? cause.code==='PROFILE_EPOCH_CHANGED' ? 'Your profile was deleted after this review started. Nothing was applied; start a new import.' : 'Your profile changed elsewhere since this review. Nothing was applied. Reload the review and check your decisions again.' : (cause as Error).message);}
    finally {setBusy(false);}
  };
  return <div className="page-wrap bank-import-review">
    <div className="page-heading"><div><div className="eyebrow">RESUME IMPORT · {record.source_type.replace('_',' ')}</div><h1>Review what we found</h1><p>Nothing is added to your profile until you apply. Correct extracted facts and skip anything you don’t want.</p></div><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Back to profile</button></div>
    <div className="import-summary">{(['new','duplicate','update','ambiguous'] as const).map(status=><Pill key={status} color={status==='new' ? 'green' : 'neutral'}>{record.candidates.filter(candidate=>candidate.kind!=='basics' && candidate.match.status===status).length} {status}</Pill>)}<span>{record.parser === 'heuristic-v1' ? 'Parsed with local heuristics — review carefully.' : record.parser}</span></div>
    {record.error_code==='MODEL_FALLBACK' && <p className="bank-empty">The optional model was unavailable or returned invalid output. Local heuristics were used instead.</p>}
    {error && <div className="bank-error" role="alert">{error}<button type="button" className="button secondary small-button" disabled={busy} onClick={async()=>{setBusy(true);try{await onReload();}catch(cause){setError((cause as Error).message);}finally{setBusy(false);}}}>Reload review</button></div>}
    <div className="import-candidates">{record.candidates.filter(candidate=>!candidate.unsorted).map(candidate=><CandidateCard key={candidate.candidate_id} candidate={candidate} decision={decisions[candidate.candidate_id]} busy={busy} onChange={changes=>change(candidate.candidate_id,changes)} />)}</div>
    {record.candidates.some(candidate=>candidate.unsorted) && <section className="import-unsorted"><h2>Unsorted</h2><p>These entries could not be classified. Add them as custom sections or skip them.</p>{record.candidates.filter(candidate=>candidate.unsorted).map(candidate=><CandidateCard key={candidate.candidate_id} candidate={candidate} decision={decisions[candidate.candidate_id]} busy={busy} onChange={changes=>change(candidate.candidate_id,changes)} />)}</section>}
    <div className="import-apply-bar"><span role="status">{accepted} candidates selected{ambiguous ? ' · Choose a merge target first' : ''}</span><div className="bank-actions"><button type="button" className="button secondary" disabled={busy} onClick={async()=>{setBusy(true);try{await onDiscard();}catch(cause){setError((cause as Error).message);setBusy(false);}}}>Discard import</button><button type="button" className="button primary" disabled={busy || ambiguous || !accepted} onClick={apply}>{busy ? 'Applying…' : 'Apply to profile'} <Icon name="check" /></button></div></div>
  </div>;
}

function Evidence({quote,value}:{quote:ImportEvidence | null | undefined;value:unknown}) {
  const query=norm(display(value)),source=norm(quote?.text || '');
  const found=!!quote && !!query && (` ${source} `).includes(` ${query} `);
  return <>{quote && <blockquote className="import-evidence">From the source{quote.page ? ` · page ${quote.page}` : ''}: {quote.text}</blockquote>}{!found && display(value) && <p className="import-flag">Not found in the source, check this</p>}</>;
}

function CandidateCard({candidate,decision,busy,onChange}:{candidate:ImportCandidate;decision:ImportDecision;busy:boolean;onChange:(changes:Partial<ImportDecision>)=>void}) {
  const data=decision.data || candidate.data;
  const basics=candidate.kind==='basics';
  const points=(data.bullets || []) as ProfilePoint[];
  const updateField=(field:string,value:unknown)=>onChange({data:{...data,[field]:value}});
  const fields=Object.keys(data).filter(field=>!hidden.has(field));
  return <article className={`panel import-candidate ${decision.action==='skip' ? 'is-skipped' : ''}`} aria-label={basics ? 'Imported personal details' : title(candidate)}>
    <div className="import-candidate-head"><div><div className="bank-actions"><Pill>{candidate.kind}</Pill><Pill color={candidate.match.status==='duplicate' ? 'neutral' : 'amber'}>{candidate.match.status}</Pill></div><h2>{basics ? 'Personal details' : title(candidate)}</h2></div>{!basics && <div className="import-decisions" role="group" aria-label={`Decision for ${title(candidate)}`}>{(['add','merge','skip'] as const).map(action=><button type="button" key={action} disabled={busy || action==='merge' && !candidate.match.item_id && !candidate.match.options?.length} aria-pressed={decision.action===action} onClick={()=>onChange({action})}>{action[0].toUpperCase()+action.slice(1)}</button>)}</div>}</div>
    {candidate.match.options && decision.action==='merge' && <label className="field"><span>Merge target</span><select aria-label={`Merge target for ${title(candidate)}`} value={decision.target_item_id || ''} disabled={busy} onChange={event=>{const match=candidate.match.options!.find(option=>option.item_id===event.target.value);onChange({target_item_id:match?.item_id,expected_revision:match?.item_revision});}}><option value="">Choose an existing item…</option>{candidate.match.options.map(match=><option key={match.item_id} value={match.item_id}>{match.label} · revision {match.item_revision}</option>)}</select></label>}
    <fieldset disabled={busy || !basics && decision.action==='skip'}><div className="form-grid">{fields.map(field=>{
      const value=data[field],conflict=candidate.match.conflicts?.[field];
      const isList=Array.isArray(value),isObject=!!value && typeof value==='object' && !isList;
      const text=display(value),label=labels[field] || field;
      return <div className="import-field" key={field}>
        {basics && !conflict && <label className="import-accept"><input type="checkbox" checked={decision.accepted_fields?.includes(field) || false} onChange={event=>onChange({accepted_fields:event.target.checked ? [...(decision.accepted_fields || []),field] : (decision.accepted_fields || []).filter(key=>key!==field)})} />Use imported {label.toLowerCase()}</label>}
        {conflict && <div className="import-conflict">Current: {display(conflict.existing)}<label><span>{label} conflict</span><select aria-label={`${label} conflict`} value={decision.accepted_fields?.includes(field) ? 'use' : 'keep'} onChange={event=>onChange({accepted_fields:event.target.value==='use' ? [...new Set([...(decision.accepted_fields || []),field])] : (decision.accepted_fields || []).filter(key=>key!==field)})}><option value="keep">Keep current</option><option value="use">Use imported</option></select></label></div>}
        {typeof value==='boolean' ? <label className="bank-check"><input type="checkbox" checked={value} onChange={event=>updateField(field,event.target.checked)} />{label}</label> : (isList || isObject) ? <JsonField label={`${basics ? 'Imported ' : ''}${label}`} value={value} onValid={next=>updateField(field,next)} /> : <label className="field"><span>{label}</span><textarea aria-label={`${basics ? 'Imported ' : ''}${label}`} rows={field==='summary' ? 3 : 1} value={text} onChange={event=>updateField(field,event.target.value)} /></label>}
        {field in candidate.evidence && <Evidence quote={candidate.evidence[field] as ImportEvidence | null} value={value}/>}
      </div>;
    })}</div>
    {!!points.length && <div className="import-points"><h3>Points</h3>{points.map((point,index)=><div key={point.id} className="import-point"><div className="import-point-row"><label className="field"><span>Point {index+1} wording</span><textarea maxLength={4000} value={point.text} rows={2} onChange={event=>updateField('bullets',points.map((row,position)=>position===index ? {...row,text:event.target.value} : row))}/></label><button type="button" className="icon-button" aria-label={`Delete point ${index+1}`} title="Delete point" onClick={()=>updateField('bullets',points.filter((_,position)=>position!==index))}><Icon name="trash" /></button></div><Evidence quote={(candidate.evidence.bullets as Record<string,ImportEvidence | null> | undefined)?.[point.id]} value={point.text}/></div>)}</div>}
    </fieldset>
    {decision.action==='merge' && !basics && <p className="bank-empty">Merge fills empty fields and adds new points. Existing facts, IDs and wordings are kept; conflicting values will be reported.</p>}
  </article>;
}

function JsonField({label,value,onValid}:{label:string;value:unknown;onValid:(value:unknown)=>void}) {
  const [text,setText]=useState(()=>display(value)),[invalid,setInvalid]=useState(false);
  return <label className="field"><span>{label} (JSON)</span><textarea aria-label={label} aria-invalid={invalid} rows={2} value={text} onChange={event=>{setText(event.target.value);try{onValid(JSON.parse(event.target.value));setInvalid(false);}catch{setInvalid(true);}}} />{invalid && <small role="alert">Not valid JSON yet; the last valid value is kept.</small>}</label>;
}
