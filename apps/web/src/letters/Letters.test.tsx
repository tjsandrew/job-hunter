import { useCallback, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api, HttpError } from '../api';
import { downloadFile } from '../download';
import type { Application, CoverLetter, Me } from '../types';
import { Letters } from './Letters';

vi.mock('../api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api')>();
  return { ...original, api: { letters: vi.fn(), createLetter: vi.fn(), patchLetter: vi.fn(), reviewLetter: vi.fn(), exportDocument: vi.fn(), downloadExport: vi.fn(), putApplication: vi.fn(), archiveDocument: vi.fn(), restoreDocument: vi.fn() } };
});
vi.mock('../download', () => ({ downloadFile: vi.fn() }));
const mockApi = vi.mocked(api);

const letter = (over: Partial<CoverLetter> = {}): CoverLetter => ({
  id: 'l1', title: 'Cover letter — Product Designer', kind: 'cover_letter', revision: 1, template: 'classic',
  content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', date: '25 October 2026', recipient: 'Hiring Team\nNorthstar', greeting: 'Dear Hiring Team,', paragraphs: ['First paragraph.', 'Second paragraph.'], closing: 'Yours sincerely,', signature: 'Alice Tan' },
  layout: { font_size: 11, margin: 22 }, reviewed_revision: null, updated_at: '2026-10-25T00:00:00Z', job_id: 'role-1', ...over,
});
const application = (jobId: string, title: string, over: Partial<Application> = {}): Application => ({ id: `app-${jobId}`, job_id: jobId, status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: jobId, title, company: 'Northstar', location: 'Singapore' }, ...over });
const me = (over: Partial<Me> = {}): Me => ({ user_id: '1', display_name: 'Alice', plan: 'free', ai_available: true, letter_available: true, allowance: { limit: 5, used: 2, remaining: 3, period: '2026-10' }, ...over });

type Harness = { me?: Me | null; apps?: Application[]; activeId?: string | null; target?: string | null; onOpen?: (id: string | null) => void; onMeChanged?: () => void; announce?: (m: string) => void; announceUndo?: (m: string, undo: () => void) => void; onSaved?: (a: Application) => void };
function Page(props: Harness) {
  const [activeId, setActiveId] = useState<string | null>(props.activeId ?? null);
  const [apps, setApps] = useState<Application[]>(props.apps ?? [application('role-1', 'Product Designer')]);
  const onOpen = useCallback((id: string | null) => { props.onOpen?.(id); setActiveId(id); }, []);
  const done = useCallback(() => undefined, []);
  const saved = useCallback((value: Application) => { props.onSaved?.(value); setApps((items) => items.map((item) => (item.job_id === value.job_id ? value : item))); }, []);
  return <Letters me={props.me === undefined ? me() : props.me} apps={apps} resumeCount={2} activeId={activeId} target={props.target ?? null} refresh={0}
    onOpen={onOpen} onTargetDone={done} onSection={() => undefined} onMeChanged={props.onMeChanged ?? (() => undefined)} onApplicationSaved={saved} announce={props.announce ?? (() => undefined)} announceUndo={props.announceUndo} />;
}

beforeEach(() => { vi.clearAllMocks(); mockApi.letters.mockResolvedValue({ items: [] }); });
afterEach(() => cleanup());

