import { Injectable, inject, signal, OnDestroy } from '@angular/core';
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

@Injectable({ providedIn: 'root' })
export class ScanService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);

  private eventSource: EventSource | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  readonly status = signal<ScanStatus>({
    running: false,
    directories: [],
    output: [],
    elapsed_seconds: null,
    exit_code: null,
  });
  readonly connected = signal(false);

  async startScan(directories: string[]): Promise<void> {
    await firstValueFrom(
      this.api.post<{ success: boolean }>('/scan/start', { directories }),
    );
    this.connect();
  }

  async loadDirectories(): Promise<ScanDirectory[]> {
    const res = await firstValueFrom(
      this.api.get<{ directories: ScanDirectory[] }>('/scan/directories'),
    );
    return res.directories;
  }

  connect(): void {
    this.disconnect();
    const token = this.auth.token;
    if (!token) return;

    const params = new URLSearchParams({ token, lines: '50' });
    const source = new EventSource(`/api/scan/stream?${params}`);
    this.eventSource = source;
    this.connected.set(true);

    source.onmessage = (event: MessageEvent) => {
      let data: ScanStatus;
      try {
        data = JSON.parse(event.data) as ScanStatus;
      } catch {
        return;
      }
      this.status.set(data);
      if (!data.running) {
        this.disconnect();
      }
    };

    source.onerror = () => {
      this.disconnect();
      this.startPolling();
    };
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

  private startPolling(): void {
    this.stopPolling();
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
      this.status.set(data);
      if (!data.running) {
        this.stopPolling();
      }
    } catch {
      this.stopPolling();
    }
  }
}
