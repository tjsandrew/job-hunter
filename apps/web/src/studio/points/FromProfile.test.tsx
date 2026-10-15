import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api, HttpError } from '../../api';
import { resetBankCache } from './bank';
import { content, current, educationItem, experienceItem, failedBank, Harness, linkedEntry, makeBank, otherItem, readyBank } from './testkit';
import { SectionEditor } from '../SectionEditor';
import type { ProfileItem } from '../../types';

vi.mock('../../api', async importOriginal => {
  const original = await importOriginal<typeof import('../../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map(key => [key, vi.fn()])) };
});
const mockApi = vi.mocked(api);
beforeEach(() => { vi.resetAllMocks(); resetBankCache(); });
afterEach(cleanup);

describe('More from this job in your profile', () => {
  it('lists points of the linked item that are not on the resume, and adds one with its source', async () => {
    const user = userEvent.setup();
    const entry = { ...linkedEntry(), bullets: ['Built FastAPI services'], bullet_sources: [{ bullet_id: 'b1', alternative_id: 'v1', base_text: 'Built FastAPI services' }] };
    render(<Harness initial={content([entry])} bank={readyBank()} />);
    const group = screen.getByRole('group', { name: 'More from this job in your profile' });
    expect(within(group).getByText('Made dashboards 4x faster')).toBeInTheDocument();
    expect(within(group).getByText('Mentored two interns')).toBeInTheDocument();
    expect(within(group).queryByText('Built FastAPI services')).toBeNull();
    await user.click(within(group).getByRole('button', { name: 'Add point: Made dashboards 4x faster' }));
    const next = current(screen).sections[0].entries[0];
    expect(next.bullets).toEqual(['Built FastAPI services', 'Made dashboards 4x faster']);
    expect(next.bullet_sources?.[1]).toEqual({ bullet_id: 'b2', alternative_id: null, base_text: 'Made dashboards 4x faster' });
    expect(within(screen.getByRole('group', { name: 'More from this job in your profile' })).queryByText('Made dashboards 4x faster')).toBeNull();
  });

  it('is absent for entries without a profile source and when every point is used', () => {
    const hand = { id: 'h', heading: 'Barista', subheading: '', dates: '', bullets: ['x'] };
    const all = { ...linkedEntry(), bullets: ['a', 'b', 'c'], bullet_sources: ['b1', 'b2', 'b3'].map(id => ({ bullet_id: id, base_text: 'a' })) };
    render(<Harness initial={content([hand, all])} bank={readyBank()} />);
    expect(screen.queryByRole('group', { name: 'More from this job in your profile' })).toBeNull();
  });
});

describe('Add from profile', () => {
  it('inserts a linked entry with structured dates and the chosen versions', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content([])} bank={readyBank()} />);
    await user.click(screen.getByRole('button', { name: 'Add from profile' }));
    const dialog = screen.getByRole('dialog', { name: 'Add from your profile' });
    expect(within(dialog).getByText('Backend Engineer · Harbour Metrics')).toBeInTheDocument();
    expect(within(dialog).queryByText(/BSc Computing/)).toBeNull();
    await user.click(within(dialog).getByRole('checkbox', { name: /Backend Engineer/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: 'Mentored two interns' }));
    await user.selectOptions(within(dialog).getByRole('combobox', { name: /Version of: Built FastAPI services/ }), 'v1');
    await user.click(within(dialog).getByRole('button', { name: 'Add to resume' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    const section = current(screen).sections[0];
    expect(section.kind).toBe('experience');
    expect(section.entries).toHaveLength(1);
    expect(section.entries[0]).toMatchObject({
      heading: 'Backend Engineer', subheading: 'Harbour Metrics · Singapore', dates: 'Jul 2023 – Present',
      bullets: ['Designed FastAPI services at scale', 'Made dashboards 4x faster'],
      source: { item_id: 'item-1', item_revision: 4 }, date_range: { start: '2023-07', end: null, current: true },
      bullet_sources: [{ bullet_id: 'b1', alternative_id: 'v1', base_text: 'Designed FastAPI services at scale' }, { bullet_id: 'b2', alternative_id: null, base_text: 'Made dashboards 4x faster' }],
    });
    expect(await screen.findByRole('status')).toHaveTextContent('from your profile');
  });

  it('offers items of the inferred kind only and keeps hand-typed entries working', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content([], 'Education')} bank={readyBank()} />);
    await user.click(screen.getByRole('button', { name: 'Add from profile' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/BSc Computing/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/Backend Engineer/)).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Add to resume' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: 'Add entry' }));
    expect(current(screen).sections[0].entries[0]).toMatchObject({ bullets: [''], heading: '' });
    expect(current(screen).sections[0].entries[0].bullet_sources).toBeUndefined();
  });

  it('is not offered for sections with no known kind', () => {
    render(<Harness initial={content([], 'Fun facts')} bank={readyBank()} />);
    expect(screen.queryByRole('button', { name: 'Add from profile' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Add entry' })).toBeInTheDocument();
  });

  it('is offered for a custom section whose kind was saved as custom, and for Skills it is not', () => {
    render(<Harness initial={content([], 'Fun facts', { kind: 'custom' })} bank={readyBank()} />);
    expect(screen.getByRole('button', { name: 'Add from profile' })).toBeInTheDocument();
    cleanup();
    render(<Harness initial={content([], 'Skills')} bank={readyBank()} />);
    expect(screen.queryByRole('button', { name: 'Add from profile' })).toBeNull();
  });
});

describe('profile loading', () => {
  it('loads the bank once for every section and enables the controls', async () => {
    mockApi.getBank.mockResolvedValue(makeBank());
    const two = { ...content(), sections: [content().sections[0], { ...content([], 'Education').sections[0], id: 's2' }] };
    render(<Harness initial={two} />);
    expect(screen.getAllByRole('button', { name: 'Add from profile' })[0]).toBeDisabled();
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Add from profile' })[0]).toBeEnabled());
    expect(mockApi.getBank).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('group', { name: 'More from this job in your profile' })).toBeInTheDocument();
  });

  it('disables the profile controls with a tooltip when the profile cannot be loaded, but editing still works', async () => {
    const user = userEvent.setup();
    mockApi.getBank.mockRejectedValue(new HttpError('down', 500));
    render(<Harness initial={content([{ ...linkedEntry() }])} />);
    const add = screen.getByRole('button', { name: 'Add from profile' });
    await waitFor(() => expect(add).toHaveAttribute('title', expect.stringContaining('could not be loaded')));
    expect(add).toBeDisabled();
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[1]);
    const save = screen.getByRole('menuitem', { name: /Save to profile/ });
    await user.click(save);
    expect(screen.getByRole('menuitem', { name: 'Save as new point…' })).toHaveAttribute('aria-disabled', 'true');
    await user.keyboard('{Escape}{Escape}');
    await user.type(screen.getByRole('textbox', { name: 'Bullet 2' }), '!');
    expect(current(screen).sections[0].entries[0].bullets[1]).toBe('Wrote a new thing here!');
  });

  it('also accepts a failed bank handle', () => {
    render(<Harness initial={content([linkedEntry()])} bank={failedBank()} />);
    expect(screen.getByRole('button', { name: 'Add from profile' })).toBeDisabled();
  });
});

