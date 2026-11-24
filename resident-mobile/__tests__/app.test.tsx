import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { fetch } from 'expo/fetch';
import * as SecureStore from 'expo-secure-store';

import App from '../src/App';
import type { Category, MetricKey, PostureSummary, SessionListItem, TimePoint } from '../src/api/types';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('expo-secure-store', () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 1,
  getItemAsync: jest.fn(), setItemAsync: jest.fn(), deleteItemAsync: jest.fn(),
}));
jest.mock('react-native-safe-area-context', () => jest.requireActual('react-native-safe-area-context/jest/mock').default);
jest.mock('../src/config', () => ({
  ...jest.requireActual('../src/config'), API_BASE_URL: 'https://station.example.test',
}));

const baseUrl = 'https://station.example.test';
const accessToken = 'sample-token-from-api';
const email = 'resident@example.test';
const storage = new Map<string, string>();
const request = jest.mocked(fetch);

const session: SessionListItem = {
  session_id: 'session 1', session_label: 'Slit-lamp practice', recorded_at: '2026-10-01T14:00:00Z',
  analysis_status: 'complete', available_views: ['side', 'rear'], plots_available: false,
  owner_user_id: 'resident-1', owner_email: 'owner@example.test', resident_or_study_id: null,
};

function category(key: string, label: string, score: number | null, percent: number, adjustment: boolean | null = null): Category {
  return { key, label, rula_score: score, rula_adjustment_present: adjustment, seconds: percent, percent_of_valid_time: percent };
}

const metrics: [MetricKey, string, Category[]][] = [
  ['neck_flexion_extension', 'Neck flexion / extension', [category('flexion_0_10', '0–10° flexion', 1, 54.75), category('flexion_10_20', '10–20° flexion', 2, 45.25)]],
  ['shoulder_hiking', 'Shoulder hiking', [category('Neutral', 'Neutral', null, 80, false), category('Bilateral Hiking', 'Bilateral Hiking', null, 20, true)]],
  ['forward_trunk_lean', 'Forward trunk lean', [category('upright', 'Approximately upright', 1, 70), category('flexion_0_20', '0–20° flexion', 2, 30)]],
  ['lateral_trunk_lean', 'Lateral trunk lean', [category('False', 'No side-bending adjustment', null, 85, false), category('True', 'Side-bending adjustment present', null, 15, true)]],
];

const summaries: PostureSummary[] = metrics.map(([metric, label, distribution], index) => {
  const within = [62.3, 80, 70, 85][index];
  return {
    metric, label, view: index % 2 ? 'rear' : 'side', unit: metric === 'shoulder_hiking' ? '% of hip width' : 'degrees',
    status: 'available', reason: null, valid_tracking_percent: 92.1, category_distribution: distribution,
    reference_zone_exposure: {
      within_seconds: within, outside_seconds: 100 - within, within_percent: within, outside_percent: 100 - within,
      rule_label: 'Project reference', rule_type: 'project_specific_automation_tolerance', rule_explanation: 'Explanation supplied by the backend.',
    },
  };
});

function response(status: number, payload?: unknown, mime = 'application/json') {
  return {
    status, ok: status >= 200 && status < 300,
    json: async () => payload,
    headers: { get: (name: string) => name === 'content-type' ? mime : null },
    arrayBuffer: async () => Uint8Array.from([0xff, 0xd8, 0xff, 0xd9]).buffer,
  } as Awaited<ReturnType<typeof fetch>>;
}

