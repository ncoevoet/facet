import { DestroyRef, Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

export interface AuthStatus {
  authenticated: boolean;
  multi_user: boolean;
  edition_enabled: boolean;
  edition_authenticated: boolean;
  edition_password_required: boolean;
  login_password_required: boolean;
  user_id: string | null;
  user_role: string | null;
  display_name: string | null;
  features: Record<string, boolean>;
  download_profiles: string[];
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  user?: { user_id: string; role: string; display_name: string };
}

/**
 * How a login attempt ended, from the caller's point of view.
 *
 * `'unavailable'` exists because the server answers 503 when it could not read
 * its own configuration and is refusing to authenticate anyone. Returning a
 * bare `false` for that made the login form say "Invalid credentials" to an
 * operator whose password was fine, and threw away the one diagnostic the
 * server had produced.
 */
export type LoginOutcome = 'ok' | 'invalid' | 'unavailable';

/** Slack allowed on the client's own clock before it judges a token dead. The
 *  verdict that matters is the server's; a browser clock running ahead would
 *  otherwise discard a token the server still accepts, and — since a fresh
 *  login token is judged by the same clock — lock the user out of a working
 *  session with no server round-trip involved. */
const CLOCK_SKEW_GRACE_MS = 5 * 60 * 1000;

/** True once the JWT's own `exp` has passed, plus the clock-skew grace. Verifying
 *  the signature is the server's business; this only stops the client presenting
 *  a token it already knows is dead, which some deployments treat as worse than
 *  no token at all. An unreadable token counts as expired — it can only be
 *  rejected anyway. */
function isExpired(token: string): boolean {
  const payload = token.split('.')[1];
  if (!payload) return true;
  try {
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const exp = (JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '='))) as { exp?: number }).exp;
    return typeof exp !== 'number' || exp * 1000 + CLOCK_SKEW_GRACE_MS <= Date.now();
  } catch {
    return true;
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  private readonly TOKEN_KEY = 'facet_token';
  private pendingRevalidation: Promise<AuthStatus | null> | null = null;

  /** Reactive auth state */
  readonly status = signal<AuthStatus | null>(null);
  readonly isAuthenticated = computed(() => this.status()?.authenticated ?? false);
  readonly isEdition = computed(() => this.status()?.edition_authenticated ?? false);
  readonly editionPasswordRequired = computed(() => this.status()?.edition_password_required ?? false);
  readonly loginPasswordRequired = computed(() => this.status()?.login_password_required ?? false);
  readonly isSuperadmin = computed(() => this.status()?.user_role === 'superadmin');
  readonly isMultiUser = computed(() => this.status()?.multi_user ?? false);
  readonly features = computed(() => this.status()?.features ?? {});
  readonly downloadProfiles = computed(() => this.status()?.download_profiles ?? []);

  constructor() {
    // Another tab rotated the shared token (login, logout, edition lock or
    // unlock). Without this, our cached status keeps advertising rights the
    // rotated token no longer carries — an amber Edition icon over a session
    // the server 403s. The event never fires in the tab that wrote the value.
    const onStorage = (event: StorageEvent) => {
      if (event.key === this.TOKEN_KEY) void this.revalidate();
    };
    window.addEventListener('storage', onStorage);
    inject(DestroyRef).onDestroy(() => window.removeEventListener('storage', onStorage));
  }

  get token(): string | null {
    const token = localStorage.getItem(this.TOKEN_KEY);
    return token && !isExpired(token) ? token : null;
  }

  /** Check auth status with the server */
  async checkStatus(): Promise<AuthStatus> {
    const status = await firstValueFrom(this.http.get<AuthStatus>('/api/auth/status'));
    this.status.set(status);
    return status;
  }

  /** Reconcile the cached status with the server, coalescing concurrent callers
   *  so a burst of rejected requests costs a single round-trip. Never rejects:
   *  a failed reconciliation must not replace the error that triggered it. */
  revalidate(): Promise<AuthStatus | null> {
    this.pendingRevalidation ??= this.checkStatus()
      .catch(() => null)
      .finally(() => { this.pendingRevalidation = null; });
    return this.pendingRevalidation;
  }

  /**
   * Store a minted token and refresh status. Shared by both login flows so
   * they cannot drift on what "success" writes.
   */
  private async acceptToken(res: LoginResponse | undefined): Promise<LoginOutcome> {
    if (!res?.access_token) return 'invalid';
    localStorage.setItem(this.TOKEN_KEY, res.access_token);
    await this.checkStatus();
    return 'ok';
  }

  /**
   * Classify a failed login. Both endpoints answer 503 when the server could
   * not read its own configuration and is refusing to authenticate at all --
   * a state the operator fixes on the server, not by retyping a password.
   * Collapsing it into 'invalid' told them their password was wrong, which is
   * the one thing it was not, and hid the only diagnostic the server produced.
   *
   * Status 0 counts too — an unreachable server, a dropped connection or a
   * CORS failure never reached the password check either, so reporting it as
   * bad credentials repeats the same conflation one layer down. The predicate
   * is the one `retry.interceptor.ts` already uses for "the server, not the
   * request, is the problem".
   */
  private classifyLoginError(err: unknown): LoginOutcome {
    if (!(err instanceof HttpErrorResponse)) return 'invalid';
    return err.status === 0 || err.status >= 500 ? 'unavailable' : 'invalid';
  }

  /** Login with credentials */
  async login(password: string, username?: string): Promise<LoginOutcome> {
    try {
      const body: Record<string, string> = { password };
      if (username) body['username'] = username;

      return await this.acceptToken(
        await firstValueFrom(this.http.post<LoginResponse>('/api/auth/login', body)),
      );
    } catch (err) {
      return this.classifyLoginError(err);
    }
  }

  /** Login for edition mode (legacy single-user) */
  async editionLogin(password: string): Promise<LoginOutcome> {
    try {
      return await this.acceptToken(
        await firstValueFrom(
          this.http.post<LoginResponse>('/api/auth/edition/login', { password }),
        ),
      );
    } catch (err) {
      return this.classifyLoginError(err);
    }
  }

  /** Logout and navigate to login */
  logout(): void {
    // Clear the server-side HttpOnly auth cookie (image/GET fallback auth);
    // fire-and-forget — local state is dropped regardless.
    this.http.post('/api/auth/logout', {}).subscribe({ error: () => undefined });
    localStorage.removeItem(this.TOKEN_KEY);
    this.status.set(null);
    this.clearThumbnailCaches();
    this.router.navigate(['/login']);
  }

  /** Drop service-worker thumbnail caches so they can't leak across users
   * sharing a browser (multi-user deployments). */
  private clearThumbnailCaches(): void {
    if (!('caches' in window)) return;
    caches.keys()
      .then(keys => Promise.allSettled(
        keys.filter(k => k.includes(':thumbnails:')).map(k => caches.delete(k)),
      ))
      .catch(() => { /* cache API unavailable - nothing to clear */ });
  }

  /** Drop edition privileges without navigating away */
  async dropEdition(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.http.post<LoginResponse>('/api/auth/edition/logout', {}),
      );
      if (res?.access_token) {
        localStorage.setItem(this.TOKEN_KEY, res.access_token);
      }
    } catch {
      // Network error — keep existing token rather than destroying the session
    }
    this.status.update(s => s ? { ...s, edition_authenticated: false } : s);
  }

  /** Re-enter edition mode locally when no password is required (server already grants it). */
  grantEditionLocal(): void {
    this.status.update(s => s ? { ...s, edition_authenticated: true } : s);
  }

  /** Check if a feature is enabled */
  hasFeature(key: string): boolean {
    return this.features()[key] ?? false;
  }
}
