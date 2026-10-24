import { UserManager, WebStorageStateStore } from 'oidc-client-ts';

export const cloudAuth = import.meta.env.VITE_AUTH_MODE === 'cognito';
let manager: UserManager | undefined;

export function authManager() {
  if (!manager) {
    const authority = import.meta.env.VITE_COGNITO_ISSUER;
    const domain = import.meta.env.VITE_COGNITO_DOMAIN;
    const client_id = import.meta.env.VITE_COGNITO_CLIENT_ID;
    if (!authority || !domain || !client_id) throw new Error('Sign-in configuration is missing.');
    manager = new UserManager({
      authority, client_id,
      redirect_uri: `${location.origin}/auth/callback`,
      response_type: 'code',
      scope: `openid email profile ${import.meta.env.VITE_API_SCOPE || 'jobhunter/use'}`,
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: sessionStorage }),
      // Explicit endpoints avoid relying on Cognito's discovery end_session support.
      metadata: {
        issuer: authority,
        authorization_endpoint: `${domain}/oauth2/authorize`,
        token_endpoint: `${domain}/oauth2/token`,
        userinfo_endpoint: `${domain}/oauth2/userInfo`,
        jwks_uri: `${authority}/.well-known/jwks.json`,
      },
    });
  }
  return manager;
}

export async function accessToken() {
  let user = await authManager().getUser();
  if (user?.expired) {
    try { user = await authManager().signinSilent(); }
    catch { await authManager().removeUser(); throw new Error('Your session expired. Please sign in again.'); }
  }
  if (!user || user.expired) throw new Error('Please sign in.');
  return user.access_token;
}

/** The sign-in email from the ID token. The API only receives an access token, so the browser is the one place that knows it. */
export async function signedInEmail(): Promise<string> {
  try {
    const email = (await authManager().getUser())?.profile.email;
    return typeof email === 'string' ? email : '';
  } catch { return ''; }
}

export async function signOut() {
  await authManager().removeUser();
  sessionStorage.clear();
  const url = new URL(`${import.meta.env.VITE_COGNITO_DOMAIN}/logout`);
  url.searchParams.set('client_id', import.meta.env.VITE_COGNITO_CLIENT_ID);
  url.searchParams.set('logout_uri', location.origin);
  location.assign(url.href);
}
