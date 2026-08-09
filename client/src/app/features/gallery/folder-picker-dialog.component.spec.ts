import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { Observable, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { FolderPickerDialogComponent, type FolderPickerData } from './folder-picker-dialog.component';
import type { FolderItem, FoldersResponse } from '../folders/folders.util';

const folder = (name: string, path: string, photo_count = 1): FolderItem =>
  ({ name, path, photo_count, cover_photo_path: null });

const rootLevel: FoldersResponse = {
  folders: [folder('Family', '/photos/Family/', 120), folder('Travel', '/photos/Travel/', 80)],
  has_direct_photos: false,
};

const familyLevel: FoldersResponse = {
  folders: [folder('2026', '/photos/Family/2026/', 40)],
  has_direct_photos: true,
};

describe('FolderPickerDialogComponent', () => {
  let mockApi: { get: Mock };
  const mockDialogRef = { close: vi.fn() };

  const createComponent = (data: FolderPickerData = {}) => {
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: ApiService, useValue: mockApi },
      ],
    });
    return TestBed.runInInjectionContext(() => new FolderPickerDialogComponent());
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockApi = { get: vi.fn(() => of(rootLevel)) };
  });

  it('loads the root level when no prefix is supplied', async () => {
    const component = createComponent();
    await Promise.resolve();

    expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: '' });
    expect(component.prefix()).toBe('');
    expect(component.children()).toHaveLength(2);
  });

  it('opens directly on the supplied prefix in a single request', async () => {
    mockApi.get.mockReturnValue(of(familyLevel));
    const component = createComponent({ path_prefix: '/photos/Family/' });
    await Promise.resolve();

    expect(mockApi.get).toHaveBeenCalledTimes(1);
    expect(mockApi.get).toHaveBeenCalledWith('/folders', { prefix: '/photos/Family/' });
    expect(component.prefix()).toBe('/photos/Family/');
  });

  it('drills in using the path returned by the API verbatim', async () => {
    const component = createComponent();
    await Promise.resolve();

    mockApi.get.mockReturnValue(of(familyLevel));
    await component.navigateTo('/photos/Family/');

    expect(mockApi.get).toHaveBeenLastCalledWith('/folders', { prefix: '/photos/Family/' });
    expect(component.prefix()).toBe('/photos/Family/');
    expect(component.children()[0].name).toBe('2026');
  });

  it('serves an already visited level from cache without refetching', async () => {
    const component = createComponent();
    await Promise.resolve();

    mockApi.get.mockReturnValue(of(familyLevel));
    await component.navigateTo('/photos/Family/');
    const callsAfterDrillIn = mockApi.get.mock.calls.length;

    await component.navigateTo('');
    await component.navigateTo('/photos/Family/');

    expect(mockApi.get.mock.calls.length).toBe(callsAfterDrillIn);
    expect(component.prefix()).toBe('/photos/Family/');
  });

  it('closes with the current prefix on apply', async () => {
    const component = createComponent();
    await Promise.resolve();

    mockApi.get.mockReturnValue(of(familyLevel));
    await component.navigateTo('/photos/Family/');
    component.dialogRef.close(component.prefix());

    expect(mockDialogRef.close).toHaveBeenCalledWith('/photos/Family/');
  });

  it('closes with an empty prefix when applied at root, which clears the filter', async () => {
    const component = createComponent({ path_prefix: '/photos/Family/' });
    await Promise.resolve();

    mockApi.get.mockReturnValue(of(rootLevel));
    await component.navigateTo('');
    component.dialogRef.close(component.prefix());

    expect(mockDialogRef.close).toHaveBeenCalledWith('');
  });

  it('shows an empty level instead of failing when the folder has no children', async () => {
    mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: true }));
    const component = createComponent({ path_prefix: '/photos/Family/2026/Beach/' });
    await Promise.resolve();

    expect(component.children()).toEqual([]);
    expect(component.loading()).toBe(false);
    expect(component.prefix()).toBe('/photos/Family/2026/Beach/');
  });

  it('recovers from a transport error without leaving the dialog spinning', async () => {
    mockApi.get.mockReturnValue(throwError(() => new Error('offline')));
    const component = createComponent();
    await Promise.resolve();

    expect(component.children()).toEqual([]);
    expect(component.loading()).toBe(false);
    expect(component.loadError()).toBe(true);
  });

  it('reports an empty level as empty, not as a failure', async () => {
    mockApi.get.mockReturnValue(of({ folders: [], has_direct_photos: true }));
    const component = createComponent();
    await Promise.resolve();

    expect(component.loadError()).toBe(false);
  });

  it('clears the error once a retry succeeds', async () => {
    mockApi.get.mockReturnValue(throwError(() => new Error('offline')));
    const component = createComponent();
    await Promise.resolve();

    mockApi.get.mockReturnValue(of(rootLevel));
    await component.navigateTo(component.prefix());

    expect(component.loadError()).toBe(false);
    expect(component.children()).toHaveLength(2);
  });
  it('filters the visible children by name, case-insensitively', async () => {
    const component = createComponent();
    await Promise.resolve();

    component.query.set('trav');

    expect(component.filteredChildren()).toHaveLength(1);
    expect(component.filteredChildren()[0].name).toBe('Travel');
  });

  it('clears the name filter when the level changes', async () => {
    const component = createComponent();
    await Promise.resolve();
    component.query.set('trav');

    mockApi.get.mockReturnValue(of(familyLevel));
    await component.navigateTo('/photos/Family/');

    expect(component.query()).toBe('');
  });

  it('discards a stale level when responses arrive out of order', async () => {
    const component = createComponent();
    await Promise.resolve();

    let resolveSlow: (value: FoldersResponse) => void = () => {};
    const slow = new Observable<FoldersResponse>(subscriber => {
      resolveSlow = value => {
        subscriber.next(value);
        subscriber.complete();
      };
    });

    mockApi.get.mockReturnValueOnce(slow);
    const stale = component.navigateTo('/photos/Family/');

    mockApi.get.mockReturnValueOnce(of(familyLevel));
    await component.navigateTo('/photos/Travel/');

    resolveSlow(rootLevel);
    await stale;

    expect(component.prefix()).toBe('/photos/Travel/');
    expect(component.children()[0].name).toBe('2026');
  });
});

