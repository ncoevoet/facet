import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { AlbumScoringContextDialogComponent } from './album-scoring-context-dialog.component';

describe('AlbumScoringContextDialogComponent', () => {

  let component: any;
  let get: ReturnType<typeof vi.fn>;
  let post: ReturnType<typeof vi.fn>;
  let setScoringContext: ReturnType<typeof vi.fn>;
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
    setScoringContext = vi.fn(() => of({ updated: 5, conflicts: 0 }));
    getSuggestedContext = vi.fn(() => of(suggestion));
    dialogClose = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get, post } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: AlbumService, useValue: { setScoringContext, getSuggestedContext } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: { albumId: 7, albumName: 'Trip', currentContext } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new AlbumScoringContextDialogComponent());
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

  it('save() materializes the context and moves to the saved phase with conflict count', async () => {
    build();
    setScoringContext.mockReturnValueOnce(of({ updated: 12, conflicts: 3 }));
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    await component.save();

    expect(setScoringContext).toHaveBeenCalledWith(7, 'party_event');
    expect(component.phase()).toBe('saved');
    expect(component.updatedCount()).toBe(12);
    expect(component.conflicts()).toBe(3);
  });

  it('save() reverts to the select phase on failure', async () => {
    build();
    await component.ngOnInit();
    setScoringContext.mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.save();

    expect(component.phase()).toBe('select');
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

  it('close() returns the persisted context after a successful save, else null before any save', async () => {
    build();
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    component.close();
    expect(dialogClose).toHaveBeenCalledWith(null);

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
    setScoringContext.mockReturnValueOnce(of({ updated: 0, conflicts: 0 }));
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
});
