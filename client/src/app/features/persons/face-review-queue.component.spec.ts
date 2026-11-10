import { ApplicationRef, Component, signal } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router, NavigationStart, NavigationEnd, NavigationCancel, NavigationCancellationCode, type Event } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { FaceReviewQueueComponent } from './face-review-queue.component';

@Component({ template: '' }) class OtherPage {}
const response = { faces: [
  { face_id: 1, photo_path: '/one.jpg', identity_token: 'a'.repeat(64), embedding_state: 'ready', suggestions: [{ person_id: 10, name: 'Alice', similarity: 0.9 }] },
  { face_id: 2, photo_path: '/two.jpg', identity_token: 'b'.repeat(64), embedding_state: 'ready', suggestions: [{ person_id: 20, name: 'Bob', similarity: 0.8 }] },
], total_unassigned: 2, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 2, suggestions_requested: true };
const assigned = { assigned_count: 1, already: [], missing: [], skipped_model: [], skipped_hidden: [], skipped_assigned: [], skipped_changed: [] };

describe('FaceReviewQueueComponent', () => {
  afterEach(() => document.querySelectorAll('.cdk-overlay-container').forEach(el => el.replaceChildren()));
  async function render(mode: 'matches' | 'unassigned' = 'matches', page: typeof response = response) {
    const api: { get: Mock; post: Mock } = { get: vi.fn(() => of(page)), post: vi.fn(() => of(assigned)) };
    const auth = { identity: signal('alice'), status: signal({ user_id: 'alice' }), isEdition: signal(true), token: 'token-a' };
    const boxes = { clear: vi.fn() };
    const chooserClosed = new Subject();
    const chooserRef = { close: vi.fn(() => { chooserClosed.next(null); chooserClosed.complete(); }), afterClosed: () => chooserClosed };
    const dialog: { open: Mock } = { open: vi.fn(() => chooserRef) };
    TestBed.configureTestingModule({ imports: [FaceReviewQueueComponent], providers: [
      provideRouter([{ path: 'persons', component: OtherPage }, { path: 'elsewhere', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: MatDialog, useValue: dialog },
      { provide: PersonFaceBoxesService, useValue: boxes },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    await TestBed.inject(Router).navigateByUrl(`/persons?tab=${mode}`);
    const fixture = TestBed.createComponent(FaceReviewQueueComponent);
    fixture.componentRef.setInput('mode', mode); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    document.body.appendChild(root);
    return { fixture, root, api, auth, boxes, dialog, chooserRef, chooserClosed };
  }
  function select(root: HTMLElement) { root.querySelectorAll<HTMLButtonElement>('[data-review-tile][aria-pressed]').forEach(tile => tile.click()); }
  function preview(root: HTMLElement) { root.querySelector<HTMLButtonElement>('[data-review-selected]')!.click(); }
  const tile = (root: HTMLElement, id: number) => root.querySelector<HTMLButtonElement>(`[data-review-face="${id}"] [data-review-tile]`)!;
  const actions = (root: HTMLElement, id: number) => root.querySelector<HTMLButtonElement>(`[data-review-face="${id}"] [data-face-actions]`)!;
  /** Opens a face's ⋮ menu and returns its panel, which the CDK overlay renders on document.body. */
  function openActions(fixture: { detectChanges(): void }, root: HTMLElement, id: number): HTMLElement {
    actions(root, id).click(); fixture.detectChanges();
    return [...document.querySelectorAll<HTMLElement>('.mat-mdc-menu-panel')].at(-1)!;
  }
  function menuItem(fixture: { detectChanges(): void }, root: HTMLElement, id: number, selector: string): HTMLButtonElement {
    return openActions(fixture, root, id).querySelector<HTMLButtonElement>(selector)!;
  }
  /** Renders and runs afterNextRender hooks, which fixture.detectChanges() alone does not. */
  function flushRender(fixture: { detectChanges(): void }) { fixture.detectChanges(); TestBed.inject(ApplicationRef).tick(); }
  const sentinel = (fixture: ComponentFixture<unknown>) =>
    fixture.debugElement.query(By.directive(InfiniteScrollDirective))?.injector.get(InfiniteScrollDirective) ?? null;
  /** Scrolls the end of the queue into view, as the IntersectionObserver would. */
  function reach(fixture: ComponentFixture<unknown>) { sentinel(fixture)!.scrollReached.emit(); }
  const groupOrder = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('[data-review-group]')].map(group => group.dataset['reviewGroup']);

  it('reload supersedes a pending next page and ignores its late completion', async () => {
    const { fixture, api } = await render();
    const oldPage = new Subject<typeof response>();
    const fresh = { ...response, faces: [response.faces[0]], total_unassigned: 1 };
    api.get.mockReturnValueOnce(oldPage).mockReturnValueOnce(of(fresh));
    const component = fixture.componentInstance as any;
    const pending = component.load(48);
    expect(component.loading()).toBe(true);
    component.reload();
    await Promise.resolve();
    expect(api.get.mock.calls.slice(-2).map(call => call[1].after_id)).toEqual([48, 0]);
    expect(component.faces()).toEqual(fresh.faces);
    oldPage.next(response); oldPage.complete(); await pending;
    expect(component.faces()).toEqual(fresh.faces);
    expect(component.total()).toBe(1);
    expect(component.loading()).toBe(false);
  });

  it('lays faces out as tiles, three per row on phones and as many as fit from sm up', async () => {
    const { fixture, root } = await render();
    const grid = root.querySelector('[data-review-face]')!.parentElement!;
    expect(grid.className).toContain('grid-cols-3');
    expect(grid.className).toContain('sm:grid-cols-[repeat(auto-fill,minmax(8rem,1fr))]');
    fixture.destroy(); root.remove();
  });

  it('shows the global queue and confirms captured face identities separately for each person', async () => {
    const { fixture, root, api, boxes } = await render();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    expect(menuItem(fixture, root, 1, '[data-open-photo]').getAttribute('target')).toBe('_blank');
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-preview]')?.textContent).toContain('Alice');
    expect(api.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenNthCalledWith(1, '/persons/10/assign_faces', {
      face_ids: [1], only_unassigned: true, tolerant: true, expected_face_tokens: { '1': 'a'.repeat(64) }, expected_person_name: 'Alice',
    });
    expect(api.post).toHaveBeenNthCalledWith(2, '/persons/20/assign_faces', expect.objectContaining({ face_ids: [2], expected_person_name: 'Bob' }));
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":2,"skipped":0');
    expect(boxes.clear).toHaveBeenCalledTimes(2);
    fixture.destroy(); root.remove();
  });

  it('splits one person\'s assignment into requests of at most 500 faces, the server cap', async () => {
    const faces = Array.from({ length: 501 }, (_, index) => ({
      face_id: index + 1, photo_path: `/p${index + 1}.jpg`, identity_token: 'c'.repeat(64), embedding_state: 'ready',
      suggestions: [{ person_id: 10, name: 'Alice', similarity: 0.9 }],
    }));
    const { fixture, root, api } = await render('matches', { ...response, faces, total_unassigned: 501 });
    api.post.mockImplementation((_url: string, body: { face_ids: number[] }) => of({ ...assigned, assigned_count: body.face_ids.length }));
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenCalledTimes(2);
    const [first, second] = api.post.mock.calls.map(call => call[1] as { face_ids: number[]; expected_face_tokens: Record<string, string> });
    expect(first.face_ids).toHaveLength(500);
    expect(second.face_ids).toEqual([501]);
    expect(Object.keys(first.expected_face_tokens)).toHaveLength(500);
    expect(Object.keys(second.expected_face_tokens)).toEqual(['501']);
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":501,"skipped":0');
    expect(root.textContent).not.toContain('persons.review_queue.uncertain');
    fixture.destroy(); root.remove();
  });

  it('keeps newer navigation blocked through an older completion and resumes once after cancellation', async () => {
    const { fixture, root, api } = await render();
    const router = TestBed.inject(Router); const events = router.events as Subject<Event>;
    api.get.mockClear();
    events.next(new NavigationStart(10, '/elsewhere'));
    events.next(new NavigationStart(11, '/elsewhere'));
    events.next(new NavigationEnd(10, '/elsewhere', '/elsewhere'));
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).not.toHaveBeenCalled(); expect(root.querySelectorAll('[data-review-face]')).toHaveLength(0);
    events.next(new NavigationCancel(11, '/elsewhere', 'redirect', NavigationCancellationCode.Redirect));
    await fixture.whenStable(); expect(api.get).not.toHaveBeenCalled();
    events.next(new NavigationStart(12, '/elsewhere'));
    events.next(new NavigationCancel(12, '/elsewhere', 'guard', NavigationCancellationCode.GuardRejected));
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(1); expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    fixture.destroy(); root.remove();
  });

  it('restarts at the first page after navigation cancels a paged queue', async () => {
    const { fixture, root, api } = await render();
    const queue = fixture.componentInstance as any;
    queue.nextAfter.set(2); fixture.detectChanges();
    api.get.mockReturnValueOnce(of({ ...response, faces: [{ ...response.faces[0], face_id: 3 }] }));
    reach(fixture);
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(3);
    api.get.mockClear();
    const events = TestBed.inject(Router).events as Subject<Event>;
    events.next(new NavigationStart(10, '/elsewhere'));
    events.next(new NavigationCancel(10, '/elsewhere', 'guard', NavigationCancellationCode.GuardRejected));
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledExactlyOnceWith('/faces/review', { after_id: 0, limit: 48, suggest: true });
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    expect(root.textContent).toContain('Alice'); expect(root.textContent).toContain('Bob');
    fixture.destroy(); root.remove();
  });

  it('appends the next page without discarding selected faces or chosen people', async () => {
    const { fixture, root, api } = await render();
    const queue = fixture.componentInstance as any;
    queue.nextAfter.set(2);
    queue.choose(1, 99, 'Zoe'); fixture.detectChanges();
    tile(root, 1).click();
    fixture.detectChanges();
    api.get.mockReturnValueOnce(of({ ...response, faces: [{ ...response.faces[0], face_id: 3 }], next_after_id: null }));
    reach(fixture);
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(3);
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('true');
    preview(root); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-preview]')?.textContent).toContain('Zoe');
    fixture.destroy(); root.remove();
  });

  it('reads the next page only while nothing else is in progress, and shows its spinner at the end', async () => {
    const { fixture, root, api } = await render();
    const queue = fixture.componentInstance as any;
    queue.nextAfter.set(2); fixture.detectChanges();
    expect(root.querySelector('[data-queue-more] [data-queue-sentinel]')).not.toBeNull();
    expect(root.querySelector('[data-queue-next]')).toBeNull();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    expect(sentinel(fixture)).toBeNull();
    queue.cancel(new Event('click')); fixture.detectChanges();
    expect(sentinel(fixture)).not.toBeNull();
    queue.choosing.set(true); fixture.detectChanges();
    expect(sentinel(fixture)).toBeNull();
    queue.choosing.set(false); fixture.detectChanges();
    const page = new Subject<object>();
    api.get.mockReturnValueOnce(page);
    reach(fixture); fixture.detectChanges();
    expect(api.get).toHaveBeenLastCalledWith('/faces/review', { after_id: 2, limit: 48, suggest: true });
    expect(sentinel(fixture)).toBeNull();
    expect(root.querySelector('[data-queue-more] mat-spinner')).not.toBeNull();
    expect(root.textContent).not.toContain('ui.labels.loading');
    page.next({ ...response, faces: [{ ...response.faces[0], face_id: 3 }], next_after_id: 3 }); page.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-queue-more] mat-spinner')).toBeNull();
    expect(sentinel(fixture)).not.toBeNull();
    api.get.mockReturnValueOnce(of({ ...response, faces: [], next_after_id: null }));
    reach(fixture); await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-queue-more]')).toBeNull();
    fixture.destroy(); root.remove();
  });

  it('stops reading after a failed next page, and Retry resumes there without dropping the selection', async () => {
    const { fixture, root, api } = await render();
    const queue = fixture.componentInstance as any;
    queue.nextAfter.set(2); fixture.detectChanges();
    tile(root, 1).click(); fixture.detectChanges();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    reach(fixture); await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).not.toBeNull();
    expect(sentinel(fixture)).toBeNull();
    api.get.mockReturnValueOnce(of({ ...response, faces: [{ ...response.faces[0], face_id: 3 }], next_after_id: null }));
    root.querySelector<HTMLButtonElement>('[data-queue-retry]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenLastCalledWith('/faces/review', { after_id: 2, limit: 48, suggest: true });
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(3);
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('[role="alert"]')).toBeNull();
    fixture.destroy(); root.remove();
  });

  it('restarts from the first page when Retry follows a failed first page', async () => {
    const { fixture, root, api } = await render();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    (fixture.componentInstance as any).reload(); await fixture.whenStable(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-queue-retry]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenLastCalledWith('/faces/review', { after_id: 0, limit: 48, suggest: true });
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    fixture.destroy(); root.remove();
  });

  it('cancels a preview without writes and returns focus to its trigger', async () => {
    const { fixture, root, api } = await render();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector('[data-assignment-preview]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(root.querySelector('[data-assignment-preview]')).toBeNull();
    expect(document.activeElement).toBe(root.querySelector('[data-review-selected]'));
    expect(api.post).not.toHaveBeenCalled();
    fixture.destroy(); root.remove();
  });

  it('stops later person groups on token rotation and exposes recovery without a blind retry', async () => {
    const { fixture, root, api, auth } = await render();
    const pending = new Subject(); api.post.mockReturnValueOnce(pending);
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    auth.token = 'rotated'; pending.next(assigned); pending.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(root.textContent).toContain('persons.review_queue.uncertain');
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(0);
    expect(root.querySelector<HTMLButtonElement>('[data-queue-reload]')?.disabled).toBe(false);
    fixture.destroy(); root.remove();
  });

  it('retains completed counts when a later group fails and requires a read before another apply', async () => {
    const { fixture, root, api } = await render();
    const pending = new Subject(); api.post.mockReturnValueOnce(of(assigned)).mockReturnValueOnce(pending);
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await Promise.resolve(); pending.error(new Error('connection lost'));
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":1');
    expect(root.textContent).toContain('persons.review_queue.uncertain');
    expect(root.querySelector<HTMLButtonElement>('[data-review-selected]')?.disabled).toBe(true);
    expect(api.post).toHaveBeenCalledTimes(2);
    fixture.destroy(); root.remove();
  });

  it('resumes the owning queue after real same-page query navigation', async () => {
    const { fixture, root, api } = await render();
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/persons?tab=matches&view=recent');
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    const reads = api.get.mock.calls.length;
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(reads + 1);
    fixture.destroy(); root.remove();
  });

  it('closes the owned chooser when the queue is destroyed before an auth effect can run', async () => {
    const { fixture, root, dialog, chooserRef } = await render();
    const choosing = (fixture.componentInstance as any).chooseOther(response.faces[0], root);
    const duplicate = (fixture.componentInstance as any).chooseOther(response.faces[0], root);
    await duplicate;
    await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
    expect(dialog.open).toHaveBeenCalledTimes(1);
    expect(dialog.open.mock.calls[0][1]).toEqual(expect.objectContaining({ data: { allowCreate: false } }));
    fixture.destroy(); await choosing;
    expect(chooserRef.close).toHaveBeenCalledWith(null);
    root.remove();
  });

  it.each([
    ['already', 'already'], ['missing', 'missing'], ['skipped_model', 'model_mismatch'],
    ['skipped_hidden', 'already_assigned'], ['skipped_assigned', 'already_assigned'], ['skipped_changed', 'face_changed'],
  ] as const)('shows the precise %s refusal receipt', async (field, reason) => {
    const { fixture, root, api } = await render();
    api.post.mockReturnValueOnce(of({ ...assigned, assigned_count: 0, [field]: [1] }));
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":1,"skipped":1');
    expect(root.querySelector('[data-receipt-reasons]')?.textContent).toContain('persons.review_queue.' + reason);
    expect(root.textContent).toContain('persons.review_queue.changed');
    expect(root.textContent).not.toContain('persons.review_queue.uncertain');
    fixture.destroy(); root.remove();
  });


  it('persists Not this person, refreshes only that face, and preserves other selections through Undo', async () => {
    const { fixture, root, api } = await render();
    select(root); fixture.detectChanges();
    const changed = { ...response.faces[0], suggestions: [{ person_id: 30, name: 'Carol', similarity: 0.7 }] };
    api.post.mockReturnValue(of({ receipt_id: 'c'.repeat(32), rejected: true }));
    api.get.mockReturnValueOnce(of({ ...response, faces: [changed] }));
    menuItem(fixture, root, 1, '[data-not-person]').click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenLastCalledWith('/faces/review/feedback', {
      face_id: 1, person_id: 10, identity_token: 'a'.repeat(64), expected_person_name: 'Alice',
    });
    expect(api.get).toHaveBeenLastCalledWith('/faces/review', { face_id: 1, limit: 1, suggest: true });
    expect(root.querySelector('[data-review-group="30"] [data-review-face="1"]')).not.toBeNull();
    expect(root.querySelector('[data-review-group="30"]')?.textContent).toContain('Carol');
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('false');
    expect(tile(root, 2).getAttribute('aria-pressed')).toBe('true');
    api.get.mockReturnValueOnce(of({ ...response, faces: [response.faces[0]] }));
    api.post.mockReturnValueOnce(of({ receipt_id: 'c'.repeat(32), rejected: false }));
    root.querySelector<HTMLButtonElement>('[data-feedback-undo]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenLastCalledWith('/faces/review/feedback/undo', {
      face_id: 1, person_id: 10, identity_token: 'a'.repeat(64), expected_person_name: 'Alice', receipt_id: 'c'.repeat(32),
    });
    expect(root.querySelector('[data-review-group="10"] [data-review-face="1"]')).not.toBeNull();
    expect(tile(root, 2).getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('[data-feedback-receipt]')).toBeNull();
    fixture.destroy(); root.remove();
  });

  it('does not apply a late feedback response or its refresh after token rotation', async () => {
    const { fixture, root, api, auth } = await render();
    const write = new Subject(); api.post.mockReturnValueOnce(write);
    menuItem(fixture, root, 1, '[data-not-person]').click();
    const reads = api.get.mock.calls.length;
    auth.token = 'rotated'; write.next({ receipt_id: 'c'.repeat(32), rejected: true }); write.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(reads);
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(0);
    expect(root.querySelector('[data-feedback-undo]')).toBeNull();
    expect(root.querySelector<HTMLButtonElement>('[data-queue-reload]')?.disabled).toBe(false);
    fixture.destroy(); root.remove();
  });

  it('retains an accepted feedback receipt but blocks edits when its targeted read fails', async () => {
    const { fixture, root, api } = await render();
    api.post.mockReturnValueOnce(of({ receipt_id: 'c'.repeat(32), rejected: true }));
    const read = new Subject(); api.get.mockReturnValueOnce(read);
    menuItem(fixture, root, 1, '[data-not-person]').click();
    await Promise.resolve(); read.error(new Error('read failed'));
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-feedback-receipt]')).not.toBeNull();
    expect(root.textContent).toContain('persons.review_queue.changed');
    expect(root.querySelector<HTMLButtonElement>('[data-feedback-undo]')?.disabled).toBe(true);
    expect(api.post).toHaveBeenCalledTimes(1);
    fixture.destroy(); root.remove();
  });

  it('offers a read retry without suggestions after discovery fails', async () => {
    const { fixture, root, api } = await render();
    api.get.mockReturnValueOnce(throwError(() => new Error('suggestions offline')));
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[role=alert]')).not.toBeNull();
    api.get.mockReturnValueOnce(of({ ...response, faces: response.faces.map(face => ({ ...face, suggestions: [] })) }));
    root.querySelector<HTMLButtonElement>('[data-browse-without-matches]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenLastCalledWith('/faces/review', { after_id: 0, limit: 48, suggest: false });
    expect(root.querySelector('[role=alert]')).toBeNull();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    expect(root.querySelector('[data-review-tile][aria-pressed]')).toBeNull();
    expect(root.querySelector('input[type=checkbox]')).toBeNull(); expect(api.post).not.toHaveBeenCalled();
    fixture.destroy(); root.remove();
  });

  it('retries once without suggestions on a 412 and says so', async () => {
    const { fixture, root, api } = await render();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 412 })))
      .mockReturnValueOnce(of({ ...response, faces: response.faces.map(face => ({ ...face, suggestions: [] })) }));
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get.mock.calls.slice(-2).map(call => call[1].suggest)).toEqual([true, false]);
    expect(root.querySelector('[role=alert]')).toBeNull();
    expect(root.querySelector('[data-suggestions-skipped]')?.textContent).toContain('persons.review_queue.suggestions_skipped');
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    fixture.destroy(); root.remove();
  });

  it('asks for suggestions again on reload after a 412, and falls back again if refused', async () => {
    const { fixture, root, api } = await render();
    const bare = of({ ...response, faces: response.faces.map(face => ({ ...face, suggestions: [] })) });
    api.get.mockReturnValueOnce(throwError(() => ({ status: 412 }))).mockReturnValueOnce(bare);
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    api.get.mockReturnValueOnce(of(response));
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get.mock.calls.at(-1)![1].suggest).toBe(true);
    expect(root.querySelector('[data-suggestions-skipped]')).toBeNull();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 412 }))).mockReturnValueOnce(bare);
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get.mock.calls.slice(-2).map(call => call[1].suggest)).toEqual([true, false]);
    expect(root.querySelector('[data-suggestions-skipped]')).not.toBeNull();
    fixture.destroy(); root.remove();
  });

  it('keeps the user\'s own Browse without matches choice across reloads', async () => {
    const { fixture, root, api } = await render();
    api.get.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    api.get.mockReturnValue(of({ ...response, faces: response.faces.map(face => ({ ...face, suggestions: [] })) }));
    root.querySelector<HTMLButtonElement>('[data-browse-without-matches]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get.mock.calls.at(-1)![1].suggest).toBe(false);
    fixture.destroy(); root.remove();
  });

  it('does not retry a non-412 failure and hides the unassigned total while the error shows', async () => {
    const { fixture, root, api } = await render();
    const reads = api.get.mock.calls.length;
    api.get.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(reads + 1);
    expect(root.querySelector('[role=alert]')).not.toBeNull();
    expect(root.querySelector('[data-suggestions-skipped]')).toBeNull();
    expect(root.textContent).not.toContain('persons.review_queue.total');
    fixture.destroy(); root.remove();
  });

  it('selects the face, drops its similarity and focuses its new tile when Choose person picks someone else', async () => {
    const { fixture, root, dialog, chooserClosed } = await render();
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('false');
    expect(root.querySelector('[data-review-face="1"] [data-tile-strip]')?.textContent).toContain('persons.find_more_similarity{"percent":90}');
    expect(tile(root, 1).getAttribute('aria-label')).toContain('persons.review_queue.similarity_label{"name":"Alice","value":90}');
    menuItem(fixture, root, 1, '[data-choose-person]').click();
    await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
    chooserClosed.next({ kind: 'select', person: { id: 30, name: 'Zoe' } }); chooserClosed.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-review-group="30"] [data-review-face="1"]')).not.toBeNull();
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('true');
    expect(tile(root, 2).getAttribute('aria-pressed')).toBe('false');
    expect(root.querySelector('[data-review-face="1"] [data-tile-strip]')).toBeNull();
    expect(tile(root, 1).getAttribute('aria-label')).not.toContain('similarity_label');
    flushRender(fixture);
    expect(document.activeElement).toBe(tile(root, 1));
    fixture.destroy(); root.remove();
  });

  it('lists several suggestions as radio items and moves the face, focus included, without selecting it', async () => {
    const two = { ...response, faces: [{ ...response.faces[0], suggestions: [{ person_id: 10, name: 'Alice', similarity: 0.9 }, { person_id: 40, name: 'Dana', similarity: 0.854 }] }, response.faces[1]] };
    const { fixture, root } = await render('matches', two);
    const panel = openActions(fixture, root, 1);
    const radios = [...panel.querySelectorAll<HTMLButtonElement>('[data-suggestion]')];
    expect(radios.map(radio => [radio.getAttribute('role'), radio.getAttribute('aria-checked'), radio.textContent!.replace(/\s+/g, ' ').trim()])).toEqual([
      ['menuitemradio', 'true', 'radio_button_checkedAlice · 90%'], ['menuitemradio', 'false', 'radio_button_uncheckedDana · 85%'],
    ]);
    radios[1].click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-review-group="40"] [data-review-face="1"]')).not.toBeNull();
    expect(tile(root, 1).getAttribute('aria-pressed')).toBe('false');
    flushRender(fixture);
    expect(document.activeElement).toBe(tile(root, 1));
    fixture.destroy(); root.remove();
  });

  it('offers no suggestion radios for a single matching suggestion, and Not {name} only with a choice', async () => {
    const none = { ...response, faces: [response.faces[0], { ...response.faces[1], suggestions: [] }] };
    const { fixture, root } = await render('matches', none);
    const withChoice = openActions(fixture, root, 1);
    expect(withChoice.querySelector('[data-suggestion]')).toBeNull();
    expect(withChoice.querySelector('[data-not-person]')?.textContent).toContain('persons.review_queue.not_person{"name":"Alice"}');
    document.querySelectorAll('.cdk-overlay-container').forEach(el => el.replaceChildren());
    const withoutChoice = openActions(fixture, root, 2);
    expect(withoutChoice.querySelector('[data-not-person]')).toBeNull();
    expect(withoutChoice.querySelector('[data-choose-person]')).not.toBeNull();
    fixture.destroy(); root.remove();
  });

  it.each(['selected', 'cancelled', 'stale'] as const)('settles a person chooser that is %s without assigning faces', async ending => {
    const { fixture, root, api, auth, dialog, chooserClosed } = await render();
    const trigger = actions(root, 1);
    trigger.focus(); menuItem(fixture, root, 1, '[data-choose-person]').click();
    await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
    fixture.detectChanges();
    if (ending === 'stale') auth.token = 'rotated';
    chooserClosed.next(ending === 'cancelled' ? null : { kind: 'select', person: { id: 30, name: 'Zoe' } }); chooserClosed.complete();
    await fixture.whenStable(); fixture.detectChanges();
    const queue = fixture.componentInstance as any;
    expect(queue.choices().get(1).personId).toBe(ending === 'selected' ? 30 : 10);
    expect(queue.choosing()).toBe(false); expect(api.post).not.toHaveBeenCalled();
    if (ending === 'selected') expect(root.textContent).toContain('Zoe');
    if (ending === 'cancelled') expect(document.activeElement).toBe(trigger);
    fixture.destroy(); root.remove();
  });

  it('skips a selected face locally and excludes it from the captured preview', async () => {
    const { fixture, root, api } = await render(); select(root); fixture.detectChanges();
    menuItem(fixture, root, 1, '[data-skip-face]').click(); flushRender(fixture);
    expect(document.activeElement).toBe(tile(root, 2));
    preview(root); fixture.detectChanges();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(1);
    expect(root.querySelector('[data-assignment-preview]')?.textContent).toContain('Bob');
    expect(root.querySelector('[data-assignment-preview]')?.textContent).not.toContain('Alice');
    expect(api.post).not.toHaveBeenCalled(); fixture.destroy(); root.remove();
  });

  it('blocks uncertain feedback retries when its write fails before a receipt arrives', async () => {
    const { fixture, root, api } = await render(); const reads = api.get.mock.calls.length;
    api.post.mockReturnValueOnce(throwError(() => new Error('lost feedback response')));
    menuItem(fixture, root, 1, '[data-not-person]').click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('persons.review_queue.uncertain');
    expect(root.querySelector('[data-feedback-receipt]')).toBeNull(); expect(api.get).toHaveBeenCalledTimes(reads);
    document.querySelectorAll('.cdk-overlay-container').forEach(el => el.replaceChildren());
    expect(menuItem(fixture, root, 1, '[data-not-person]').disabled).toBe(true);
    expect(tile(root, 1).getAttribute('aria-disabled')).toBe('true');
    expect(api.post).toHaveBeenCalledTimes(1); fixture.destroy(); root.remove();
  });

  it('refuses Undo after its captured feedback credentials change', async () => {
    const { fixture, root, api, auth } = await render();
    api.post.mockReturnValueOnce(of({ receipt_id: 'c'.repeat(32), rejected: true }));
    menuItem(fixture, root, 1, '[data-not-person]').click();
    await fixture.whenStable(); fixture.detectChanges();
    auth.token = 'rotated'; root.querySelector<HTMLButtonElement>('[data-feedback-undo]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenCalledTimes(1); expect(root.querySelector('[data-feedback-undo]')).toBeNull();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(0); fixture.destroy(); root.remove();
  });

  it('refuses captured confirmation after navigation starts', async () => {
    const { fixture, root, api } = await render();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    const confirm = root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!;
    await TestBed.inject(Router).navigateByUrl('/elsewhere');
    confirm.click(); fixture.detectChanges();
    expect(api.post).not.toHaveBeenCalled();
    expect(root.querySelector('[data-assignment-preview]')).toBeNull();
    fixture.destroy(); root.remove();
  });
  it('puts the faces with no suggested person last, under a header with their count', async () => {
    const page = { ...response, faces: [{ ...response.faces[1], face_id: 3, suggestions: [] }, ...response.faces] };
    const { fixture, root } = await render('matches', page);
    expect(groupOrder(root)).toEqual(['10', '20', '0']);
    const unchosen = root.querySelector('[data-review-group="0"]')!;
    expect(unchosen.querySelector('h3')?.textContent).toContain('persons.review_queue.no_suggestion');
    expect(unchosen.querySelector('h3')?.textContent).toContain('persons.review_queue.group_count{"count":1}');
    expect(unchosen.querySelector('[data-select-group]')).toBeNull();
    expect(root.querySelector('[data-review-group="10"] h3')?.textContent).toContain('Alice');
    expect(root.querySelector('[data-review-group="10"] img')?.getAttribute('alt')).toBe('');
    fixture.destroy(); root.remove();
  });

  it('selects one group with Select all, and shows a partial group as indeterminate', async () => {
    const page = { ...response, faces: [...response.faces, { ...response.faces[0], face_id: 3, suggestions: [{ person_id: 10, name: 'Alice', similarity: 0.7 }] }] };
    const { fixture, root } = await render('matches', page);
    const selectAll = () => root.querySelector<HTMLInputElement>('[data-review-group="10"] [data-select-group]')!;
    expect(root.querySelector('[data-review-group="10"] h3')?.textContent).toContain('persons.review_queue.group_count_plural{"count":2}');
    expect(selectAll().getAttribute('aria-label')).toBe('persons.review_queue.select_group{"name":"Alice"}');
    selectAll().click(); fixture.detectChanges();
    expect([1, 3, 2].map(id => tile(root, id).getAttribute('aria-pressed'))).toEqual(['true', 'true', 'false']);
    expect(selectAll().checked).toBe(true);
    tile(root, 3).click(); fixture.detectChanges();
    expect(selectAll().checked).toBe(false); expect(selectAll().indeterminate).toBe(true);
    selectAll().click(); fixture.detectChanges();
    expect([1, 3].map(id => tile(root, id).getAttribute('aria-pressed'))).toEqual(['true', 'true']);
    selectAll().click(); fixture.detectChanges();
    expect([1, 3].map(id => tile(root, id).getAttribute('aria-pressed'))).toEqual(['false', 'false']);
    fixture.destroy(); root.remove();
  });

  it('locks Select all and the tiles while a preview is pending, and undoes a refused Select all', async () => {
    const { fixture, root } = await render();
    tile(root, 1).click(); fixture.detectChanges(); preview(root); fixture.detectChanges();
    expect(root.querySelector<HTMLInputElement>('[data-select-group]')!.disabled).toBe(true);
    expect(tile(root, 2).getAttribute('aria-disabled')).toBe('true');
    tile(root, 2).click(); tile(root, 1).click(); fixture.detectChanges();
    expect([1, 2].map(id => tile(root, id).getAttribute('aria-pressed'))).toEqual(['true', 'false']);
    const queue = fixture.componentInstance as any;
    const refused = { checked: true, indeterminate: false };
    queue.toggleGroup(queue.groups().find((group: { id: number }) => group.id === 20), { target: refused });
    expect(refused).toEqual({ checked: false, indeterminate: false });
    expect(queue.selected().has(2)).toBe(false);
    fixture.destroy(); root.remove();
  });

  it('shows no header over unassigned faces, and a chooser pick moves the face into a named group it can be selected from', async () => {
    const bare = { ...response, faces: response.faces.map(face => ({ ...face, suggestions: [] })) };
    const { fixture, root, dialog, chooserClosed } = await render('unassigned', bare);
    expect(groupOrder(root)).toEqual(['0']);
    expect(root.querySelector('[data-review-group="0"] h3')).toBeNull();
    expect(tile(root, 2).getAttribute('aria-pressed')).toBeNull();
    expect(tile(root, 2).getAttribute('aria-label')).toBe('persons.review_queue.choose_for{"id":2}');
    tile(root, 2).click();
    await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
    chooserClosed.next({ kind: 'select', person: { id: 30, name: 'Zoe' } }); chooserClosed.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(groupOrder(root)).toEqual(['30', '0']);
    expect(root.querySelector('[data-review-group="30"] [data-select-group]')).not.toBeNull();
    expect(tile(root, 2).getAttribute('aria-pressed')).toBe('true');
    flushRender(fixture);
    expect(document.activeElement).toBe(tile(root, 2));
    fixture.destroy(); root.remove();
  });

  it('flags a face whose embedding cannot be compared', async () => {
    const page = { ...response, faces: [{ ...response.faces[0], embedding_state: 'incompatible' }, response.faces[1]] };
    const { fixture, root } = await render('matches', page as typeof response);
    expect(root.querySelector('[data-review-face="1"] [data-tile-warning]')).not.toBeNull();
    expect(tile(root, 1).getAttribute('aria-label')).toContain('persons.review_queue.model_mismatch');
    expect(root.querySelector('[data-review-face="2"] [data-tile-warning]')).toBeNull();
    fixture.destroy(); root.remove();
  });

  it('shows a selection bar only while faces are selected, with a count, Clear and a singular or plural Review', async () => {
    const { fixture, root } = await render();
    expect(root.querySelector('[data-review-bar]')).toBeNull();
    tile(root, 1).click(); fixture.detectChanges();
    expect(root.querySelector('[data-review-count]')?.textContent).toContain('gallery.selection.count{"count":1}');
    expect(root.querySelector('[data-review-selected]')?.textContent).toContain('persons.review_queue.preview{"count":1}');
    tile(root, 2).click(); fixture.detectChanges();
    expect(root.querySelector('[data-review-selected]')?.textContent).toContain('persons.review_queue.preview_plural{"count":2}');
    root.querySelector<HTMLButtonElement>('[data-review-clear]')!.click(); fixture.detectChanges();
    expect((fixture.componentInstance as any).selected().size).toBe(0);
    expect(root.querySelector('[data-review-bar]')).toBeNull();
    fixture.destroy(); root.remove();
  });

  it('opens the confirmation inside the selection bar and focuses it', async () => {
    const { fixture, root } = await render();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges(); await fixture.whenStable();
    const panel = root.querySelector('[data-review-bar] [data-assignment-preview]');
    expect(panel).not.toBeNull();
    expect(document.activeElement).toBe(panel);
    fixture.destroy(); root.remove();
  });

  it('moves focus to the receipt after an apply, and to the alert when it fails', async () => {
    const done = await render();
    select(done.root); done.fixture.detectChanges(); preview(done.root); done.fixture.detectChanges();
    done.root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await done.fixture.whenStable(); flushRender(done.fixture);
    expect(document.activeElement).toBe(done.root.querySelector('[data-assignment-receipt]'));
    expect(done.root.querySelector('[data-review-bar]')).toBeNull();
    done.fixture.destroy(); done.root.remove(); TestBed.resetTestingModule();
    const failed = await render();
    failed.api.post.mockReturnValueOnce(throwError(() => new Error('connection lost')));
    select(failed.root); failed.fixture.detectChanges(); preview(failed.root); failed.fixture.detectChanges();
    failed.root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await failed.fixture.whenStable(); flushRender(failed.fixture);
    expect(document.activeElement).toBe(failed.root.querySelector('[role=alert]'));
    failed.fixture.destroy(); failed.root.remove();
  });
});