function mockApi(options: { role?: 'admin' | 'resident'; invalidLogin?: boolean; expired?: boolean; media?: boolean } = {}) {
  request.mockImplementation(async (path, init) => {
    const route = new URL(String(path)).pathname;
    if (route === '/auth/token') {
      if (options.invalidLogin) return response(401, { detail: 'A technical error which the app should not display' });
      return response(200, { access_token: accessToken, token_type: 'bearer', expires_in: 3600 });
    }
    const headers = init?.headers as Record<string, string>;
    if (headers.Authorization !== `Bearer ${accessToken}`) return response(401);
    if (route === '/auth/me') return response(200, { id: 'resident-1', email, role: options.role ?? 'resident' });
    if (route === '/auth/logout') return response(204);
    if (route === '/sessions') return response(200, { sessions: [session, {
      ...session, session_id: 'processing', session_label: 'Processing sample', analysis_status: 'processing', owner_email: null,
    }, {
      ...session, session_id: 'failed', session_label: 'Failed sample', analysis_status: 'failed', owner_email: null,
    }] });
    if (route === '/sessions/session%201') return options.expired ? response(401) : response(200, {
      session_id: session.session_id, metadata: { session_label: session.session_label }, analysis_status: { status: 'complete' },
      available_views: session.available_views, posture_summaries: summaries, review_media_available: options.media ?? false,
    });
    if (route.endsWith('/analysis/frame')) return response(200, undefined, 'image/jpeg');
    const summary = summaries.find((item) => route.endsWith(`/analysis/metrics/${item.metric}`));
    if (summary) {
      const points: TimePoint[] = [
        { time_seconds: 0, frame: 0, category: summary.category_distribution[0].key, value: 2, right_value: null, left_value: 2 },
        { time_seconds: 36.7, frame: 1101, category: summary.category_distribution[1].key, value: 18.24, posture_angle_deg: 16.1, right_value: 22, left_value: 20 },
      ];
      return response(200, { metric: summary.metric, points });
    }
    return response(404);
  });
}

async function enterCredentials() {
  await fireEvent.changeText(await screen.findByLabelText('Email'), email);
  await fireEvent.changeText(screen.getByLabelText('Password'), 'example-only-password');
  await fireEvent.press(screen.getByRole('button', { name: 'Log In' }));
}

function seedSession(expiresAt = Date.now() + 60000, address = baseUrl) {
  storage.set('ophthalmology-review-session', JSON.stringify({ token: accessToken, expiresAt, baseUrl: address }));
}

async function openAnalysis() {
  await fireEvent.press(await screen.findByText('Slit-lamp practice'));
  await screen.findByText('Reference Zone Exposure');
}

async function tapLatePoint() {
  const panel = await screen.findByTestId('time-series-layout');
  await fireEvent(panel, 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 330, height: 216 } } });
  await fireEvent.press(screen.getByTestId('time-series-touch'), { nativeEvent: { locationX: 250 } });
  await screen.findByText('00:36.7');
}

beforeEach(() => {
  jest.clearAllMocks();
  storage.clear();
  jest.mocked(SecureStore.getItemAsync).mockImplementation(async (key) => storage.get(key) ?? null);
  jest.mocked(SecureStore.setItemAsync).mockImplementation(async (key, value) => { storage.set(key, value); });
  jest.mocked(SecureStore.deleteItemAsync).mockImplementation(async (key) => { storage.delete(key); });
});

test('signs in, restores from SecureStore through /auth/me, and removes credentials on logout', async () => {
  mockApi();
  const first = await render(<App />);
  await enterCredentials();
  await screen.findByText('Slit-lamp practice');
  expect(screen.queryByText('owner@example.test')).toBeNull();
  expect(screen.getByText('Processing')).toBeOnTheScreen();
  expect(screen.getByText('Analysis needs attention')).toBeOnTheScreen();
  const persisted = JSON.parse([...storage.values()][0]);
  expect(persisted).toEqual({ token: accessToken, expiresAt: expect.any(Number), baseUrl });
  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(expect.any(String), expect.any(String), { keychainAccessible: 1 });
  expect(request).toHaveBeenCalledWith(`${baseUrl}/auth/token`, expect.objectContaining({ redirect: 'error', credentials: 'omit' }));

  await first.unmount();
  request.mockClear();
  await render(<App />);
  await screen.findByText('Slit-lamp practice');
  expect(request.mock.calls.map(([url]) => String(url))).toEqual([`${baseUrl}/auth/me`, `${baseUrl}/sessions`]);
  await fireEvent.press(screen.getByRole('button', { name: 'Log out' }));
  await screen.findByRole('button', { name: 'Log In' });
  expect(storage.size).toBe(0);
  await waitFor(() => expect(request).toHaveBeenCalledWith(`${baseUrl}/auth/logout`, expect.objectContaining({ method: 'POST' })));
});

