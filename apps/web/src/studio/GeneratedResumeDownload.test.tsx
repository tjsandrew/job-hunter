import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../api';
import { downloadFile } from '../download';
import { resume } from './build/testData';
import { GeneratedResumeDownload } from './GeneratedResumeDownload';
vi.mock('../api', () => ({api: {exportDocument: vi.fn(), downloadExport: vi.fn()}}));
vi.mock('../download', () => ({downloadFile: vi.fn()}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('downloads the reviewed PDF through the existing export endpoints', async () => {
  const doc = resume({title: 'My Resume', revision: 3, reviewed_revision: 3});
  vi.mocked(api.exportDocument).mockResolvedValue({export_id: 'export-1', revision: 3, download_url: '/v1/exports/export-1'});
  const file = new Blob(['%PDF']); vi.mocked(api.downloadExport).mockResolvedValue(file);
  render(<GeneratedResumeDownload resume={doc} busy={false} onReview={vi.fn()} />);
  await userEvent.click(screen.getByRole('button', {name: 'Download My Resume as PDF'}));
  await waitFor(() => expect(downloadFile).toHaveBeenCalledWith(file, 'my-resume.pdf'));
  expect(api.exportDocument).toHaveBeenCalledExactlyOnceWith(doc.id);
});

it('opens an unreviewed draft instead of bypassing the review requirement', async () => {
  const onReview = vi.fn();
  render(<GeneratedResumeDownload resume={resume({reviewed_revision: null})} busy={false} onReview={onReview} />);
  await userEvent.click(screen.getByRole('button'));
  expect(onReview).toHaveBeenCalledTimes(1); expect(api.exportDocument).not.toHaveBeenCalled();
});

it('disables repeated export clicks while the PDF is being prepared', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.exportDocument>>) => void;
  vi.mocked(api.exportDocument).mockImplementation(() => new Promise(done => { finish = done; }));
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(['%PDF']));
  render(<GeneratedResumeDownload resume={resume({revision: 1, reviewed_revision: 1})} busy={false} onReview={vi.fn()} />);
  const button = screen.getByRole('button'); await userEvent.dblClick(button);
  expect(button).toBeDisabled(); expect(button).toHaveTextContent('Preparing PDF…');
  expect(api.exportDocument).toHaveBeenCalledTimes(1);
  finish({export_id: 'one', revision: 1, download_url: '/v1/exports/one'});
  await waitFor(() => expect(button).toBeEnabled());
});