describe('section controls', () => {
  it('hides and shows a section without removing it, and saves its inferred kind', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content([linkedEntry()])} bank={readyBank()} />);
    expect(screen.queryByText('Hidden on the resume')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Hide section on the resume' }));
    expect(current(screen).sections[0]).toMatchObject({ hidden: true, kind: 'experience' });
    expect(current(screen).sections[0].entries).toHaveLength(1);
    expect(screen.getByText('Hidden on the resume')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Bullet 1' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Show section on the resume' }));
    expect(current(screen).sections[0].hidden).toBe(false);
    expect(screen.queryByText('Hidden on the resume')).toBeNull();
  });

  it('typing new dates drops the structured date range', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content([linkedEntry()])} bank={readyBank()} />);
    await user.type(screen.getByRole('textbox', { name: 'Dates' }), '!');
    expect(current(screen).sections[0].entries[0].date_range).toBeUndefined();
    expect(current(screen).sections[0].entries[0].dates).toBe('Jul 2023 – Present!');
  });

  it('renders standalone without a bank prop on sections of a plain resume', async () => {
    mockApi.getBank.mockResolvedValue(makeBank([educationItem()]));
    render(<SectionEditor section={{ id: 's', title: 'Projects', entries: [] }} index={0} count={1} content={{ name: '', email: '', phone: '', location: '', summary: '', sections: [] }} onContent={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Add entry' })).toBeInTheDocument();
  });
});

