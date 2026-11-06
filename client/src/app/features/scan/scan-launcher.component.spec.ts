import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService, ScanStatus } from '../../core/services/scan.service';
import { ScanLauncherComponent } from './scan-launcher.component';

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
      connected: signal(false),
    };
    dialogClose = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: ScanService, useValue: mockScan },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: I18nService, useValue: { t: (key: string) => `T(${key})`, translations: () => ({}) } },
      ],
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

  describe('a refused start', () => {
    async function startRefused(err: unknown): Promise<HTMLElement> {
      mockScan.startScan.mockReturnValueOnce(Promise.reject(err));
      const fixture = TestBed.createComponent(ScanLauncherComponent);
      const c = fixture.componentInstance as unknown as { selectedDir: { set(v: string): void }; start(): Promise<void> };
      fixture.detectChanges();
      await fixture.whenStable();
      c.selectedDir.set('/photos/a');
      await c.start();
      fixture.detectChanges();
      expect((fixture.componentInstance as unknown as { started(): boolean }).started()).toBe(false);
      return fixture.nativeElement as HTMLElement;
    }

    it("shows the server's detail and gives the button back", async () => {
      const el = await startRefused({ error: { detail: 'A scan is already running' } });
      expect(el.querySelector('[role="alert"]')?.textContent?.trim()).toBe('A scan is already running');
    });

    it('falls back to the translated generic error when there is no detail', async () => {
      const el = await startRefused(new Error('boom'));
      expect(el.querySelector('[role="alert"]')?.textContent?.trim()).toBe('T(errors.action_failed)');
    });
  });
});
