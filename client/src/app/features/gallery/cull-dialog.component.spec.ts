import { TestBed } from '@angular/core/testing';
import { NEVER, Subject, of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { CullDialogComponent } from './cull-dialog.component';

describe('CullDialogComponent', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [
      provideRouter([]),
      { provide: AuthService, useValue: { identity: () => 'alice', isEdition: () => true } },
    ] });
  });
  let component: CullDialogComponent;
  let post: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;
  let snackOpen: ReturnType<typeof vi.fn>;

  function build(paths = ['/a.jpg', '/b.jpg'], trashAvailable?: boolean, allowTrash?: boolean) {
    post = vi.fn(() => of({ would_copy: paths, skipped: [] }));
    dialogClose = vi.fn();
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { post } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: dialogClose, beforeClosed: () => NEVER } },
        { provide: MAT_DIALOG_DATA, useValue: { paths, trashAvailable, allowTrash } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new CullDialogComponent());
  }

  function set<T>(name: string, value: T) {
    (component as unknown as Record<string, { set(v: T): void }>)[name].set(value);
  }
  function read<T>(name: string): T {
    return (component as unknown as Record<string, () => T>)[name]();
  }
  function actions(): string[] {
    return (component as unknown as { actions: string[] }).actions;
  }

  it('defaults to the additive copy action and needs a target', () => {
    build();
    expect(read<string>('action')).toBe('copy_keeps');
    expect(read<boolean>('needsTarget')).toBe(true);
  });

  it('trash does not require a target dir', () => {
    build();
    (component as unknown as { setAction(a: string): void }).setAction('trash_rejects');
    expect(read<boolean>('needsTarget')).toBe(false);
  });

  it('omits trash_rejects from actions when trashAvailable is false', () => {
    build(['/a.jpg', '/b.jpg'], false);
    expect(actions()).not.toContain('trash_rejects');
  });

  it('omits trash_rejects from actions when trashAvailable is not passed (fail-closed)', () => {
    build();
    expect(actions()).not.toContain('trash_rejects');
  });

  it('includes trash_rejects in actions when trashAvailable is true', () => {
    build(['/a.jpg', '/b.jpg'], true);
    expect(actions()).toContain('trash_rejects');
  });

  it('a preset action is the only one offered and previews on open', () => {
    post = vi.fn(() => of({ would_trash: ['/r.jpg'], skipped: [], matched: 1 }));
    const filters = { show_rejected: '1' };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { post } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: vi.fn(), beforeClosed: () => NEVER } },
        { provide: MAT_DIALOG_DATA,
          useValue: { paths: [], filters, trashAvailable: true, action: 'trash_rejects' } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new CullDialogComponent());

    expect(actions()).toEqual(['trash_rejects']);
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({
      action: 'trash_rejects', filters, dry_run: true, include_companions: false,
    }));
  });

  describe('trash availability message', () => {
    function buildRendered(trashAvailable?: boolean, allowTrash?: boolean) {
      TestBed.configureTestingModule({
        imports: [CullDialogComponent],
        providers: [
          { provide: ApiService, useValue: { post: vi.fn(() => of({ would_copy: [], skipped: [] })) } },
          { provide: MatSnackBar, useValue: { open: vi.fn() } },
          { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
          { provide: MatDialogRef, useValue: { close: vi.fn(), beforeClosed: () => NEVER } },
          { provide: MAT_DIALOG_DATA, useValue: { paths: ['/a.jpg'], trashAvailable, allowTrash } },
        ],
      });
      const fixture = TestBed.createComponent(CullDialogComponent);
      fixture.detectChanges();
      return fixture;
    }

    function paragraphs(fixture: ReturnType<typeof buildRendered>): string[] {
      return Array.from(fixture.debugElement.nativeElement.querySelectorAll('p'))
        .map((el) => (el as HTMLElement).textContent?.trim() ?? '');
    }

    it('shows cull.trash_disabled when the operator has not enabled trashing', () => {
      const fixture = buildRendered(false, false);
      expect(paragraphs(fixture)).toContain('cull.trash_disabled');
    });

    it('shows cull.trash_missing_pkg when enabled but the send2trash package is missing', () => {
      const fixture = buildRendered(false, true);
      expect(paragraphs(fixture)).toContain('cull.trash_missing_pkg');
    });

    it('falls back to cull.trash_disabled when allowTrash is not passed (fail-closed)', () => {
      const fixture = buildRendered(false, undefined);
      expect(paragraphs(fixture)).toContain('cull.trash_disabled');
    });

    it('shows neither message when trashAvailable is true', () => {
      const fixture = buildRendered(true, true);
      expect(paragraphs(fixture).some((p) => p.startsWith('cull.trash_'))).toBe(false);
    });
  });

  it('preview posts dry_run=true and stores the affected list', async () => {
    build(['/a.jpg', '/b.jpg']);
    set('targetDir', '/dest');
    await component.runPreview();
    expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({ dry_run: true, target_dir: '/dest' }));
    expect(read<{ affected: string[] }>('preview')!.affected).toEqual(['/a.jpg', '/b.jpg']);
  });

  it('apply posts dry_run=false and closes with true', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    await component.apply();
    expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({ dry_run: false }));
    expect(dialogClose).toHaveBeenCalledWith(true);
  });

  it('does not close on apply error', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.apply();
    expect(dialogClose).not.toHaveBeenCalled();
  });

  it('surfaces the server-supplied reason in the dialog on apply failure', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => ({
      error: { detail: 'target_dir is not an allowed export location. Configure viewer.export.allowed_target_dirs' },
    })));
    await component.apply();
    expect(read<string | null>('errorDetail')).toBe(
      'target_dir is not an allowed export location. Configure viewer.export.allowed_target_dirs',
    );
  });

  it('surfaces the server-supplied reason in the dialog on preview failure', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => ({ error: { detail: 'no allowed roots configured' } })));
    await component.runPreview();
    expect(read<string | null>('errorDetail')).toBe('no allowed roots configured');
  });

  it('titles a failed dry run "Could not preview" and keeps the toast out when the inline error shows', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => ({ error: { detail: 'no allowed roots configured' } })));
    await component.runPreview();
    expect(read<string>('errorTitleKey')).toBe('cull.preview_error');
    expect(snackOpen).not.toHaveBeenCalled();
  });

  it('still toasts a dry-run failure that has no detail to show inline', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.runPreview();
    expect(snackOpen).toHaveBeenCalledTimes(1);
  });

  it('keeps the apply failure title for a failed apply', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => ({ error: { detail: 'nope' } })));
    await component.apply();
    expect(read<string>('errorTitleKey')).toBe('cull.error');
  });

  it('preserves the server cap detail for ordinary filtered previews', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => ({ status: 412,
      error: { detail: 'This view holds 10001 photos. Narrow the filters and try again.' } })));
    await component.runPreview();
    expect(read<string | null>('errorDetail')).toBe(
      'This view holds 10001 photos. Narrow the filters and try again.');
  });

  it('falls back to null errorDetail when the error has no detail', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.apply();
    expect(read<string | null>('errorDetail')).toBeNull();
  });

  it('clears a prior errorDetail on a new attempt', async () => {
    build();
    set('targetDir', '/dest');
    await component.runPreview();
    post.mockReturnValueOnce(throwError(() => ({ error: { detail: 'first failure' } })));
    await component.apply();
    expect(read<string | null>('errorDetail')).toBe('first failure');

    post.mockReturnValueOnce(of({ would_copy: [], skipped: [] }));
    await component.runPreview();
    expect(read<string | null>('errorDetail')).toBeNull();
  });

  describe('include_sequence_siblings', () => {
    it('request body carries include_sequence_siblings as the checkbox sets it', async () => {
      build();
      set('targetDir', '/dest');
      set('includeSequenceSiblings', true);
      await component.runPreview();
      expect(post).toHaveBeenCalledWith(
        '/cull/apply',
        expect.objectContaining({ include_sequence_siblings: true }),
      );
    });

    it('sameRequest is false when only include_sequence_siblings differs, so a stale preview is not reused across a toggle', async () => {
      build();
      set('targetDir', '/dest');
      const response = new Subject<{ would_copy: string[]; skipped: string[] }>();
      post.mockReturnValueOnce(response);

      const pending = component.runPreview();
      // Toggle after the request went out but before the response lands --
      // the in-flight request no longer matches the current form.
      set('includeSequenceSiblings', true);
      response.next({ would_copy: ['/a.jpg'], skipped: [] });
      response.complete();
      await pending;

      expect(read('preview')).toBeNull();
    });
  });

  describe('view-scoped body() (filters/exclude/count)', () => {
    function buildFiltered(
      filters: Record<string, string>,
      exclude: string[] = [],
      count?: number,
      paths: string[] = ['/a.jpg', '/b.jpg'],
    ) {
      post = vi.fn(() => of({ would_copy: [], skipped: [] }));
      dialogClose = vi.fn();
      TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: { post } },
          { provide: MatSnackBar, useValue: { open: vi.fn() } },
          { provide: I18nService, useValue: { t: (k: string) => k } },
          { provide: MatDialogRef, useValue: { close: dialogClose, beforeClosed: () => NEVER } },
          { provide: MAT_DIALOG_DATA, useValue: { paths, filters, exclude, count } },
        ],
      });
      component = TestBed.runInInjectionContext(() => new CullDialogComponent());
    }

    it('sends the filter and exclude list instead of a path list', async () => {
      buildFiltered({ camera: 'Canon' }, ['/skip.jpg'], 650);
      set('targetDir', '/dest');

      await component.runPreview();

      expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({
        paths: undefined,
        filters: { camera: 'Canon' },
        exclude: ['/skip.jpg'],
      }));
    });

    it('carries the same filter/exclude shape into the destructive apply request', async () => {
      buildFiltered({ camera: 'Canon' }, ['/skip.jpg'], 650);
      set('targetDir', '/dest');

      await component.runPreview();
      await component.apply();

      expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({
        paths: undefined,
        filters: { camera: 'Canon' },
        exclude: ['/skip.jpg'],
      }));
    });

    it('falls count back to paths.length when data.count is absent', () => {
      buildFiltered({ camera: 'Canon' }, [], undefined, ['/a.jpg', '/b.jpg', '/c.jpg']);

      expect((component as unknown as { count: number }).count).toBe(3);
    });
  });

  describe('preview rendering', () => {
    function buildRendered(paths = ['/a.jpg', '/b.jpg']) {
      post = vi.fn(() => of({ would_copy: paths, skipped: [] }));
      TestBed.configureTestingModule({
        imports: [CullDialogComponent],
        providers: [
          { provide: ApiService, useValue: { post } },
          { provide: MatSnackBar, useValue: { open: vi.fn() } },
          { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
          { provide: MatDialogRef, useValue: { close: vi.fn(), beforeClosed: () => NEVER } },
          { provide: MAT_DIALOG_DATA, useValue: { paths } },
        ],
      });
      const fixture = TestBed.createComponent(CullDialogComponent);
      fixture.detectChanges();
      return fixture;
    }

    function paragraphs(fixture: ReturnType<typeof buildRendered>): string[] {
      return Array.from(fixture.debugElement.nativeElement.querySelectorAll('p'))
        .map((el) => (el as HTMLElement).textContent?.trim() ?? '');
    }

    it('matched: 0 renders the cull.nothing_matched message', async () => {
      const fixture = buildRendered();
      post.mockReturnValueOnce(of({ would_copy: [], skipped: [], matched: 0 }));
      const comp = fixture.componentInstance as unknown as { targetDir: { set(v: string): void } };
      comp.targetDir.set('/dest');
      await fixture.componentInstance.runPreview();
      fixture.detectChanges();

      const text = paragraphs(fixture);
      expect(text).toContain('cull.nothing_matched');
      expect(text).not.toContain('cull.would_affect');
    });

    it('sequence_siblings: 4 renders the siblings line', async () => {
      const fixture = buildRendered();
      post.mockReturnValueOnce(of({ would_copy: ['/a.jpg'], skipped: [], matched: 1, sequence_siblings: 4 }));
      const comp = fixture.componentInstance as unknown as { targetDir: { set(v: string): void } };
      comp.targetDir.set('/dest');
      await fixture.componentInstance.runPreview();
      fixture.detectChanges();

      expect(paragraphs(fixture)).toContain('4 cull.sequence_siblings');
    });
  });
});
