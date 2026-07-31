import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { CategoryOverrideDialogComponent } from './category-override-dialog.component';

describe('CategoryOverrideDialogComponent', () => {

  let component: any;
  let get: ReturnType<typeof vi.fn>;
  let post: ReturnType<typeof vi.fn>;
  let dialogClose: ReturnType<typeof vi.fn>;
  let snackOpen: ReturnType<typeof vi.fn>;

  function build(currentCategory: string | null = 'silhouette') {
    get = vi.fn(() => of({ categories: [{ name: 'silhouette' }, { name: 'sports' }, { name: 'fashion' }] }));
    post = vi.fn(() => of({ success: true, path: '/a.jpg', old_category: 'silhouette', new_category: 'sports' }));
    dialogClose = vi.fn();
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get, post } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: { path: '/a.jpg', currentCategory } },
      ],
    });
    component = TestBed.runInInjectionContext(() => new CategoryOverrideDialogComponent());
  }

  it('loads the configured categories and preselects the current one', async () => {
    build('sports');
    await component.ngOnInit();

    expect(get).toHaveBeenCalledWith('/config/category_priorities');
    expect(component.categories()).toEqual(['silhouette', 'sports', 'fashion']);
    expect(component.selectedCategory()).toBe('sports');
    expect(component.loading()).toBe(false);
  });

  it('falls back to the first category when no current category is set', async () => {
    build(null);
    await component.ngOnInit();

    expect(component.selectedCategory()).toBe('silhouette');
  });

  it('saves the override and closes with the new category', async () => {
    build('silhouette');
    await component.ngOnInit();
    component.selectedCategory.set('sports');

    await component.save();

    expect(post).toHaveBeenCalledWith('/comparison/override_category', { path: '/a.jpg', category: 'sports' });
    expect(dialogClose).toHaveBeenCalledWith('sports');
  });

  it('does not close on save error', async () => {
    build('silhouette');
    await component.ngOnInit();
    post.mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.save();

    expect(dialogClose).not.toHaveBeenCalled();
    expect(component.saving()).toBe(false);
  });
});
