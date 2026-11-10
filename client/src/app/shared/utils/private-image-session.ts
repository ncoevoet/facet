import { signal } from '@angular/core';

function newSessionKey(): string {
  // getRandomValues also works on HTTP LAN deployments, unlike randomUUID.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

// A document-local nonce separates decoded browser images across credentials.
// It contains no account/token material and grants no access to the image.
const sessionKey = signal(newSessionKey());
export const privateImageSessionKey = sessionKey.asReadonly();

export function resetPrivateImageSession(): void {
  sessionKey.set(newSessionKey());
}
