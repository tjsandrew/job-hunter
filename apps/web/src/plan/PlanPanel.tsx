import { useEffect, useRef, useState } from 'react';
import type { Me } from '../types';
import { Icon } from '../ui';
import './plan.css';

// The plan limits mirror backend `preparation/allowance.py` (LIMITS); the price is a proposal (docs/design/13-PRICING-AND-PLANS.md).
// There is no billing yet: the upgrade button is a demo and never changes the plan.
export const FREE_LIMIT = 5;
export const PREMIUM_LIMIT = 50;
export const PREMIUM_MONTHLY = 'S$6.90';
export const PREMIUM_YEARLY = 'S$59';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export const planName = (plan?: string) => (plan === 'premium' ? 'Premium' : 'Free');

/** "2026-10" (the allowance month) becomes "1 November": the day the uses come back. */
export function resetLabel(period?: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period || '');
  const month = match ? Number(match[2]) : 0;
  return month >= 1 && month <= 12 ? `1 ${MONTHS[month % 12]}` : 'the 1st of next month';
}

export function PlanPill({ me, open, onClick }: { me: Me | null; open: boolean; onClick: () => void }) {
  if (!me) return null;
  const { used, remaining, limit } = me.allowance;
  const share = limit > 0 ? Math.max(0, Math.min(100, Math.round((used / limit) * 100))) : 0;     // the bar fills as uses are spent
  return <button type="button" className="plan-pill" aria-haspopup="dialog" aria-expanded={open} aria-label={`${planName(me.plan)} plan, ${remaining} of ${limit} AI uses left. Open plan details`} onClick={onClick}>
    <span className="plan-pill-plan">{planName(me.plan)} plan</span>
    <span className="plan-pill-uses">{remaining} of {limit} AI uses left</span>
    <span className="plan-meter" aria-hidden="true"><i style={{ width: `${share}%` }} /></span>
  </button>;
}

function useEscape(onClose: () => void) {
  const ref = useRef(onClose); ref.current = onClose;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); ref.current(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

export function UpgradeDialog({ onClose, onConfirm }: { onClose: () => void; onConfirm: () => void }) {
  const [yearly, setYearly] = useState(false);
  const dialog = useRef<HTMLElement | null>(null);
  useEscape(onClose);
  useEffect(() => { dialog.current?.focus(); }, []);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section ref={dialog} tabIndex={-1} className="modal upgrade-dialog" role="dialog" aria-modal="true" aria-labelledby="upgrade-title">
      <div className="modal-heading"><div><h2 id="upgrade-title">Upgrade to Premium</h2><p>More AI uses for fit checks, resume tailoring and cover letters.</p></div><button type="button" className="icon-button" aria-label="Close" onClick={onClose}><Icon name="close" /></button></div>
      <div className="upgrade-prices" role="group" aria-label="Billing period">
        <button type="button" className={`upgrade-price ${yearly ? '' : 'selected'}`} aria-pressed={!yearly} onClick={() => setYearly(false)}><b>Monthly</b><strong>{PREMIUM_MONTHLY}</strong><span>per month</span></button>
        <button type="button" className={`upgrade-price ${yearly ? 'selected' : ''}`} aria-pressed={yearly} onClick={() => setYearly(true)}><b>Yearly</b><strong>{PREMIUM_YEARLY}</strong><span>per year, about S$4.90 a month</span></button>
      </div>
      <ul className="upgrade-points">
        <li><Icon name="check" /> {PREMIUM_LIMIT} AI uses a month (Free has {FREE_LIMIT})</li>
        <li><Icon name="check" /> Fit checks, Tailor with AI and cover letters share one use per job</li>
        <li><Icon name="check" /> Repeating a job you already used costs nothing</li>
      </ul>
      <p className="demo-note"><b>Demo only.</b> Payments are not built. Pressing Upgrade shows this message again and does not change your plan.</p>
      <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose}>Not now</button><button type="button" className="button primary" onClick={onConfirm}>Upgrade (demo)</button></div>
    </section>
  </div>;
}

export function PlanPanel({ me, name, email, onClose, onProfile, onSignOut, onDemoUpgrade }: { me: Me; name: string; email: string; onClose: () => void; onProfile: () => void; onSignOut?: () => void; onDemoUpgrade: () => void }) {
  const [upgrading, setUpgrading] = useState(false);
  const panel = useRef<HTMLElement | null>(null);
  useEscape(() => { if (!upgrading) onClose(); });
  useEffect(() => { if (!upgrading) panel.current?.focus(); }, [upgrading]);
  const { used, remaining, limit, period } = me.allowance;
  const share = limit > 0 ? Math.max(0, Math.min(100, Math.round((used / limit) * 100))) : 0;
  const premium = me.plan === 'premium';
  // While the upgrade dialog is open the panel steps aside (it floats above the dialog's backdrop otherwise) and comes back after.
  return <>
    {!upgrading && <div className="plan-backdrop" role="presentation" onMouseDown={onClose} />}
    {!upgrading && <section ref={panel} tabIndex={-1} className="plan-panel" role="dialog" aria-label="Your plan">
      <div className="plan-panel-head">
        <div className="avatar" aria-hidden="true">{(name.match(/\b\w/g) || ['?']).slice(0, 2).join('').toUpperCase()}</div>
        <div className="plan-panel-who"><strong>{name}</strong><span>{email}</span></div>
        <span className={`plan-chip ${premium ? 'premium' : ''}`}>{planName(me.plan)} plan</span>
      </div>
      <div className="plan-usage">
        <div className="plan-usage-row"><strong>AI uses this month</strong><span>{used} used, {remaining} left</span></div>
        <div className="plan-bar" role="img" aria-label={`${used} of ${limit} AI uses used`}><i className={remaining === 0 ? 'full' : ''} style={{ width: `${share}%` }} /></div>
        <p>Resets on {resetLabel(period)} (Singapore time). One use covers one job for the month: a fit check, Tailor with AI or a cover letter for the same job count once, and repeating it is free. Rule-based tailoring never uses one.</p>
      </div>
      <div className="plan-compare">
        <div className={premium ? '' : 'current'}><b>Free{premium ? '' : ' (your plan)'}</b><strong>S$0</strong><span>{FREE_LIMIT} AI uses a month<br />Resume builder and tracker</span></div>
        <div className={premium ? 'current' : ''}><b>Premium{premium ? ' (your plan)' : ''}</b><strong>{PREMIUM_MONTHLY}<small> / month</small></strong><span>{PREMIUM_LIMIT} AI uses a month<br />{PREMIUM_YEARLY} a year</span></div>
      </div>
      {premium ? <p className="plan-note">You are on Premium. Thank you.</p> : <>
        <button type="button" className="button primary" onClick={() => setUpgrading(true)}>Upgrade to Premium</button>
        <p className="plan-note">Demo only. No payment is taken.</p>
      </>}
      <div className="plan-links"><button type="button" className="link-button" onClick={onProfile}>Open my profile</button>{onSignOut && <button type="button" className="link-button" onClick={onSignOut}>Sign out</button>}<button type="button" className="link-button" onClick={onClose}>Close</button></div>
    </section>}
    {upgrading && <UpgradeDialog onClose={() => setUpgrading(false)} onConfirm={() => { setUpgrading(false); onClose(); onDemoUpgrade(); }} />}
  </>;
}
