import { useEffect, useState } from 'react';
import App from './App';
import { waitForWorkspace } from './workspaceWake';
import { signOut } from './auth';
import { AuthScreen } from './AuthScreen';
import { Icon } from './ui';

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
  return <AuthScreen title="Opening your workspace" text="The first visit after a quiet spell can take a few seconds.">
    {error ? <><p className="auth-message error" role="alert">{error}</p><button className="auth-button" onClick={() => setAttempt(value => value + 1)}>Try again</button></>
      : <p className="auth-message" role="status"><span className="spinner" /> Connecting to your workspace…</p>}
    <button className="signout-button wide" onClick={() => void signOut()}><Icon name="signout" /> Sign out</button>
  </AuthScreen>;
}