// A transport failure used to render the "No folders found." copy -- indistinguishable
// from a folder that genuinely has no children, on what the API documents as a
// potentially slow uncached subtree scan. It must say so, and offer a working retry.
describe('FolderPickerDialogComponent — a failed load surfaces a retry (rendered)', () => {
  let fixture: ComponentFixture<FolderPickerDialogComponent>;
  let component: FolderPickerDialogComponent;
  let get: Mock;

  async function render(): Promise<void> {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: {} },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: ApiService, useValue: { get } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
    fixture = TestBed.createComponent(FolderPickerDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function retryButton(): HTMLButtonElement | undefined {
    return (Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[])
      .find(b => (b.textContent ?? '').includes(I18N.gallery.load_error.retry));
  }

  it('renders the failure message and a retry control instead of the empty-folder copy', async () => {
    get = vi.fn(() => throwError(() => new Error('offline')));
    await render();

    expect(fixture.nativeElement.textContent).toContain(I18N.folders.load_error.message);
    expect(fixture.nativeElement.textContent).not.toContain(I18N.folders.empty);
    expect(retryButton()).toBeTruthy();
  });

  it('a click on retry refetches the level and renders the folders', async () => {
    get = vi.fn(() => throwError(() => new Error('offline')));
    await render();

    get.mockReturnValue(of(rootLevel));
    retryButton()!.click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(get).toHaveBeenCalledTimes(2);
    expect(component.loadError()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Family');
    expect(fixture.nativeElement.textContent).not.toContain(I18N.folders.load_error.message);
  });

  it('renders the empty-folder copy, and no retry, for a genuinely empty level', async () => {
    get = vi.fn(() => of({ folders: [], has_direct_photos: true }));
    await render();

    expect(fixture.nativeElement.textContent).toContain(I18N.folders.empty);
    expect(fixture.nativeElement.textContent).not.toContain(I18N.folders.load_error.message);
    expect(retryButton()).toBeUndefined();
  });
});
