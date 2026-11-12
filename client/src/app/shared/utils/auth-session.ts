import type { AuthService } from '../../core/services/auth.service';

/** Captures who is signed in now and returns a check that the same identity and token still are,
 *  for an async step that must not land in another account's (or a refreshed) session. */
export function captureSession(auth: Pick<AuthService, 'identity' | 'token'>): () => boolean {
  const owner = auth.identity();
  const token = auth.token;
  return () => owner === auth.identity() && token === auth.token;
}
