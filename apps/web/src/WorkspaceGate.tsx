import { useEffect, useState } from 'react';
import App from './App';
import { waitForWorkspace } from './workspaceWake';
import { signOut } from './auth';

export default function WorkspaceGate() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    // StrictMode's discarded effect is cleaned up before it can connect.
    const timer = window.setTimeout(() => {
      void waitForWorkspace(controller.signal).then(() => {
        if (!controller.signal.aborted) setReady(true);
      }).catch(cause => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Please try again.');
      });
    }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [attempt]);
  if (ready) return <App />;
  return <main style={{maxWidth: 480, margin: '15vh auto', padding: 24}}>
    <h1>Job Hunter</h1>
    {error ? <><p role="alert">{error}</p><button onClick={() => setAttempt(value => value + 1)}>Try again</button></>
      : <p role="status">Connecting to your workspace…</p>}
    <button onClick={() => void signOut()}>Sign out</button>
  </main>;
}
