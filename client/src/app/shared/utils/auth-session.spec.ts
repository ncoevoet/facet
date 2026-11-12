import { signal } from '@angular/core';
import { captureSession } from './auth-session';

describe('captureSession', () => {
  it('holds while identity and token are unchanged and fails once either changes', () => {
    const auth = { identity: signal('alice'), token: 'a' as string | null };
    const same = captureSession(auth);
    expect(same()).toBe(true);
    auth.token = 'b';
    expect(same()).toBe(false);
    auth.token = 'a'; auth.identity.set('bob');
    expect(same()).toBe(false);
  });
});
