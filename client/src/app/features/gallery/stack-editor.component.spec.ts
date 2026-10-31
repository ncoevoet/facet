import english from '../../../../../i18n/translations/en.json';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationStart, Router } from '@angular/router';
import { NEVER, Subject } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from './gallery.store';
import { StackEditorComponent } from './stack-editor.component';
import { STACK_EDITOR_HOST, SKIP_SUGGESTION, StackEditorData } from './stack-editor-host';

const stack = { id: 's1', revision: 7, cover_path: '/a.jpg', editable: true,
  members: [{ path: '/b.jpg', position: 0 }, { path: '/a.jpg', position: 1 }] };

describe('StackDialog HTTP workflow', () => {
  let component: StackEditorComponent;
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let events: Subject<unknown>;
  let close: ReturnType<typeof vi.fn>;
  let register: ReturnType<typeof vi.fn>;
  let journal: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;
  function create(data: StackEditorData = { stackId: 's1', selectedPaths: ['/c.jpg'] }) {
    identity = signal('alice'); events = new Subject(); close = vi.fn(); register = vi.fn(); journal = vi.fn(); refresh = vi.fn(async () => undefined);
    TestBed.configureTestingModule({ providers: [StackEditorComponent,
      provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: STACK_EDITOR_HOST, useValue: { data, presentation: 'dialog', keydown$: NEVER, closing$: NEVER, setBusy: vi.fn(),
         finish: (result: string) => (close as (value?: unknown) => void)(result === 'saved' ? true : result === 'skip' ? SKIP_SUGGESTION : undefined), invalidate: close } },
      { provide: Router, useValue: { url: '/gallery', events, navigate: vi.fn() } },
      { provide: AuthService, useValue: { identity, isEdition: signal(true) } },
      { provide: GalleryStore, useValue: { pinnedPaths: signal(null), refreshPaths: refresh, restoreSelection: vi.fn(), showPaths: vi.fn(async () => []), loadError: signal(false), photos: signal(stack.members.map(m => ({ path: m.path }))) } },
      { provide: UndoService, useValue: { register } },
      { provide: UserActivityJournal, useValue: { record: journal } },
    ] });
    component = TestBed.inject(StackEditorComponent); http = TestBed.inject(HttpTestingController);
  }
  async function addSelected() {
    const done = component.addSelected();
    http.expectOne('/api/stacks/regroup/preview').flush({ selected_paths: ['/b.jpg', '/a.jpg', '/c.jpg'], mode: 'combine', paths: ['/b.jpg', '/a.jpg', '/c.jpg'], cover_path: '/a.jpg', source_stacks: [stack], unstacked_paths: ['/c.jpg'], affected_paths: ['/b.jpg', '/a.jpg', '/c.jpg'], expected_state: 'a'.repeat(64) });
    await done;
  }
  async function load() {
    const done = component.load();
    http.expectOne('/api/stacks/s1').flush(stack); await done;
  }
  afterEach(() => { http.verify({ ignoreCancelled: true }); TestBed.resetTestingModule(); });

  it('renders compact filenames with full-path tooltips, accessible names and unchanged thumbnail identities', async () => {
    create();
    const paths = ['/a/very/long/directory/same.jpg', '/another/long/directory/same.jpg'];
    const fixture = TestBed.createComponent(StackEditorComponent); fixture.detectChanges();
    http.expectOne('/api/stacks/s1').flush({ ...stack, cover_path: paths[0], members: paths.map((path, position) => ({ path, position })) });
    await fixture.whenStable(); fixture.detectChanges();
    const labels = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('[data-stack-filename]')];
    expect(labels.map(label => label.textContent?.trim())).toEqual(['same.jpg', 'same.jpg']);
    expect(labels.map(label => label.title)).toEqual(paths);
    expect(labels.map(label => label.getAttribute('aria-label'))).toEqual(paths);
    const images = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLImageElement>('[data-stack-tile] img')];
    expect(images.map(image => new URL(image.src).searchParams.get('path'))).toEqual(paths);
    expect(labels.every(label => label.classList.contains('truncate'))).toBe(true);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-member-count]')?.textContent?.trim()).toBe('stacks.member_count_plural');
    fixture.componentInstance.paths.set([paths[0]]); fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-member-count]')?.textContent?.trim()).toBe('stacks.member_count');
    fixture.destroy();
  });

  it('renders the shipped translated count after each explicit Reject and Undo', async () => {
    create();
    const i18n = TestBed.inject(I18nService); i18n.locale.set('en');
    const loading = i18n.load(); http.expectOne('/api/i18n/en').flush(english); await loading;
    const fixture = TestBed.createComponent(StackEditorComponent); fixture.detectChanges();
    http.expectOne('/api/stacks/s1').flush(stack); await fixture.whenStable(); fixture.detectChanges();
    const editor = fixture.componentInstance;
    for (const [index, path] of ['/b.jpg', '/a.jpg'].entries()) {
      editor.focusMember(path); fixture.detectChanges();
      (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-stack-reject]')!.click();
      http.expectOne(request => request.url === '/api/photo' && request.params.get('path') === path)
        .flush({ path, is_rejected: true }); await fixture.whenStable(); fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-excluded]')?.textContent?.trim())
        .toBe(`${index + 1} rejected and excluded from draft`);
    }
    await register.mock.calls[1][0].undo(); await fixture.whenStable(); fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-excluded]')?.textContent?.trim())
      .toBe('1 rejected and excluded from draft');
    fixture.destroy();
  });

  it('rejects the focused nonfirst photo immediately, excludes only it, and Undo preserves later order and cover', async () => {
    create(); await load(); await addSelected(); component.focusMember('/a.jpg');
    const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg', is_kept: true, is_favorite: true, star_rating: 4 });
    await Promise.resolve();
    const write = http.expectOne('/api/photos/batch_review');
    expect(write.request.body).toEqual({ photo_paths: ['/a.jpg'], decision: 'rejected' });
    expect(component.paths()).toEqual(['/b.jpg', '/a.jpg', '/c.jpg']);
    write.flush({ success: true, count: 1, undo_entry_id: 23 }); await rejecting;
    expect(component.paths()).toEqual(['/b.jpg', '/c.jpg']);
    expect(component.focused()).toBe('/c.jpg');
    expect(journal).toHaveBeenCalledWith('reject', ['/a.jpg'], true);
    component.move(1, -1); component.setCover('/c.jpg');
    const undoing = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/23/revert').flush({ changed: 1 }); await undoing;
    expect(component.paths()).toEqual(['/c.jpg', '/b.jpg', '/a.jpg']);
    expect(component.cover()).toBe('/c.jpg');
  });
  it('keeps a failed Reject draft unchanged and retries the captured path, with Save blocked while pending', async () => {
    create(); await load(); component.focusMember('/a.jpg');
    const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg', is_rejected: false });
    await Promise.resolve();
    await component.save(); await component.rejectFocused();
    http.expectNone(request => request.url === '/api/stacks/s1');
    http.expectOne('/api/photos/batch_review').flush({}, { status: 500, statusText: 'Failed' }); await rejecting;
    expect(component.paths()).toEqual(['/b.jpg', '/a.jpg']); expect(component.cover()).toBe('/a.jpg');
    expect(register).not.toHaveBeenCalled();
    component.focusMember('/b.jpg'); component.retry();
    http.expectOne(request => request.url === '/api/photo' && request.params.get('path') === '/a.jpg').flush({ path: '/a.jpg', is_rejected: true });
    await Promise.resolve(); await Promise.resolve();
    expect(component.paths()).toEqual(['/b.jpg']);
    http.expectNone('/api/photos/batch_review'); expect(journal).not.toHaveBeenCalled();
  });
  it('does not restore a removed draft member when review Undo is refused', async () => {
    create(); await load(); component.focusMember('/a.jpg');
    const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' }); await Promise.resolve();
    http.expectOne('/api/photos/batch_review').flush({ count: 1, undo_entry_id: 24 }); await rejecting;
    const undoing = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/24/revert').flush({}, { status: 409, statusText: 'Conflict' });
    await expect(undoing).rejects.toThrow();
    expect(component.paths()).toEqual(['/b.jpg']); expect(component.cover()).toBe('/b.jpg'); expect(component.saving()).toBe(false);
  });
  it.each(['identity', 'navigation', 'edition'])('ignores Reject completion after %s changes, before auth effects', async change => {
    create(); await load(); component.focusMember('/a.jpg');
    const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' }); await Promise.resolve();
    if (change === 'identity') identity.set('bob');
    else if (change === 'navigation') events.next(new NavigationStart(1, '/albums'));
    else (TestBed.inject(AuthService).isEdition as ReturnType<typeof signal<boolean>>).set(false);
    http.expectOne('/api/photos/batch_review').flush({ count: 1, undo_entry_id: 25 }); await rejecting;
    expect(register).not.toHaveBeenCalled(); expect(journal).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
  });
  it('does not dispatch a review write after identity changes during the authorized read', async () => {
    create(); await load(); const rejecting = component.rejectFocused(); identity.set('bob');
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' }); await rejecting;
    http.expectNone('/api/photos/batch_review'); expect(register).not.toHaveBeenCalled();
  });
  it('restores only currently eligible members after a policy change', async () => {
    create({ paths: ['/a.jpg', '/c.jpg'] });
    const combined = { selected_paths: ['/a.jpg', '/c.jpg'], mode: 'combine', paths: ['/b.jpg', '/a.jpg', '/c.jpg'], cover_path: '/a.jpg', source_stacks: [stack], unstacked_paths: ['/c.jpg'], affected_paths: ['/b.jpg', '/a.jpg', '/c.jpg'], expected_state: 'a'.repeat(64) };
    const loading = component.load(); http.expectOne('/api/stacks/regroup/preview').flush(combined); await loading;
    component.focusMember('/b.jpg'); const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/b.jpg' }); await Promise.resolve();
    http.expectOne('/api/photos/batch_review').flush({ count: 1, undo_entry_id: 26 }); await rejecting;
    component.changeMode('selected');
    http.expectOne('/api/stacks/regroup/preview').flush({ ...combined, mode: 'selected', paths: ['/a.jpg', '/c.jpg'] }); await Promise.resolve();
    const undoing = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/26/revert').flush({ changed: 1 }); await undoing;
    expect(component.paths()).toEqual(['/a.jpg', '/c.jpg']);
    component.changeMode('combine'); http.expectOne('/api/stacks/regroup/preview').flush(combined); await Promise.resolve();
    expect(component.paths()).toEqual(['/a.jpg', '/c.jpg', '/b.jpg']);
  });
  it('preserves a later explicit cover choice even after returning to the automatic fallback', async () => {
    create({ paths: ['/a.jpg', '/b.jpg', '/c.jpg'], skippable: true });
    const loading = component.load();
    http.expectOne('/api/photos/by_paths').flush({ photos: ['/a.jpg', '/b.jpg', '/c.jpg'].map(path => ({ path })), missing: [] }); await loading;
    component.setCover('/c.jpg'); component.focusMember('/c.jpg'); const rejecting = component.rejectFocused();
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/c.jpg' }); await Promise.resolve();
    http.expectOne('/api/photos/batch_review').flush({ count: 1, undo_entry_id: 29 }); await rejecting;
    expect(component.cover()).toBe('/a.jpg');
    component.setCover('/b.jpg'); component.setCover('/a.jpg');
    const undoing = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/29/revert').flush({ changed: 1 }); await undoing;
    expect(component.paths()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']); expect(component.cover()).toBe('/a.jpg');
  });
  it('reviews chronological initial order separately from the selected cover and writes explicit paths', async () => {
    create({ paths: ['/a.jpg', '/b.jpg'], activePath: '/a.jpg', skippable: true });
    const loading = component.load();
    http.expectOne('/api/photos/by_paths').flush({ photos: [
      { path: '/a.jpg', date_taken: '2025-02-02', filename: 'a.jpg' },
      { path: '/b.jpg', date_taken: '2025-01-01', filename: 'b.jpg' },
    ], missing: [], total: 2 }); await loading;
    expect(component.paths()).toEqual(['/b.jpg', '/a.jpg']);
    expect(component.cover()).toBe('/a.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks');
    expect(req.request.body).toEqual({ paths: ['/b.jpg', '/a.jpg'], cover_path: '/a.jpg' });
    req.flush({ stack, undo: { entry_id: 9 } }); await saving;
    expect(register).toHaveBeenCalled(); expect(journal).toHaveBeenCalledWith('stack', ['/b.jpg', '/a.jpg'], 'create');
  });
  it('orders equivalent EXIF and ISO capture dates together and leaves missing dates last', async () => {
    create({ paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'], activePath: '/b.jpg', skippable: true });
    const loading = component.load();
    http.expectOne('/api/photos/by_paths').flush({ photos: [
      { path: '/a.jpg', date_taken: '2025:01:01 10:00:00' },
      { path: '/b.jpg', date_taken: '2025-12-01T10:00:00' },
      { path: '/c.jpg', date_taken: '2025-01-01 10:00:01' },
      { path: '/d.jpg', date_taken: null },
    ], missing: [] });
    await loading;
    expect(component.paths()).toEqual(['/a.jpg', '/c.jpg', '/b.jpg', '/d.jpg']);
    expect(component.cover()).toBe('/b.jpg');
    const saving = component.save();
    const request = http.expectOne('/api/stacks');
    expect(request.request.body.paths).toEqual(['/a.jpg', '/c.jpg', '/b.jpg', '/d.jpg']);
    request.flush({ stack, undo: null });
    await saving;
  });
  it('edits order, cover and selected additions with the loaded revision', async () => {
    create(); await load(); await addSelected(); component.move(2, -1); component.setCover('/c.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks/s1');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ paths: ['/b.jpg', '/c.jpg', '/a.jpg'], cover_path: '/c.jpg', expected_revision: 7 });
    req.flush({ stack: { ...stack, revision: 8 }, undo: { entry_id: 10 } }); await saving;
    const undo = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/10/revert').flush({ changed: 3 }); await undo;
    expect(refresh).toHaveBeenCalledTimes(2);
  });
  it('removes without deleting photos and preserves the earliest surviving cover', async () => {
    create(); await load(); component.remove('/a.jpg');
    expect(component.paths()).toEqual(['/b.jpg']); expect(component.cover()).toBe('/b.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks/s1'); expect(req.request.method).toBe('PUT');
    req.flush({ stack: null, undo: { entry_id: 2 } }); await saving; expect(close).toHaveBeenCalled();
    http.expectNone(request => /delete|reject/.test(request.url));
  });
  it('offers to skip a suggestion only once its draft is too small to create', async () => {
    const draft = async (data: StackEditorData) => {
      create(data);
      const loading = component.load();
      http.expectOne('/api/photos/by_paths').flush({ photos: [
        { path: '/a.jpg', date_taken: '2025-01-01', filename: 'a.jpg' },
        { path: '/b.jpg', date_taken: '2025-01-02', filename: 'b.jpg' },
      ], missing: [], total: 2 }); await loading;
    };
    await draft({ paths: ['/a.jpg', '/b.jpg'], activePath: '/a.jpg', skippable: true });
    expect(component.skippable()).toBe(false);
    component.remove('/b.jpg');
    expect(component.skippable()).toBe(true);
    component.skipSuggestion();
    expect(close).toHaveBeenCalledWith(SKIP_SUGGESTION);
    http.expectNone('/api/stacks');
    TestBed.resetTestingModule();
    create({ paths: ['/a.jpg', '/b.jpg'], activePath: '/a.jpg' });
    const loading = component.load();
    http.expectOne('/api/stacks/regroup/preview').flush({ selected_paths: ['/a.jpg', '/b.jpg'], mode: 'combine', paths: ['/a.jpg', '/b.jpg'], cover_path: '/a.jpg', source_stacks: [], unstacked_paths: ['/a.jpg', '/b.jpg'], affected_paths: ['/a.jpg', '/b.jpg'], expected_state: 'a'.repeat(64) });
    await loading;
    component.remove('/b.jpg');
    expect(component.skippable()).toBe(false);
  });
  it('can save a draft with no members to dissolve without an invalid empty cover', async () => {
    create(); await load(); component.remove('/a.jpg'); component.remove('/b.jpg');
    const saving = component.save();
    const request = http.expectOne('/api/stacks/s1');
    expect(request.request.body).toEqual({ paths: [], cover_path: null, expected_revision: 7 });
    request.flush({ stack: null, undo: { entry_id: 3 } }); await saving;
    expect(close).toHaveBeenCalled();
  });
  it('unstack uses the revision query parameter and offers organization Undo', async () => {
    create(); await load(); const saving = component.unstack();
    const req = http.expectOne('/api/stacks/s1?expected_revision=7'); expect(req.request.method).toBe('DELETE');
    req.flush({ stack: null, undo: { entry_id: 12 } }); await saving;
    expect(register).toHaveBeenCalled();
  });
  it('retains the draft after a conflict until an explicit reload', async () => {
    create(); await load(); component.setCover('/b.jpg');
    const saving = component.save();
    http.expectOne('/api/stacks/s1').flush({}, { status: 409, statusText: 'Conflict' }); await saving;
    expect(component.error()).toBe('conflict'); expect(component.cover()).toBe('/b.jpg'); expect(close).not.toHaveBeenCalled();
    await load(); expect(component.cover()).toBe('/a.jpg');
  });
  it.each(['identity', 'navigation'])('ignores successful writes after %s changes', async change => {
    create(); await load(); component.setCover('/b.jpg'); const saving = component.save();
    if (change === 'identity') identity.set('bob'); else events.next(new NavigationStart(1, '/albums'));
    http.expectOne('/api/stacks/s1').flush({ stack, undo: { entry_id: 13 } }); await saving;
    expect(register).not.toHaveBeenCalled(); expect(journal).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
  });
  it('opens a member without replacing the source gallery or installing a pinned list', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg');
    const photo = { path: '/a.jpg' };
    http.expectOne(request => request.url === '/api/photo').flush(photo); await opening;
    expect(TestBed.inject(GalleryStore).showPaths).not.toHaveBeenCalled();
    expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/a.jpg' }, state: { photo }, replaceUrl: false });
  });
  it('opens a newly added draft member without saving or changing gallery scope', async () => {
    create(); await load(); await addSelected();
    const opening = component.openMember('/c.jpg');
    const photo = { path: '/c.jpg' };
    http.expectOne(request => request.url === '/api/photo').flush(photo); await opening;
    expect(TestBed.inject(GalleryStore).showPaths).not.toHaveBeenCalled();
    expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/c.jpg' }, state: { photo }, replaceUrl: false });
    http.expectNone(request => request.method === 'PUT');
  });
  it('does not open a member outside an existing exact pinned list', async () => {
    create(); await load(); TestBed.inject(GalleryStore).pinnedPaths.set(['/a.jpg']);
    await component.openMember('/b.jpg');
    http.expectNone(request => request.url === '/api/photo');
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
  });
  it.each([null, ['/a.jpg', '/b.jpg']])('rechecks pin %j after reading an editor member', async initial => {
    create(); await load();
    const store = TestBed.inject(GalleryStore);
    store.pinnedPaths.set(initial);
    const opening = component.openMember('/a.jpg');
    store.pinnedPaths.set(['/b.jpg']);
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' });
    await opening;
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
    expect(store.pinnedPaths()).toEqual(['/b.jpg']);
    expect(close).not.toHaveBeenCalled();
  });
  it('permits an editor member retained by a changed exact pin', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg');
    TestBed.inject(GalleryStore).pinnedPaths.set(['/a.jpg']);
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' });
    await opening;
    expect(TestBed.inject(Router).navigate).toHaveBeenCalled();
    expect(TestBed.inject(GalleryStore).pinnedPaths()).toEqual(['/a.jpg']);
  });
  it('refuses Undo after leaving and returning to the same route', async () => {
    create(); await load(); const saving = component.unstack();
    http.expectOne('/api/stacks/s1?expected_revision=7').flush({ stack: null, undo: { entry_id: 12 } }); await saving;
    events.next(new NavigationStart(1, '/albums')); events.next(new NavigationStart(2, '/gallery'));
    await expect(register.mock.calls[0][0].undo()).rejects.toThrow();
    http.expectNone('/api/organization_history/12/revert');
  });
  it('does not navigate to a member after an account change during its read', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg'); identity.set('bob');
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' }); await opening;
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
  });
  it('keeps failed writes retryable without losing the chosen cover', async () => {
    create(); await load(); component.setCover('/b.jpg');
    const failed = component.save();
    http.expectOne('/api/stacks/s1').flush({}, { status: 500, statusText: 'Failed' }); await failed;
    expect(component.error()).toBe('error'); expect(component.saving()).toBe(false);
    const retried = component.save();
    const request = http.expectOne('/api/stacks/s1'); expect(request.request.body.cover_path).toBe('/b.jpg');
    request.flush({ stack: { ...stack, revision: 8 }, undo: null }); await retried;
    expect(journal).toHaveBeenCalledTimes(1);
  });
  it('chunks initial photo metadata reads at the exact-list endpoint cap', async () => {
    const paths = Array.from({ length: 1000 }, (_, i) => `/photo-${i}.jpg`);
    create({ paths, skippable: true }); const loading = component.load();
    for (const offset of [0, 500]) {
      const request = http.expectOne('/api/photos/by_paths');
      expect(request.request.body.paths).toEqual(paths.slice(offset, offset + 500));
      request.flush({ photos: paths.slice(offset, offset + 500).map(path => ({ path, date_taken: null })), missing: [] });
      // Advancing the awaited HTTP continuation starts the next bounded request.
      await Promise.resolve();
    }
    await loading; expect(component.paths()).toHaveLength(1000);
    http.expectNone(request => request.url.startsWith('/image'));
  });
  it('ignores load completion immediately after identity changes, before an auth effect runs', async () => {
    create(); const loading = component.load(); identity.set('bob');
    http.expectOne('/api/stacks/s1').flush(stack); await loading;
    expect(component.paths()).toEqual([]); expect(component.ready()).toBe(false);
  });
  it('does not edit partially visible stacks but can explicitly select all permitted members', async () => {
    create(); const loading = component.load(); http.expectOne('/api/stacks/s1').flush({ ...stack, editable: false }); await loading;
    component.remove('/a.jpg'); component.setCover('/b.jpg'); await component.save(); await component.unstack();
    expect(component.paths()).toHaveLength(2); http.expectNone(request => request.method !== 'GET');
    component.selectMembers();
    expect(TestBed.inject(GalleryStore).restoreSelection).toHaveBeenCalledWith(['/b.jpg', '/a.jpg']);
  });
  describe('unavailable and error outcomes', () => {
    const renderedFailure = (fixture: ReturnType<typeof TestBed.createComponent<StackEditorComponent>>) =>
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"] p')?.textContent?.trim();
    it('reports an unavailable stack when the server returns none, and offers a reload', async () => {
      create(); const fixture = TestBed.createComponent(StackEditorComponent); fixture.detectChanges();
      http.expectOne('/api/stacks/s1').flush(null); await fixture.whenStable(); fixture.detectChanges();
      expect(component.ready()).toBe(false); expect(fixture.componentInstance.error()).toBe('unavailable');
      expect(renderedFailure(fixture)).toBe('stacks.unavailable');
      expect((fixture.nativeElement as HTMLElement).textContent).toContain('stacks.reload');
      fixture.destroy();
    });
    it.each([[['/only.jpg']], [Array.from({ length: 1001 }, (_, i) => `/p${i}.jpg`)]])('refuses to open a creation draft of %j members without any request', async paths => {
      create({ paths }); await component.load();
      expect(component.error()).toBe('unavailable'); expect(component.ready()).toBe(false);
      http.expectNone(() => true);
    });
    it('reports unavailable when the exact-list read misses a photo', async () => {
      create({ paths: ['/a.jpg', '/b.jpg'], skippable: true }); const loading = component.load();
      http.expectOne('/api/photos/by_paths').flush({ photos: [{ path: '/a.jpg', date_taken: null }], missing: ['/b.jpg'] }); await loading;
      expect(component.error()).toBe('unavailable'); expect(component.ready()).toBe(false);
    });
    it('reports a generic error when the stack read fails, then recovers on reload', async () => {
      create(); const failed = component.load();
      http.expectOne('/api/stacks/s1').flush({}, { status: 500, statusText: 'Failed' }); await failed;
      expect(component.error()).toBe('error'); expect(component.loading()).toBe(false); expect(component.ready()).toBe(false);
      await load(); expect(component.error()).toBeNull(); expect(component.ready()).toBe(true);
    });
    it.each([[404, 'unavailable'], [403, 'unavailable'], [409, 'conflict'], [500, 'error']] as const)('maps a %i write failure to %s', async (status, expected) => {
      create(); await load(); component.setCover('/b.jpg'); const saving = component.save();
      http.expectOne('/api/stacks/s1').flush({}, { status, statusText: 'Failed' }); await saving;
      expect(component.error()).toBe(expected); expect(close).not.toHaveBeenCalled();
    });
  });
});
