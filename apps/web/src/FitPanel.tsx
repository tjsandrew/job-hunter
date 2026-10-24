import { useCallback, useEffect, useRef, useState } from 'react';
import { api, HttpError } from './api';
import type { FitAnalysis, FitResult, FitVerdict } from './types';
import { Icon, Loading } from './ui';
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
  { key: 'met', title: 'Your profile shows', icon: 'check', verdicts: ['met', 'partly'] },
  { key: 'gap', title: 'Not evidenced in your profile', icon: 'close', verdicts: ['not_evidenced'] },
  { key: 'judge', title: 'Needs your judgement', icon: 'help', verdicts: ['needs_judgement'] },
];

function Result({ result, stale }: { result: FitResult; stale: boolean }) {
  const { coverage } = result;
  return <div className="fit-result">
    {stale && <p className="fit-note" role="status">Your profile changed after this analysis. Run it again to include the changes.</p>}
    <div className="fit-score">
      {coverage.percent === null
        ? <div><strong>No score</strong><span>Too few requirements could be checked to give a fair percentage.</span></div>
        : <div><strong>{coverage.percent}%</strong><span>of this job's must-have requirements are evidenced in your profile</span></div>}
      <small>{coverage.met} met, {coverage.partly} partly, out of {coverage.considered} checked. This is not a chance of being hired.</small>
    </div>
    {GROUPS.map((group) => {
      const rows = result.requirements.map((requirement, index) => ({ requirement, verdict: result.verdicts[index] })).filter(({ verdict }) => verdict && group.verdicts.includes(verdict.verdict));
      if (!rows.length) return null;
      return <section key={group.key} className={`fit-group ${group.key}`} aria-label={group.title}>
        <h4><Icon name={group.icon} /> {group.title}</h4>
        <ul>{rows.map(({ requirement, verdict }) => <li key={requirement.text}>
          <span>{requirement.text}{requirement.importance === 'nice' && <em> (nice to have)</em>}{verdict.verdict === 'partly' && <em> (partly)</em>}</span>
          {verdict.note && <small>{verdict.note}</small>}
          {verdict.evidence.length > 0 && <small className="fit-evidence">From your profile: {verdict.evidence.map((id) => result.evidence[id] ?? id).join(' · ')}</small>}
        </li>)}</ul>
      </section>;
    })}
    {result.suggestions.length > 0 && <section className="fit-suggestions" aria-label="Suggestions">
      <h4>Suggestions</h4>
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
      <div><div className="eyebrow">FIT WITH YOUR PROFILE</div><h3>How well does your profile cover this job?</h3></div>
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