test('gives a friendly error for rejected credentials', async () => {
  mockApi({ invalidLogin: true });
  await render(<App />);
  await enterCredentials();
  await screen.findByText('That email or password is incorrect. Try again.');
  expect(storage.size).toBe(0);
  expect(screen.queryByText(/technical error/)).toBeNull();
});

test('shows admin owner information and all four API summaries with interactive details', async () => {
  mockApi({ role: 'admin' });
  seedSession();
  await render(<App />);
  await screen.findByText('owner@example.test');
  await openAnalysis();
  expect(screen.getAllByText('Trial assessed: 92.1%')).toHaveLength(4);
  expect(screen.getByText('62.3%')).toBeOnTheScreen();
  expect(screen.getByText('54.75%')).toBeOnTheScreen();
  expect(screen.getByRole('button', { name: /^Neck flexion \/ extension\./ }).props.accessibilityState.selected).toBe(true);
  await tapLatePoint();
  expect(screen.getByText('18.24°')).toBeOnTheScreen();
  expect(screen.getByText('10–20° flexion')).toBeOnTheScreen();
  expect(screen.getByText('RULA posture score')).toBeOnTheScreen();

  for (const [key, label, distribution] of metrics.slice(1)) {
    await fireEvent.press(screen.getByRole('button', { name: new RegExp(`^${label}\\.`) }));
    await screen.findByText(`${label} details`);
    await screen.findByText(distribution[0].rula_score === null ? distribution[0].label : `${distribution[0].label} · RULA ${distribution[0].rula_score}`);
    await tapLatePoint();
    expect(request.mock.calls.some(([url]) => String(url).endsWith(`/analysis/metrics/${key}`))).toBe(true);
    expect(screen.getByText('Recorded frame unavailable on mobile for this session.')).toBeOnTheScreen();
    if (key === 'shoulder_hiking') {
      expect(screen.getByText('22.00% of hip width')).toBeOnTheScreen();
      expect(screen.getByText('RULA raised-shoulder adjustment')).toBeOnTheScreen();
      expect(screen.queryByText('RULA posture score')).toBeNull();
    }
  }
  expect(request.mock.calls.some(([url]) => String(url).includes('/analysis/frame'))).toBe(false);
});

test('keeps saved credentials when the API is down during restore and allows retry', async () => {
  mockApi();
  request.mockRejectedValueOnce(new TypeError('Fetch failed'));
  seedSession();
  await render(<App />);
  await screen.findByText('Can’t reach the station API. Check your connection and try again.');
  expect(storage.size).toBe(1);
  await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByText('Slit-lamp practice');
});

test('requests and displays a selected frame only when remote media is enabled', async () => {
  mockApi({ media: true });
  seedSession();
  await render(<App />);
  await openAnalysis();
  expect(request.mock.calls.some(([url]) => String(url).includes('/analysis/frame'))).toBe(false);
  await tapLatePoint();
  const image = await screen.findByLabelText('Recorded side frame at 00:36.7');
  expect(image.props.source.uri).toMatch(/^data:image\/jpeg;base64,/);
  expect(request).toHaveBeenCalledWith(`${baseUrl}/sessions/session%201/analysis/frame?view=side&frame=1101`, expect.objectContaining({
    headers: { Authorization: `Bearer ${accessToken}` },
  }));
});

test('clears invalid authentication and returns to Login on a review request returning 401', async () => {
  mockApi({ expired: true });
  seedSession();
  await render(<App />);
  await fireEvent.press(await screen.findByText('Slit-lamp practice'));
  await screen.findByText('Your session expired. Log in again.');
  await waitFor(() => expect(storage.size).toBe(0));
});

test.each([
  [Date.now() - 1000, baseUrl],
  [Date.now() + 60000, 'https://different.example.test'],
])('clears stale or differently scoped saved sessions before a request', async (expiresAt, address) => {
  mockApi();
  seedSession(expiresAt, address);
  await render(<App />);
  await screen.findByRole('button', { name: 'Log In' });
  expect(request).not.toHaveBeenCalled();
  expect(storage.size).toBe(0);
});
