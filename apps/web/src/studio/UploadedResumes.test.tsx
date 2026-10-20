import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../api';
import { UploadedResumes } from './UploadedResumes';
vi.mock('../api', () => ({api: {uploads: vi.fn(), deleteUpload: vi.fn(), downloadUpload: vi.fn()}}));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.uploads).mockResolvedValue({items: [{upload_id: 'source-1', filename: 'Example.pdf', status: 'ready', page_count: 1, created_at: '2026-10-21'}], next_cursor: null});
});
afterEach(cleanup);
it('confirms deletion, blocks duplicate submits, then removes the upload', async () => {
  let finish!: () => void;
  vi.mocked(api.deleteUpload).mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
  const user = userEvent.setup(); render(<UploadedResumes />);
  await user.click(await screen.findByRole('button', {name: 'Delete uploaded Example.pdf'}));
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', {name: 'Cancel'}));
  expect(api.deleteUpload).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', {name: 'Delete uploaded Example.pdf'}));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('Imported profile details, generated resumes, and application PDFs will be kept');
  await user.dblClick(within(screen.getByRole('alertdialog')).getByRole('button', {name: 'Delete upload'}));
  expect(api.deleteUpload).toHaveBeenCalledExactlyOnceWith('source-1');
  expect(screen.getByRole('button', {name: 'Deleting…'})).toBeDisabled();
  finish();
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  expect(screen.queryByText('Example.pdf')).not.toBeInTheDocument();
});
it('keeps the file and offers retry when deletion fails', async () => {
  vi.mocked(api.deleteUpload).mockRejectedValueOnce(new Error('Please try again')).mockResolvedValueOnce(undefined);
  const user = userEvent.setup(); render(<UploadedResumes />);
  await user.click(await screen.findByRole('button', {name: 'Delete uploaded Example.pdf'}));
  await user.click(screen.getByRole('button', {name: 'Delete upload'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Please try again');
  expect(screen.getByText('Example.pdf')).toBeInTheDocument();
  await user.click(screen.getByRole('button', {name: 'Delete upload'}));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
});