describe('cover letters: the list', () => {
  it('shows each letter with its status, and the saved jobs that still have none', async () => {
    mockApi.letters.mockResolvedValue({ items: [letter(), letter({ id: 'l2', title: 'Cover letter — Data Analyst', job_id: 'role-2', reviewed_revision: 1 })] });
    const apps = [application('role-1', 'Product Designer'), application('role-2', 'Data Analyst', { cover_letter_packet: { export_id: 'e1', document_id: 'l2', title: 'Cover letter — Data Analyst', revision: 1, download_url: '/v1/exports/e1' } }), application('role-3', 'UX Writer')];
    render(<Page apps={apps} />);
    expect(await screen.findByText('Cover letter — Product Designer')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Cover letters/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /Resumes/ })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getAllByText('Draft')).toHaveLength(1);
    expect(screen.getAllByText('Reviewed')).toHaveLength(1);
    expect(screen.getByText('Attached')).toBeInTheDocument();
    const waiting = within(screen.getByRole('region', { name: 'Saved jobs without a letter' }));
    expect(waiting.getByText('UX Writer')).toBeInTheDocument();
    expect(waiting.queryByText('Product Designer')).not.toBeInTheDocument();
    expect(waiting.getByRole('button', { name: 'Write with AI (3 of 5 left)' })).toBeInTheDocument();
  });

  it('says so when there are no letters', async () => {
    render(<Page />);
    expect(await screen.findByText('No cover letters yet.')).toBeInTheDocument();
  });

  it('deletes a letter after asking in a dialog, and Undo brings it back', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.archiveDocument.mockResolvedValue(undefined);
    mockApi.restoreDocument.mockResolvedValue(letter() as never);
    const announceUndo = vi.fn();
    render(<Page apps={[]} announceUndo={announceUndo} />);
    await user.click(await screen.findByRole('button', { name: 'Delete Cover letter — Product Designer' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete "Cover letter — Product Designer"?' });
    expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument();   // not attached anywhere: nothing to ask
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(mockApi.archiveDocument).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete Cover letter — Product Designer' }));
    await user.click(screen.getByRole('button', { name: 'Delete letter' }));
    await waitFor(() => expect(mockApi.archiveDocument).toHaveBeenCalledWith('l1'));
    await waitFor(() => expect(screen.queryByText('Cover letter — Product Designer')).not.toBeInTheDocument());
    expect(announceUndo).toHaveBeenCalledWith('"Cover letter — Product Designer" deleted.', expect.any(Function));
    act(() => announceUndo.mock.calls[0][1]());
    await waitFor(() => expect(mockApi.restoreDocument).toHaveBeenCalledWith('l1'));
    expect(await screen.findByText('Cover letter — Product Designer')).toBeInTheDocument();
  });

  it('keeps the sent copy in the tracker unless asked to remove it too', async () => {
    const user = userEvent.setup();
    const packet = { export_id: 'e1', document_id: 'l1', title: 'Cover letter — Product Designer', revision: 1, download_url: '/x' };
    const attached = application('role-1', 'Product Designer', { revision: 4, cover_letter_packet: packet });
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.archiveDocument.mockResolvedValue(undefined);
    mockApi.putApplication.mockResolvedValue({ ...attached, revision: 5, cover_letter_packet: null });
    const onSaved = vi.fn(), announceUndo = vi.fn();
    render(<Page apps={[attached]} onSaved={onSaved} announceUndo={announceUndo} />);
    await user.click(await screen.findByRole('button', { name: 'Delete Cover letter — Product Designer' }));
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('attached to Product Designer · Northstar');
    await user.click(within(dialog).getByRole('checkbox', { name: 'Also remove it from that application' }));
    await user.click(within(dialog).getByRole('button', { name: 'Delete and remove copy' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-1', { cover_letter_document_id: null, expected_revision: 4 }));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ cover_letter_packet: null }));
    expect(announceUndo).toHaveBeenCalledWith('"Cover letter — Product Designer" deleted and removed from Product Designer.', expect.any(Function));
  });
});

describe('cover letters: starting one', () => {
  const created = (over: Partial<CoverLetter> = {}) => ({ document: letter({ id: 'new', title: 'Cover letter — Product Designer', ...over }), notes: [{ kind: 'ok' as const, text: 'Built pipelines: from your profile (Designed SQL pipelines).' }, { kind: 'warn' as const, text: 'Led a team: could not be matched to your profile. Check it is true, or edit or remove it.' }, { kind: 'info' as const, text: 'These checks are automatic. Read the whole letter before you attach it.' }], ai: { status: 'applied' as const, reason: null } });

  it('writes from the profile, sends the tone and the points, then opens the editor with the notes', async () => {
    const user = userEvent.setup();
    const onMeChanged = vi.fn(); const onOpen = vi.fn();
    mockApi.createLetter.mockResolvedValue(created());
    mockApi.letters.mockResolvedValue({ items: [] });
    render(<Page onMeChanged={onMeChanged} onOpen={onOpen} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    const dialog = within(screen.getByRole('dialog', { name: 'Write a cover letter' }));
    await user.click(dialog.getByRole('button', { name: 'Friendly' }));
    await user.type(dialog.getByRole('textbox', { name: 'Anything to stress' }), 'my pipeline work');
    await user.click(dialog.getByRole('button', { name: 'Write with AI (3 of 5 left)' }));
    await waitFor(() => expect(mockApi.createLetter).toHaveBeenCalledWith('role-1', { mode: 'write', tone: 'friendly', points: 'my pipeline work' }));
    expect(await screen.findByRole('textbox', { name: 'Letter title' })).toHaveValue('Cover letter — Product Designer');
    expect(onOpen).toHaveBeenCalledWith('new');
    expect(onMeChanged).toHaveBeenCalled();
    const notes = within(screen.getByRole('region', { name: 'Check these before you send' }));
    expect(notes.getByText(/Built pipelines/)).toBeInTheDocument();
    expect(notes.getByText(/could not be matched to your profile/)).toBeInTheDocument();
    expect(notes.getByText(/checks are automatic/)).toBeInTheDocument();
    expect(screen.getByText(/1 confirmed, 1 to check/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Check these before you send' }).querySelector('details')).toHaveProperty('open', true);   // something needs a look
  });

  it('folds the notes away when every claim was confirmed, so the fields stay in view', async () => {
    const user = userEvent.setup();
    mockApi.createLetter.mockResolvedValue({ ...created(), notes: [{ kind: 'ok', text: 'Built pipelines: from your profile (Designed SQL pipelines).' }, { kind: 'info', text: 'These checks are automatic. Read the whole letter before you attach it.' }] });
    render(<Page />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    await user.click(within(screen.getByRole('dialog', { name: 'Write a cover letter' })).getByRole('button', { name: /Write with AI/ }));
    const region = await screen.findByRole('region', { name: 'Check these before you send' });
    expect(region.querySelector('details')).toHaveProperty('open', false);
    expect(screen.getByText(/1 confirmed/)).toBeInTheDocument();
    expect(screen.queryByText(/to check/)).not.toBeInTheDocument();
  });

  it('improves a pasted letter only once there is enough text, and a saved letter can be picked instead', async () => {
    const user = userEvent.setup();
    mockApi.createLetter.mockResolvedValue(created());
    mockApi.letters.mockResolvedValue({ items: [letter({ id: 'old', title: 'My old letter' })] });
    render(<Page />);
    await screen.findByText('My old letter');
    await user.click(screen.getByRole('button', { name: /Write cover letter/ }));
    await user.click(screen.getByRole('radio', { name: /Improve a letter I have/ }));
    const start = screen.getByRole('button', { name: 'Improve with AI (3 of 5 left)' });
    expect(start).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: 'Letter to improve' }), 'Dear sir, I would like a job in design please do consider me.');
    expect(start).toBeEnabled();
    await user.click(start);
    await waitFor(() => expect(mockApi.createLetter).toHaveBeenCalledWith('role-1', { mode: 'improve', tone: 'formal', source_text: 'Dear sir, I would like a job in design please do consider me.' }));
  });

  it('can improve a letter picked from the saved ones', async () => {
    const user = userEvent.setup();
    mockApi.createLetter.mockResolvedValue(created());
    mockApi.letters.mockResolvedValue({ items: [letter({ id: 'old', title: 'My old letter', job_id: 'role-9' })] });
    render(<Page />);
    await screen.findByText('My old letter');
    await user.click(screen.getByRole('button', { name: /Write cover letter/ }));
    await user.click(screen.getByRole('radio', { name: /Improve a letter I have/ }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Saved letter to improve' }), 'old');
    expect(screen.queryByRole('textbox', { name: 'Letter to improve' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Improve with AI (3 of 5 left)' }));
    await waitFor(() => expect(mockApi.createLetter).toHaveBeenCalledWith('role-1', { mode: 'improve', tone: 'formal', source_document_id: 'old' }));
  });

  it('starts a blank letter without the model and without using an AI use', async () => {
    const user = userEvent.setup();
    const onMeChanged = vi.fn();
    mockApi.createLetter.mockResolvedValue({ document: letter({ id: 'new', content: { ...letter().content, paragraphs: [''] } }), notes: [], ai: { status: 'off', reason: null } });
    render(<Page onMeChanged={onMeChanged} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    await user.click(screen.getByRole('radio', { name: /Start blank/ }));
    expect(screen.queryByRole('group', { name: 'Tone' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start a blank letter' }));
    await waitFor(() => expect(mockApi.createLetter).toHaveBeenCalledWith('role-1', { mode: 'blank' }));
    expect(await screen.findByRole('textbox', { name: 'Letter title' })).toBeInTheDocument();
    expect(onMeChanged).not.toHaveBeenCalled();
  });

  it('puts a letter the person already has into the editor as it is, without the model', async () => {
    const user = userEvent.setup();
    const onMeChanged = vi.fn();
    mockApi.createLetter.mockResolvedValue({ document: letter({ id: 'own' }), notes: [], ai: { status: 'off', reason: null } });
    render(<Page onMeChanged={onMeChanged} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    await user.click(screen.getByRole('radio', { name: /Start blank, or paste my own/ }));
    expect(screen.getByRole('button', { name: 'Start a blank letter' })).toBeEnabled();
    await user.type(screen.getByRole('textbox', { name: 'Your own letter' }), 'Dear Ms Lim, I would like this job.');
    await user.click(screen.getByRole('button', { name: 'Use my letter' }));
    await waitFor(() => expect(mockApi.createLetter).toHaveBeenCalledWith('role-1', { mode: 'blank', source_text: 'Dear Ms Lim, I would like this job.' }));
    expect(onMeChanged).not.toHaveBeenCalled();
  });

  it('keeps the window open and shows the reason when the letter could not be written', async () => {
    const user = userEvent.setup();
    mockApi.createLetter.mockRejectedValue(new HttpError('You have used all 5 AI uses this month', 402, 'AI_LIMIT_REACHED'));
    render(<Page />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    await user.click(within(screen.getByRole('dialog', { name: 'Write a cover letter' })).getByRole('button', { name: /Write with AI/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You have used all 5 AI uses this month');
    expect(screen.getByRole('dialog', { name: 'Write a cover letter' })).toBeInTheDocument();
    expect(within(screen.getByRole('dialog', { name: 'Write a cover letter' })).getByRole('button', { name: /Write with AI/ })).toBeEnabled();
  });

  it('only offers a blank letter when no AI model is configured, and warns when the month is used up', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Page me={me({ letter_available: false })} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    expect(within(screen.getByRole('dialog', { name: 'Write a cover letter' })).getByRole('button', { name: /Write with AI/ })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('No AI model is configured');
    await user.click(screen.getByRole('radio', { name: /Start blank/ }));
    expect(screen.getByRole('button', { name: 'Start a blank letter' })).toBeEnabled();
    unmount();
    render(<Page me={me({ allowance: { limit: 5, used: 5, remaining: 0, period: '2026-10' } })} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    expect(screen.getByRole('status')).toHaveTextContent('You have used all 5 AI uses this month');
  });

  it('asks to save a job first when there is nothing to write a letter for', async () => {
    const user = userEvent.setup();
    render(<Page apps={[]} />);
    await user.click(await screen.findByRole('button', { name: /Write cover letter/ }));
    expect(screen.getByRole('dialog', { name: 'Write a cover letter' })).toHaveTextContent('Save a job from Discover first');
  });

  it('opens the start window for the job an application was prepared for, or the letter that already exists', async () => {
    mockApi.letters.mockResolvedValue({ items: [] });
    const first = render(<Page target="role-1" />);
    expect(await screen.findByRole('dialog', { name: 'Write a cover letter' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Job for this letter' })).toBeDisabled();
    first.unmount();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    render(<Page target="role-1" />);
    expect(await screen.findByRole('textbox', { name: 'Letter title' })).toHaveValue('Cover letter — Product Designer');
  });
});

describe('cover letters: the editor', () => {
  it('saves what you type after a pause, with the revision it started from', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.patchLetter.mockImplementation(async (_id, values) => letter({ revision: values.expected_revision + 1, content: values.content! }));
    render(<Page activeId="l1" />);
    const first = await screen.findByRole('textbox', { name: 'Paragraph 1' });
    await user.clear(first);
    await user.type(first, 'My own words.');
    expect(screen.getByText('Unsaved changes', { selector: '.save-state' })).toBeInTheDocument();
    await waitFor(() => expect(mockApi.patchLetter).toHaveBeenCalled(), { timeout: 3000 });
    const [id, values] = mockApi.patchLetter.mock.calls.at(-1)!;
    expect(id).toBe('l1'); expect(values.expected_revision).toBe(1);
    expect(values.content!.paragraphs).toEqual(['My own words.', 'Second paragraph.']);
    await waitFor(() => expect(screen.getByText('Saved', { selector: '.save-state' })).toBeInTheDocument());
    expect(screen.getAllByText('Dear Hiring Team,').length).toBeGreaterThan(0);          // the preview shows the greeting
  });

  it('has the resume editor\'s toolbar: style buttons and a layout settings pop-over, and saves the choices', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.patchLetter.mockImplementation(async (_id, values) => letter({ revision: values.expected_revision + 1, template: values.template!, layout: values.layout! }));
    render(<Page activeId="l1" />);
    await screen.findByRole('textbox', { name: 'Letter title' });
    expect(screen.getByRole('button', { name: 'Classic serif' })).toHaveClass('selected');
    await user.click(screen.getByRole('button', { name: 'Modern sans' }));
    expect(screen.getByRole('button', { name: 'Modern sans' })).toHaveClass('selected');
    await user.click(screen.getByText('Layout settings'));
    const labels = screen.getAllByRole('combobox').map((select) => select.getAttribute('aria-label'));
    expect(labels).toEqual(expect.arrayContaining(['Font size', 'Page margin', 'Letter typeface', 'Line spacing', 'Page size']));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Line spacing' }), '1.6');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Page size' }), 'letter');
    await waitFor(() => expect(mockApi.patchLetter).toHaveBeenCalled(), { timeout: 3000 });
    const values = mockApi.patchLetter.mock.calls.at(-1)![1];
    expect(values.template).toBe('modern');
    expect(values.layout).toMatchObject({ line_spacing: 1.6, page_size: 'letter', font_family: 'auto' });
  });

  it('adds, moves and removes paragraphs', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.patchLetter.mockImplementation(async (_id, values) => letter({ revision: values.expected_revision + 1, content: values.content! }));
    render(<Page activeId="l1" />);
    await screen.findByRole('textbox', { name: 'Paragraph 1' });
    await user.click(screen.getByRole('button', { name: 'Add paragraph' }));
    expect(screen.getByRole('textbox', { name: 'Paragraph 3' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Move paragraph 2 up' }));
    expect(screen.getByRole('textbox', { name: 'Paragraph 1' })).toHaveValue('Second paragraph.');
    await user.click(screen.getByRole('button', { name: 'Remove paragraph 3' }));
    expect(screen.queryByRole('textbox', { name: 'Paragraph 3' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove paragraph 1' })).toBeEnabled();
  });

  it('can only be downloaded or attached once the saved revision was reviewed, then attaches a PDF snapshot to the application', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn(); const announce = vi.fn();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.reviewLetter.mockResolvedValue(letter({ reviewed_revision: 1 }));
    mockApi.exportDocument.mockResolvedValue({ export_id: 'ex1', revision: 1, download_url: '/v1/exports/ex1' });
    mockApi.downloadExport.mockResolvedValue(new Blob(['%PDF']));
    const attached = application('role-1', 'Product Designer', { revision: 2, cover_letter_packet: { export_id: 'ex1', document_id: 'l1', title: 'Cover letter — Product Designer', revision: 1, download_url: '/v1/exports/ex1' } });
    mockApi.putApplication.mockResolvedValue(attached);
    render(<Page activeId="l1" onSaved={onSaved} announce={announce} />);
    await screen.findByRole('textbox', { name: 'Letter title' });
    expect(screen.getByRole('button', { name: /Download PDF/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Attach reviewed letter' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Mark as reviewed' }));
    await waitFor(() => expect(mockApi.reviewLetter).toHaveBeenCalledWith('l1', 1));
    const download = await screen.findByRole('button', { name: /Download PDF/ });
    await waitFor(() => expect(download).toBeEnabled());
    await user.click(download);
    await waitFor(() => expect(downloadFile).toHaveBeenCalled());
    expect(vi.mocked(downloadFile).mock.calls[0][1]).toBe('cover-letter-product-designer.pdf');
    await user.click(screen.getByRole('button', { name: 'Attach reviewed letter' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-1', { cover_letter_document_id: 'l1', expected_cover_letter_revision: 1, expected_revision: 1 }));
    expect(onSaved).toHaveBeenCalledWith(attached);
    expect(await screen.findByRole('button', { name: 'Attached to application' })).toBeDisabled();
  });

  it('asks for another save when the letter changed somewhere else and loads the latest', async () => {
    const user = userEvent.setup();
    const announce = vi.fn();
    mockApi.letters.mockResolvedValueOnce({ items: [letter()] }).mockResolvedValue({ items: [letter({ revision: 3, content: { ...letter().content, paragraphs: ['From the other tab.'] } })] });
    mockApi.patchLetter.mockRejectedValue(new HttpError('Document changed', 409, 'REVISION_CONFLICT'));
    render(<Page activeId="l1" announce={announce} />);
    const first = await screen.findByRole('textbox', { name: 'Paragraph 1' });
    await user.type(first, '!');
    await waitFor(() => expect(announce).toHaveBeenCalledWith(expect.stringMatching(/changed somewhere else/)), { timeout: 3000 });
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Paragraph 1' })).toHaveValue('From the other tab.'));
  });

  it('does not retry on its own after a failed save', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    mockApi.patchLetter.mockRejectedValue(new Error('Network down'));
    render(<Page activeId="l1" />);
    await user.type(await screen.findByRole('textbox', { name: 'Paragraph 1' }), '!');
    await waitFor(() => expect(screen.getByText('Not saved', { selector: '.save-state' })).toBeInTheDocument(), { timeout: 3000 });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1800)); });
    expect(mockApi.patchLetter).toHaveBeenCalledTimes(1);
  });

  it('goes back to the list for a letter that is not there', async () => {
    const onOpen = vi.fn(); const announce = vi.fn();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    render(<Page activeId="gone" onOpen={onOpen} announce={announce} />);
    await waitFor(() => expect(announce).toHaveBeenCalledWith('That cover letter was not found.'));
    expect(onOpen).toHaveBeenCalledWith(null);
  });

  it('writes another version for the same job from the editor', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letter()] });
    render(<Page activeId="l1" />);
    await user.click(await screen.findByRole('button', { name: 'Write another version' }));
    expect(screen.getByRole('combobox', { name: 'Job for this letter' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Job for this letter' })).toHaveValue('role-1');
  });
});
