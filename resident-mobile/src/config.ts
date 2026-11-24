export function httpsApiUrl(value: string | undefined): string | null {
  if (!value?.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search || url.hash) return null;
    if (url.hostname === 'station-dev.example.edu') return null;
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
  } catch {
    return null;
  }
}

export const API_BASE_URL = httpsApiUrl(process.env.EXPO_PUBLIC_API_BASE_URL);
