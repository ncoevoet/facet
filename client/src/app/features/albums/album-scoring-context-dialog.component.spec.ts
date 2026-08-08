import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { AlbumScoringContextDialogComponent } from './album-scoring-context-dialog.component';

describe('AlbumScoringContextDialogComponent', () => {

  let fixture: ComponentFixture<AlbumScoringContextDialogComponent>;
  let component: any;
  let get: ReturnType<typeof vi.fn>;
  let post: ReturnType<typeof vi.fn>;
  let setScoringContext: ReturnType<typeof vi.fn>;
  let clearScoringContext: ReturnType<typeof vi.fn>;
  let getSuggestedContext: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;

  const CONTEXTS = {
    contexts: [
      { name: 'default', label_key: 'comparison.context.default' },
      { name: 'party_event', label_key: 'comparison.context.party_event' },
    ],
  };

  function build(currentContext: string | null = null, suggestion: unknown = { suggested: null, moment: null, share: 0, counts: {} }) {
    get = vi.fn((url: string) => {
      if (url === '/config/scoring_contexts') return of(CONTEXTS);
      if (url === '/scan/recompute_status') return of({ running: false, kind: 'recompute', progress: null, exit_code: 0 });
      return of({});
    });
    post = vi.fn(() => of({}));
    setScoringContext = vi.fn(() => of({ updated: 5, conflicts: 0, manual_skipped: 0 }));
    clearScoringContext = vi.fn(() => of({ ok: true, cleared: 5 }));
    getSuggestedContext = vi.fn(() => of(suggestion));
    dialogClose = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get, post } },
        { provide: I18nService, useValue: { t: (k: string) => k, locale: () => 'en', translations: () => ({}) } },
        { provide: AlbumService, useValue: { setScoringContext, clearScoringContext, getSuggestedContext } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: { albumId: 7, albumName: 'Trip', currentContext } },
      ],
    });
    fixture = TestBed.createComponent(AlbumScoringContextDialogComponent);
    component = fixture.componentInstance as any;
  }

  function buttons(): HTMLButtonElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
  }

  it('loads contexts and the suggestion, defaulting the selection to "default"', async () => {
    build();
    await component.ngOnInit();

    expect(get).toHaveBeenCalledWith('/config/scoring_contexts');
    expect(getSuggestedContext).toHaveBeenCalledWith(7);
    expect(component.contexts()).toEqual(CONTEXTS.contexts);
    expect(component.selectedContext()).toBe('default');
    expect(component.loading()).toBe(false);
  });

  it('preselects the album\'s current context when set', async () => {
    build('party_event');
    await component.ngOnInit();

    expect(component.selectedContext()).toBe('party_event');
  });

  // Defect 3: the suggestion is optional and its failure must never blow away the
  // real context list nor the current selection — previously one `catch` around
  // `Promise.all([contexts, suggested])` replaced the whole list with a single
  // fabricated entry whenever ONLY the suggestion call failed.
  it('keeps the real context list and just clears the suggestion when only the suggestion call fails', async () => {
    build();
    getSuggestedContext.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.ngOnInit();

    expect(component.contexts()).toEqual(CONTEXTS.contexts);
    expect(component.suggestion()).toBeNull();
    expect(component.selectedContext()).toBe('default');
    expect(component.loading()).toBe(false);
  });

  it('falls back to a minimal context list when the contexts call itself fails, independently of the suggestion', async () => {
    build();
    get.mockImplementation((url: string) => {
      if (url === '/config/scoring_contexts') return throwError(() => new Error('boom'));
      if (url === '/scan/recompute_status') return of({ running: false, kind: 'recompute', progress: null, exit_code: 0 });
      return of({});
    });
    await component.ngOnInit();

    expect(component.contexts()).toEqual([{ name: 'default', label_key: expect.any(String) }]);
    expect(component.suggestion()).toEqual({ suggested: null, moment: null, share: 0, counts: {} });
    expect(component.loading()).toBe(false);
  });

  // F11 regression: `suggestionPromise` used to get its rejection handler only after
  // `await contextsPromise` resolved, so a failing suggestion left an unhandled
  // rejection window while the (slower) contexts call was in flight. Production is
  // zoneless, so this is a real unhandled rejection there; the fix attaches
  // `.catch()` synchronously when the promise is created.
  it('attaches a rejection handler to the suggestion promise synchronously, so a failing suggestion never produces an unhandled rejection', async () => {
    build();
    get.mockImplementation((url: string) => {
      if (url === '/config/scoring_contexts') {
        return new Observable<typeof CONTEXTS>(sub => {
          setTimeout(() => { sub.next(CONTEXTS); sub.complete(); }, 25);
        });
      }
      return of({});
    });
    getSuggestedContext.mockReturnValue(throwError(() => new Error('suggestion-500')));

    interface NodeProc {
      on: (e: string, h: (r: unknown) => void) => void;
      off: (e: string, h: (r: unknown) => void) => void;
    }
    const proc = (globalThis as unknown as { process: NodeProc }).process;

    const seen: string[] = [];
    const onUnhandled = (reason: unknown) => { seen.push(String(reason)); };
    const onWindowUnhandled = (e: Event) => {
      seen.push(String((e as PromiseRejectionEvent).reason));
      e.preventDefault();
    };
    proc.on('unhandledRejection', onUnhandled);
    window.addEventListener('unhandledrejection', onWindowUnhandled);
    try {
      await component.ngOnInit();
      await new Promise(r => setTimeout(r, 5));
    } finally {
      proc.off('unhandledRejection', onUnhandled);
      window.removeEventListener('unhandledrejection', onWindowUnhandled);
    }

    expect(seen).toEqual([]);
  });

  it('save() materializes the context and moves to the saved phase with conflict count', async () => {
    build();
    setScoringContext.mockReturnValueOnce(of({ updated: 12, conflicts: 3, manual_skipped: 0 }));
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    await component.save();

    expect(setScoringContext).toHaveBeenCalledWith(7, 'party_event');
    expect(component.phase()).toBe('saved');
    expect(component.updatedCount()).toBe(12);
    expect(component.conflicts()).toBe(3);
    expect(component.cleared()).toBe(false);
  });

  // F2 regression: a member's manual override is skipped by the server, not silently
  // converted -- the count is reported separately from `conflicts` so the UI can
  // tell the user something was intentionally left alone.
  it('save() surfaces manual_skipped separately from conflicts', async () => {
    build();
    setScoringContext.mockReturnValueOnce(of({ updated: 3, conflicts: 1, manual_skipped: 2 }));
    await component.ngOnInit();

    await component.save();

    expect(component.conflicts()).toBe(1);
    expect(component.manualSkipped()).toBe(2);
  });

  // F6 regression: the server's `warning` field used to be dead payload -- the
  // dialog now surfaces it, via its own i18n message rather than raw server text.
  it('save() surfaces a server warning as a dedicated i18n message', async () => {
    build();
    setScoringContext.mockReturnValueOnce(of({
      updated: 0, conflicts: 0, manual_skipped: 0,
      warning: 'Smart album currently matches no photos; nothing was updated.',
    }));
    await component.ngOnInit();

    await component.save();

    expect(component.warning()).toBe('albums.scoring_context.empty_warning');
  });

  it('save() reverts to the select phase on failure', async () => {
    build();
    await component.ngOnInit();
    setScoringContext.mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.save();

    expect(component.phase()).toBe('select');
  });

  // F6 regression: clearing must be reachable as its own action, distinct from
  // selecting the "default" context (which stamps `default` rather than clearing).
  it('clear() calls the clear endpoint and reports the cleared count distinctly from a save', async () => {
    build('party_event');
    clearScoringContext.mockReturnValueOnce(of({ ok: true, cleared: 7 }));
    await component.ngOnInit();

    await component.clear();

    expect(clearScoringContext).toHaveBeenCalledWith(7);
    expect(component.phase()).toBe('saved');
    expect(component.updatedCount()).toBe(7);
    expect(component.cleared()).toBe(true);
    component.close();
    expect(dialogClose).toHaveBeenCalledWith(null);
  });

  it('renders a "Clear context" action only when the album currently carries a context', async () => {
    build('party_event');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(buttons().some(b => (b.textContent ?? '').includes('albums.scoring_context.clear_button'))).toBe(true);
  });

  it('does not render the "Clear context" action when the album has no context yet', async () => {
    build(null);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(buttons().some(b => (b.textContent ?? '').includes('albums.scoring_context.clear_button'))).toBe(false);
  });

  // F1: the stamped count is the album's filter definition, not the gallery view --
  // this note must actually be wired into the saved-phase template.
  it('shows the membership note after a successful save', async () => {
    build();
    fixture.detectChanges();
    await fixture.whenStable();

    await component.save();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('albums.scoring_context.membership_note');
  });

  it('recompute() runs to completion and reports recompute_done', async () => {
    build();
    await component.ngOnInit();
    await component.save();

    await component.recompute();
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(post).toHaveBeenCalledWith('/scan/recompute', { confirm: true });
    expect(component.phase()).toBe('recompute_done');
  });

  it('recompute() surfaces a busy error on 409 without leaving the saved phase', async () => {
    build();
    await component.ngOnInit();
    await component.save();
    post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 409 })));

    await component.recompute();

    expect(component.phase()).toBe('saved');
    expect(component.recomputeError()).toBe('busy');
  });

  // documents: `_scan_state` in api/routers/scan.py is a per-process module global,
  // and a status poll served by a worker that never saw the POST returns
  // {running: false, exit_code: null} -- indistinguishable, for this client, from a
  // failed job. Not a defect in this component (the ambiguity is server-side and
  // out of scope here); pinned so a future change to this interpretation is deliberate.
  it('reports recompute_error when a status poll returns {running:false, exit_code:null}', async () => {
    build();
    get.mockImplementation((url: string) => {
      if (url === '/config/scoring_contexts') return of(CONTEXTS);
      if (url === '/scan/recompute_status') return of({ running: false, kind: null, progress: null, exit_code: null });
      return of({});
    });
    await component.ngOnInit();
    await component.save();

    await component.recompute();
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(component.phase()).toBe('recompute_error');
  });

  it('close() returns the persisted context after a successful save, else undefined before any save', async () => {
    build();
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    component.close();
    expect(dialogClose).toHaveBeenCalledWith(undefined);

    await component.save();
    component.close();
    expect(dialogClose).toHaveBeenCalledWith('party_event');
  });

  // Defect 4: the server sets albums.scoring_context unconditionally on a successful
  // save (e.g. an empty album, or one where every member was filtered out still gets
  // `updated: 0`). The dialog must report what was actually persisted, not gate on
  // `updatedCount() > 0` -- otherwise the caller keeps stale state and a re-open
  // preselects the wrong context.
  it('close() returns the persisted context even when the server reports zero updated photos', async () => {
    build();
    setScoringContext.mockReturnValueOnce(of({ updated: 0, conflicts: 0, manual_skipped: 0 }));
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    await component.save();

    expect(component.updatedCount()).toBe(0);
    component.close();
    expect(dialogClose).toHaveBeenCalledWith('party_event');
  });

  // Defect 5: a second click on "Recompute now" before the first POST resolves must
  // not overwrite the stored interval handle (which would leak the first one forever).
  it('recompute() ignores a second call while already recomputing (re-entrancy guard)', async () => {
    build();
    await component.ngOnInit();
    await component.save();

    const first = component.recompute();
    const second = component.recompute();
    await Promise.all([first, second]);
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(post).toHaveBeenCalledTimes(1);
  });

  // F9 regression: `disableClose: true` (set by the caller, albums.component.ts) kills
  // ESC/backdrop dismissal, and the template used to render NO closing control while
  // phase() === 'recomputing' -- trapping the user for the whole duration of a
  // full-library recompute. A dismissable control must be rendered in every phase.
  it('a rendered control can always dismiss the dialog, even mid-recompute', async () => {
    build();
    get.mockImplementation((url: string) => {
      if (url === '/config/scoring_contexts') return of(CONTEXTS);
      if (url === '/scan/recompute_status') return of({ running: true, kind: 'recompute', progress: null, exit_code: null });
      return of({});
    });
    fixture.detectChanges();
    await fixture.whenStable();

    await component.save();
    fixture.detectChanges();

    await component.recompute();
    await new Promise(resolve => setTimeout(resolve, 0));
    fixture.detectChanges();
    expect(component.phase()).toBe('recomputing');

    buttons().forEach(b => b.click());
    fixture.detectChanges();

    expect(dialogClose).toHaveBeenCalled();
  });

  // F10 regression: Cancel is rendered AND enabled during phase() === 'saving', but
  // used to close (with `mat-dialog-close`, bypassing `close()`) immediately -- discarding
  // whatever the in-flight save would go on to persist. Cancel must stay clickable
  // (the save may not be instant for a large album) but must not throw away a save
  // the server ends up committing.
  it('Cancel during "saving" requests a close for once the in-flight save settles, with the persisted result', async () => {
    build();
    let emit: ((v: { updated: number; conflicts: number; manual_skipped: number }) => void) | null = null;
    setScoringContext.mockReturnValue(new Observable<{ updated: number; conflicts: number; manual_skipped: number }>(sub => {
      emit = v => { sub.next(v); sub.complete(); };
    }));
    fixture.detectChanges();
    await fixture.whenStable();

    component.selectedContext.set('party_event');
    const saving = component.save();
    fixture.detectChanges();
    expect(component.phase()).toBe('saving');

    const cancel = buttons().find(b => /cancel/i.test(b.textContent ?? ''));
    expect(cancel).toBeTruthy();
    expect(cancel!.disabled).toBe(false);
    cancel!.click();

    emit!({ updated: 5, conflicts: 0, manual_skipped: 0 });
    await saving;

    expect(dialogClose).toHaveBeenCalledWith('party_event');
  });
});
