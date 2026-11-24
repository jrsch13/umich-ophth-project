import { fromByteArray } from 'base64-js';
import { fetch as expoFetch } from 'expo/fetch';

import { httpsApiUrl } from '../config';
import type { AnalysisState, Identity, MetricKey, SessionDetail, SessionListItem, TimeSeries, TokenResponse, View } from './types';

type RequestErrorKind = 'configuration' | 'network' | 'timeout' | 'response' | 'http' | 'aborted';

export class ApiError extends Error {
  constructor(readonly kind: RequestErrorKind, readonly status?: number) {
    super(kind === 'http' ? `HTTP ${status}` : kind);
    this.name = 'ApiError';
  }
}

export function requestMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.kind === 'configuration') return 'Set a valid HTTPS API address to connect.';
    if (error.kind === 'network') return 'Can’t reach the station API. Check your connection and try again.';
    if (error.kind === 'timeout') return 'The station took too long to respond. Try again.';
  }
  return fallback;
}

const sessionPath = (id: string) => `/sessions/${encodeURIComponent(id)}`;

type Options = { signal?: AbortSignal; token?: string; data?: unknown; method?: 'POST' };
type ClientConfig = {
  baseUrl: string | null;
  getToken: () => string | null;
  onUnauthorized: (token: string) => void;
  timeoutMs?: number;
};

export function createApiClient({ baseUrl, getToken, onUnauthorized, timeoutMs = 15_000 }: ClientConfig) {
  const address = httpsApiUrl(baseUrl ?? undefined);

  async function request<T>(
    path: string,
    { signal, data, method, token }: Options,
    decode: (response: Awaited<ReturnType<typeof expoFetch>>) => Promise<T>,
  ): Promise<T> {
    if (!address) throw new ApiError('configuration');
    if (signal?.aborted) throw new ApiError('aborted');

    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    try {
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      if (data !== undefined) headers['Content-Type'] = 'application/json';
      const response = await expoFetch(address + path, {
        method,
        headers,
        body: data === undefined ? undefined : JSON.stringify(data),
        credentials: 'omit',
        redirect: 'error',
        signal: controller.signal,
      });
      if (response.status === 401 && token) onUnauthorized(token);
      if (!response.ok) throw new ApiError('http', response.status);
      try {
        return await decode(response);
      } catch (error) {
        if (controller.signal.aborted) throw error;
        throw new ApiError('response');
      }
    } catch (error) {
      if (signal?.aborted) throw new ApiError('aborted');
      if (timedOut) throw new ApiError('timeout');
      if (error instanceof ApiError) throw error;
      throw new ApiError('network');
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
    }
  }

  const json = <T,>(path: string, options: Options = {}) => request(path, options, async (response) => response.json() as Promise<T>);

  function authenticated(signal?: AbortSignal): Options {
    const token = getToken();
    if (!token) throw new ApiError('http', 401);
    return { token, signal };
  }

  return {
    login: (email: string, password: string) => json<TokenResponse>('/auth/token', { method: 'POST', data: { email, password } }),
    me: (token: string, signal?: AbortSignal) => json<Identity>('/auth/me', { token, signal }),
    logout: (token: string) => request('/auth/logout', { method: 'POST', token }, async () => undefined),
    async sessions(signal?: AbortSignal) {
      const result = await json<{ sessions: SessionListItem[] }>('/sessions', authenticated(signal));
      if (!Array.isArray(result.sessions)) throw new ApiError('response');
      return result.sessions;
    },
    async session(id: string, signal?: AbortSignal) {
      return json<SessionDetail>(sessionPath(id), authenticated(signal));
    },
    async status(id: string, signal?: AbortSignal) {
      return json<AnalysisState>(`${sessionPath(id)}/analysis-status`, authenticated(signal));
    },
    async series(id: string, metric: MetricKey, signal?: AbortSignal) {
      return json<TimeSeries>(`${sessionPath(id)}/analysis/metrics/${metric}`, authenticated(signal));
    },
    async frame(id: string, view: View, frame: number, signal?: AbortSignal) {
      return request(`${sessionPath(id)}/analysis/frame?view=${view}&frame=${frame}`, authenticated(signal), async (response) => {
        const type = response.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase();
        if (type !== 'image/jpeg' && type !== 'image/png') throw new ApiError('response');
        const bytes = new Uint8Array(await response.arrayBuffer());
        return `data:${type};base64,${fromByteArray(bytes)}`;
      });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
