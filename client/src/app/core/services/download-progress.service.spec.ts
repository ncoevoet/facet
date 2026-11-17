import { TestBed } from '@angular/core/testing';
import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable, Subject, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import { DownloadProgressService, DownloadProgressState } from './download-progress.service';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../utils/http-error-context';
import { DownloadProgressSnackComponent } from '../../shared/components/download-progress-snack/download-progress-snack.component';

describe('DownloadProgressService', () => {
  let getRaw: ReturnType<typeof vi.fn>;
  let open: ReturnType<typeof vi.fn>;
  let snackBar: { open: unknown; openFromComponent: unknown; _openedSnackBarRef: unknown };
  let openFromComponent: ReturnType<typeof vi.fn>;
  let dismiss: ReturnType<typeof vi.fn>;
  let dismissals: Subject<void>[];
  let saved: string[];
  let service: DownloadProgressService;

  const items = (...names: string[]) => names.map(name => ({ url: `/api/download?path=${name}`, filename: name }));
  const state = (): DownloadProgressState => openFromComponent.mock.calls.at(-1)![1].data;
  const blob = () => of(new Blob(['x']));

  beforeEach(() => {
    saved = [];
    dismissals = [];
    dismiss = vi.fn();
    getRaw = vi.fn(blob);
    open = vi.fn();
    openFromComponent = vi.fn(() => {
      const dismissed = new Subject<void>();
      dismissals.push(dismissed);
      return { afterDismissed: () => dismissed, dismiss };
    });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    snackBar = { open, openFromComponent, _openedSnackBarRef: null };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { getRaw } },
        { provide: MatSnackBar, useValue: snackBar },
        { provide: I18nService, useValue: { t: (key: string, vars?: Record<string, unknown>) => `${key} ${JSON.stringify(vars ?? {})}` } },
      ],
    });
    service = TestBed.inject(DownloadProgressService);
  });

  afterEach(() => vi.restoreAllMocks());

  it('saves every file, counts progress and reports completion', async () => {
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    expect(saved).toEqual(['a.jpg', 'b.jpg', 'c.jpg']);
    expect(openFromComponent).toHaveBeenCalledTimes(1);
    expect(state().done()).toBe(3);
    expect(state().total).toBe(3);
    expect(dismiss).toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith('gallery.selection.download_done {"count":3}', '', { duration: 5000 });
  });

  it('says a single photo was downloaded', async () => {
    await service.run(items('a.jpg'));
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_done_one {}');
  });

  it('skips a failed file, keeps going and reports the failure', async () => {
    getRaw.mockImplementation((url: string) => url.endsWith('b.jpg') ? throwError(() => new Error('render failed')) : blob());
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    expect(saved).toEqual(['a.jpg', 'c.jpg']);
    expect(state().failed()).toBe(1);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_partial {"saved":2,"total":3,"failed":1}');
  });

  it('stops on Cancel, aborts the pending request and never fetches the rest', async () => {
    const pending = new Subject<Blob>();
    getRaw.mockReturnValueOnce(blob()).mockReturnValueOnce(pending);
    const run = service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    await vi.waitFor(() => expect(getRaw).toHaveBeenCalledTimes(2));
    state().cancel();
    await run;
    expect(getRaw).toHaveBeenCalledTimes(2);
    expect(pending.observed).toBe(false);
    expect(saved).toEqual(['a.jpg']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_cancelled {"saved":1,"total":3}');
  });

  it('stops silently once the caller is no longer current', async () => {
    let live = true;
    const pending = new Subject<Blob>();
    getRaw.mockReturnValueOnce(pending);
    const run = service.run(items('a.jpg', 'b.jpg'), () => live);
    live = false;
    pending.next(new Blob(['late'])); pending.complete();
    await run;
    expect(getRaw).toHaveBeenCalledTimes(1);
    expect(saved).toEqual([]);
    expect(dismiss).toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });

  it('fetches nothing more when the file in flight fails after the caller stopped being current', async () => {
    let live = true;
    const pending = new Subject<Blob>();
    getRaw.mockReturnValueOnce(pending);
    const run = service.run(items('a.jpg', 'b.jpg'), () => live);
    live = false;
    pending.error(new HttpErrorResponse({ status: 500 }));
    await run;
    expect(getRaw).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
  });

  it('drops a result toast that waited behind another snackbar once the caller is no longer current', async () => {
    let live = true;
    const pending = new Subject<Blob>();
    getRaw.mockReturnValueOnce(pending);
    const run = service.run(items('a.jpg'), () => live);
    const undoGone = new Subject<void>();
    snackBar._openedSnackBarRef = { afterDismissed: () => undoGone };
    pending.next(new Blob(['x'])); pending.complete();
    await run;
    expect(open).not.toHaveBeenCalled();
    live = false;
    snackBar._openedSnackBarRef = null;
    undoGone.next();
    expect(open).not.toHaveBeenCalled();
  });

  it('handles server errors locally so no global toast replaces the progress', async () => {
    await service.run(items('a.jpg'));
    const context = getRaw.mock.calls[0][1] as HttpContext;
    expect(context.get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
  });

  it('reopens the progress snackbar when something dismissed it', async () => {
    const first = new Subject<Blob>();
    getRaw.mockReturnValueOnce(first as Observable<Blob>);
    const run = service.run(items('a.jpg', 'b.jpg'));
    dismissals[0].next();
    first.next(new Blob(['x'])); first.complete();
    await run;
    expect(openFromComponent).toHaveBeenCalledTimes(2);
    expect(saved).toEqual(['a.jpg', 'b.jpg']);
  });
  it('brings the progress back as soon as a replacing snackbar has gone, mid-file', async () => {
    const pending = new Subject<Blob>();
    getRaw.mockReturnValueOnce(pending);
    const run = service.run(items('a.jpg'));
    const undoGone = new Subject<void>();
    snackBar._openedSnackBarRef = { afterDismissed: () => undoGone };
    dismissals[0].next();
    expect(openFromComponent).toHaveBeenCalledTimes(1);
    snackBar._openedSnackBarRef = null;
    undoGone.next();
    expect(openFromComponent).toHaveBeenCalledTimes(2);
    pending.next(new Blob(['x'])); pending.complete();
    await run;
    expect(saved).toEqual(['a.jpg']);
  });

  it('does not cover another snackbar, such as an Undo offer, while it is showing', async () => {
    const first = new Subject<Blob>();
    getRaw.mockReturnValueOnce(first as Observable<Blob>);
    const run = service.run(items('a.jpg', 'b.jpg'));
    const undoGone = new Subject<void>();
    snackBar._openedSnackBarRef = { afterDismissed: () => undoGone };
    dismissals[0].next();
    first.next(new Blob(['x'])); first.complete();
    await run;
    expect(openFromComponent).toHaveBeenCalledTimes(1);
    expect(saved).toEqual(['a.jpg', 'b.jpg']);
    expect(open).not.toHaveBeenCalled();
    snackBar._openedSnackBarRef = null;
    undoGone.next();
    expect(open).toHaveBeenCalledWith('gallery.selection.download_done {"count":2}', '', { duration: 5000 });
  });

  it('keeps going after a server error on one photo', async () => {
    getRaw.mockImplementation((url: string) => url.endsWith('b.jpg')
      ? throwError(() => new HttpErrorResponse({ status: 500, url }))
      : blob());
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    expect(getRaw).toHaveBeenCalledTimes(3);
    expect(saved).toEqual(['a.jpg', 'c.jpg']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_partial {"saved":2,"total":3,"failed":1}');
  });

  it.each([0, 401, 403])('stops the batch on a %i instead of failing every remaining photo', async status => {
    getRaw.mockImplementation((url: string) => url.endsWith('b.jpg')
      ? throwError(() => new HttpErrorResponse({ status, url }))
      : blob());
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    expect(getRaw).toHaveBeenCalledTimes(2);
    expect(saved).toEqual(['a.jpg']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_cancelled {"saved":1,"total":3}');
  });

  it('stops after three failures in a row, as when a shared link is revoked mid-batch', async () => {
    getRaw.mockImplementation((url: string) => url.endsWith('a.jpg')
      ? blob()
      : throwError(() => new HttpErrorResponse({ status: 404, url })));
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg', 'd.jpg', 'e.jpg', 'f.jpg'));
    expect(getRaw).toHaveBeenCalledTimes(4);
    expect(saved).toEqual(['a.jpg']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_cancelled {"saved":1,"total":6}');
  });

  it('restarts the failure count after a photo saves', async () => {
    getRaw.mockImplementation((url: string) => url.includes('bad')
      ? throwError(() => new HttpErrorResponse({ status: 500, url }))
      : blob());
    await service.run(items('bad1', 'bad2', 'ok1', 'bad3', 'bad4', 'ok2'));
    expect(saved).toEqual(['ok1', 'ok2']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_partial {"saved":2,"total":6,"failed":4}');
  });
});

describe('DownloadProgressService with the real MatSnackBar', () => {
  beforeEach(() => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    TestBed.configureTestingModule({
      providers: [
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        { provide: I18nService, useValue: { translations: () => ({}), t: (key: string) => key } },
      ],
    });
  });

  afterEach(() => vi.restoreAllMocks());

  it('leaves an Undo offer already showing alone and shows the progress once it has gone', async () => {
    const pending = new Subject<Blob>();
    TestBed.overrideProvider(ApiService, { useValue: { getRaw: vi.fn(() => pending) } });
    const snackBar = TestBed.inject(MatSnackBar);
    const undo = snackBar.open('undo offer', 'Undo');
    const run = TestBed.inject(DownloadProgressService).run([{ url: '/api/download?path=a.jpg', filename: 'a.jpg' }]);
    expect(snackBar._openedSnackBarRef).toBe(undo);
    undo.dismiss();
    await vi.waitFor(() => expect(snackBar._openedSnackBarRef?.instance).toBeInstanceOf(DownloadProgressSnackComponent));
    pending.next(new Blob(['x'])); pending.complete();
    await run;
  });

  it('waits for an Undo offer opened during the batch before showing its result', async () => {
    const pending = new Subject<Blob>();
    TestBed.overrideProvider(ApiService, { useValue: { getRaw: vi.fn(() => pending) } });
    const snackBar = TestBed.inject(MatSnackBar);
    const run = TestBed.inject(DownloadProgressService).run([{ url: '/api/download?path=a.jpg', filename: 'a.jpg' }]);
    const undo = snackBar.open('undo offer', 'Undo');
    // The service reads Material's underscore-named handle on the open snackbar.
    expect(snackBar._openedSnackBarRef).toBe(undo);
    const open = vi.spyOn(snackBar, 'open');
    pending.next(new Blob(['x'])); pending.complete();
    await run;
    expect(snackBar._openedSnackBarRef).toBe(undo);
    expect(open).not.toHaveBeenCalled();
    undo.dismiss();
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith('gallery.selection.download_done_one', '', { duration: 5000 }));
  });
});
