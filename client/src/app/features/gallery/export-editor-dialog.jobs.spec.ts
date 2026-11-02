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
import { ExportService, ExportPreview, ExportPreviewRequest, SidecarJobStatus } from '../../core/services/export.service';
import { I18nService } from '../../core/services/i18n.service';
import { ExportEditorDialogComponent, ExportEditorDialogData } from './export-editor-dialog.component';

function job(overrides: Partial<SidecarJobStatus> = {}): SidecarJobStatus {
  return { id: 'job', state: 'running', started_at: 1, total: 3, processed: 0, written: 0, skipped: 0, errors: 0, cancel_requested: false, ...overrides };
}

function preview(request: ExportPreviewRequest): ExportPreview {
  return { request, preview_token: 'captured-plan', receipt_id: 'job', expires_at: 9999999999,
    mode: request.mode ?? 'sidecars', target_dir: request.target_dir ?? null,
    selected_paths: request.paths ?? ['/a.jpg', '/b.jpg', '/c.jpg'],
    items: [], ready: 3, missing: 0, writer: 'xml' };
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
  let token: string;
  let session: ReturnType<typeof signal<{ user: string; edition: boolean; revision: number }>>;

  function build(data: ExportEditorDialogData = { paths: ['/a.jpg'] }, flushRecent = true): void {
    token = 'session-a';
    session = signal({ user: 'alice', edition: true, revision: 1 });
    events = new Subject(); beforeClosed = new Subject();
    close = vi.fn(); snack = vi.fn();
    TestBed.configureTestingModule({ imports: [ExportEditorDialogComponent], providers: [
      ApiService, ExportService, provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: AuthService, useValue: { status: session, get token() { return token; }, identity: computed(() => session().user), isEdition: computed(() => session().edition) } },
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

  async function capture(): Promise<ExportPreview> {
    const pending = component.previewExport();
    const request = http.expectOne('/api/export/preview');
    const result = preview(request.request.body);
    request.flush(result); await pending;
    http.expectNone('/api/export/apply');
    return result;
  }

  async function start(status = job()): Promise<void> {
    const captured = await capture();
    const pending = component.confirmPreview();
    const request = http.expectOne('/api/export/apply');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ ...captured.request, preview_token: captured.preview_token, selected_paths: captured.selected_paths });
    request.flush(status, { status: 202, statusText: 'Accepted' });
    await pending;
  }

  afterEach(() => {
    fixture?.destroy(); fixture = null;
    http.verify();
    vi.useRealTimers();
  });

  it.each([
    [{ paths: ['/a.jpg', '/b.jpg'] }, { paths: ['/a.jpg', '/b.jpg'], exclude: [] }],
    [{ filters: { camera: 'Canon' }, exclude: ['/skip.jpg'] }, { filters: { camera: 'Canon' }, exclude: ['/skip.jpg'] }],
    [{ albumId: 7 }, { album_id: 7 }],
  ] as [ExportEditorDialogData, unknown][])('previews scope without writes and confirms captured membership for %j', async (data, body) => {
    build(data);
    component.overwrite.set(true);
    const pending = component.previewExport();
    const request = http.expectOne('/api/export/preview');
    expect(request.request.body).toEqual({ ...(body as object), overwrite: true, mode: 'sidecars', target_dir: null, include_companions: false });
    http.expectNone('/api/export/sidecars');
    http.expectNone('/api/albums/7/export');
    const captured = preview(request.request.body);
    request.flush(captured);
    await pending;
    expect(component.running()).toBe(false);
    expect(component.job()).toBeNull();
    http.expectNone('/api/export/apply');
    const confirming = component.confirmPreview();
    const apply = http.expectOne('/api/export/apply');
    expect(apply.request.body.selected_paths).toEqual(captured.selected_paths);
    expect(apply.request.body.preview_token).toBe(captured.preview_token);
    apply.flush(job()); await confirming;
    expect(component.running()).toBe(true);
    expect(close).not.toHaveBeenCalled();
  });

  it('opens the receipts workspace without export controls and retains a successful explicit retry receipt', async () => {
    build({ receiptsOnly: true, paths: ['/accidental.jpg'] }, false);
    const receipt = job({ state: 'completed', processed: 3, written: 2, skipped: 1 });
    http.expectOne('/api/export/sidecar_jobs').flush([receipt]);
    await flushMicrotasks(2); fixture!.detectChanges();
    expect(component.canRun()).toBe(false);
    await component.previewExport();
    http.expectNone(request => request.method === 'POST');
    expect(fixture!.nativeElement.querySelector('mat-radio-group')).toBeNull();
    expect(fixture!.nativeElement.textContent).not.toContain('export.lightroom.title');
    expect(fixture!.nativeElement.textContent).toContain('export.jobs.workspace_title');
    const selected = component.viewJob(receipt);
    http.expectOne('/api/export/sidecar_jobs/job').flush(receipt); await selected; fixture!.detectChanges();
    expect(fixture!.nativeElement.querySelector('[aria-live=polite]')?.textContent).toContain('export.jobs.partial');
    expect(fixture!.nativeElement.querySelector('.font-mono')?.textContent).toBe('export.jobs.receipt_id {}: job');
    const retry = component.retryJob();
    http.expectOne('/api/export/sidecar_jobs/job/preview').flush(preview({ paths: ['/a.jpg'], source_job: 'job' }));
    await retry; fixture!.detectChanges();
    expect(component.job()?.id).toBe('job');
    expect(fixture!.nativeElement.querySelector('[data-export-confirm]')).not.toBeNull();
    http.expectNone('/api/export/apply');
    const confirming = component.confirmPreview();
    http.expectOne('/api/export/apply').flush(job({ id: 'repair', state: 'completed', total: 1, processed: 1, written: 1 }));
    await confirming;
    expect(component.job()?.id).toBe('repair');
    expect(close).not.toHaveBeenCalled();
  });

  it('closes a pending receipts read after same-owner token rotation, but retains stable-token revalidation', async () => {
    build({ receiptsOnly: true }, false);
    const request = http.expectOne('/api/export/sidecar_jobs');
    session.update(value => ({ ...value, revision: 2 })); TestBed.tick();
    expect(close).not.toHaveBeenCalled();
    expect(request.cancelled).toBe(false);
    token = 'session-b';
    session.update(value => ({ ...value, revision: 3 })); TestBed.tick();
    await flushMicrotasks(2);
    expect(close).toHaveBeenCalledTimes(1);
    expect(request.cancelled).toBe(true);
    expect(component.recentLoading()).toBe(false);
    await component.loadRecent(); await component.previewExport();
    http.expectNone('/api/export/sidecar_jobs');
  });

  it('captures export scope and refuses a retry after same-owner token rotation', async () => {
    const data = { paths: ['/a.jpg'] }; build(data); data.paths.push('/later.jpg');
    await start(job({ state: 'failed', processed: 1, errors: 1 }));
    // start() verified the real request; changing the caller array cannot retarget it.
    expect(component.lightroomScope()).toEqual({ paths: ['/a.jpg'] });
    token = 'session-b';
    await component.retryJob(); await component.cancelJob(); await component.previewExport();
    http.expectNone(request => request.method === 'POST');
    expect(component.job()?.state).toBe('failed');
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
    const retry = http.expectOne('/api/export/sidecar_jobs/job/preview');
    expect(retry.request.method).toBe('POST');
    const captured = preview({ paths: ['/a.jpg'], source_job: 'job' });
    retry.flush(captured);
    await retrying;
    expect(component.preview()).toEqual(captured);
    expect(component.job()?.id).toBe(status.id);
    http.expectNone('/api/export/apply');
    const confirming = component.confirmPreview();
    http.expectOne('/api/export/apply').flush(job({ id: 'retry-job', total: 2 })); await confirming;
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
    await capture();
    const starting = component.confirmPreview();
    const mutation = http.expectOne('/api/export/apply');
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
    await component.cancelJob(); await component.retryJob(); await component.previewExport();
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

  it('does not abort an explicit cancellation mutation when the dialog closes', async () => {
    vi.useFakeTimers(); build();
    await start(job());
    const before = component.job();
    const pending = component.cancelJob();
    const request = http.expectOne('/api/export/sidecar_jobs/job/cancel');
    component.close();
    expect(request.cancelled).toBe(false);
    request.flush(job({ state: 'cancelled' }));
    await pending;
    expect(component.job()).toBe(before);
    vi.advanceTimersByTime(3000);
    http.expectNone(r => r.method === 'GET');
    expect(snack).not.toHaveBeenCalled();
  });

  it('cancels an obsolete retry preview on close without starting another export', async () => {
    build(); await start(job({ state: 'cancelled', processed: 1, written: 1 }));
    const pending = component.retryJob();
    const request = http.expectOne('/api/export/sidecar_jobs/job/preview');
    component.close();
    expect(request.cancelled).toBe(true);
    await pending;
    http.expectNone('/api/export/apply');
    expect(component.preview()).toBeNull();
  });

  it('blocks mutations while switching receipts so an old visible receipt cannot be retried by mistake', async () => {
    build();
    await start(job({ id: 'old', state: 'completed', processed: 3, written: 2, errors: 1 }));
    const selecting = component.viewJob(job({ id: 'selected', state: 'interrupted' }));
    const status = http.expectOne('/api/export/sidecar_jobs/selected');
    await component.retryJob(); await component.cancelJob(); await component.previewExport();
    http.expectNone(r => r.method === 'POST');
    status.flush(job({ id: 'selected', state: 'interrupted' }));
    await selecting;
    const retrying = component.retryJob();
    http.expectOne('/api/export/sidecar_jobs/selected/preview').flush(preview({ paths: ['/a.jpg'], source_job: 'selected' }));
    await retrying;
    const confirming = component.confirmPreview();
    http.expectOne('/api/export/apply').flush(job({ id: 'retry-selected' })); await confirming;
    expect(component.job()?.id).toBe('retry-selected');
  });

  it('keeps a private-album refusal visible and never claims a successful export', async () => {
    build({ albumId: 7 });
    const pending = component.previewExport();
    const request = http.expectOne('/api/export/preview');
    expect(request.request.body).toEqual({ album_id: 7, overwrite: false, mode: 'sidecars', target_dir: null, include_companions: false });
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

  it('invalidates captured preview when options change and refuses a stale confirmation', async () => {
    build(); await capture();
    expect(component.canConfirm()).toBe(true);
    component.overwrite.set(true);
    // The synchronous guard must work before the scheduled cleanup effect.
    await component.confirmPreview();
    http.expectNone('/api/export/apply');
    TestBed.tick();
    expect(component.preview()).toBeNull();
    expect(component.canConfirm()).toBe(false);
    await capture();
    expect(component.preview()?.request.overwrite).toBe(true);
    expect(component.canConfirm()).toBe(true);
  });

  it('recovers an uncertain confirmation by reading its exact receipt without another apply', async () => {
    build(); const captured = await capture();
    const confirming = component.confirmPreview();
    http.expectOne('/api/export/apply').flush({}, { status: 503, statusText: 'Unavailable' });
    await confirming; fixture!.detectChanges();
    expect(component.uncertainReceipt()).toBe(captured.receipt_id);
    expect(component.canConfirm()).toBe(false);
    expect(fixture!.nativeElement.textContent).toContain('export.preview.uncertain');
    await component.confirmPreview(); await component.previewExport();
    http.expectNone(request => request.method === 'POST');
    const recovering = component.recoverConfirmation();
    const read = http.expectOne(`/api/export/sidecar_jobs/${captured.receipt_id}`);
    expect(read.request.method).toBe('GET');
    read.flush(job({ state: 'completed', total: 3, processed: 3, written: 3, confirmed: true }));
    await recovering;
    expect(component.uncertainReceipt()).toBeNull();
    expect(component.preview()).toBeNull();
    expect(component.job()?.written).toBe(3);
    expect(close).not.toHaveBeenCalled();
    http.expectNone(request => request.method === 'POST');
  });

  it('cancels an obsolete preview read on navigation without starting an export', async () => {
    build(); const pending = component.previewExport();
    const readOnlyPreview = http.expectOne('/api/export/preview');
    events.next(new NavigationStart(1, '/albums'));
    expect(readOnlyPreview.cancelled).toBe(true);
    await pending;
    expect(component.preview()).toBeNull();
    http.expectNone('/api/export/apply');
  });

  it('pages all captured file rows without extra requests or truncating the confirmed selection', async () => {
    build(); const pending = component.previewExport();
    const request = http.expectOne('/api/export/preview');
    const captured = preview(request.request.body);
    captured.selected_paths = Array.from({ length: 27 }, (_, i) => `/photo-${i}.jpg`);
    captured.items = captured.selected_paths.map(path => ({ photo_path: path, source_name: path.slice(1),
      target_name: path.slice(1) + '.xmp', state: 'ready', companion: false, target_exists: false, metadata: null }));
    captured.ready = 27;
    request.flush(captured); await pending; fixture!.detectChanges();
    expect(fixture!.nativeElement.querySelectorAll('[data-export-preview] > details')).toHaveLength(25);
    component.previewPage.set(1); fixture!.detectChanges();
    const text = fixture!.nativeElement.querySelector('[data-export-preview]').textContent;
    expect(text).toContain('photo-25.jpg'); expect(text).toContain('photo-26.jpg');
    expect(text).not.toContain('photo-24.jpg');
    const confirm = component.confirmPreview();
    const apply = http.expectOne('/api/export/apply');
    expect(apply.request.body.selected_paths).toEqual(captured.selected_paths);
    apply.flush(job({ total: 27 })); await confirm;
    http.expectNone(request => request.method === 'GET');
  });

  it('renders mapped XMP values and distinguishes two full hierarchy paths from flat keywords', async () => {
    build(); const pending = component.previewExport();
    const request = http.expectOne('/api/export/preview');
    const captured = preview(request.request.body);
    captured.items = [{ photo_path: '/a.jpg', source_name: 'a.jpg', target_name: 'a.jpg.xmp',
      state: 'ready', companion: false, target_exists: false, metadata: {
        star_rating: 0, is_favorite: true, is_rejected: false, is_kept: true, date_taken: null,
        date_manually_set: false, gps_manually_set: false, gps_latitude: null, gps_longitude: null,
        tags: ['literal/slash'], ai_tags: [], manual_tags: ['literal/slash'],
        hierarchy_paths: ['Animals|Domestic|Cat', 'Animals|Wild|Cat'], caption: '', category: '', person_names: [], regions: [],
        aggregate: null, xmp_rating: 0, xmp_label: 'Yellow', review_decision: 'kept', manual_date: null,
        gps_state: null, review_scope: 'personal', keywords: ['literal/slash', 'Animals|Domestic|Cat', 'Animals|Wild|Cat'], face_regions_supported: false,
        provenance: { review_scope: 'personal', review: [], manual_tags: [], manual_tags_truncated: false,
          capture_date_override: false, gps_override: false },
      } }];
    request.flush(captured); await pending; fixture!.detectChanges();
    const details = fixture!.nativeElement.querySelector('[data-export-preview] > details') as HTMLDetailsElement;
    details.open = true;
    const values = Array.from(details.querySelectorAll('dl > dt')).map(label => [label.textContent, label.nextElementSibling?.textContent]);
    expect(values).toContainEqual(['export.preview.rating {}', '0']);
    expect(values).toContainEqual(['export.preview.color_label {}', 'Yellow']);
    expect(values).toContainEqual(['rating.favorite {}', 'organization_history.yes {}']);
    expect(values).toContainEqual(['export.preview.decision {}', 'review.kept {}']);
    expect(values).toContainEqual(['export.preview.hierarchical_keywords {}', 'Animals|Domestic|Cat\nAnimals|Wild|Cat']);
    expect(details.querySelector('[data-export-hierarchy]')?.textContent).not.toContain('literal/slash');
    http.expectNone('/api/export/apply');
  });
});
