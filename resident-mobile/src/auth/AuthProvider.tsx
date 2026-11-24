import { createContext, type PropsWithChildren, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { ApiError, createApiClient, type ApiClient, requestMessage } from '../api/client';
import type { Identity } from '../api/types';
import { API_BASE_URL } from '../config';
import { readSession, removeSession, saveSession, type StoredSession } from './vault';

type AuthState =
  | { phase: 'restoring' }
  | { phase: 'restoreError'; message: string }
  | { phase: 'signedOut'; notice?: string }
  | { phase: 'signedIn'; user: Identity; expiresAt: number };

type AuthContextValue = {
  state: AuthState;
  api: ApiClient;
  configured: boolean;
  logIn: (email: string, password: string) => Promise<void>;
  logOut: () => Promise<void>;
  restore: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<AuthState>(API_BASE_URL ? { phase: 'restoring' } : { phase: 'signedOut' });
  const activeSession = useRef<StoredSession | null>(null);

  const invalidate = useCallback((token: string) => {
    if (activeSession.current?.token !== token) return;
    activeSession.current = null;
    const deletion = removeSession();
    setState({ phase: 'signedOut', notice: 'Your session expired. Log in again.' });
    void deletion.catch(() => {
      setState((previous) => previous.phase === 'signedOut'
        ? { ...previous, notice: 'Your session expired. Secure storage could not be cleared. Log in again.' }
        : previous);
    });
  }, []);

  const getToken = useCallback(() => activeSession.current?.token ?? null, []);
  // The client calls getToken only when it sends a request.
  // eslint-disable-next-line react-hooks/refs
  const api = useMemo(() => createApiClient({
    baseUrl: API_BASE_URL,
    getToken,
    onUnauthorized: invalidate,
  }), [getToken, invalidate]);

  const restore = useCallback(async (signal?: AbortSignal) => {
    try {
      const saved = await readSession();
      if (signal?.aborted) return;
      if (!saved) {
        setState({ phase: 'signedOut' });
        return;
      }
      if (saved.baseUrl !== API_BASE_URL || saved.expiresAt <= Date.now()) {
        activeSession.current = null;
        await removeSession();
        if (!signal?.aborted) {
          setState({ phase: 'signedOut', notice: saved.baseUrl === API_BASE_URL ? 'Your session expired. Log in again.' : undefined });
        }
        return;
      }

      activeSession.current = saved;
      const user = await api.me(saved.token, signal);
      if (!signal?.aborted && activeSession.current === saved) {
        setState({ phase: 'signedIn', user, expiresAt: saved.expiresAt });
      }
    } catch (error) {
      if (signal?.aborted || (error instanceof ApiError && error.status === 401)) return;
      setState({ phase: 'restoreError', message: requestMessage(error, 'Could not restore your sign-in. Try again.') });
    }
  }, [api]);

  useEffect(() => {
    if (!API_BASE_URL) return;
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (!controller.signal.aborted) return restore(controller.signal);
    });
    return () => controller.abort();
  }, [restore]);

  const expiresAt = state.phase === 'signedIn' ? state.expiresAt : null;
  useEffect(() => {
    if (expiresAt === null) return;
    const session = activeSession.current;
    if (!session) return;
    const expireIfNeeded = () => {
      if (Date.now() >= expiresAt) invalidate(session.token);
    };
    const timer = setTimeout(expireIfNeeded, Math.max(0, expiresAt - Date.now()));
    const subscription = AppState.addEventListener('change', (next) => {
      if (next === 'active') expireIfNeeded();
    });
    return () => {
      clearTimeout(timer);
      subscription.remove();
    };
  }, [expiresAt, invalidate]);

  async function logIn(email: string, password: string) {
    if (!API_BASE_URL) throw new ApiError('configuration');
    const response = await api.login(email, password);
    if (!response.access_token || response.token_type !== 'bearer' || !Number.isFinite(response.expires_in) || response.expires_in <= 0) {
      throw new ApiError('response');
    }
    const saved = {
      token: response.access_token,
      baseUrl: API_BASE_URL,
      expiresAt: Date.now() + response.expires_in * 1000,
    };
    try {
      const user = await api.me(saved.token);
      await saveSession(saved);
      activeSession.current = saved;
      setState({ phase: 'signedIn', user, expiresAt: saved.expiresAt });
    } catch (error) {
      void api.logout(saved.token).catch(() => {});
      throw error;
    }
  }

  async function logOut() {
    const saved = activeSession.current;
    await removeSession();
    activeSession.current = null;
    setState({ phase: 'signedOut' });
    if (saved) void api.logout(saved.token).catch(() => {});
  }

  return (
    <AuthContext.Provider value={{ state, api, configured: Boolean(API_BASE_URL), logIn, logOut, restore: () => {
      setState({ phase: 'restoring' });
      return restore();
    } }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('AuthProvider is required');
  return auth;
}
