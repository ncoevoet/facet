import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
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
});
