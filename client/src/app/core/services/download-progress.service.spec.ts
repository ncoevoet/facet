import { TestBed } from '@angular/core/testing';
import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable, Subject, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { I18nService } from './i18n.service';
import { DownloadProgressService, DownloadProgressState } from './download-progress.service';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../utils/http-error-context';

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
    await Promise.resolve();
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

  it('handles server errors locally so no global toast replaces the progress', async () => {
    await service.run(items('a.jpg'));
    const context = getRaw.mock.calls[0][1] as HttpContext;
    expect(context.get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
  });

  it('reopens the progress snackbar when another one replaced it', async () => {
    const first = new Subject<Blob>();
    getRaw.mockReturnValueOnce(first as Observable<Blob>);
    const run = service.run(items('a.jpg', 'b.jpg'));
    dismissals[0].next();
    first.next(new Blob(['x'])); first.complete();
    await run;
    expect(openFromComponent).toHaveBeenCalledTimes(2);
    expect(saved).toEqual(['a.jpg', 'b.jpg']);
  });
  it('does not cover another snackbar, such as an Undo offer, while it is showing', async () => {
    const first = new Subject<Blob>();
    getRaw.mockReturnValueOnce(first as Observable<Blob>);
    const run = service.run(items('a.jpg', 'b.jpg'));
    dismissals[0].next();
    snackBar._openedSnackBarRef = { undo: true };
    first.next(new Blob(['x'])); first.complete();
    await run;
    expect(openFromComponent).toHaveBeenCalledTimes(1);
    expect(saved).toEqual(['a.jpg', 'b.jpg']);
  });

  it.each([401, 403])('stops the batch on a %i instead of failing every remaining photo', async status => {
    getRaw.mockImplementation((url: string) => url.endsWith('b.jpg')
      ? throwError(() => new HttpErrorResponse({ status, url }))
      : blob());
    await service.run(items('a.jpg', 'b.jpg', 'c.jpg'));
    expect(getRaw).toHaveBeenCalledTimes(2);
    expect(saved).toEqual(['a.jpg']);
    expect(open.mock.calls[0][0]).toBe('gallery.selection.download_partial {"saved":1,"total":3,"failed":1}');
  });
});
