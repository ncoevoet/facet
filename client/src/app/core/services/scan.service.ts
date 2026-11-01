import { Injectable, inject, signal, computed, OnDestroy, effect } from '@angular/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { AuthService, AuthStatus } from './auth.service';

export interface ScanProgress {
  phase: string;
  current?: number;
  total?: number;
  current_file?: string;
  eta_seconds?: number;
}

export interface ScanStatus {
  running: boolean;
  directories: string[];
  output: string[];
  elapsed_seconds: number | null;
  exit_code: number | null;
  progress?: ScanProgress | null;
}

export interface ScanDirectory {
  path: string;
  owner: string;
}

interface ScanSession {
  generation: number;
  owner: string;
  status: AuthStatus | null;
  token: string | null;
}

function emptyScanStatus(): ScanStatus {
  return { running: false, directories: [], output: [], elapsed_seconds: null, exit_code: null };
}

/** Check wire data before publishing it to the scan templates. */
function isScanStatus(value: unknown): value is ScanStatus {
  if (!value || typeof value !== 'object') return false;
  const data = value as Record<string, unknown>;
  const textList = (v: unknown) => Array.isArray(v) && v.every(line => typeof line === 'string');
  const finiteOrNull = (v: unknown) => v === null || (typeof v === 'number' && Number.isFinite(v));
  if (typeof data['running'] !== 'boolean' || !textList(data['directories']) || !textList(data['output'])
    || !finiteOrNull(data['elapsed_seconds']) || !finiteOrNull(data['exit_code'])) return false;
  const progress = data['progress'];
  if (progress == null) return true;
  if (typeof progress !== 'object' || typeof (progress as Record<string, unknown>)['phase'] !== 'string') return false;
  return ['current', 'total', 'eta_seconds'].every(key => {
    const v = (progress as Record<string, unknown>)[key];
    return v == null || (typeof v === 'number' && Number.isFinite(v));
  });
}

