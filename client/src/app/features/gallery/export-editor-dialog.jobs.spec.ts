import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ExportService, SidecarJobStatus } from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { ExportEditorDialogComponent, ExportEditorDialogData } from './export-editor-dialog.component';

function job(overrides: Partial<SidecarJobStatus> = {}): SidecarJobStatus {
  return { id: 'job', state: 'running', started_at: 1, total: 3, processed: 0, written: 0, skipped: 0, errors: 0, cancel_requested: false, ...overrides };
}

/** Lets already-resolved promise continuations (service subscribe -> signal set) run before an assertion. */
async function flushMicrotasks(turns = 1): Promise<void> {
  for (let turn = 0; turn < turns; turn++) await Promise.resolve();
}

describe('Export editor background jobs with HttpClient', () => {
  let fixture: ComponentFixture<ExportEditorDialogComponent> | null;
  let component: ExportEditorDialogComponent;
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let snack: ReturnType<typeof vi.fn>;
  let events: Subject<NavigationStart>;
  let beforeClosed: Subject<void>;
  let session: ReturnType<typeof signal<{ user: string; edition: boolean; revision: number }>>;

  function build(data: ExportEditorDialogData = { paths: ['/a.jpg'] }, flushRecent = true): void {
    session = signal({ user: 'alice', edition: true, revision: 1 });
    events = new Subject(); beforeClosed = new Subject();
    close = vi.fn(); snack = vi.fn();
    TestBed.configureTestingModule({ imports: [ExportEditorDialogComponent], providers: [
      ApiService, ExportService, provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: AuthService, useValue: { identity: computed(() => session().user), isEdition: computed(() => session().edition) } },
      { provide: Router, useValue: { url: '/', events } },
      { provide: MAT_DIALOG_DATA, useValue: data },
      { provide: MatDialogRef, useValue: { close, beforeClosed: () => beforeClosed } },
      { provide: MatSnackBar, useValue: { open: snack } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string, params?: unknown) => `${key} ${JSON.stringify(params ?? {})}` } },
    ] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ExportEditorDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    if (flushRecent) http.expectOne('/api/export/sidecar_jobs').flush([]);
  }

  function start(status = job()): Promise<void> {
    const pending = component.run();
    const request = http.expectOne('/api/export/sidecar_jobs');
    expect(request.request.method).toBe('POST');
    request.flush(status, { status: 202, statusText: 'Accepted' });
    return pending;
  }

  afterEach(() => {
    fixture?.destroy(); fixture = null;
    http.verify();
    vi.useRealTimers();
  });

  it.each([
    [{ paths: ['/a.jpg', '/b.jpg'] }, { paths: ['/a.jpg', '/b.jpg'], overwrite: true }],
    [{ filters: { camera: 'Canon' }, exclude: ['/skip.jpg'] }, { filters: { camera: 'Canon' }, exclude: ['/skip.jpg'], overwrite: true }],
    [{ albumId: 7 }, { filters: { album_id: '7' }, overwrite: true }],
  ] as [ExportEditorDialogData, unknown][])('starts the bounded server job for dialog scope %j', async (data, body) => {
    build(data);
    component.overwrite.set(true);
    const pending = component.run();
    const request = http.expectOne('/api/export/sidecar_jobs');
    expect(request.request.body).toEqual(body);
    http.expectNone('/api/export/sidecars');
    http.expectNone('/api/albums/7/export');
    request.flush(job());
    await pending;
    expect(component.running()).toBe(true);
    expect(close).not.toHaveBeenCalled();
  });

  it('opens the receipts workspace without export controls and retains a successful explicit retry receipt', async () => {
    build({ receiptsOnly: true, paths: ['/accidental.jpg'] }, false);
    const receipt = job({ state: 'completed', processed: 3, written: 2, skipped: 1 });
    http.expectOne('/api/export/sidecar_jobs').flush([receipt]);
    await flushMicrotasks(2); fixture!.detectChanges();
    expect(component.canRun()).toBe(false);
    await component.run();
    http.expectNone(request => request.method === 'POST');
    expect(fixture!.nativeElement.querySelector('mat-radio-group')).toBeNull();
    expect(fixture!.nativeElement.textContent).not.toContain('export.lightroom.title');
    expect(fixture!.nativeElement.textContent).toContain('export.jobs.workspace_title');
    const selected = component.viewJob(receipt);
    http.expectOne('/api/export/sidecar_jobs/job').flush(receipt); await selected; fixture!.detectChanges();
    expect(fixture!.nativeElement.querySelector('[aria-live=polite]')?.textContent).toContain('export.jobs.partial');
    expect(fixture!.nativeElement.querySelector('.font-mono')?.textContent).toBe('export.jobs.receipt_id {}: job');
    const retry = component.retryJob();
    http.expectOne('/api/export/sidecar_jobs/job/retry').flush(job({ id: 'repair', state: 'completed', total: 1, processed: 1, written: 1 }));
    await retry; fixture!.detectChanges();
    expect(component.job()?.id).toBe('repair');
    expect(close).not.toHaveBeenCalled();
  });

  it('recovers a transient failed poll with reads only and shows terminal progress', async () => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush({}, { status: 503, statusText: 'Unavailable' });
    await flushMicrotasks(2);
    expect(component.readError()).toBe(true);
    vi.advanceTimersByTime(4999);
    http.expectNone('/api/export/sidecar_jobs/job');
    vi.advanceTimersByTime(1);
    const retryRead = http.expectOne('/api/export/sidecar_jobs/job');
    expect(retryRead.request.method).toBe('GET');
    retryRead.flush(job({ state: 'completed', processed: 3, written: 2, skipped: 1 }));
    await flushMicrotasks(2);
    expect(component.readError()).toBe(false);
    expect(component.job()?.processed).toBe(3);
    expect(component.job()?.skipped).toBe(1);
    expect(close).not.toHaveBeenCalled();
    http.expectNone(request => request.method === 'POST');
  });

  it.each([401, 403, 404])('does not retry an unavailable or unauthorized receipt (%s)', async status => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush({}, { status, statusText: 'Unavailable' });
    await flushMicrotasks(2);
    vi.advanceTimersByTime(60000);
    http.expectNone('/api/export/sidecar_jobs/job');
    expect(component.readError()).toBe(true);
  });

  it('cancels a scheduled status recovery on close without retrying the mutation', async () => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush({}, { status: 503, statusText: 'Unavailable' });
    await flushMicrotasks(2);
    component.close();
    vi.advanceTimersByTime(60000);
    http.expectNone('/api/export/sidecar_jobs/job');
    http.expectNone(request => request.method === 'POST');
  });

  it('renders receipt dates in the project day/month/year and 24-hour format', async () => {
    build({ paths: ['/a.jpg'] }, false);
    http.expectOne('/api/export/sidecar_jobs').flush([job({ started_at: new Date(2026, 9, 25, 14, 7).getTime() / 1000 })]);
    await flushMicrotasks(2); fixture!.detectChanges();
    expect(fixture!.nativeElement.textContent).toContain('25/10/2026 14:07');
  });

  it('gives current-status and recent-history refresh controls distinct accessible names', async () => {
    build();
    await start(job({ state: 'interrupted', processed: 1, errors: 1 }));
    fixture!.detectChanges();
    const refreshes = [...fixture!.nativeElement.querySelectorAll('button')]
      .filter((button: HTMLElement) => button.textContent?.includes('export.jobs.refresh')) as HTMLElement[];
    expect(refreshes).toHaveLength(2);
    const names = refreshes.map(button => button.getAttribute('aria-label') ?? button.textContent!.trim());
    expect(names[0]).not.toBe(names[1]);
    expect(names[1]).toContain('export.jobs.recent');
  });

  it('announces state changes without putting changing progress or controls in the live region', async () => {
    build();
    await start(job({ state: 'interrupted', processed: 1, errors: 1 }));
    fixture!.detectChanges();
    const region = fixture!.nativeElement.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(region.textContent).toContain('export.jobs.interrupted');
    expect(region.querySelector('button, mat-progress-bar')).toBeNull();
    expect(region.textContent).not.toContain('export.jobs.progress');
    const pending = component.viewJob(component.job()!);
    http.expectOne('/api/export/sidecar_jobs/job').flush(job({ state: 'cancelled', processed: 2, errors: 1 }));
    await pending;
    fixture!.detectChanges();
    expect(region.textContent).toContain('export.jobs.cancelled');
  });

  it('identifies only the receipt whose status is currently displayed', async () => {
    build({}, false);
    const first = job({ id: 'first', state: 'failed', processed: 1, errors: 1 });
    const second = job({ id: 'second', state: 'interrupted', processed: 2, errors: 1 });
    http.expectOne('/api/export/sidecar_jobs').flush([first, second]);
    await fixture!.whenStable();
    expect(fixture!.nativeElement.querySelector('[aria-current="true"]')).toBeNull();
    for (const receipt of [first, second]) {
      const selected = component.viewJob(receipt);
      http.expectOne(`/api/export/sidecar_jobs/${receipt.id}`).flush(receipt);
      await selected;
      fixture!.detectChanges();
      const current = fixture!.nativeElement.querySelectorAll('[aria-current="true"]');
      expect(current).toHaveLength(1);
      expect(current[0].textContent).toContain(`export.jobs.${receipt.state}`);
      http.expectNone(request => request.method === 'POST');
    }
  });

  it('polls progress, cancels the pending read before an explicit stop, and retains cancelled counts', async () => {
    vi.useFakeTimers(); build();
    await start();
    vi.advanceTimersByTime(1000);
    const poll = http.expectOne('/api/export/sidecar_jobs/job');
    const stopping = component.cancelJob();
    expect(poll.cancelled).toBe(true);
    const cancel = http.expectOne('/api/export/sidecar_jobs/job/cancel');
    expect(cancel.request.method).toBe('POST');
    cancel.flush(job({ processed: 1, written: 1, cancel_requested: true }));
    await stopping;
    expect(component.job()?.cancel_requested).toBe(true);
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush(job({ state: 'cancelled', processed: 2, written: 1, skipped: 1 }));
    await flushMicrotasks(); fixture!.detectChanges();
    expect(component.job()?.processed).toBe(2);
    expect(component.canRetry()).toBe(true);
    expect(fixture!.nativeElement.textContent).toContain('export.jobs.cancelled');
    expect(fixture!.nativeElement.textContent).toContain('"skipped":1');
    expect(close).not.toHaveBeenCalled(); expect(snack).not.toHaveBeenCalled();
  });

  it.each([
    job({ state: 'completed', processed: 3, written: 2, errors: 1 }),
    job({ state: 'completed', processed: 3, written: 2, skipped: 1 }),
    job({ state: 'failed', processed: 1, errors: 1 }),
    job({ state: 'cancelled', processed: 1, written: 1 }),
    job({ state: 'interrupted', processed: 1, written: 1 }),
  ])('keeps terminal $state partial results visible for explicit retry', async status => {
    build(); await start(status); fixture!.detectChanges();
    expect(component.job()).toEqual(status);
    expect(component.canRetry()).toBe(true);
    expect(fixture!.nativeElement.textContent).toContain(`export.jobs.${status.state === 'completed' ? 'partial' : status.state}`);
    expect(fixture!.nativeElement.textContent).toContain('export.jobs.retry');
    expect(close).not.toHaveBeenCalled(); expect(snack).not.toHaveBeenCalled();
    http.expectNone(r => r.method === 'POST');
    const retrying = component.retryJob();
    const retry = http.expectOne('/api/export/sidecar_jobs/job/retry');
    expect(retry.request.method).toBe('POST');
    retry.flush(job({ id: 'retry-job', total: 2 }));
    await retrying;
    expect(component.job()?.id).toBe('retry-job');
  });

  it.each([
    ['metadata_repair', 'export.jobs.errors.metadata_repair'],
    ['write_failed', 'export.jobs.errors.write_failed'],
    ['exiftool_upgrade', 'export.jobs.errors.exiftool_upgrade'],
    ['stopped', 'export.jobs.errors.stopped'],
  ] as const)('renders the translated text for the %s receipt error code, not the English message', async (code, key) => {
    build(); await start(job({ state: 'completed', processed: 1, errors: 1, first_error: 'English server message', first_error_code: code }));
    fixture!.detectChanges();
    const text = fixture!.nativeElement.textContent as string;
    expect(text).toContain(key);
    expect(text).not.toContain('English server message');
  });

  it('falls back to the server message when a receipt carries no error code', async () => {
    build(); await start(job({ state: 'completed', processed: 1, errors: 1, first_error: 'Server message', first_error_code: null }));
    fixture!.detectChanges();
    expect(fixture!.nativeElement.textContent as string).toContain('Server message');
  });

  it('preserves the success snack and close only for a completely successful new job', async () => {
    build(); await start(job({ state: 'completed', processed: 3, written: 3 }));
    expect(close).toHaveBeenCalledOnce();
    expect(snack).toHaveBeenCalledWith(expect.stringContaining('export.done'), '', { duration: 2500 });
  });

  it('recovers recent receipts through reads without starting or retrying a job on open', async () => {
    build({ paths: [] }, false);
    const receipt = job({ state: 'interrupted', processed: 1, errors: 1, first_error: 'Export stopped' });
    http.expectOne('/api/export/sidecar_jobs').flush([receipt]);
    await flushMicrotasks(); fixture!.detectChanges();
    expect(component.recentJobs()).toEqual([receipt]);
    http.expectNone(r => r.method === 'POST');
    const selecting = component.viewJob(receipt);
    http.expectOne('/api/export/sidecar_jobs/job').flush({ ...receipt, state: 'cancelled' });
    await selecting;
    expect(component.job()?.state).toBe('cancelled');
    expect(close).not.toHaveBeenCalled(); http.expectNone(r => r.method === 'POST');
  });

  it.each(['close', 'navigation', 'destroy', 'identity'] as const)('does not abort a submitted job start or apply its late response after %s', async ending => {
    vi.useFakeTimers(); build();
    const starting = component.run();
    const mutation = http.expectOne('/api/export/sidecar_jobs');
    if (ending === 'close') component.close();
    else if (ending === 'navigation') events.next(new NavigationStart(1, '/stats'));
    else if (ending === 'destroy') { fixture!.destroy(); fixture = null; }
    else { session.update(s => ({ ...s, user: 'bob' })); TestBed.tick(); }
    expect(mutation.cancelled).toBe(false);
    mutation.flush(job());
    await starting;
    vi.advanceTimersByTime(2000);
    http.expectNone('/api/export/sidecar_jobs/job');
    expect(component.job()).toBeNull(); expect(component.recentJobs()).toEqual([]);
    expect(snack).not.toHaveBeenCalled();
  });

  it('aborts pending status/recent reads on identity change and immediately clears the old owner receipts', async () => {
    vi.useFakeTimers(); build({}, false);
    const recent = http.expectOne('/api/export/sidecar_jobs');
    component.recentJobs.set([job()]);
    component.job.set(job());
    const selecting = component.viewJob(job());
    const status = http.expectOne('/api/export/sidecar_jobs/job');
    session.update(s => ({ ...s, user: 'bob' }));
    // Method guards refuse mutations even before the scheduled auth effect runs.
    await component.cancelJob(); await component.retryJob(); await component.run();
    http.expectNone(r => r.method === 'POST');
    TestBed.tick();
    expect(recent.cancelled).toBe(true); expect(status.cancelled).toBe(true);
    await selecting;
    expect(component.recentJobs()).toEqual([]); expect(component.job()).toBeNull();
    expect(close).toHaveBeenCalled();
  });

  it('continues observing after valid same-principal session revalidation', async () => {
    vi.useFakeTimers(); build(); await start();
    session.update(s => ({ ...s, revision: s.revision + 1 })); TestBed.tick();
    expect(close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush(job({ processed: 1, written: 1 }));
    await flushMicrotasks();
    expect(component.job()?.written).toBe(1);
  });

  it.each(['cancel', 'retry'] as const)('does not abort an explicit %s mutation when the dialog closes', async action => {
    vi.useFakeTimers(); build();
    await start(action === 'cancel' ? job() : job({ state: 'completed', processed: 3, written: 2, errors: 1 }));
    const before = component.job();
    const pending = action === 'cancel' ? component.cancelJob() : component.retryJob();
    const request = http.expectOne(`/api/export/sidecar_jobs/job/${action}`);
    component.close();
    expect(request.cancelled).toBe(false);
    request.flush(action === 'cancel' ? job({ state: 'cancelled' }) : job({ id: 'new-job' }));
    await pending;
    expect(component.job()).toBe(before);
    vi.advanceTimersByTime(3000);
    http.expectNone(r => r.method === 'GET');
    expect(snack).not.toHaveBeenCalled();
  });

  it('blocks mutations while switching receipts so an old visible receipt cannot be retried by mistake', async () => {
    build();
    await start(job({ id: 'old', state: 'completed', processed: 3, written: 2, errors: 1 }));
    const selecting = component.viewJob(job({ id: 'selected', state: 'interrupted' }));
    const status = http.expectOne('/api/export/sidecar_jobs/selected');
    await component.retryJob(); await component.cancelJob(); await component.run();
    http.expectNone(r => r.method === 'POST');
    status.flush(job({ id: 'selected', state: 'interrupted' }));
    await selecting;
    const retrying = component.retryJob();
    http.expectOne('/api/export/sidecar_jobs/selected/retry').flush(job({ id: 'retry-selected' }));
    await retrying;
    expect(component.job()?.id).toBe('retry-selected');
  });

  it('keeps a private-album refusal visible and never claims a successful export', async () => {
    build({ albumId: 7 });
    const pending = component.run();
    const request = http.expectOne('/api/export/sidecar_jobs');
    expect(request.request.body).toEqual({ filters: { album_id: '7' }, overwrite: false });
    request.flush({ detail: 'Album is not visible to this user' }, { status: 403, statusText: 'Forbidden' });
    await pending;
    expect(component.errorDetail()).toBe('Album is not visible to this user');
    expect(component.job()).toBeNull(); expect(close).not.toHaveBeenCalled();
    expect(component.running()).toBe(false);
    http.expectNone('/api/export/sidecar_jobs/job');
  });

  it('preserves polling during same-path query navigation', async () => {
    vi.useFakeTimers(); build(); await start();
    events.next(new NavigationStart(1, '/?camera=Canon'));
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush(job({ processed: 1, written: 1 }));
    await flushMicrotasks();
    expect(component.job()?.processed).toBe(1); expect(close).not.toHaveBeenCalled();
  });

  it('stops observing when edition permission is revoked without cancelling the server job', async () => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    const poll = http.expectOne('/api/export/sidecar_jobs/job');
    session.update(s => ({ ...s, edition: false })); TestBed.tick();
    expect(poll.cancelled).toBe(true); expect(close).toHaveBeenCalled();
    expect(component.job()).toBeNull(); expect(component.recentJobs()).toEqual([]);
    http.expectNone('/api/export/sidecar_jobs/job/cancel');
  });

  it('keeps progress-read failures visible and retries the read only on explicit refresh', async () => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    http.expectOne('/api/export/sidecar_jobs/job').flush({ detail: 'Progress temporarily unavailable' }, { status: 503, statusText: 'Unavailable' });
    await flushMicrotasks();
    expect(component.errorDetail()).toBe('Progress temporarily unavailable');
    vi.advanceTimersByTime(3000);
    http.expectNone(r => r.method === 'GET');
    const reading = component.viewJob(component.job()!);
    http.expectOne('/api/export/sidecar_jobs/job').flush(job({ state: 'completed', processed: 3, written: 2, errors: 1 }));
    await reading;
    expect(component.errorDetail()).toBeNull(); expect(close).not.toHaveBeenCalled();
    http.expectNone(r => r.method === 'POST');
  });

  it('stops polling on close without sending a server cancellation', async () => {
    vi.useFakeTimers(); build(); await start();
    vi.advanceTimersByTime(1000);
    const poll = http.expectOne('/api/export/sidecar_jobs/job');
    beforeClosed.next();
    expect(poll.cancelled).toBe(true);
    vi.advanceTimersByTime(3000);
    http.expectNone('/api/export/sidecar_jobs/job');
    http.expectNone('/api/export/sidecar_jobs/job/cancel');
  });
});
