import { DestroyRef, Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom, timeout, TimeoutError } from 'rxjs';
import { clearReviewQueues, REVIEW_QUEUE_STORAGE_KEY } from './review-queue.storage';
import { clearPersonAssignmentHistory } from './person-assignment-history.storage';
import { resetPrivateImageSession } from '../../shared/utils/private-image-session';

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
 *
 * `'rate_limited'` exists for the same reason, one status code down: both login
 * routes answer 429 from `_login_limiter.is_allowed()` before the password is
 * ever checked, so it is never a wrong password either -- and retyping one
 * only extends the lockout window.
 */
export type LoginOutcome = 'ok' | 'invalid' | 'unavailable' | 'rate_limited';

/** Slack allowed on the client's own clock before it judges a token dead. The
 *  verdict that matters is the server's; a browser clock running ahead would
 *  otherwise discard a token the server still accepts, and — since a fresh
 *  login token is judged by the same clock — lock the user out of a working
 *  session with no server round-trip involved. */
const CLOCK_SKEW_GRACE_MS = 5 * 60 * 1000;
const AUTH_REQUEST_TIMEOUT_MS = 15_000;
const AUTH_LOCK_TIMEOUT_MS = 60_000;

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
  private readonly COOKIE_UNCERTAINTY_KEY = 'facet_auth_cookie_uncertain';
  private pendingRevalidation: Promise<AuthStatus | null> | null = null;
  private pendingLoad: Promise<AuthStatus> | null = null;
  private authEpoch = 0;
  private statusRequest = 0;
  private appliedStatusRequest = 0;
  private cookieQueue: Promise<void> | null = null;
  private pendingCookieMutations = 0;
  private confirmedStatus: AuthStatus | null = null;
  private cookieUncertain = false;
  // Public installation mode keeps the retry form usable even when an unknown
  // HttpOnly cookie prevents restoring any identity, including after a reload.
  private readonly multiUserMode = signal(localStorage.getItem('facet_multi_user_mode') === '1');

  /** Reactive auth state */
  readonly status = signal<AuthStatus | null>(null);
  /** Who is signed in, not the session's other status fields; changes exactly when the identity does. */
  readonly identity = computed(() => {
    const status = this.status();
    return `${status?.authenticated ? 1 : 0}|${status?.user_id ?? ''}`;
  });
  readonly isAuthenticated = computed(() => this.status()?.authenticated ?? false);
  readonly isEdition = computed(() => this.status()?.edition_authenticated ?? false);
  readonly editionPasswordRequired = computed(() => this.status()?.edition_password_required ?? false);
  /** Single-user install with no edition password: read-only until one is set. */
  readonly isReadOnlyInstall = computed(() => {
    const status = this.status();
    return status !== null && !status.multi_user && !status.edition_authenticated && !status.edition_password_required;
  });
  readonly loginPasswordRequired = computed(() => this.status()?.login_password_required ?? false);
  readonly isSuperadmin = computed(() => this.status()?.user_role === 'superadmin');
  readonly isMultiUser = computed(() => this.status()?.multi_user ?? this.multiUserMode());
  /** Who may administer the installation, as `require_scan_access` decides: the
   *  superadmin in multi-user mode, edition access otherwise. */
  readonly isInstallAdmin = computed(() => this.isMultiUser() ? this.isSuperadmin() : this.isEdition());
  readonly features = computed(() => this.status()?.features ?? {});
  readonly downloadProfiles = computed(() => this.status()?.download_profiles ?? []);

  constructor() {
    // Another tab rotated the shared token (login, logout, edition lock or
    // unlock). Without this, our cached status keeps advertising rights the
    // rotated token no longer carries — an amber Edition icon over a session
    // the server 403s. The event never fires in the tab that wrote the value.
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== localStorage) return;
      if (event.key === this.COOKIE_UNCERTAINTY_KEY) {
        this.cookieUncertain = event.newValue !== null;
        this.invalidateSession();
        if (!this.cookieUncertain) void this.revalidate();
      } else if (event.key === this.TOKEN_KEY || event.key === null) {
        if (event.newValue === null) clearReviewQueues();
        this.invalidateSession();
        void this.revalidate();
      } else if (event.key === REVIEW_QUEUE_STORAGE_KEY && event.newValue === null) clearReviewQueues();
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
    // Cookie mutations also affect <img> requests. Wait until they have settled
    // before exposing an identity to guards or to account-dependent views.
    while (this.cookieQueue) await this.cookieQueue;
    if (this.hasUncertainCookie()) {
      await this.mutateCookie(async () => {
        if (this.hasUncertainCookie()) await this.reconcileCookie();
      });
      if (this.hasUncertainCookie()) throw new Error('Authentication cookie could not be reconciled; sign in again');
    }
    return this.refreshStatus();
  }

  private async refreshStatus(): Promise<AuthStatus> {
    const epoch = this.authEpoch;
    const token = localStorage.getItem(this.TOKEN_KEY);
    const request = ++this.statusRequest;
    const status = await firstValueFrom(
      this.http.get<AuthStatus>('/api/auth/status').pipe(timeout(AUTH_REQUEST_TIMEOUT_MS)),
    );
    if (!this.isCurrentSession(epoch, token)) {
      throw new Error('Authentication changed while loading status');
    }
    // Concurrent startup callers may finish in either order. An older result
    // can satisfy a guard while the newer request is pending, but cannot undo
    // a newer result that has already been applied.
    if (request < this.appliedStatusRequest) {
      const current = this.confirmedStatus ?? this.status();
      if (current) return current;
      throw new Error('Authentication status was superseded');
    }
    this.appliedStatusRequest = request;
    this.multiUserMode.set(status.multi_user);
    localStorage.setItem('facet_multi_user_mode', status.multi_user ? '1' : '0');
    this.confirmedStatus = status;
    if (!this.pendingCookieMutations) this.status.set(status);
    return status;
  }

  private isCurrentSession(epoch: number, token: string | null): boolean {
    return epoch === this.authEpoch && token === localStorage.getItem(this.TOKEN_KEY);
  }

  /** Drop state and in-flight ownership whenever the shared credential changes.
   * A late request may still finish, but cannot restore the previous account.
   * CacheStorage cleanup does not clear the browser's HTTP cache. */
  private invalidateSession(): void {
    this.authEpoch++;
    resetPrivateImageSession();
    this.pendingLoad = null;
    this.pendingRevalidation = null;
    this.status.set(null);
    this.confirmedStatus = null;
    this.clearThumbnailCaches();
  }

  /** The cached status, or the one server load every caller shares while it is
   *  in flight. Route guards run concurrently, so a cold load must cost a single
   *  `/api/auth/status` request and no guard may read the signal before it
   *  settles. Rejects like `checkStatus`. */
  loadStatus(): Promise<AuthStatus> {
    const cached = this.status();
    if (cached) return Promise.resolve(cached);
    if (!this.pendingLoad) {
      const pending = this.checkStatus().finally(() => {
        if (this.pendingLoad === pending) this.pendingLoad = null;
      });
      this.pendingLoad = pending;
    }
    return this.pendingLoad;
  }

  /** Reconcile the cached status with the server, coalescing concurrent callers
   *  so a burst of rejected requests costs a single round-trip. Never rejects:
   *  a failed reconciliation must not replace the error that triggered it. */
  revalidate(): Promise<AuthStatus | null> {
    if (!this.pendingRevalidation) {
      const pending = this.checkStatus()
        .catch(() => null)
        .finally(() => {
          if (this.pendingRevalidation === pending) this.pendingRevalidation = null;
        });
      this.pendingRevalidation = pending;
    }
    return this.pendingRevalidation;
  }

  /**
   * Store a minted token and refresh status. Shared by both login flows so
   * they cannot drift on what "success" writes.
   */
  private async acceptToken(res: LoginResponse | undefined): Promise<LoginOutcome> {
    if (!res?.access_token) {
      await this.reconcileCookie();
      return 'unavailable';
    }
    localStorage.setItem(this.TOKEN_KEY, res.access_token);
    this.markCookieUncertain(false);
    this.invalidateSession();
    await this.refreshStatus();
    return 'ok';
  }

  /** Serialize responses that set the HttpOnly image-auth cookie. Ignoring an
   * obsolete JSON body cannot undo Set-Cookie, so every completed mutation must
   * be applied before the next starts. Web Locks extend this order across tabs
   * on secure origins; HTTP deployments retain the per-instance queue. */
  private mutateCookie<T>(operation: (previous: AuthStatus | null) => Promise<T>): Promise<T> {
    if (!this.pendingCookieMutations) {
      this.confirmedStatus = this.status();
      if (this.confirmedStatus) {
        this.multiUserMode.set(this.confirmedStatus.multi_user);
        localStorage.setItem('facet_multi_user_mode', this.confirmedStatus.multi_user ? '1' : '0');
      }
    }
    this.pendingCookieMutations++;
    this.status.set(null);
    const run = async () => {
      const apply = async () => {
        const previous = this.confirmedStatus;
        const token = localStorage.getItem(this.TOKEN_KEY);
        this.invalidateSession();
        const epoch = this.authEpoch;
        const restorePrevious = () => {
          if (!this.confirmedStatus && !this.hasUncertainCookie() && this.isCurrentSession(epoch, token)) {
            this.confirmedStatus = previous;
          }
        };
        try {
          const result = await operation(previous);
          restorePrevious();
          return result;
        } catch (error) {
          restorePrevious();
          throw error;
        }
      };
      if (!navigator.locks) return apply();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), AUTH_LOCK_TIMEOUT_MS);
      try {
        return await navigator.locks.request('facet-auth-cookie', { signal: controller.signal }, () => {
          clearTimeout(timer);
          return apply();
        });
      } finally {
        clearTimeout(timer);
      }
    };
    const pending = this.cookieQueue ? this.cookieQueue.then(run) : run();
    const settled = pending.finally(() => {
      this.pendingCookieMutations--;
      if (!this.pendingCookieMutations) this.status.set(this.confirmedStatus);
      if (this.cookieQueue === tail) this.cookieQueue = null;
    });
    const tail = settled.then(() => undefined, () => undefined);
    this.cookieQueue = tail;
    return settled;
  }

  private async postAuth<T>(url: string, body: object): Promise<T> {
    // RxJS timeout unsubscribes from HttpClient, aborting the actual request
    // before the queue/lock is released; a plain Promise race would not.
    const wasUncertain = this.hasUncertainCookie();
    this.markCookieUncertain(true);
    try {
      return await firstValueFrom(this.http.post<T>(url, body).pipe(timeout(AUTH_REQUEST_TIMEOUT_MS)));
    } catch (error) {
      // A transport/parse failure can happen after headers applied Set-Cookie.
      // Only an explicit HTTP error response proves this auth route refused
      // the request without issuing a new cookie.
      if (!(error instanceof HttpErrorResponse) || error.status < 400) await this.reconcileCookie();
      else if (!wasUncertain) this.markCookieUncertain(false);
      throw error;
    }
  }

  private hasUncertainCookie(): boolean {
    return this.cookieUncertain || localStorage.getItem(this.COOKIE_UNCERTAINTY_KEY) !== null;
  }

  private markCookieUncertain(value: boolean): void {
    this.cookieUncertain = value;
    if (value) localStorage.setItem(this.COOKIE_UNCERTAINTY_KEY, '1');
    else localStorage.removeItem(this.COOKIE_UNCERTAINTY_KEY);
  }

  private async reconcileCookie(): Promise<void> {
    this.markCookieUncertain(true);
    for (let attempt = 0; attempt < 2; attempt++) {
      const token = this.token;
      if (!token) break;
      const epoch = this.authEpoch;
      const storedToken = localStorage.getItem(this.TOKEN_KEY);
      try {
        // Re-establish the cookie from the known Bearer, without minting a new
        // credential. Only a complete response confirms their identities match.
        const response = await firstValueFrom(this.http.post('/api/auth/cookie', {}, {
          headers: { Authorization: `Bearer ${token}` },
          observe: 'response',
        }).pipe(timeout(AUTH_REQUEST_TIMEOUT_MS)));
        if (response.status !== 204) break;
        if (!this.isCurrentSession(epoch, storedToken)) continue;
        this.markCookieUncertain(false);
        return;
      } catch { break; /* Invalid or unconfirmed Bearer: clear the complete session. */ }
    }
    localStorage.removeItem(this.TOKEN_KEY);
    clearPersonAssignmentHistory();
    clearReviewQueues();
    this.invalidateSession();
    this.router.navigate(['/login']);
    try {
      // Stay inside the current mutation's lock. Do not recurse through
      // postAuth: one bounded cleanup attempt is enough; failure must keep the
      // identity unknown instead of re-authenticating from the uncertain cookie.
      await firstValueFrom(this.http.post('/api/auth/logout', {}).pipe(timeout(AUTH_REQUEST_TIMEOUT_MS)));
      this.markCookieUncertain(false);
    } catch { /* An explicit successful login can reconcile a later retry. */ }
  }

  /**
   * Classify a failed login. Both endpoints answer 503 when the server could
   * not read its own configuration and is refusing to authenticate at all --
   * a state the operator fixes on the server, not by retyping a password.
   * Collapsing it into 'invalid' told them their password was wrong, which is
   * the one thing it was not, and hid the only diagnostic the server produced.
   *
   * Status 0 counts too — an unreachable server, a dropped connection or a
   * CORS failure cannot establish whether the credentials were accepted, so
   * reporting bad credentials repeats the same conflation. The predicate
   * is the one `retry.interceptor.ts` already uses for "the server, not the
   * request, is the problem".
   *
   * Status 429 is the same conflation one layer further down: both routes'
   * rate limiter rejects the request before any password check runs, so it is
   * never bad credentials either.
   */
  private classifyLoginError(err: unknown): LoginOutcome {
    if (err instanceof TimeoutError || (err instanceof DOMException && err.name === 'AbortError')) return 'unavailable';
    if (!(err instanceof HttpErrorResponse)) return 'invalid';
    if (err.status < 400 || err.status >= 500) return 'unavailable';
    return err.status === 429 ? 'rate_limited' : 'invalid';
  }

  /** Login with credentials */
  async login(password: string, username?: string): Promise<LoginOutcome> {
    try {
      const body: Record<string, string> = { password };
      if (username) body['username'] = username;

      return await this.mutateCookie(async () => this.acceptToken(
        await this.postAuth<LoginResponse>('/api/auth/login', body),
      ));
    } catch (err) {
      return this.classifyLoginError(err);
    }
  }

  /** Login for edition mode (legacy single-user) */
  async editionLogin(password: string): Promise<LoginOutcome> {
    try {
      return await this.mutateCookie(async () => this.acceptToken(
        await this.postAuth<LoginResponse>('/api/auth/edition/login', { password }),
      ));
    } catch (err) {
      return this.classifyLoginError(err);
    }
  }

  /** Logout and navigate to login */
  logout(): Promise<void> {
    // Hide the account immediately, then clear the cookie after every earlier
    // cookie response. A pending login must not set its cookie after logout.
    const clearingCookie = this.mutateCookie(async () => {
      try {
        await this.postAuth('/api/auth/logout', {});
        this.markCookieUncertain(false);
      } finally {
        localStorage.removeItem(this.TOKEN_KEY);
        this.invalidateSession();
      }
    }).catch(() => undefined);
    localStorage.removeItem(this.TOKEN_KEY);
    clearPersonAssignmentHistory();
    clearReviewQueues();
    this.invalidateSession();
    this.router.navigate(['/login']);
    return clearingCookie;
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
  async dropEdition(): Promise<boolean> {
    try {
      return await this.mutateCookie(async previous => {
        const res = await this.postAuth<LoginResponse>('/api/auth/edition/logout', {});
        if (!res?.access_token) {
          await this.reconcileCookie();
          return false;
        }
        localStorage.setItem(this.TOKEN_KEY, res.access_token);
        this.markCookieUncertain(false);
        this.invalidateSession();
        this.confirmedStatus = previous ? { ...previous, edition_authenticated: false } : null;
        return true;
      });
    } catch {
      // No confirmed token swap: keep the actual rights and let the caller
      // report the failed lock instead of claiming edition has been dropped.
      return false;
    }
  }

  /** Check if a feature is enabled */
  hasFeature(key: string): boolean {
    return this.features()[key] ?? false;
  }
}
