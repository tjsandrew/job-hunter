import { afterEach, beforeEach, expect, test, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ getUser: vi.fn(), signinSilent: vi.fn(), removeUser: vi.fn(), options: vi.fn() }));
vi.mock('oidc-client-ts', () => ({
  UserManager: class {
    constructor(options: unknown) { mocks.options(options); }
    getUser = mocks.getUser;
    signinSilent = mocks.signinSilent;
    removeUser = mocks.removeUser;
  },
  WebStorageStateStore: class { constructor(public options: unknown) {} },
}));
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks();
  vi.stubEnv('VITE_COGNITO_ISSUER', 'https://cognito-idp.ap-southeast-1.amazonaws.com/pool');
  vi.stubEnv('VITE_COGNITO_DOMAIN', 'https://test.auth.ap-southeast-1.amazoncognito.com');
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-client');
});
afterEach(() => { vi.unstubAllEnvs(); });

test('public client uses code flow, API scope and session-scoped storage', async () => {
  const { authManager } = await import('./auth');
  authManager();
  const options = mocks.options.mock.calls[0][0];
  expect(options.response_type).toBe('code');
  expect(options.client_secret).toBeUndefined();
  expect(options.scope).toContain('jobhunter/use');
  expect(options.redirect_uri).toBe(`${location.origin}/auth/callback`);
  expect(options.userStore.options.store).toBe(sessionStorage);
});

test('expired sessions renew before returning an API token', async () => {
  mocks.getUser.mockResolvedValue({ expired: true });
  mocks.signinSilent.mockResolvedValue({ expired: false, access_token: 'fresh-token' });
  const { accessToken } = await import('./auth');
  expect(await accessToken()).toBe('fresh-token');
});

test('failed renewal removes stale credentials', async () => {
  mocks.getUser.mockResolvedValue({ expired: true });
  mocks.signinSilent.mockRejectedValue(new Error('expired refresh token'));
  const { accessToken } = await import('./auth');
  await expect(accessToken()).rejects.toThrow('session expired');
  expect(mocks.removeUser).toHaveBeenCalledOnce();
});
