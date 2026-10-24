import { useEffect, useState } from 'react';
import App from './App';
import WorkspaceGate from './WorkspaceGate';
import { AuthScreen } from './AuthScreen';
import { Icon } from './ui';
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
  if (subject && !import.meta.env.VITE_API_BASE_URL) return <AuthScreen title="You're signed in" text="Your workspace is being prepared. Please check back soon.">
    <button className="signout-button wide" onClick={() => void signOut()}><Icon name="signout" /> Sign out</button>
  </AuthScreen>;
  if (subject) return <WorkspaceGate key={subject} />;
  return <AuthScreen title="Welcome back" text="Sign in to pick up your search, your profile and your resumes.">
    {error ? <p className="auth-message error" role="alert">{error}</p> : subject === undefined ? <p className="auth-message" role="status">Checking your session…</p> : null}
    <button className="auth-button" onClick={() => { setError(''); void authManager().signinRedirect().catch(e => setError(e.message)); }}>Sign in <Icon name="arrow" /></button>
    <p className="auth-note">Access is by invitation. Ask the team if you need an account.</p>
  </AuthScreen>;
}
