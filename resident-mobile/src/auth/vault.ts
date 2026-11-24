import * as SecureStore from 'expo-secure-store';

export type StoredSession = { token: string; expiresAt: number; baseUrl: string };

const key = 'ophthalmology-review-session';
const options = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
let pendingWrite = Promise.resolve();

// Keep an invalidation from deleting a subsequent sign-in.
function updateVault(write: () => Promise<void>) {
  const operation = pendingWrite.then(write);
  pendingWrite = operation.catch(() => {});
  return operation;
}

export const saveSession = (session: StoredSession) =>
  updateVault(() => SecureStore.setItemAsync(key, JSON.stringify(session), options));

export const removeSession = () => updateVault(() => SecureStore.deleteItemAsync(key, options));

export async function readSession(): Promise<StoredSession | null> {
  await pendingWrite;
  const raw = await SecureStore.getItemAsync(key, options);
  if (!raw) return null;
  try {
    const value: Partial<StoredSession> | null = JSON.parse(raw);
    if (value && typeof value.token === 'string' && value.token && typeof value.baseUrl === 'string' &&
      typeof value.expiresAt === 'number' && Number.isFinite(value.expiresAt)) {
      return { token: value.token, baseUrl: value.baseUrl, expiresAt: value.expiresAt };
    }
  } catch {
    // Clear credentials from an unreadable or obsolete record.
  }
  await removeSession();
  return null;
}
