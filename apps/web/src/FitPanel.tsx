import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { api, HttpError } from './api';
import type { FitAnalysis, FitResult, FitVerdict } from './types';
import { Loading } from './ui';
import './fit.css';

const POLL_MS = 2500;
const ERRORS: Record<string, string> = {
  MODEL_UNAVAILABLE: 'The AI model could not be reached. Please try again in a moment.',
  NO_REQUIREMENTS: 'No requirements could be found in this listing, so there is nothing to compare your profile with.',
  TIMEOUT: 'The analysis took too long. Please try again.',
  INVALID_RESULT: 'The AI answer could not be checked, so it was not used. Please try again.',
};

type Group = { key: string; title: string; icon: string; verdicts: FitVerdict[] };
const GROUPS: Group[] = [
  { key: 'met', title: 'Your profile shows', icon: 'ok', verdicts: ['met', 'partly'] },
  { key: 'gap', title: 'Not evidenced in your profile', icon: 'no', verdicts: ['not_evidenced'] },
  { key: 'judge', title: 'Needs your judgement', icon: 'ask', verdicts: ['needs_judgement'] },
];

/** Small round icons in the same style as the walkthrough; local to this panel so the shared icon set stays as it is. */
const FIT_ICONS: Record<string, ReactNode> = {
  spark: <><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /><path d="M18.5 16.5v3M17 18h3" /></>,
  ok: <><circle cx="12" cy="12" r="9" /><path d="M8 12.5l2.7 2.7L16 9.5" /></>,
  no: <><circle cx="12" cy="12" r="9" /><path d="M9 9l6 6M15 9l-6 6" /></>,
  ask: <><circle cx="12" cy="12" r="9" /><path d="M9.7 9.6a2.4 2.4 0 1 1 3.5 2.1c-.8.4-1.2 1-1.2 1.7" /><path d="M12 16.9h.01" /></>,
  bulb: <><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-3.6 10.8c.4.4.6.9.6 1.4V16h6v-.8c0-.5.2-1 .6-1.4A6 6 0 0 0 12 3z" /></>,
};
function FitIcon({ name }: { name: string }) {
  return <svg className="fit-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{FIT_ICONS[name]}</svg>;
}

