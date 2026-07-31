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

  it('falls back to a minimal context list when loading fails', async () => {
    build();
    getSuggestedContext.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.ngOnInit();

    expect(component.contexts()).toEqual([{ name: 'default', label_key: expect.any(String) }]);
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

  it('close() returns the selected context once photos were updated, else null', async () => {
    build();
    await component.ngOnInit();
    component.selectedContext.set('party_event');

    component.close();
    expect(dialogClose).toHaveBeenCalledWith(null);

    await component.save();
    component.close();
    expect(dialogClose).toHaveBeenCalledWith('party_event');
  });
});
