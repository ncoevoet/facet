import { signal } from '@angular/core';

/** localStorage slot shared by every tab: the image key and the identity it serves. */
export const PRIVATE_IMAGE_SESSION_STORAGE_KEY = 'facet_private_image_session';

const SESSION_KEY_PATTERN = /^[a-f0-9]{32}$/;

interface StoredSession {
  /** Identity confirmed for this key, or null until the server confirms one. */
  owner: string | null;
  key: string;
}

function newSessionKey(): string {
  // getRandomValues also works on HTTP LAN deployments, unlike randomUUID.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

function readStored(): StoredSession | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY) ?? 'null');
    if (value && typeof value === 'object') {
      const { owner, key } = value as Partial<StoredSession>;
      if (typeof key === 'string' && SESSION_KEY_PATTERN.test(key) && (owner === null || typeof owner === 'string')) {
        return { owner, key };
      }
    }
  } catch { /* Unreadable entry: start a new session below. */ }
  return null;
}

function store(session: StoredSession): void {
  try {
    localStorage.setItem(PRIVATE_IMAGE_SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch { /* Storage unavailable: this document still separates accounts. */ }
}

// The image URL key separates decoded browser images across accounts. It is
// kept in localStorage, so a reload, another tab or an edition toggle reuses the
// same URLs and the browser revalidates them instead of downloading every image
// again. It contains no account or token material and grants no access.
let current = readStored() ?? { owner: null, key: newSessionKey() };
store(current);
const cacheKey = signal(current.key);
export const privateImageCacheKey = cacheKey.asReadonly();

// The session key marks history state and in-flight work as this document's,
// for the current account. It is never stored, so a reload rechecks access
// before showing a photo from history, and it changes with the image URL key.
const sessionKey = signal(newSessionKey());
export const privateImageSessionKey = sessionKey.asReadonly();

// Keys this document stopped using. Another tab can still write one back from
// an outdated view of storage; adopting it would let images cached for an
// earlier identity serve the next one, so a new key starts instead.
const dropped = new Set<string>();

function adopt(session: StoredSession): void {
  const changed = session.key !== current.key;
  if (changed) dropped.add(current.key);
  current = session;
  if (!changed) return;
  cacheKey.set(session.key);
  sessionKey.set(newSessionKey());
}

/** Start new keys: an account credential was accepted or dropped. */
export function resetPrivateImageSession(): void {
  const session = { owner: null, key: newSessionKey() };
  store(session);
  adopt(session);
}

/** Bind the key to the identity the server confirmed. A key that served
 *  another identity is replaced, so its images cannot be reused. */
export function confirmPrivateImageOwner(owner: string): void {
  const stored = readStored() ?? current;
  const reusable = !dropped.has(stored.key) && (stored.owner === null || stored.owner === owner);
  const session = { owner, key: reusable ? stored.key : newSessionKey() };
  if (stored.owner !== session.owner || stored.key !== session.key) store(session);
  adopt(session);
}

/** Adopt the key another tab wrote; a cleared entry, or a key this document
 *  already dropped, starts a new one. */
export function syncPrivateImageSession(): void {
  const stored = readStored();
  if (stored && !dropped.has(stored.key)) adopt(stored);
  else resetPrivateImageSession();
}
