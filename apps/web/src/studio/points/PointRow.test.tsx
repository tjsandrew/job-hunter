import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { content, current, Harness, linkedEntry, readyBank } from './testkit';

vi.mock('../../api', async importOriginal => {
  const original = await importOriginal<typeof import('../../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map(key => [key, vi.fn()])) };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const texts = () => screen.getAllByRole('textbox').filter(el => el.tagName === 'TEXTAREA').map(el => (el as HTMLTextAreaElement).value);
const menuLabels = () => within(screen.getByRole('menu', { name: 'Point actions' })).getAllByRole('menuitem').map(el => el.textContent);

describe('point row controls', () => {
  it('shows move and more buttons for every point without hovering', () => {
    render(<Harness initial={content()} bank={readyBank()} />);
    expect(screen.getAllByRole('button', { name: 'Move point up' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'Move point down' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'More actions for this point' })).toHaveLength(3);
  });

  it('moves points with the arrow buttons, keeps sources aligned, and disables the ends', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    const ups = () => screen.getAllByRole('button', { name: 'Move point up' }), downs = () => screen.getAllByRole('button', { name: 'Move point down' });
    expect(ups()[0]).toBeDisabled(); expect(downs()[2]).toBeDisabled(); expect(ups()[1]).toBeEnabled();
    await user.click(downs()[0]);
    expect(texts()).toEqual(['Wrote a new thing here', 'Built FastAPI services', 'Mentored two interns']);
    const entry = current(screen).sections[0].entries[0];
    expect(entry.bullet_sources?.map(source => source?.bullet_id ?? null)).toEqual([null, 'b1', 'b3']);
    await user.click(ups()[2]);
    expect(texts()).toEqual(['Wrote a new thing here', 'Mentored two interns', 'Built FastAPI services']);
    expect(current(screen).sections[0].entries[0].bullet_sources).toHaveLength(3);
  });

  it('moves the focused point with Alt+Arrow and keeps focus on it', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    screen.getByRole('textbox', { name: 'Bullet 1' }).focus();
    await user.keyboard('{Alt>}{ArrowDown}{/Alt}');
    expect(texts()[1]).toBe('Built FastAPI services');
    expect(screen.getByRole('textbox', { name: 'Bullet 2' })).toHaveFocus();
    await user.keyboard('{Alt>}{ArrowUp}{/Alt}');
    expect(texts()[0]).toBe('Built FastAPI services');
    await user.keyboard('{Alt>}{ArrowUp}{/Alt}');
    expect(texts()[0]).toBe('Built FastAPI services');
  });

  it('opens the same menu from the more button and from right-click', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[0]);
    const fromButton = menuLabels();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    await user.pointer({ keys: '[MouseRight]', target: screen.getByRole('textbox', { name: 'Bullet 1' }) });
    expect(menuLabels()).toEqual(fromButton);
    expect(fromButton).toEqual(['Versions▸', 'Move down', 'Remove from resume']);
  });

  it('opens the menu from the keyboard and navigates it with arrows', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    screen.getByRole('textbox', { name: 'Bullet 1' }).focus();
    await user.keyboard('{Shift>}{F10}{/Shift}');
    const menu = screen.getByRole('menu', { name: 'Point actions' });
    expect(within(menu).getAllByRole('menuitem')[0]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Move down' })).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: /Versions/ })).toHaveFocus();
    await user.keyboard('{ArrowRight}');
    const sub = await screen.findByRole('menu', { name: 'Versions' });
    expect(within(sub).getAllByRole('menuitem')[0]).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', { name: 'Versions' })).toBeNull();
    expect(screen.getByRole('menu', { name: 'Point actions' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('runs Move up and Remove from the menu', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[2]);
    await user.click(screen.getByRole('menuitem', { name: 'Move up' }));
    expect(texts()).toEqual(['Built FastAPI services', 'Mentored two interns', 'Wrote a new thing here']);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[0]);
    await user.click(screen.getByRole('menuitem', { name: 'Remove from resume' }));
    expect(texts()).toEqual(['Mentored two interns', 'Wrote a new thing here']);
    expect(current(screen).sections[0].entries[0].bullet_sources?.map(source => source?.bullet_id ?? null)).toEqual(['b3', null]);
  });

  it('swaps in another version from Versions and marks the current one', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[0]);
    await user.click(screen.getByRole('menuitem', { name: /Versions/ }));
    const sub = screen.getByRole('menu', { name: 'Versions' });
    const items = within(sub).getAllByRole('menuitem');
    expect(items.map(el => el.textContent)).toEqual(['Version 1: Built FastAPI services✓', 'Version 2: Designed FastAPI services at scale']);
    expect(items[0]).toHaveAttribute('aria-current', 'true');
    await user.click(items[1]);
    expect(texts()[0]).toBe('Designed FastAPI services at scale');
    expect(current(screen).sections[0].entries[0].bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: 'v1', base_text: 'Designed FastAPI services at scale' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('shows only the options that apply to a point written in the resume', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[1]);
    expect(menuLabels()).toEqual(['Move up', 'Move down', 'Remove from resume', 'Save to profile▸']);
    await user.click(screen.getByRole('menuitem', { name: /Save to profile/ }));
    expect(within(screen.getByRole('menu', { name: 'Save to profile' })).getAllByRole('menuitem').map(el => el.textContent)).toEqual(['Save as new point…']);
  });

  it('offers Update and Save as new version only once a linked point is edited, and hides Versions when there are none', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[2]);
    expect(menuLabels()).toEqual(['Move up', 'Remove from resume']);
    await user.keyboard('{Escape}');
    await user.type(screen.getByRole('textbox', { name: 'Bullet 3' }), ' abroad');
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[2]);
    await user.click(screen.getByRole('menuitem', { name: /Save to profile/ }));
    expect(within(screen.getByRole('menu', { name: 'Save to profile' })).getAllByRole('menuitem').map(el => el.textContent)).toEqual(['Update in profile', 'Save as new version', 'Save as new point…']);
  });

  it('shows the same options as a bottom sheet with Save to profile as a section on narrow screens', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn() }));
    const user = userEvent.setup();
    const entry = { ...linkedEntry(), bullets: ['Built FastAPI services edited', 'x', 'y'] };
    render(<Harness initial={content([entry])} bank={readyBank()} />);
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[0]);
    const sheet = screen.getByRole('menu', { name: 'Point actions' });
    expect(sheet).toHaveClass('point-sheet');
    expect(within(screen.getByRole('group', { name: 'Save to profile' })).getAllByRole('menuitem').map(el => el.textContent)).toEqual(['Update in profile', 'Save as new version', 'Save as new point…']);
    expect(within(screen.getByRole('group', { name: 'Versions' })).getAllByRole('menuitem')).toHaveLength(2);
  });
});
