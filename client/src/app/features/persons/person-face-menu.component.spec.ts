import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PersonFaceMenuComponent, PersonFaceMenuTarget } from './person-face-menu.component';

describe('PersonFaceMenuComponent', () => {
  let fixture: ComponentFixture<PersonFaceMenuComponent>;
  let menu: PersonFaceMenuComponent;
  let mockApi: { post: Mock };
  let mockStore: { reloadPersonOptions: Mock; resetFilters: Mock; updateFilters: Mock };
  let mockSnackBar: { open: Mock };
  let mockRouter: { navigate: Mock; url: string };
  /** The Undo action of the last snackbar opened. */
  let snackAction: Subject<void>;
  const identity = signal('owner');

  async function openOn(target: PersonFaceMenuTarget, canEdit = true): Promise<string[]> {
    fixture = TestBed.createComponent(PersonFaceMenuComponent);
    menu = fixture.componentInstance;
    fixture.componentRef.setInput('path', '/p/a.jpg');
    fixture.componentRef.setInput('canEdit', canEdit);
    fixture.detectChanges();
    menu.open(target, 10, 10);
    fixture.detectChanges();
    await fixture.whenStable();
    return ([...document.querySelectorAll('.mat-mdc-menu-panel [mat-menu-item]')] as HTMLElement[])
      .map((b) => b.textContent!.replace(/\s+/g, ' ').trim());
  }

  beforeEach(() => {
    mockApi = { post: vi.fn(() => of({})) };
    identity.set('owner');
    mockStore = {
      reloadPersonOptions: vi.fn(async () => undefined),
      resetFilters: vi.fn(async () => undefined),
      updateFilters: vi.fn(async () => undefined),
    };
    snackAction = new Subject<void>();
    mockSnackBar = { open: vi.fn(() => ({ onAction: () => snackAction, afterDismissed: () => new Subject<void>() })) };
    mockRouter = { navigate: vi.fn(() => Promise.resolve(true)), url: '/persons' };
    TestBed.configureTestingModule({
      imports: [PersonFaceMenuComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: { identity, isEdition: () => true } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: GalleryStore, useValue: mockStore },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: Router, useValue: mockRouter },
        { provide: UserActivityJournal, useValue: { record: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
  });

  afterEach(() => fixture?.destroy());

  it('with a face: offers detection Ignore separately from person-group Ignore', async () => {
    const items = await openOn({ person: { id: 5, name: 'Valerie' }, face: { id: 1 } });
    expect(items).toEqual([
      'photo_library photo_faces.view_photos',
      'manage_accounts photo_faces.change_person',
      'visibility_off photo_faces.ignore_detection',
      'account_circle photo_faces.use_picture',
      'person_search photo_faces.find_more',
      'person_remove photo_faces.not_person',
    ]);
  });

  it('an unknown detection offers naming and Ignore; read-only and manual marks cannot Ignore', async () => {
    const items = await openOn({ person: null, face: { id: 1 } });
    expect(items).toEqual(['manage_accounts photo_faces.name_face', 'visibility_off photo_faces.ignore_detection']);
    fixture.componentRef.setInput('canEdit', false);
    fixture.detectChanges();
    expect(document.querySelector('.mat-mdc-menu-panel')!.textContent).not.toContain('photo_faces.ignore_detection');
    fixture.componentRef.setInput('canEdit', true);
    menu.target.set({ person: null, face: { id: 1, automatic: false } });
    fixture.detectChanges();
    expect(document.querySelector('.mat-mdc-menu-panel')!.textContent).not.toContain('photo_faces.ignore_detection');
  });

  it('ignores exactly this photo detection and Undo restores the captured target after navigation', async () => {
    await openOn({ person: null, face: { id: 1 } });
    mockApi.post.mockReturnValueOnce(of({ ignore_id: 'correction' }));
    const changed = vi.fn();
    menu.changed.subscribe(changed);
    await menu.ignoreDetection();
    expect(mockApi.post).toHaveBeenCalledWith('/face/1/ignore', { photo_path: '/p/a.jpg' });
    expect(changed).toHaveBeenCalledTimes(1);
    expect(mockSnackBar.open).toHaveBeenLastCalledWith('photo_faces.detection_ignored', 'undo.action', { duration: 10_000 });
    fixture.componentRef.setInput('path', '/p/b.jpg');
    menu.target.set({ person: null, face: { id: 2 } });
    snackAction.next();
    await vi.waitFor(() => expect(mockApi.post).toHaveBeenCalledWith('/ignored-face/correction/restore', { photo_path: '/p/a.jpg' }));
    expect(changed).toHaveBeenCalledTimes(1); // Never refresh B from A's completion.
  });

  it('failed Ignore leaves the face present and reports the failure', async () => {
    await openOn({ person: null, face: { id: 1 } });
    mockApi.post.mockReturnValueOnce(throwError(() => new Error('offline')));
    const changed = vi.fn();
    menu.changed.subscribe(changed);
    await menu.ignoreDetection();
    expect(changed).not.toHaveBeenCalled();
    expect(mockSnackBar.open).toHaveBeenLastCalledWith('errors.action_failed', '', { duration: 3000 });
  });

  it('late Ignore completion never refreshes another photo or registers Undo for another identity', async () => {
    await openOn({ person: null, face: { id: 1 } });
    const pending = new Subject<{ ignore_id: string }>();
    mockApi.post.mockReturnValueOnce(pending);
    const changed = vi.fn();
    menu.changed.subscribe(changed);
    const request = menu.ignoreDetection();
    fixture.componentRef.setInput('path', '/p/b.jpg');
    identity.set('another-owner');
    pending.next({ ignore_id: 'correction' });
    pending.complete();
    await request;
    expect(changed).not.toHaveBeenCalled();
    expect(mockStore.reloadPersonOptions).not.toHaveBeenCalled();
    expect(mockSnackBar.open).not.toHaveBeenCalled();
  });

  it('unnamed person with a face: the group wording', async () => {
    const items = await openOn({ person: { id: 5, name: null }, face: { id: 1 } });
    expect(items).toContain('person_search photo_faces.find_more_group');
    expect(items).toContain('person_remove photo_faces.not_group');
    expect(items).not.toContain('person_search photo_faces.find_more');
    expect(items).not.toContain('person_remove photo_faces.not_person');
  });

  it('unnamed person only: the group wording for Find more', async () => {
    const items = await openOn({ person: { id: 5, name: null }, face: null });
    expect(items).toContain('person_search photo_faces.find_more_group');
  });

  it('See all photos, already in the gallery, tells the user when resetting the filters fails', async () => {
    mockRouter.url = '/?person_id=5,7';
    mockStore.resetFilters.mockRejectedValueOnce(new Error('boom'));
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    menu.viewPhotos();
    await vi.waitFor(() => expect(mockSnackBar.open).toHaveBeenCalledWith('errors.action_failed', '', { duration: 3000 }));
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
  });

  it('person only: no face items, and Ignore', async () => {
    const items = await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    expect(items).toEqual([
      'photo_library photo_faces.view_photos',
      'person_search photo_faces.find_more',
      'block persons.hide',
    ]);
  });

  it('person only, hidden: Restore instead of Ignore', async () => {
    const items = await openOn({ person: { id: 5, name: 'Valerie', hidden: true }, face: null });
    expect(items.at(-1)).toBe('visibility persons.unhide');
  });

  it('read-only person only: just See all photos', async () => {
    const items = await openOn({ person: { id: 5, name: 'Valerie' }, face: null }, false);
    expect(items).toEqual(['photo_library photo_faces.view_photos']);
  });

  it('See all photos navigates to the person', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    menu.viewPhotos();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { queryParams: { person_id: '5' } });
  });

  it('See all photos, already in the gallery, replaces every filter with the one person', async () => {
    mockRouter.url = '/?person_id=5,7&min_score=6';
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    menu.viewPhotos();
    await fixture.whenStable();
    expect(mockStore.resetFilters).toHaveBeenCalled();
    expect(mockStore.updateFilters).toHaveBeenCalledWith({ person_id: '5' });
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('Ignore hides the person and reports it', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    const hidden = vi.fn();
    const changed = vi.fn();
    menu.hiddenChanged.subscribe(hidden);
    menu.changed.subscribe(changed);
    await menu.setHidden(true);
    expect(mockApi.post).toHaveBeenCalledWith('/persons/5/hide');
    expect(hidden).toHaveBeenCalledWith({ personId: 5, hidden: true });
    expect(changed).toHaveBeenCalled();
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
  });

  it('Ignore shows the notification with Undo for 10 s', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    await menu.setHidden(true);
    expect(mockSnackBar.open).toHaveBeenCalledWith('persons.hidden_done', 'undo.action', { duration: 10_000 });
  });

  it('Undo restores the person: unhide, and the chip learns it is visible again', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    const hidden = vi.fn();
    menu.hiddenChanged.subscribe(hidden);
    await menu.setHidden(true);
    mockStore.reloadPersonOptions.mockClear();
    snackAction.next();
    await new Promise((r) => setTimeout(r));
    expect(mockApi.post).toHaveBeenCalledWith('/persons/5/unhide');
    expect(hidden).toHaveBeenLastCalledWith({ personId: 5, hidden: false });
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
    expect(mockSnackBar.open).toHaveBeenLastCalledWith('undo.restored', '', { duration: 2000 });
  });

  it('without Undo the ignore stays: no restore call after the 10 s', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    vi.useFakeTimers();
    try {
      await menu.setHidden(true);
      await vi.advanceTimersByTimeAsync(11_000);
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(mockApi.post).not.toHaveBeenCalledWith('/persons/5/unhide');
    } finally {
      vi.useRealTimers();
    }
  });

  it('a failed restore says so', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    await menu.setHidden(true);
    mockApi.post.mockReturnValue(throwError(() => new Error('down')));
    snackAction.next();
    await new Promise((r) => setTimeout(r));
    expect(mockSnackBar.open).toHaveBeenLastCalledWith('undo.restore_failed', '', { duration: 3000 });
  });

  it('Restore unhides the person', async () => {
    await openOn({ person: { id: 5, name: 'Valerie', hidden: true }, face: null });
    await menu.setHidden(false);
    expect(mockApi.post).toHaveBeenCalledWith('/persons/5/unhide');
  });

  it('a failed Ignore says so and changes nothing', async () => {
    await openOn({ person: { id: 5, name: 'Valerie' }, face: null });
    mockApi.post.mockReturnValue(throwError(() => new Error('down')));
    const hidden = vi.fn();
    menu.hiddenChanged.subscribe(hidden);
    await menu.setHidden(true);
    expect(mockSnackBar.open).toHaveBeenCalledWith('persons.hide_error', '', { duration: 3000 });
    expect(hidden).not.toHaveBeenCalled();
  });
});
