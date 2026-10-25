import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Me } from '../types';
import { PlanPanel, PlanPill, resetLabel } from './PlanPanel';

afterEach(() => cleanup());
const me = (over: Partial<Me> = {}, allowance: Partial<Me['allowance']> = {}): Me => ({ user_id: '1', display_name: 'Alice', plan: 'free', ai_available: true, allowance: { limit: 5, used: 2, remaining: 3, period: '2026-10', ...allowance }, ...over });

describe('plan', () => {
  it('says which day the uses come back', () => {
    expect(resetLabel('2026-10')).toBe('1 November');
    expect(resetLabel('2026-12')).toBe('1 January');
    expect(resetLabel('2026-01')).toBe('1 February');
    expect(resetLabel('nonsense')).toBe('the 1st of next month');
    expect(resetLabel(undefined)).toBe('the 1st of next month');
  });

  it('shows the plan and the uses left in the sidebar pill, and nothing before the account has loaded', async () => {
    const click = vi.fn();
    const { rerender } = render(<PlanPill me={null} open={false} onClick={click} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    rerender(<PlanPill me={me()} open={false} onClick={click} />);
    const pill = screen.getByRole('button', { name: /Free plan, 3 of 5 AI uses left/ });
    expect(pill).toHaveTextContent('Free plan');
    expect(pill).toHaveTextContent('3 of 5 AI uses left');
    await userEvent.setup().click(pill);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('shows the premium plan with its own limit', () => {
    render(<PlanPill me={me({ plan: 'premium' }, { limit: 50, used: 10, remaining: 40 })} open={false} onClick={() => undefined} />);
    expect(screen.getByRole('button')).toHaveTextContent('Premium plan');
    expect(screen.getByRole('button')).toHaveTextContent('40 of 50 AI uses left');
  });

  it('fills the pill bar with the uses spent, not the uses left', () => {
    const { container, rerender } = render(<PlanPill me={me({ plan: 'premium' }, { limit: 50, used: 9, remaining: 41 })} open={false} onClick={() => undefined} />);
    expect(container.querySelector('.plan-meter i')).toHaveStyle({ width: '18%' });
    rerender(<PlanPill me={me({}, { limit: 5, used: 0, remaining: 5 })} open={false} onClick={() => undefined} />);
    expect(container.querySelector('.plan-meter i')).toHaveStyle({ width: '0%' });
    rerender(<PlanPill me={me({}, { limit: 5, used: 5, remaining: 0 })} open={false} onClick={() => undefined} />);
    expect(container.querySelector('.plan-meter i')).toHaveStyle({ width: '100%' });
  });

  it('opens a panel with the plan, the uses, the reset day and the two plans side by side', () => {
    render(<PlanPanel me={me()} name="Alice Tan" email="alice@example.com" onClose={() => undefined} onProfile={() => undefined} onDemoUpgrade={() => undefined} />);
    const panel = screen.getByRole('dialog', { name: 'Your plan' });
    expect(panel).toHaveTextContent('Alice Tan');
    expect(panel).toHaveTextContent('alice@example.com');
    expect(panel).toHaveTextContent('2 used, 3 left');
    expect(panel).toHaveTextContent('Resets on 1 November');
    expect(panel).toHaveTextContent('Free (your plan)');
    expect(panel).toHaveTextContent('50 AI uses a month');
    expect(panel).toHaveTextContent('S$6.90');
    expect(panel).toHaveTextContent('Demo only. No payment is taken.');
  });

  it('upgrades only as a demo: a notice, no plan change, and the panel closes', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn(); const onDemoUpgrade = vi.fn();
    render(<PlanPanel me={me()} name="Alice" email="" onClose={onClose} onProfile={() => undefined} onDemoUpgrade={onDemoUpgrade} />);
    await user.click(screen.getByRole('button', { name: 'Upgrade to Premium' }));
    const dialog = screen.getByRole('dialog', { name: 'Upgrade to Premium' });
    expect(dialog).toHaveTextContent('Demo only');
    await user.click(screen.getByRole('button', { name: /^Yearly/ }));
    expect(screen.getByRole('button', { name: /^Yearly/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Upgrade (demo)' }));
    expect(onDemoUpgrade).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('lets the person back out of the upgrade dialog and close the panel with Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<PlanPanel me={me()} name="Alice" email="" onClose={onClose} onProfile={() => undefined} onDemoUpgrade={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'Upgrade to Premium' }));
    await user.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByRole('dialog', { name: 'Upgrade to Premium' })).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('offers no upgrade to a premium user, and sign out only when the app gives a way to', async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn(); const onProfile = vi.fn();
    const { rerender } = render(<PlanPanel me={me({ plan: 'premium' }, { limit: 50, used: 5, remaining: 45 })} name="Casey" email="" onClose={() => undefined} onProfile={onProfile} onSignOut={onSignOut} onDemoUpgrade={() => undefined} />);
    expect(screen.queryByRole('button', { name: 'Upgrade to Premium' })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Your plan' })).toHaveTextContent('You are on Premium');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await user.click(screen.getByRole('button', { name: 'Open my profile' }));
    expect(onSignOut).toHaveBeenCalled(); expect(onProfile).toHaveBeenCalled();
    rerender(<PlanPanel me={me()} name="Casey" email="" onClose={() => undefined} onProfile={onProfile} onDemoUpgrade={() => undefined} />);
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });

  it('marks a used-up month', () => {
    render(<PlanPanel me={me({}, { used: 5, remaining: 0 })} name="Alice" email="" onClose={() => undefined} onProfile={() => undefined} onDemoUpgrade={() => undefined} />);
    expect(screen.getByRole('dialog', { name: 'Your plan' })).toHaveTextContent('5 used, 0 left');
    expect(screen.getByRole('img', { name: '5 of 5 AI uses used' })).toBeInTheDocument();
  });
});
