import { useEffect, useState } from 'react';
import App from './App';
import WorkspaceGate from './WorkspaceGate';
import { authManager, cloudAuth, signOut } from './auth';

// Kept outside React effects so StrictMode cannot redeem a callback code twice.
let initialization: Promise<string | null> | undefined;
function initialize() {
  return initialization ??= (async () => {
    const manager = authManager();
    if (location.pathname === '/auth/callback') {
      const user = await manager.signinRedirectCallback();
      history.replaceState({}, '', '/');
      return user.profile.sub;
    }
    const user = await manager.getUser();
    if (!user) return null;
    if (user.expired) {
      try { return (await manager.signinSilent())?.profile.sub || null; }
      catch { await manager.removeUser(); return null; }
    }
    return user.profile.sub;
  })();
}

export default function AuthGate() {
  const [subject, setSubject] = useState<string | null>();
  const [error, setError] = useState('');
  useEffect(() => {
    if (!cloudAuth) return;
    let alive = true;
    initialize().then(value => { if (alive) setSubject(value); }).catch(e => { if (alive) setError(e.message); });
    const expired = () => { initialization = undefined; setSubject(null); };
    authManager().events.addAccessTokenExpired(expired);
    authManager().events.addSilentRenewError(expired);
    return () => { alive = false; authManager().events.removeAccessTokenExpired(expired); authManager().events.removeSilentRenewError(expired); };
  }, []);
  if (!cloudAuth) return <App />;
  if (subject && !import.meta.env.VITE_API_BASE_URL) return <main style={{ maxWidth: 480, margin: '15vh auto', padding: 24 }}>
    <h1>You're signed in</h1><p>Your resume workspace is being prepared. Please check back soon.</p>
    <button onClick={() => void signOut()}>Sign out</button>
  </main>;
  if (subject) return <WorkspaceGate key={subject} />;
  return <main style={{ maxWidth: 480, margin: '15vh auto', padding: 24 }}>
    <h1>Job Hunter</h1><p>Build your profile and prepare your next resume.</p>
    {error ? <p role="alert">{error}</p> : subject === undefined ? <p>Checking your session…</p> : null}
    <button onClick={() => { setError(''); void authManager().signinRedirect().catch(e => setError(e.message)); }}>Sign in</button>
    <p>Project access is by invitation. Ask the team for an account.</p>
  </main>;
}
