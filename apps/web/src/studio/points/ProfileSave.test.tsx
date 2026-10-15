import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api, HttpError } from '../../api';
import type { ProfileItem } from '../../types';
import { content, current, educationItem, experienceItem, Harness, linkedEntry, readyBank } from './testkit';

vi.mock('../../api', async importOriginal => {
  const original = await importOriginal<typeof import('../../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map(key => [key, vi.fn()])) };
});
const mockApi = vi.mocked(api);
afterEach(cleanup);

let stored: ProfileItem;
const withBullets = (item: ProfileItem, bullets: ProfileItem['data']['bullets']): ProfileItem => ({ ...item, revision: item.revision + 1, data: { ...item.data, bullets } });
beforeEach(() => {
  vi.resetAllMocks();
  stored = experienceItem();
  mockApi.getItem.mockImplementation(async () => structuredClone(stored));
  mockApi.updatePoint.mockImplementation(async (_id, pointId, values) => { stored = withBullets(stored, stored.data.bullets.map(point => point.id === pointId ? { ...point, text: values.text } : point)); return structuredClone(stored); });
  mockApi.addAlternative.mockImplementation(async (_id, pointId, values) => { stored = withBullets(stored, stored.data.bullets.map(point => point.id === pointId ? { ...point, alternatives: [...point.alternatives, { id: 'v-new', text: values.text }] } : point)); return structuredClone(stored); });
  mockApi.addPoint.mockImplementation(async (id, values) => { stored = withBullets(stored, [...stored.data.bullets, { id: 'b-new', text: values.text, alternatives: [] }]); return structuredClone({ ...stored, id }); });
});

const openSaveMenu = async (user: ReturnType<typeof userEvent.setup>, point: number) => {
  await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[point]);
  await user.click(screen.getByRole('menuitem', { name: /Save to profile/ }));
};
const edit = async (user: ReturnType<typeof userEvent.setup>, label: string, suffix: string) => user.type(screen.getByRole('textbox', { name: label }), suffix);

