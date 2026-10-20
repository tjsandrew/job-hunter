import { StrictMode } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
vi.mock('./App', () => ({default: () => <div>Loaded workspace</div>}));
vi.mock('./auth', () => ({signOut: vi.fn()}));
vi.mock('./workspaceWake', () => ({waitForWorkspace: vi.fn()}));
import WorkspaceGate from './WorkspaceGate';
import { waitForWorkspace } from './workspaceWake';

afterEach(() => { cleanup(); vi.mocked(waitForWorkspace).mockReset(); });

test('does not mount the app or fire its parallel requests until wake succeeds', async () => {
  let finish!: () => void;
  vi.mocked(waitForWorkspace).mockReturnValue(new Promise<void>(resolve => { finish = resolve; }));
  render(<StrictMode><WorkspaceGate /></StrictMode>);
  expect(screen.getByRole('status').textContent).toContain('Connecting');
  expect(screen.queryByText('Loaded workspace')).toBeNull();
  await waitFor(() => expect(waitForWorkspace).toHaveBeenCalledTimes(1));
  finish();
  expect(await screen.findByText('Loaded workspace')).toBeTruthy();
});

test('unmount aborts wake-up work', async () => {
  vi.mocked(waitForWorkspace).mockReturnValue(new Promise(() => {}));
  const view = render(<WorkspaceGate />);
  await waitFor(() => expect(waitForWorkspace).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(waitForWorkspace).mock.calls[0][0];
  view.unmount();
  expect(signal.aborted).toBe(true);
});