function Result({ result, stale }: { result: FitResult; stale: boolean }) {
  const { coverage } = result;
  const gaps = result.verdicts.filter((verdict) => verdict?.verdict === 'not_evidenced').length;
  const tone = coverage.percent === null ? 'none' : coverage.percent >= 70 ? 'high' : coverage.percent >= 40 ? 'mid' : 'low';
  return <div className="fit-result">
    {stale && <p className="fit-note" role="status">Your profile changed after this analysis. Run it again to include the changes.</p>}
    <div className={`fit-score ${tone}`}>
      {coverage.percent === null
        ? <div className="fit-score-main"><strong>No score</strong><span>Too few requirements could be checked to give a fair percentage.</span></div>
        : <div className="fit-score-main"><strong>{coverage.percent}%</strong><span>of this job's must-have requirements are evidenced in your profile</span></div>}
      {coverage.percent !== null && <div className="fit-meter" aria-hidden="true"><i style={{ width: `${coverage.percent}%` }} /></div>}
      <div className="fit-pills">
        <span className="fit-pill met"><FitIcon name="ok" />{coverage.met} met</span>
        {coverage.partly > 0 && <span className="fit-pill partly"><FitIcon name="ok" />{coverage.partly} partly</span>}
        {gaps > 0 && <span className="fit-pill gap"><FitIcon name="no" />{gaps} not evidenced</span>}
        {coverage.needs_judgement > 0 && <span className="fit-pill judge"><FitIcon name="ask" />{coverage.needs_judgement} needs your judgement</span>}
      </div>
      <small>{coverage.met} met, {coverage.partly} partly, out of {coverage.considered} checked. This is not a chance of being hired.</small>
    </div>
    {GROUPS.map((group) => {
      const rows = result.requirements.map((requirement, index) => ({ requirement, verdict: result.verdicts[index] })).filter(({ verdict }) => verdict && group.verdicts.includes(verdict.verdict));
      if (!rows.length) return null;
      return <section key={group.key} className={`fit-group ${group.key}`} aria-label={group.title}>
        <h4><FitIcon name={group.icon} /> {group.title} <span className="fit-count">{rows.length}</span></h4>
        <ul>{rows.map(({ requirement, verdict }) => <li key={requirement.text}>
          <span>{requirement.text}{requirement.importance === 'nice' && <em> (nice to have)</em>}{verdict.verdict === 'partly' && <em> (partly)</em>}</span>
          {verdict.note && <small>{verdict.note}</small>}
          {verdict.evidence.length > 0 && <small className="fit-evidence">From your profile: {verdict.evidence.map((id) => result.evidence[id] ?? id).join(' · ')}</small>}
        </li>)}</ul>
      </section>;
    })}
    {result.suggestions.length > 0 && <section className="fit-suggestions" aria-label="Suggestions">
      <h4><FitIcon name="bulb" /> Suggestions</h4>
      <ul>{result.suggestions.map((suggestion) => <li key={suggestion.text}>{suggestion.text}</li>)}</ul>
      <small>Only add something if it is true for you.</small>
    </section>}
  </div>;
}

export function FitPanel({ jobId, available, remaining, onUsed }: { jobId: string; available: boolean; remaining: number; onUsed: () => void }) {
  const [analysis, setAnalysis] = useState<FitAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const settled = useRef<string | null>(null);

  const apply = useCallback((next: FitAnalysis) => {
    setAnalysis(next);
    if (next.status === 'ready' && settled.current !== next.id) { settled.current = next.id; onUsed(); }
  }, [onUsed]);

  useEffect(() => {
    let cancelled = false;
    setAnalysis(null); setError(''); setLoading(true);
    api.jobFit(jobId).then((found) => { if (!cancelled) apply(found); })
      .catch((cause) => { if (!cancelled && !(cause instanceof HttpError && cause.status === 404)) setError(cause instanceof Error ? cause.message : 'Could not load the analysis.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [jobId, apply]);

  const id = analysis?.status === 'pending' ? analysis.id : null;
  useEffect(() => {
    if (!id) return;
    const timer = window.setInterval(() => {
      api.fit(id).then(apply).catch((cause) => setError(cause instanceof Error ? cause.message : 'Could not check the analysis.'));
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [id, apply]);

  const start = async () => {
    setBusy(true); setError('');
    try { apply(await api.startFit(jobId)); }
    catch (cause) { setError(cause instanceof HttpError && cause.status === 409 ? 'Confirm your profile first, then check your fit.' : cause instanceof Error ? cause.message : 'Could not start the analysis.'); }
    finally { setBusy(false); }
  };

  const pending = analysis?.status === 'pending';
  const hasSlot = remaining > 0 || analysis?.status === 'ready';
  return <section className="fit-panel" aria-label="Fit analysis">
    <div className="fit-head">
      <div className="fit-title"><span className="fit-badge"><FitIcon name="spark" /></span><div><div className="eyebrow">FIT WITH YOUR PROFILE</div><h3>How well does your profile cover this job?</h3></div></div>
      <button type="button" className="button secondary" disabled={!available || busy || pending || loading || !hasSlot} onClick={start}>
        {analysis?.status === 'ready' ? 'Run again' : 'Check my fit'}
      </button>
    </div>
    {!available && <p className="fit-note">AI is not available right now.</p>}
    {available && !hasSlot && <p className="fit-note">You have used all your AI uses for this month.</p>}
    {loading && <Loading label="Loading…" />}
    {pending && <Loading label="Reading the job and your profile. This takes about 30 seconds…" />}
    {error && <div className="alert" role="alert">{error}</div>}
    {analysis?.status === 'failed' && <div className="alert" role="alert">{ERRORS[analysis.error_code ?? ''] ?? 'The analysis could not be completed. Please try again.'}</div>}
    {analysis?.status === 'ready' && analysis.result && <Result result={analysis.result} stale={analysis.stale} />}
  </section>;
}
