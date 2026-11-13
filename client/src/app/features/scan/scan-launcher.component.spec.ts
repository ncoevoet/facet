import { TestBed } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA, signal, computed } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService, ScanStatus } from '../../core/services/scan.service';
import { ScanLauncherComponent } from './scan-launcher.component';
import { ScanHistoryComponent } from './scan-history.component';

function idleStatus(): ScanStatus {
  return { running: false, directories: [], output: [], elapsed_seconds: null, exit_code: null };
}

describe('ScanLauncherComponent', () => {
  let component: ScanLauncherComponent;
  let mockScan: {
    loadDirectories: ReturnType<typeof vi.fn>;
    startScan: ReturnType<typeof vi.fn>;
    status: ReturnType<typeof signal<ScanStatus>>;
    connected: ReturnType<typeof signal<boolean>>;
    statusKnown: ReturnType<typeof signal<boolean>>;
    observationError: ReturnType<typeof signal<boolean>>;
    connect: ReturnType<typeof vi.fn>;
    cancelScan: ReturnType<typeof vi.fn>;
    canCancel: ReturnType<typeof computed<boolean>>;
  };
  let dialogClose: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockScan = {
      loadDirectories: vi.fn(() => Promise.resolve([
        { path: '/photos/a', owner: 'alice' },
        { path: '/photos/b', owner: 'bob' },
      ])),
      startScan: vi.fn(() => Promise.resolve()),
      status: signal<ScanStatus>(idleStatus()),
      connected: signal(false), statusKnown: signal(true), observationError: signal(false), connect: vi.fn(async () => undefined),
      cancelScan: vi.fn(async () => undefined),
      canCancel: computed(() => mockScan.status().running && !!mockScan.status().job_id && !mockScan.status().cancel_requested),
    };
    dialogClose = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: ScanService, useValue: mockScan },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: I18nService, useValue: { t: (key: string) => `T(${key})`, translations: () => ({}) } },
      ],
    });
    // Scan history has its own service contract; only the launcher is under test.
    TestBed.overrideComponent(ScanLauncherComponent, {
      remove: { imports: [ScanHistoryComponent] }, add: { schemas: [NO_ERRORS_SCHEMA] },
    });
    component = TestBed.runInInjectionContext(() => new ScanLauncherComponent());
  });

  function read<T>(name: string): T {
    return (component as unknown as Record<string, () => T>)[name]();
  }

  it('loads directories on init', async () => {
    await component.ngOnInit();
    expect(mockScan.loadDirectories).toHaveBeenCalled();
    expect(read<unknown[]>('directories')).toHaveLength(2);
    expect(read<boolean>('loadingDirs')).toBe(false);
  });

  it('leaves the choice open when there are several directories', async () => {
    await component.ngOnInit();
    expect(read<string | null>('selectedDir')).toBeNull();
  });

  it('preselects the only directory, so Start needs no extra click', async () => {
    mockScan.loadDirectories.mockResolvedValue([{ path: '/photos/only', owner: '' }]);
    await component.ngOnInit();
    expect(read<string | null>('selectedDir')).toBe('/photos/only');
    await component.start();
    expect(mockScan.startScan).toHaveBeenCalledWith(['/photos/only']);
  });

  it('starts a scan with the selected directory', async () => {
    (component as unknown as { selectedDir: { set(v: string): void } }).selectedDir.set('/photos/b');
    await component.start();
    expect(mockScan.startScan).toHaveBeenCalledWith(['/photos/b']);
    expect(read<boolean>('started')).toBe(true);
  });

  it('does not start without a selected directory', async () => {
    await component.start();
    expect(mockScan.startScan).not.toHaveBeenCalled();
  });

  it('recovers observation after an uncertain start without allowing a second start', async () => {
    mockScan.startScan.mockRejectedValueOnce(new Error('lost response'));
    (component as any).selectedDir.set('/photos/a');
    await component.start();
    expect(read<boolean>('startError')).toBe(true);
    expect(mockScan.connect).toHaveBeenCalledTimes(1);
    await component.start();
    expect(mockScan.startScan).toHaveBeenCalledTimes(1);
  });

  describe('a refused start', () => {
    async function startRefused(err: unknown): Promise<HTMLElement> {
      mockScan.startScan.mockRejectedValueOnce(err);
      const fixture = TestBed.createComponent(ScanLauncherComponent);
      const c = fixture.componentInstance as unknown as { selectedDir: { set(v: string): void }; start(): Promise<void> };
      fixture.detectChanges();
      await fixture.whenStable();
      c.selectedDir.set('/photos/a');
      await c.start();
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    it("shows the server's detail and gives the Start button back", async () => {
      const el = await startRefused(new HttpErrorResponse({ status: 409, error: { detail: 'A library job is running' } }));
      expect(el.querySelector('[role="alert"]')?.textContent?.trim()).toBe('A library job is running');
      expect(el.querySelector('[data-scan-start]')).not.toBeNull();
      // Re-read status once more: a 409 may mean a scan started elsewhere, whose progress then shows.
      expect(mockScan.connect).toHaveBeenCalledTimes(2);
    });

    it('falls back to the translated generic error when a refusal has no detail', async () => {
      const el = await startRefused(new HttpErrorResponse({ status: 400 }));
      expect(el.querySelector('[role="alert"]')?.textContent?.trim()).toBe('T(errors.action_failed)');
      expect(el.querySelector('[data-scan-start]')).not.toBeNull();
    });

    it.each([[422, undefined], [429, undefined], [503, 'library_busy']])('treats a %s answer as a refusal', async (status, detail) => {
      const el = await startRefused(new HttpErrorResponse({ status, error: detail ? { detail } : undefined }));
      expect(el.querySelector('[data-scan-start]')).not.toBeNull();
    });

    it('keeps a bare 503 as an uncertain start', async () => {
      const el = await startRefused(new HttpErrorResponse({ status: 503 }));
      expect(el.querySelector('[data-scan-start]')).toBeNull();
    });

    it('keeps the uncertain-start message and no Start button for a lost response', async () => {
      const el = await startRefused(new HttpErrorResponse({ status: 0 }));
      expect(el.querySelector('[role="alert"]')?.textContent?.trim()).toBe('T(scan.start_unconfirmed)');
      expect(el.querySelector('[data-scan-start]')).toBeNull();
    });
  });

  it('does not start before status is known or while observation has failed', async () => {
    (component as any).selectedDir.set('/photos/a');
    mockScan.statusKnown.set(false); await component.start();
    mockScan.statusKnown.set(true); mockScan.observationError.set(true); await component.start();
    expect(mockScan.startScan).not.toHaveBeenCalled();
  });

  it('computes a determinate progress percentage', () => {
    mockScan.status.set({ ...idleStatus(), running: true,
      progress: { phase: 'scoring', current: 5, total: 20 } });
    expect(read<number | null>('progressValue')).toBe(25);
  });

  it('reports indeterminate progress when total is unknown', () => {
    mockScan.status.set({ ...idleStatus(), running: true, progress: { phase: 'scoring' } });
    expect(read<number | null>('progressValue')).toBeNull();
  });

  it('does NOT auto-close on a stale prior-run success, only after this run runs', () => {
    // A previous scan left the shared signal at completed/clean.
    mockScan.status.set({ ...idleStatus(), running: false, exit_code: 0 });
    TestBed.tick();
    expect(dialogClose).not.toHaveBeenCalled();

    // Start: started flips true while status is still the stale success.
    (component as unknown as { started: { set(v: boolean): void } }).started.set(true);
    TestBed.tick();
    expect(dialogClose).not.toHaveBeenCalled();

    // This run goes live, then finishes cleanly -> now it closes.
    mockScan.status.set({ ...idleStatus(), running: true, exit_code: null });
    TestBed.tick();
    mockScan.status.set({ ...idleStatus(), running: false, exit_code: 0 });
    TestBed.tick();
    expect(dialogClose).toHaveBeenCalledWith(true);
  });
});