@Injectable({ providedIn: 'root' })
export class ScanService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly dialog = inject(MatDialog);
  private eventSource: EventSource | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollRequest: object | null = null;
  private generation = 0;
  private destroyed = false;
  private session: ScanSession | null = null;
  private launcher: { ref: MatDialogRef<unknown>; session: ScanSession } | null = null;
  private retriedMintOnError = false;

  readonly status = signal<ScanStatus>(emptyScanStatus());
  readonly connected = signal(false);
  readonly statusKnown = signal(false);
  readonly observationError = signal(false);

  readonly canLaunch = computed(() => {
    const flagged = this.auth.hasFeature('show_scan_button') && (this.auth.isMultiUser()
      ? this.auth.isSuperadmin()
      : this.auth.editionPasswordRequired() && this.auth.isEdition());
    // On an open install the server reports edition only for a trusted-local session.
    return flagged || (!this.auth.isMultiUser() && !this.auth.editionPasswordRequired()
      && !this.auth.loginPasswordRequired() && this.auth.isEdition());
  });

  constructor() {
    effect(() => {
      this.auth.identity(); this.auth.status(); this.canLaunch();
      if (this.session && !this.authCurrent(this.session)) this.disconnect();
      if (this.launcher && !this.authCurrent(this.launcher.session)) {
        this.launcher.ref.close(false);
        this.launcher = null;
      }
    });
  }

  private capture(): ScanSession {
    return { generation: this.generation, owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
  }

  private authCurrent(session: ScanSession): boolean {
    return !this.destroyed && session.owner === this.auth.identity() && session.status === this.auth.status()
      && session.token === this.auth.token && this.canLaunch();
  }

  private current(session: ScanSession): boolean {
    if (session.generation !== this.generation) return false;
    if (this.authCurrent(session)) return true;
    this.disconnect();
    return false;
  }

  async openLauncher(): Promise<boolean> {
    const session = this.capture();
    if (!this.authCurrent(session)) return false;
    const { ScanLauncherComponent } = await import('../../features/scan/scan-launcher.component');
    if (!this.authCurrent(session)) return false;
    const ref = this.dialog.open(ScanLauncherComponent, { width: '36rem' });
    const launcher = { ref, session };
    this.launcher = launcher;
    const result = await firstValueFrom(ref.afterClosed());
    if (this.launcher === launcher) this.launcher = null;
    return this.authCurrent(session) && !!result;
  }

  async startScan(directories: string[]): Promise<void> {
    const session = this.capture();
    if (!this.authCurrent(session)) throw new Error('Scan session changed');
    await firstValueFrom(this.api.post<{ success: boolean }>('/scan/start', { directories: [...directories] }));
    // An accepted start belongs to its captured session, never the new account.
    if (this.authCurrent(session)) await this.connect(false);
  }

  async loadDirectories(): Promise<ScanDirectory[]> {
    const session = this.capture();
    if (!this.authCurrent(session)) throw new Error('Scan session changed');
    const res = await firstValueFrom(this.api.get<{ directories: ScanDirectory[] }>('/scan/directories'));
    if (!this.authCurrent(session)) throw new Error('Scan session changed');
    return res.directories;
  }

  async connect(retainSameSession = true): Promise<void> {
    const previous = retainSameSession && this.session && this.authCurrent(this.session) ? this.status() : null;
    this.disconnect();
    const session = this.capture();
    if (!this.authCurrent(session)) return;
    this.session = session;
    if (previous) this.status.set(previous);
    this.retriedMintOnError = false;
    await this.openStream(session);
  }

  disconnect(): void {
    this.generation++;
    this.session = null;
    this.stopTransport();
    this.status.set(emptyScanStatus());
    this.statusKnown.set(false);
    this.observationError.set(false);
  }

  private stopTransport(): void {
    this.eventSource?.close();
    this.eventSource = null;
    this.stopPolling();
    this.connected.set(false);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.disconnect();
  }

  private async openStream(session: ScanSession): Promise<void> {
    let token: string | null = null;
    try {
      const res = await firstValueFrom(this.api.get<{ token: string }>('/scan/stream_token'));
      token = res.token;
    } catch { /* The supported status GET is the read-only fallback. */ }
    if (!this.current(session)) return;
    if (!token) { this.startPolling(session); return; }
    const params = new URLSearchParams({ token, lines: '50' });
    let source: EventSource;
    try { source = new EventSource(`/api/scan/stream?${params}`); }
    catch { this.startPolling(session); return; }
    this.eventSource = source;
    this.connected.set(true);
    source.onmessage = (event: MessageEvent) => {
      if (!this.current(session) || this.eventSource !== source) return;
      let data: unknown;
      try { data = JSON.parse(event.data); } catch { data = null; }
      if (!isScanStatus(data)) {
        this.observationError.set(true);
        this.stopTransport();
        return;
      }
      this.retriedMintOnError = false;
      this.status.set(data);
      this.statusKnown.set(true);
      this.observationError.set(false);
      if (!data.running) this.stopTransport();
    };
    source.onerror = () => {
      if (!this.current(session) || this.eventSource !== source) return;
      this.stopTransport();
      if (this.retriedMintOnError) { this.startPolling(session); return; }
      this.retriedMintOnError = true;
      void this.openStream(session);
    };
  }

  private startPolling(session: ScanSession): void {
    if (!this.current(session)) return;
    this.stopPolling();
    void this.pollOnce(session);
    this.pollTimer = setInterval(() => void this.pollOnce(session), 2000);
  }

  private stopPolling(): void {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = null;
    this.pollRequest = null;
  }

  private async pollOnce(session: ScanSession): Promise<void> {
    if (!this.current(session) || this.pollRequest) return;
    const request = {};
    this.pollRequest = request;
    try {
      const data = await firstValueFrom(this.api.get<unknown>('/scan/status', { lines: 50 }));
      if (!this.current(session) || this.pollRequest !== request) return;
      if (!isScanStatus(data)) throw new Error('Invalid scan status');
      this.status.set(data);
      this.statusKnown.set(true);
      this.observationError.set(false);
      if (!data.running) this.stopPolling();
    } catch {
      if (!this.current(session) || this.pollRequest !== request) return;
      this.observationError.set(true);
      this.stopPolling();
    } finally {
      if (this.pollRequest === request) this.pollRequest = null;
    }
  }
}
