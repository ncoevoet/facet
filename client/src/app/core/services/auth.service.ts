import { DestroyRef, Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
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

  /** Login with credentials */
  async login(password: string, username?: string): Promise<boolean> {
    try {
      const body: Record<string, string> = { password };
      if (username) body['username'] = username;

      const res = await firstValueFrom(this.http.post<LoginResponse>('/api/auth/login', body));
      if (res?.access_token) {
        localStorage.setItem(this.TOKEN_KEY, res.access_token);
        await this.checkStatus();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  /** Login for edition mode (legacy single-user) */
  async editionLogin(password: string): Promise<boolean> {
    try {
      const res = await firstValueFrom(
        this.http.post<LoginResponse>('/api/auth/edition/login', { password }),
      );
      if (res?.access_token) {
        localStorage.setItem(this.TOKEN_KEY, res.access_token);
        await this.checkStatus();
        return true;
      }
      return false;
    } catch {
      return false;
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
