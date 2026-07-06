import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { PortfolioExportDialogComponent } from './portfolio-export-dialog.component';

describe('PortfolioExportDialogComponent', () => {
  let component: PortfolioExportDialogComponent;
  let post: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;

  function build(albumName = 'Trip') {
    post = vi.fn(() => of({ exported: 2, from_original: 2, from_thumbnail: 0, output_dir: '/site' }));
    dialogClose = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { post } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: { albumId: 7, albumName } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new PortfolioExportDialogComponent());
  }

  function set<T>(name: string, value: T) {
    (component as unknown as Record<string, { set(v: T): void }>)[name].set(value);
  }
  function read<T>(name: string): T {
    return (component as unknown as Record<string, () => T>)[name]();
  }

  it('defaults the gallery title to the album name and captions on', () => {
    build('Summer');
    expect(read<string>('title')).toBe('Summer');
    expect(read<boolean>('includeCaptions')).toBe(true);
  });

  it('posts to the album portfolio endpoint and closes with true', async () => {
    build();
    set('targetDir', '/dest');
    await component.exportPortfolio();
    expect(post).toHaveBeenCalledWith(
      '/albums/7/export-portfolio',
      expect.objectContaining({ target_dir: '/dest', include_captions: true }),
    );
    expect(dialogClose).toHaveBeenCalledWith(true);
  });

  it('does not close on export error', async () => {
    build();
    set('targetDir', '/dest');
    post.mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.exportPortfolio();
    expect(dialogClose).not.toHaveBeenCalled();
  });
});