describe('Add from profile: certifications, awards and volunteering', () => {
  const profileItem = (id: string, kind: ProfileItem['kind'], data: ProfileItem['data'], parent_id: string | null = null): ProfileItem => ({ ...educationItem(), id, kind, parent_id, data });
  const extras = [
    profileItem('cert-1', 'certification', { name: 'AWS Developer', issuer: 'Amazon', start: '2024-03', bullets: [] }),
    profileItem('award-1', 'award', { title: 'Hackathon winner', awarder: 'City Council', start: '2021', bullets: [] }),
    profileItem('vol-1', 'volunteering', { title: 'Mentor', organisation: 'Code Club', start: '2020', end: '2021', bullets: [{ id: 'vp1', text: 'Taught Python.', alternatives: [] }] }),
  ];

  it.each([['Certifications', 'AWS Developer', 'Amazon', 'certifications'], ['Awards', 'Hackathon winner', 'City Council', 'awards'], ['Volunteering', 'Mentor', 'Code Club', 'volunteering']])('%s: offers its items and adds an entry linked to the item', async (title, heading, subheading, kind) => {
    const user = userEvent.setup();
    render(<Harness initial={content([], title)} bank={readyBank([experienceItem(), ...extras])} />);
    await user.click(screen.getByRole('button', { name: 'Add from profile' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByText(/Backend Engineer/)).toBeNull();
    await user.click(within(dialog).getByRole('checkbox', { name: new RegExp(heading) }));
    await user.click(within(dialog).getByRole('button', { name: 'Add to resume' }));
    const entry = current(screen).sections[0].entries[0];
    expect([entry.heading, entry.subheading]).toEqual([heading, subheading]);
    expect(entry.source?.item_id).toBe(extras.find((row) => row.kind === ({ certifications: 'certification', awards: 'award', volunteering: 'volunteering' } as Record<string, string>)[kind])!.id);
  });

  it('lists a project under its job in an Experience section, and under the job heading in a Projects section', async () => {
    const user = userEvent.setup();
    const project = profileItem('proj-1', 'project', { name: 'Billing rewrite', bullets: [] }, 'item-1');
    const lone = profileItem('proj-2', 'project', { name: 'Pottery blog', bullets: [] });
    const bank = () => readyBank([experienceItem(), otherItem(), project, lone]);
    const { unmount } = render(<Harness initial={content([], 'Experience')} bank={bank()} />);
    await user.click(screen.getByRole('button', { name: 'Add from profile' }));
    let dialog = screen.getByRole('dialog');
    const names = within(dialog).getAllByRole('checkbox').map((box) => box.closest('label')!.textContent);
    expect(names.findIndex((text) => text?.includes('Billing rewrite'))).toBe(names.findIndex((text) => text?.includes('Backend Engineer')) + 1);
    expect(within(dialog).getByText('Project in this role')).toBeInTheDocument();
    expect(within(dialog).queryByText(/Pottery blog/)).toBeNull();
    await user.click(within(dialog).getByRole('checkbox', { name: /Billing rewrite/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Add to resume' }));
    expect(current(screen).sections[0].entries[0].heading).toBe('Billing rewrite');   // the resume stays flat
    unmount();

    render(<Harness initial={content([], 'Projects')} bank={bank()} />);
    await user.click(screen.getByRole('button', { name: 'Add from profile' }));
    dialog = screen.getByRole('dialog');
    const rows = [...dialog.querySelectorAll('.point-picker > div')].map((row) => row.textContent || '');
    expect(rows[0]).toContain('Pottery blog');
    expect(rows[1]).toMatch(/Backend Engineer/);
    expect(rows[2]).toContain('Project in this role');
    expect(rows[2]).toContain('Billing rewrite');
  });
});