describe('saving a point to the profile', () => {
  it('updates the profile with the current revision, then records the saved wording', async () => {
    const user = userEvent.setup();
    const bank = readyBank();
    render(<Harness initial={content()} bank={bank} />);
    await edit(user, 'Bullet 1', ' for 3 teams');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Built FastAPI services for 3 teams' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Updated in your profile.');
    const entry = current(screen).sections[0].entries[0];
    expect(entry.bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: null, base_text: 'Built FastAPI services for 3 teams' });
    expect(entry.source?.item_revision).toBe(5);
    expect(bank.refresh).toHaveBeenCalled();
    // Now the point matches its source again, so the profile options go away.
    await user.click(screen.getAllByRole('button', { name: 'More actions for this point' })[0]);
    expect(screen.queryByRole('menuitem', { name: /Save to profile/ })).toBeNull();
  });

  it('passes the alternative id when the point came from another version', async () => {
    const user = userEvent.setup();
    const entry = { ...linkedEntry(), bullets: ['Designed FastAPI services at scale', 'x', 'y'], bullet_sources: [{ bullet_id: 'b1', alternative_id: 'v1', base_text: 'Designed FastAPI services at scale' }, null, null] };
    render(<Harness initial={content([entry])} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Designed FastAPI services at scale!', alternative_id: 'v1' }));
  });

  it('does not touch the resume when the profile write fails', async () => {
    const user = userEvent.setup();
    mockApi.updatePoint.mockRejectedValue(new HttpError('Server is down', 500));
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Server is down');
    expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.base_text).toBe('Built FastAPI services');
  });

  it('explains a 409 from the server and offers Save as new version or Cancel', async () => {
    const user = userEvent.setup();
    mockApi.updatePoint.mockRejectedValue(new HttpError('Conflict', 409, 'REVISION_CONFLICT'));
    mockApi.getItem.mockResolvedValueOnce(structuredClone(stored)).mockImplementation(async () => withBullets(stored, stored.data.bullets.map(point => point.id === 'b1' ? { ...point, text: 'Built FastAPI services (edited elsewhere)' } : point)));
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'This point changed in your profile since you added it' });
    expect(dialog).toHaveTextContent('Built FastAPI services (edited elsewhere)');
    expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.base_text).toBe('Built FastAPI services');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(mockApi.addAlternative).not.toHaveBeenCalled();
  });

  it('detects changed profile wording before writing and saves as a new version from the conflict box', async () => {
    const user = userEvent.setup();
    stored = withBullets(stored, stored.data.bullets.map(point => point.id === 'b1' ? { ...point, text: 'Built FastAPI services v2' } : point));
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Built FastAPI services v2');
    expect(mockApi.updatePoint).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Save as new version' }));
    await waitFor(() => expect(mockApi.addAlternative).toHaveBeenCalledWith('item-1', 'b1', { expected_revision: 5, text: 'Built FastAPI services!' }));
    await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: 'v-new', base_text: 'Built FastAPI services!' }));
  });

  it('saves as a new version and points the bullet at the new version', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', ' fast');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Save as new version' }));
    await waitFor(() => expect(mockApi.addAlternative).toHaveBeenCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Built FastAPI services fast' }));
    await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: 'v-new', base_text: 'Built FastAPI services fast' }));
    expect(await screen.findByRole('status')).toHaveTextContent('new version');
  });

  const limitError = () => new HttpError('too many', 422, 'POINT_VERSION_LIMIT');

  it('opens the chooser on a version limit and resubmits Save as new version with the chosen id', async () => {
    const user = userEvent.setup();
    mockApi.addAlternative.mockRejectedValueOnce(limitError());
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', ' fast');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Save as new version' }));
    const dialog = await screen.findByRole('dialog', { name: 'Your profile keeps 5 versions of a point. Replace which one?' });
    expect(within(dialog).queryByRole('button', { name: "Don't keep the old wording" })).toBeNull();
    expect(within(dialog).getAllByRole('radio')).toHaveLength(1);
    expect(within(dialog).getByRole('button', { name: 'Replace selected version' })).toBeDisabled();
    expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.base_text).toBe('Built FastAPI services');
    await user.click(within(dialog).getByRole('radio', { name: /Designed FastAPI services at scale/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Replace selected version' }));
    await waitFor(() => expect(mockApi.addAlternative).toHaveBeenLastCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Built FastAPI services fast', replace_alternative_id: 'v1' }));
    await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.alternative_id).toBe('v-new'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('Update in profile offers "Don\'t keep the old wording" and resubmits with keep_previous false', async () => {
    const user = userEvent.setup();
    mockApi.updatePoint.mockRejectedValueOnce(limitError());
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    const dialog = await screen.findByRole('dialog', { name: /Replace which one/ });
    await user.click(within(dialog).getByRole('button', { name: "Don't keep the old wording" }));
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenLastCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Built FastAPI services!', keep_previous: false }));
    expect(await screen.findByRole('status')).toHaveTextContent('Updated in your profile.');
  });

  it('Update in profile can replace a chosen version instead, and Cancel writes nothing more', async () => {
    const user = userEvent.setup();
    mockApi.updatePoint.mockRejectedValue(limitError());
    render(<Harness initial={content()} bank={readyBank()} />);
    await edit(user, 'Bullet 1', '!');
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    await user.click(within(await screen.findByRole('dialog', { name: /Replace which one/ })).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockApi.updatePoint).toHaveBeenCalledTimes(1);
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
    const dialog = await screen.findByRole('dialog', { name: /Replace which one/ });
    await user.click(within(dialog).getByRole('radio'));
    await user.click(within(dialog).getByRole('button', { name: 'Replace selected version' }));
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenLastCalledWith('item-1', 'b1', { expected_revision: 4, text: 'Built FastAPI services!', replace_alternative_id: 'v1' }));
  });

  describe('Undo', () => {
    const undoButton = async () => within(await screen.findByRole('status')).getByRole('button', { name: 'Undo' });
    beforeEach(() => {
      mockApi.revertItem.mockImplementation(async (_id, values) => structuredClone({ ...stored, revision: values.expected_revision + 1, data: values.data as ProfileItem['data'] }));
    });

    it('after Update in profile restores the item and the resume link', async () => {
      const user = userEvent.setup();
      const original = structuredClone(stored.data);
      render(<Harness initial={content()} bank={readyBank()} />);
      await edit(user, 'Bullet 1', ' for 3 teams');
      await openSaveMenu(user, 0);
      await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
      await waitFor(() => expect(current(screen).sections[0].entries[0].source?.item_revision).toBe(5));
      await user.click(await undoButton());
      await waitFor(() => expect(mockApi.revertItem).toHaveBeenCalledWith('item-1', { expected_revision: 5, data: original }));
      expect(await screen.findByRole('status')).toHaveTextContent('Undone');
      const entry = current(screen).sections[0].entries[0];
      expect(entry.bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: null, base_text: 'Built FastAPI services' });
      expect(entry.source?.item_revision).toBe(4);
      expect(entry.bullets[0]).toBe('Built FastAPI services for 3 teams');
    });

    it('after Save as new version restores the earlier source', async () => {
      const user = userEvent.setup();
      const original = structuredClone(stored.data);
      render(<Harness initial={content()} bank={readyBank()} />);
      await edit(user, 'Bullet 1', ' fast');
      await openSaveMenu(user, 0);
      await user.click(screen.getByRole('menuitem', { name: 'Save as new version' }));
      await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.alternative_id).toBe('v-new'));
      await user.click(await undoButton());
      await waitFor(() => expect(mockApi.revertItem).toHaveBeenCalledWith('item-1', { expected_revision: 5, data: original }));
      await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: null, base_text: 'Built FastAPI services' }));
    });

    it('after Save as new point into an existing item clears the new link', async () => {
      const user = userEvent.setup();
      const original = structuredClone(stored.data);
      render(<Harness initial={content()} bank={readyBank()} />);
      await openSaveMenu(user, 1);
      await user.click(screen.getByRole('menuitem', { name: 'Save as new point…' }));
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save to profile' }));
      await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[1]?.bullet_id).toBe('b-new'));
      await user.click(await undoButton());
      await waitFor(() => expect(mockApi.revertItem).toHaveBeenCalledWith('item-1', { expected_revision: 5, data: original }));
      await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[1]).toBeNull());
      expect(current(screen).sections[0].entries[0].source?.item_revision).toBe(4);
    });

    it('after Save as new point into a new item archives that item', async () => {
      const user = userEvent.setup();
      mockApi.createItem.mockImplementation(async values => { stored = { ...experienceItem(), id: 'item-new', revision: 1, data: { ...values.data } }; return structuredClone(stored); });
      mockApi.archiveItem.mockResolvedValue({ ...stored });
      const hand = { id: 'h1', heading: 'Barista', subheading: 'Cafe', dates: '2019', bullets: ['Served coffee quickly'] };
      render(<Harness initial={content([hand])} bank={readyBank()} />);
      await openSaveMenu(user, 0);
      await user.click(screen.getByRole('menuitem', { name: 'Save as new point…' }));
      await user.click(within(screen.getByRole('dialog')).getByRole('radio', { name: 'New experience' }));
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save to profile' }));
      await user.click(await undoButton());
      await waitFor(() => expect(mockApi.archiveItem).toHaveBeenCalledWith('item-new', 1));
      expect(mockApi.revertItem).not.toHaveBeenCalled();
      expect(await screen.findByRole('status')).toHaveTextContent('Undone');
    });

    it('says "Can\'t undo" on a 409 and leaves the resume link alone', async () => {
      const user = userEvent.setup();
      mockApi.revertItem.mockRejectedValue(new HttpError('Conflict', 409, 'REVISION_CONFLICT'));
      render(<Harness initial={content()} bank={readyBank()} />);
      await edit(user, 'Bullet 1', '!');
      await openSaveMenu(user, 0);
      await user.click(screen.getByRole('menuitem', { name: 'Update in profile' }));
      await user.click(await undoButton());
      expect(await screen.findByRole('alert')).toHaveTextContent("Can't undo: this point changed since");
      expect(current(screen).sections[0].entries[0].bullet_sources?.[0]?.base_text).toBe('Built FastAPI services!');
      expect(current(screen).sections[0].entries[0].source?.item_revision).toBe(5);
    });
  });

  it('asks which experience, preselecting the linked one, and links the new point', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await openSaveMenu(user, 1);
    await user.click(screen.getByRole('menuitem', { name: 'Save as new point…' }));
    const dialog = screen.getByRole('dialog', { name: 'Which experience?' });
    expect(within(dialog).getAllByRole('radio').map(el => el.parentElement?.textContent)).toEqual(['Backend Engineer · Harbour Metrics', 'Data Analyst · Fictional Co', 'New experience']);
    expect(within(dialog).getByRole('radio', { name: /Backend Engineer/ })).toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Save to profile' }));
    await waitFor(() => expect(mockApi.addPoint).toHaveBeenCalledWith('item-1', { expected_revision: 4, text: 'Wrote a new thing here' }));
    await waitFor(() => expect(current(screen).sections[0].entries[0].bullet_sources?.[1]).toEqual({ bullet_id: 'b-new', alternative_id: null, base_text: 'Wrote a new thing here' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('creates a new item when "New experience" is chosen and leaves the resume entry unlinked from it', async () => {
    const user = userEvent.setup();
    mockApi.createItem.mockImplementation(async values => { stored = { ...experienceItem(), id: 'item-new', revision: 1, data: { ...values.data } }; return structuredClone(stored); });
    const hand = { id: 'h1', heading: 'Barista', subheading: 'Cafe', dates: '2019', bullets: ['Served coffee quickly'] };
    render(<Harness initial={content([hand])} bank={readyBank()} />);
    await openSaveMenu(user, 0);
    await user.click(screen.getByRole('menuitem', { name: 'Save as new point…' }));
    const dialog = screen.getByRole('dialog', { name: 'Which experience?' });
    expect(within(dialog).getByRole('button', { name: 'Save to profile' })).toBeDisabled();
    await user.click(within(dialog).getByRole('radio', { name: 'New experience' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save to profile' }));
    // One request creates the item with its point: no separate addPoint that could fail and leave an empty item.
    await waitFor(() => expect(mockApi.createItem).toHaveBeenCalledWith({ kind: 'experience', data: expect.objectContaining({ title: 'Barista', organisation: 'Cafe', dates_text: '2019',
      bullets: [expect.objectContaining({ text: 'Served coffee quickly', alternatives: [] })] }) }));
    expect(mockApi.addPoint).not.toHaveBeenCalled();
    expect(current(screen).sections[0].entries[0].bullet_sources).toBeUndefined();
    expect(await screen.findByRole('status')).toHaveTextContent('Saved to a new item');
  });

  it('cancelling the dialog writes nothing', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content()} bank={readyBank()} />);
    await openSaveMenu(user, 1);
    await user.click(screen.getByRole('menuitem', { name: 'Save as new point…' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockApi.addPoint).not.toHaveBeenCalled();
  });

  it('hides Save as new point in sections that are not saved to the profile as points', async () => {
    const user = userEvent.setup();
    render(<Harness initial={content([{ id: 'sk', heading: 'Languages', subheading: '', dates: '', bullets: ['Python'] }], 'Skills')} bank={readyBank([educationItem()])} />);
    await user.click(screen.getByRole('button', { name: 'More actions for this point' }));
    expect(screen.queryByRole('menuitem', { name: /Save to profile/ })).toBeNull();
  });
});
