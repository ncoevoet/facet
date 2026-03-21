import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

export interface AuthStatus {
  authenticated: boolean;
  multi_user: boolean;
  edition_enabled: boolean;
  edition_authenticated: boolean;
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

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  private readonly TOKEN_KEY = 'facet_token';

  /** Reactive auth state */
  readonly status = signal<AuthStatus | null>(null);
  readonly isAuthenticated = computed(() => this.status()?.authenticated ?? false);
  readonly isEdition = computed(() => this.status()?.edition_authenticated ?? false);
  readonly isSuperadmin = computed(() => this.status()?.user_role === 'superadmin');
  readonly isMultiUser = computed(() => this.status()?.multi_user ?? false);
  readonly features = computed(() => this.status()?.features ?? {});
  readonly downloadProfiles = computed(() => this.status()?.download_profiles ?? []);

  get token(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  /** Check auth status with the server */
  async checkStatus(): Promise<AuthStatus> {
    const status = await firstValueFrom(this.http.get<AuthStatus>('/api/auth/status'));
    this.status.set(status);
    return status;
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
    localStorage.removeItem(this.TOKEN_KEY);
    this.status.set(null);
    this.router.navigate(['/login']);
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

  /** Check if a feature is enabled */
  hasFeature(key: string): boolean {
    return this.features()[key] ?? false;
  }
}
