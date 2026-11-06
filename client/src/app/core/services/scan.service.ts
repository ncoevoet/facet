import { Injectable, inject, signal, computed, OnDestroy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';

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

/** Consecutive failed status polls tolerated before polling gives up. */
export const MAX_POLL_FAILURES = 5;

@Injectable({ providedIn: 'root' })
export class ScanService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly dialog = inject(MatDialog);

  private eventSource: EventSource | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private retriedMintOnError = false;
  private pollFailures = 0;

  readonly status = signal<ScanStatus>({
    running: false,
    directories: [],
    output: [],
    elapsed_seconds: null,
    exit_code: null,
  });
  readonly connected = signal(false);

  readonly canLaunch = computed(() => {
    const flagged = this.auth.hasFeature('show_scan_button') && (this.auth.isMultiUser()
      ? this.auth.isSuperadmin()
      : this.auth.editionPasswordRequired() && this.auth.isEdition());
    // On an open install the server reports edition only for a trusted-local session.
    return flagged || (!this.auth.isMultiUser() && !this.auth.editionPasswordRequired()
      && !this.auth.loginPasswordRequired() && this.auth.isEdition());
  });

  /** Opens the scan launcher dialog; resolves true when it closed after a scan completed. */
  async openLauncher(): Promise<boolean> {
    const { ScanLauncherComponent } = await import('../../features/scan/scan-launcher.component');
    const ref = this.dialog.open(ScanLauncherComponent, { width: '36rem' });
    return !!(await firstValueFrom(ref.afterClosed()));
  }

  async startScan(directories: string[]): Promise<void> {
    await firstValueFrom(
      this.api.post<{ success: boolean }>('/scan/start', { directories }),
    );
    await this.connect();
  }

  async loadDirectories(): Promise<ScanDirectory[]> {
    const res = await firstValueFrom(
      this.api.get<{ directories: ScanDirectory[] }>('/scan/directories'),
    );
    return res.directories;
  }

  async connect(): Promise<void> {
    this.disconnect();
    if (!this.auth.token) return;
    this.retriedMintOnError = false;
    await this.openStream();
  }

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.stopPolling();
    this.connected.set(false);
  }

  ngOnDestroy(): void {
    this.disconnect();
  }

  private async openStream(): Promise<void> {
    const token = await this.mintStreamToken();
    if (!token) {
      this.startPolling();
      return;
    }
    this.openEventSource(token);
  }

  private async mintStreamToken(): Promise<string | null> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ token: string }>('/scan/stream_token'),
      );
      return res.token;
    } catch {
      return null;
    }
  }

  private openEventSource(token: string): void {
    const params = new URLSearchParams({ token, lines: '50' });
    const source = new EventSource(`/api/scan/stream?${params}`);
    this.eventSource = source;
    source.onopen = () => this.connected.set(true);

    source.onmessage = (event: MessageEvent) => {
      let data: ScanStatus;
      try {
        data = JSON.parse(event.data) as ScanStatus;
      } catch {
        return;
      }
      this.retriedMintOnError = false;
      this.status.set(data);
      if (!data.running) {
        this.disconnect();
      }
    };

    source.onerror = () => {
      this.disconnect();
      if (this.retriedMintOnError) {
        this.startPolling();
        return;
      }
      this.retriedMintOnError = true;
      void this.openStream();
    };
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollFailures = 0;
    this.pollOnce();
    this.pollTimer = setInterval(() => this.pollOnce(), 2000);
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private async pollOnce(): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.api.get<ScanStatus>('/scan/status', { lines: 50 }),
      );
      // One transient failure must not freeze the progress view for a scan
      // that is still running: the interval keeps firing, the next poll
      // re-arms the flag.
      this.pollFailures = 0;
      this.connected.set(true);
      this.status.set(data);
      if (!data.running) {
        this.stopPolling();
      }
    } catch (err) {
      // Keep the interval alive through a hiccup: one failure skips a tick
      // instead of ending the updates for a scan still running server-side.
      // A refusal (401/403) or a persistent failure stops it, or this root
      // service would poll -- and the error interceptor toast -- every tick
      // for the rest of the session.
      this.connected.set(false);
      const status = (err as { status?: number })?.status;
      this.pollFailures++;
      if (status === 401 || status === 403 || this.pollFailures >= MAX_POLL_FAILURES) {
        this.stopPolling();
      }
    }
  }
}
