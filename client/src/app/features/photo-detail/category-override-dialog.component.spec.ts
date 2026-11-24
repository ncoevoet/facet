import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
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
    post = vi.fn(() => of({ success: true, path: '/a.jpg', old_category: 'silhouette', new_category: 'sports', aggregate: 7.42 }));
    dialogClose = vi.fn();
    snackOpen = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get, post } },
        { provide: MatSnackBar, useValue: { open: snackOpen } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
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

  it('saves the override and closes with the new category and recomputed aggregate', async () => {
    build('silhouette');
    await component.ngOnInit();
    component.selectedCategory.set('sports');

    await component.save();

    expect(post).toHaveBeenCalledWith('/comparison/override_category', { path: '/a.jpg', category: 'sports' });
    expect(dialogClose).toHaveBeenCalledWith({ category: 'sports', aggregate: 7.42 });
  });

  it('does not close on save error', async () => {
    build('silhouette');
    await component.ngOnInit();
    post.mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.save();

    expect(dialogClose).not.toHaveBeenCalled();
    expect(component.saving()).toBe(false);
  });
  it('cannot save a seeded category during the initial load', async () => {
    build('silhouette');
    const response = new Subject<{ categories: { name: string }[] }>();
    get.mockReturnValueOnce(response);
    const fixture = TestBed.createComponent(CategoryOverrideDialogComponent);
    fixture.detectChanges();

    const saveButton: HTMLButtonElement = fixture.nativeElement.querySelector('mat-dialog-actions button:last-child');
    expect(saveButton.disabled).toBe(true);
    await (fixture.componentInstance as any).save();
    expect(post).not.toHaveBeenCalled();

    response.next({ categories: [{ name: 'silhouette' }] });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(saveButton.disabled).toBe(false);
  });

  it('does not save a category that is missing from the returned options', async () => {
    build('retired_category');
    const fixture = TestBed.createComponent(CategoryOverrideDialogComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const instance = fixture.componentInstance as any;
    const saveButton: HTMLButtonElement = fixture.nativeElement.querySelector('mat-dialog-actions button:last-child');

    expect(instance.selectedCategory()).toBe('');
    expect(saveButton.disabled).toBe(true);
    await instance.save();
    expect(post).not.toHaveBeenCalled();

    instance.selectedCategory.set('sports');
    fixture.detectChanges();
    expect(saveButton.disabled).toBe(false);
    saveButton.click();
    await fixture.whenStable();
    expect(post).toHaveBeenCalledExactlyOnceWith('/comparison/override_category', { path: '/a.jpg', category: 'sports' });
  });

  it('a failed category load shows the alert, disables Save, and Retry recovers', async () => {
    build('silhouette');
    get.mockReturnValueOnce(throwError(() => new Error('boom')));
    const fixture = TestBed.createComponent(CategoryOverrideDialogComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const saveButton = () => el.querySelector('mat-dialog-actions button:last-child') as HTMLButtonElement;

    expect((fixture.componentInstance as any).loadFailed()).toBe(true);
    expect(el.querySelector('[role="alert"]')).not.toBeNull();
    expect(saveButton().disabled).toBe(true);

    const response = new Subject<{ categories: { name: string }[] }>();
    get.mockReturnValueOnce(response);
    (el.querySelector('[role="alert"] button') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(saveButton().disabled).toBe(true);
    await (fixture.componentInstance as any).save();
    expect(post).not.toHaveBeenCalled();

    response.next({ categories: [{ name: 'silhouette' }, { name: 'sports' }, { name: 'fashion' }] });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(get).toHaveBeenCalledTimes(2);
    expect((fixture.componentInstance as any).loadFailed()).toBe(false);
    expect((fixture.componentInstance as any).categories()).toEqual(['silhouette', 'sports', 'fashion']);
    expect(el.querySelector('[role="alert"]')).toBeNull();
    expect(saveButton().disabled).toBe(false);
  });
});
