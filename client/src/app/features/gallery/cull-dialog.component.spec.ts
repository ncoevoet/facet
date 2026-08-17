import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { CullDialogComponent } from './cull-dialog.component';

describe('CullDialogComponent', () => {
  let component: CullDialogComponent;
  let post: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;

  function build(paths = ['/a.jpg', '/b.jpg']) {
    post = vi.fn(() => of({ would_copy: paths, skipped: [] }));
    dialogClose = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { post } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: { paths } },
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
    await component.apply();
    expect(post).toHaveBeenCalledWith('/cull/apply', expect.objectContaining({ dry_run: false }));
    expect(dialogClose).toHaveBeenCalledWith(true);
  });

  it('does not close on apply error', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.apply();
    expect(dialogClose).not.toHaveBeenCalled();
  });

  it('surfaces the server-supplied reason in the dialog on apply failure', async () => {
    build();
    set('targetDir', '/dest');
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
    post.mockReturnValueOnce(throwError(() => ({ error: { detail: 'no allowed roots configured' } })));
    await component.runPreview();
    expect(read<string | null>('errorDetail')).toBe('no allowed roots configured');
  });

  it('falls back to null errorDetail when the error has no detail', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.apply();
    expect(read<string | null>('errorDetail')).toBeNull();
  });

  it('clears a prior errorDetail on a new attempt', async () => {
    build();
    set('targetDir', '/dest');
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

  describe('preview rendering', () => {
    function buildRendered(paths = ['/a.jpg', '/b.jpg']) {
      post = vi.fn(() => of({ would_copy: paths, skipped: [] }));
      TestBed.configureTestingModule({
        imports: [CullDialogComponent],
        providers: [
          { provide: ApiService, useValue: { post } },
          { provide: MatSnackBar, useValue: { open: vi.fn() } },
          { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
          { provide: MatDialogRef, useValue: { close: vi.fn() } },
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
