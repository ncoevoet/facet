import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService, ScanStatus } from '../../core/services/scan.service';
import { ScanLauncherComponent } from './scan-launcher.component';

const translations = {
  scan: {
    checking_status: 'Checking scan status…', status_unavailable: 'Status unavailable', retry_status: 'Read scan status again', failed: 'Scan ended with an error',
    title: 'Scan Photos', close: 'Close', start_button: 'Start Scan', running: 'Running',
    pick_directory: 'Pick a directory', eta: 'ETA',
    phase: { scoring: 'Scoring', moments: 'Detecting moments', junk: 'Detecting junk', recompute: 'Recomputing scores' },
  },
  // These are real translation namespaces, not displayable phase labels.
  moments: { title: 'Moments' }, junk: { title: 'Junk' }, gallery: { title: 'Gallery' },
};

describe('Scan launcher rendered phase labels', () => {
  let fixture: ComponentFixture<ScanLauncherComponent>;
  let http: HttpTestingController;
  let root: HTMLElement;
  let status: ReturnType<typeof signal<ScanStatus>>;
  let statusKnown: ReturnType<typeof signal<boolean>>;
  let observationError: ReturnType<typeof signal<boolean>>;
  let reconnect: ReturnType<typeof vi.fn>;
  let startScan: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    status = signal<ScanStatus>({ running: false, directories: [], output: [], elapsed_seconds: null, exit_code: null });
    statusKnown = signal(true); observationError = signal(false); reconnect = vi.fn(async () => undefined);
    startScan = vi.fn(async () => { statusKnown.set(false); });
    TestBed.configureTestingModule({ imports: [ScanLauncherComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: ScanService, useValue: {
        status, connected: signal(true), statusKnown, observationError, connect: reconnect,
        loadDirectories: vi.fn(async () => [{ path: '/fixture/photos', owner: '' }]),
        startScan,
      } },
      { provide: MatDialogRef, useValue: { close: vi.fn() } },
    ] });
    http = TestBed.inject(HttpTestingController);
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('en');
    const loaded = i18n.load();
    http.expectOne('/api/i18n/en').flush(translations);
    await loaded;
    fixture = TestBed.createComponent(ScanLauncherComponent);
    root = fixture.nativeElement;
    await settle();
    root.querySelector<HTMLInputElement>('input[type="radio"]')!.dispatchEvent(new Event('change'));
    await settle();
    const start = [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === 'Start Scan')!;
    expect(start.disabled).toBe(false);
    start.click();
    await settle();
  });

  afterEach(() => { http.verify(); TestBed.resetTestingModule(); });

  async function settle() {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function progress(phase: string) {
    statusKnown.set(true);
    status.set({ running: true, directories: ['/fixture/photos'], output: [], elapsed_seconds: 3, exit_code: null,
      progress: { phase, current: 5, total: 20, eta_seconds: 12 } });
    await settle();
  }

  for (const [phase, label] of [
    ['scoring', 'Scoring'], ['moments', 'Detecting moments'],
    ['junk', 'Detecting junk'], ['recompute', 'Recomputing scores'],
  ]) {
    it(`renders the ${phase} label while preserving numeric progress`, async () => {
      await progress(phase);
      expect(root.textContent).toContain(label);
      expect(root.textContent).not.toContain('[object Object]');
      expect(root.querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBe('25');
      expect(root.textContent).toContain('12s');
    });
  }

  for (const phase of ['gallery', 'future-phase', 'constructor']) {
    it(`renders the unknown phase ${phase} literally`, async () => {
      await progress(phase);
      expect(root.textContent).toContain(phase);
      expect(root.textContent).not.toContain('[object Object]');
    });
  }

  it('shows the running label before structured progress arrives', async () => {
    expect(root.textContent).toContain('Checking scan status…');
    statusKnown.set(true); status.set({ ...status(), running: true }); await settle();
    expect(root.textContent).toContain('Running');
    expect(root.querySelector('mat-progress-bar')?.getAttribute('aria-valuenow')).toBeNull();
  });

  it('keeps read recovery distinct from starting a scan and hides stale progress', async () => {
    await progress('scoring');
    observationError.set(true); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain('Status unavailable');
    expect(root.querySelector('mat-progress-bar')).toBeNull();
    const retry = [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('Read scan status again'))!;
    retry.click(); await settle();
    expect(reconnect).toHaveBeenCalledTimes(2); // open + explicit read recovery
    expect(startScan).toHaveBeenCalledTimes(1); // original user intent only
  });

  it('shows an actual nonzero exit as failure rather than running', async () => {
    statusKnown.set(true); status.set({ ...status(), running: false, exit_code: 1 }); await settle();
    expect(root.textContent).toContain('Scan ended with an error');
    expect(root.querySelector('mat-progress-bar')).toBeNull();
  });

  it('updates translated phase labels when the language changes', async () => {
    await progress('scoring');
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('fr');
    const loaded = i18n.load();
    http.expectOne('/api/i18n/fr').flush({ ...translations, scan: { ...translations.scan, phase: { scoring: 'Évaluation' } } });
    await loaded;
    await settle();
    expect(root.textContent).toContain('Évaluation');
    expect(root.textContent).not.toContain('Scoring');
  });
});
