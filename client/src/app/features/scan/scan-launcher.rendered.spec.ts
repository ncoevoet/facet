import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal, computed } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { By } from '@angular/platform-browser';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService, ScanStatus } from '../../core/services/scan.service';
import { ScanLauncherComponent } from './scan-launcher.component';
import { ScanHistoryComponent } from './scan-history.component';

const translations = {
  scan: {
    checking_status: 'Checking scan status…', status_unavailable: 'Status unavailable', retry_status: 'Read scan status again', failed: 'Scan ended with an error',
    title: 'Scan Photos', close: 'Close', start_button: 'Start Scan', running: 'Running',
    pick_directory: 'Pick a directory', eta: 'ETA',
    stop_button: 'Stop scan', stop_confirm: 'Stop this scan?', stop_consequence: 'Saved results stay.',
    stopping: 'Stop requested', ended_after_stop: 'Scan ended after a stop request',
    stop_unconfirmed: 'Stop request unconfirmed',
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
  let cancelScan: ReturnType<typeof vi.fn>;
  let close: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    status = signal<ScanStatus>({ running: false, directories: [], output: [], elapsed_seconds: null, exit_code: null });
    statusKnown = signal(true); observationError = signal(false); reconnect = vi.fn(async () => undefined);
    startScan = vi.fn(async () => { statusKnown.set(false); });
    cancelScan = vi.fn(async () => { status.update(s => ({ ...s, cancel_requested: true })); });
    close = vi.fn();
    TestBed.configureTestingModule({ imports: [ScanLauncherComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: ScanService, useValue: {
        status, canLaunch: () => true, connected: signal(true), statusKnown, observationError, connect: reconnect,
        loadDirectories: vi.fn(async () => [{ path: '/fixture/photos', owner: '' }]),
        startScan,
        cancelScan, canCancel: computed(() => statusKnown() && !observationError() && status().running && !!status().job_id && !status().cancel_requested),
      } },
      { provide: MatDialogRef, useValue: { close } },
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

  it('refreshes a captured accepted retry that finishes before its running state is observed', async () => {
    const history = fixture.debugElement.query(By.directive(ScanHistoryComponent)).componentInstance as ScanHistoryComponent;
    history.retryAccepted.emit('b'.repeat(32));
    statusKnown.set(true);
    status.set({ ...status(), job_id: 'b'.repeat(32), running: false, exit_code: 0 });
    await settle();
    expect(close).toHaveBeenCalledWith(true);
  });

  it('does not treat an unrelated ended job as the captured retry completion', async () => {
    const history = fixture.debugElement.query(By.directive(ScanHistoryComponent)).componentInstance as ScanHistoryComponent;
    history.retryAccepted.emit('b'.repeat(32));
    statusKnown.set(true);
    status.set({ ...status(), job_id: 'c'.repeat(32), running: false, exit_code: 0 });
    await settle();
    expect(close).not.toHaveBeenCalled();
    [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === 'Close')!.click();
    await settle();
    expect(close).toHaveBeenCalledWith(false);
  });

  it('keeps prior partial refresh without auto-closing a retry for a different later job', async () => {
    await progress('scoring');
    status.update(value => ({ ...value, job_id: 'a'.repeat(32), running: false, exit_code: 1 }));
    await settle();
    expect(close).not.toHaveBeenCalled();
    const history = fixture.debugElement.query(By.directive(ScanHistoryComponent)).componentInstance as ScanHistoryComponent;
    history.retrySubmitted.emit(); history.retryAccepted.emit('b'.repeat(32));
    status.set({ ...status(), job_id: 'c'.repeat(32), running: false, exit_code: 0 });
    await settle();
    expect(close).not.toHaveBeenCalled();
    [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === 'Close')!.click();
    await settle();
    expect(close).toHaveBeenCalledWith(true); // Already observed A may have committed partial results.
  });

  it('requires a captured stop confirmation and does not auto-close a zero exit after stopping', async () => {
    await progress('scoring');
    const job = '1'.repeat(32);
    status.update(s => ({ ...s, job_id: job, kind: 'scan' })); await settle();
    const button = (label: string) => [...root.querySelectorAll<HTMLButtonElement>('button')]
      .find(element => element.textContent?.trim() === label)!;
    button('Stop scan').click(); await settle();
    expect(cancelScan).not.toHaveBeenCalled();
    expect(root.textContent).toContain('Saved results stay.');
    button('Stop this scan?').click(); await settle();
    expect(cancelScan).toHaveBeenCalledExactlyOnceWith(job);
    expect(root.textContent).toContain('Stop requested');
    expect(root.textContent).not.toContain('12s');
    status.update(s => ({ ...s, running: false, exit_code: 0 })); await settle();
    expect(root.textContent).toContain('Scan ended after a stop request');
    expect(close).not.toHaveBeenCalled();
    button('Close').click(); await settle();
    expect(close).toHaveBeenCalledWith(true); // caller refreshes already committed scan results
  });

  it('recovers an uncertain stop using status only and clears the alert when observation confirms it', async () => {
    await progress('scoring');
    status.update(s => ({ ...s, job_id: '1'.repeat(32), kind: 'scan' })); await settle();
    cancelScan.mockRejectedValueOnce(new Error('connection lost'));
    const button = (label: string) => [...root.querySelectorAll<HTMLButtonElement>('button')]
      .find(element => element.textContent?.trim() === label)!;
    button('Stop scan').click(); await settle();
    button('Stop this scan?').click(); await settle();
    expect(cancelScan).toHaveBeenCalledTimes(1);
    expect(reconnect).toHaveBeenCalledTimes(2);
    expect(root.textContent).toContain('Stop request unconfirmed');
    status.update(s => ({ ...s, cancel_requested: true })); await settle();
    expect(root.textContent).not.toContain('Stop request unconfirmed');
    expect(root.textContent).toContain('Stop requested');
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
