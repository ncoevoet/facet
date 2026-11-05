import type { Mock } from 'vitest';
import { signal, type WritableSignal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController, type TestRequest } from '@angular/common/http/testing';
import { AuthService } from '../../core/services/auth.service';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { Observable, Subject, from, of, throwError } from 'rxjs';
import { Router, provideRouter } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { JunkSweepComponent } from './junk-sweep.component';

describe('JunkSweepComponent', () => {

  let component: any;
  let mockApi: { get: Mock; post: Mock };
  let mockI18n: { t: Mock };
  let mockSnackBar: { open: Mock };
  let mockDialog: { open: Mock };
  let photosCall: number;
  let journal: { record: Mock };

  const initialPhotos = [
    { path: '/p/meme.jpg', filename: 'meme.jpg', junk_kind: 'meme', aggregate: 2.1 },
    { path: '/p/s1.jpg', filename: 's1.jpg', junk_kind: 'screenshot', aggregate: 1.0 },
    { path: '/p/s2.jpg', filename: 's2.jpg', junk_kind: 'screenshot', aggregate: 1.1 },
    { path: '/p/s3.jpg', filename: 's3.jpg', junk_kind: 'screenshot', aggregate: 1.2 },
  ];

  const defaultFirstPage = { photos: initialPhotos, total: 4, total_pages: 1, page: 1, has_more: false };

  const kindsList = { junk_kinds: [['meme', 1], ['screenshot', 3]] };

  const emptyPage = { photos: [], total: 0, total_pages: 1, page: 1, has_more: false };

  function configureComponent(
    firstPage: Record<string, unknown> | Observable<unknown> = defaultFirstPage,
    kindsReply: Observable<unknown> = of(kindsList),
    laterPages: () => Observable<unknown> = () => of(emptyPage),
  ) {
    photosCall = 0;
    mockApi = {
      get: vi.fn((url: string) => {
        if (url.includes('junk_kinds')) {
          return kindsReply;
        }
        photosCall += 1;
        if (photosCall === 1) {
          return firstPage instanceof Observable ? firstPage : of(firstPage);
        }
        return laterPages();
      }),
      post: vi.fn((_url: string, body: { photo_paths?: string[] }) => of({ count: body.photo_paths?.length ?? 1 })),
    };
    mockI18n = { t: vi.fn((k: string, vars?: Record<string, unknown>) => (vars ? `${k} ${JSON.stringify(vars)}` : k)), translations: () => ({}) } as unknown as { t: Mock };
    mockSnackBar = { open: vi.fn() };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };
    journal = { record: vi.fn() };

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        JunkSweepComponent,
        provideRouter([{ path: 'junk', children: [] }]),
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: { identity: signal('owner-a'), isEdition: signal(true) } },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MatDialog, useValue: mockDialog },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
  }

  function createComponent(...args: Parameters<typeof configureComponent>) {
    configureComponent(...args);
    component = TestBed.inject(JunkSweepComponent);
  }

  describe('a navigation made by the assistant', () => {
    const go = (url: string) => TestBed.inject(Router).navigateByUrl(url);
    const gate = () => {
      let release!: (value: unknown) => void;
      const promise = new Promise<unknown>(resolve => { release = resolve; });
      return { reply: from(promise), release };
    };

    it('applies the kind only after the kind list has loaded, through selectKind, once', async () => {
      const kinds = gate();
      createComponent(defaultFirstPage, kinds.reply);
      const selectKind = vi.spyOn(component, 'selectKind');
      void component.ngOnInit();
      await go('/junk?kind=screenshot');
      expect(selectKind).not.toHaveBeenCalled();
      expect(component.activeKind()).toBe('any');
      kinds.release(kindsList);
      await vi.waitFor(() => expect(component.activeKind()).toBe('screenshot'));
      expect(selectKind).toHaveBeenCalledTimes(1);
      expect(selectKind).toHaveBeenCalledWith('screenshot');
    });

    it('keeps the requested kind when the kind list answers after the URL cleanup navigation', async () => {
      const kinds = gate();
      createComponent(defaultFirstPage, kinds.reply);
      void component.ngOnInit();
      await go('/junk?kind=screenshot');
      await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/junk'));
      await new Promise(resolve => setTimeout(resolve, 20));
      expect(component.activeKind()).toBe('any');
      kinds.release(kindsList);
      await vi.waitFor(() => expect(component.activeKind()).toBe('screenshot'));
    });

    it('ignores a kind the list does not hold, and "any" goes back to every kind', async () => {
      createComponent();
      await component.ngOnInit();
      await go('/junk?kind=zzz');
      expect(component.activeKind()).toBe('any');
      await go('/junk?kind=meme');
      await vi.waitFor(() => expect(component.activeKind()).toBe('meme'));
      await go('/junk?kind=any');
      await vi.waitFor(() => expect(component.activeKind()).toBe('any'));
    });

    it('removes the kind from the URL once applied', async () => {
      createComponent();
      await component.ngOnInit();
      const router = TestBed.inject(Router);
      await go('/junk?kind=meme');
      await vi.waitFor(() => expect(router.url).toBe('/junk'));
    });

    it('keeps the kind when the navigation names none', async () => {
      createComponent();
      await component.ngOnInit();
      await go('/junk?kind=meme');
      await vi.waitFor(() => expect(component.activeKind()).toBe('meme'));
      await go('/junk');
      expect(component.activeKind()).toBe('meme');
    });
  });

  it('reads the total candidate count from the API `total` field, not `total_count`', async () => {
    createComponent();

    await component.ngOnInit();

    expect(component.total()).toBe(4);
  });

  it('lists every stacked junk frame, not only the stack representative', async () => {
    createComponent();

    await component.ngOnInit();

    expect(mockApi.get).toHaveBeenCalledWith('/photos', expect.objectContaining({ collapse_stacks: 0 }));
  });

  it('keeps the counter a finite number after rejecting a photo (no NaN)', async () => {
    createComponent();
    await component.ngOnInit();

    await component.reject(initialPhotos[1]);

    expect(component.total()).toBe(3);
    expect(Number.isNaN(component.total())).toBe(false);
  });

  it('rejectAllShown refreshes the per-kind counts feeding the filter menu items', async () => {
    createComponent();
    await component.ngOnInit();
    expect(component.kinds()).toEqual([['meme', 1], ['screenshot', 3]]);

    await component.rejectAllShown();

    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_reject', {
      photo_paths: initialPhotos.map(p => p.path),
    });
    const counts = new Map(component.kinds() as [string, number][]);
    expect(counts.get('meme')).toBe(0);
    expect(counts.get('screenshot')).toBe(0);
  });

  // `loadMore` has no ceiling, so 21 clicks at 48/page puts `shown` past the
  // server's 1,000-entry photo_paths cap: one POST of the lot is a 422 behind a
  // generic error toast, which is the whole action failing.
  it('splits reject-all past the server cap into request-sized chunks', async () => {
    const many = Array.from({ length: 1500 }, (_, i) => ({
      path: `/p/j${i}.jpg`, filename: `j${i}.jpg`, junk_kind: 'meme', aggregate: 1.0,
    }));
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();

    await component.rejectAllShown();

    const chunks = mockApi.post.mock.calls
      .filter(c => c[0] === '/photos/batch_reject')
      .map(c => (c[1] as { photo_paths: string[] }).photo_paths);
    expect(chunks.map(c => c.length)).toEqual([1000, 500]);
    expect(chunks.flat()).toEqual(many.map(p => p.path));
  });

  it('journals a single reject and a clear, and nothing when either fails', async () => {
    createComponent();
    await component.ngOnInit();

    await component.reject(initialPhotos[0]);
    await component.keep(initialPhotos[1]);
    expect(journal.record).toHaveBeenNthCalledWith(1, 'junk', ['/p/meme.jpg'], { action: 'reject', count: 1 });
    expect(journal.record).toHaveBeenNthCalledWith(2, 'junk', ['/p/s1.jpg'], { action: 'clear', count: 1 });

    journal.record.mockClear();
    mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
    await component.reject(initialPhotos[2]);
    await component.keep(initialPhotos[3]);
    expect(journal.record).not.toHaveBeenCalled();
  });

  it('journals one entry for a reject-all, and only the chunks that landed when a later one fails', async () => {
    const many = Array.from({ length: 1500 }, (_, i) => ({
      path: `/p/j${i}.jpg`, filename: `j${i}.jpg`, junk_kind: 'meme', aggregate: 1.0,
    }));
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();
    await component.rejectAllShown();
    expect(journal.record).toHaveBeenCalledTimes(1);
    const [kind, paths, value] = journal.record.mock.calls[0];
    expect([kind, paths.length, value]).toEqual(['junk', 1500, { action: 'reject', count: 1500 }]);

    journal.record.mockClear();
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();
    mockApi.post.mockReturnValueOnce(of({ count: 1000 })).mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.rejectAllShown();
    expect(journal.record).toHaveBeenCalledTimes(1);
    const [, partialPaths, partialValue] = journal.record.mock.calls[0];
    expect(partialPaths).toEqual(many.slice(0, 1000).map(p => p.path));
    expect(partialValue).toEqual({ action: 'reject', count: 1000, partial: true });
  });

  it('feeds the count of *shown* candidates (not the API total) into the reject-all tooltip', async () => {
    // Only 2 of 10 candidates are loaded on the first page; the reject-all button
    // binds junk.reject_all with { count: photos().length }, so the tooltip must
    // reflect the shown count (2), decoupled from the whole-library total (10).
    createComponent({ photos: initialPhotos.slice(0, 2), total: 10, total_pages: 5, page: 1, has_more: true });
    await component.ngOnInit();

    expect(component.photos().length).toBe(2);
    expect(component.total()).toBe(10);
  });

  describe('rendered: candidate count and empty states', () => {
    /** createComponent, but rendered as the fixture root so the template can be asserted. */
    async function render(...args: Parameters<typeof createComponent>): Promise<{ fixture: ComponentFixture<JunkSweepComponent>; host: HTMLElement }> {
      configureComponent(...args);
      const fixture = TestBed.createComponent(JunkSweepComponent);
      component = fixture.componentInstance;
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      return { fixture, host: fixture.nativeElement as HTMLElement };
    }

    const countChip = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-junk-count]');
    const photosCalls = (): number => mockApi.get.mock.calls.filter(([url]) => url === '/photos').length;
    /** Exact leaf text: 'junk.empty' is a prefix of 'junk.empty_kind', and
     *  ancestor divs inherit the message into their own textContent. */
    const emptyMessages = (host: HTMLElement): (string | undefined)[] => [...host.querySelectorAll('div')]
      .filter(d => d.children.length === 0)
      .map(d => d.textContent?.trim())
      .filter(t => t === 'junk.empty' || t === 'junk.empty_kind');

    it('shows the candidate total beside the kind filter once loaded', async () => {
      const { host } = await render();
      expect(countChip(host)!.textContent).toContain('junk.candidates_plural');
      expect(countChip(host)!.textContent).toContain('"count":4');
    });

    it('hides the count while the first page is still loading', async () => {
      const { host } = await render(new Subject<unknown>());
      expect(countChip(host)).toBeNull();
    });

    it('counts down as a card is rejected from its visible decision button', async () => {
      const { fixture, host } = await render();
      const rejectButtons = [...host.querySelectorAll<HTMLButtonElement>('button[data-junk-reject]')];
      expect(rejectButtons.length).toBe(4);
      rejectButtons[0].click();
      fixture.detectChanges();
      expect(countChip(host)!.textContent).toContain('"count":3');
    });

    it('uses the singular label once a kind with one candidate is selected', async () => {
      const { fixture, host } = await render(defaultFirstPage, of(kindsList),
        () => of({ photos: [initialPhotos[0]], total: 1, total_pages: 1, page: 1, has_more: false }));
      await component.selectKind('meme');
      fixture.detectChanges();
      expect(countChip(host)!.textContent).toContain('junk.candidates {"count":1}');
    });

    it('shows a persistent error rather than an empty queue when the new kind fails to load', async () => {
      const { fixture, host } = await render(defaultFirstPage, of(kindsList), () => throwError(() => new Error('boom')));
      await component.selectKind('meme');
      fixture.detectChanges();
      expect(countChip(host)).toBeNull();
      expect(emptyMessages(host)).toEqual([]);
      expect(host.querySelector('[data-junk-load-error]')).not.toBeNull();
      expect(host.querySelector('[data-junk-retry]')).not.toBeNull();
    });

    it('re-reads the first page once every loaded card is handled while more remain', async () => {
      const next = { ...initialPhotos[1], path: '/p/next.jpg', filename: 'next.jpg' };
      const { fixture, host } = await render(
        { photos: [initialPhotos[0]], total: 2, total_pages: 2, page: 1, has_more: true }, of(kindsList),
        () => of({ photos: [next], total: 1, total_pages: 1, page: 1, has_more: false }));
      await component.keep(initialPhotos[0]);
      fixture.detectChanges();
      expect(mockApi.get).toHaveBeenLastCalledWith('/photos', expect.objectContaining({ page: 1 }));
      expect(component.photos().map((p: { path: string }) => p.path)).toEqual(['/p/next.jpg']);
      expect(countChip(host)!.textContent).toContain('"count":1');
      expect(emptyMessages(host)).toEqual([]);
    });

    it('waits for the last write in flight before re-reading the first page', async () => {
      const { fixture } = await render(
        { photos: initialPhotos.slice(0, 2), total: 3, total_pages: 2, page: 1, has_more: true }, of(kindsList),
        () => of({ photos: [initialPhotos[2]], total: 1, total_pages: 1, page: 1, has_more: false }));
      const second = new Subject<unknown>();
      mockApi.post.mockReturnValueOnce(of({})).mockReturnValueOnce(second);
      const first = component.keep(initialPhotos[0]);
      const pending = component.keep(initialPhotos[1]);
      await first;
      expect(photosCalls()).toBe(1);
      second.next({});
      second.complete();
      await pending;
      fixture.detectChanges();
      expect(photosCalls()).toBe(2);
      expect(component.photos().map((p: { path: string }) => p.path)).toEqual([initialPhotos[2].path]);
    });

    it('shows the generic no-junk message when All kinds is empty', async () => {
      const { host } = await render(emptyPage);
      expect(emptyMessages(host)).toEqual(['junk.empty']);
    });

    it('points at All kinds instead of a rescan when a kind filter comes up empty', async () => {
      const { fixture, host } = await render(emptyPage);
      await TestBed.inject(Router).navigateByUrl('/junk?kind=meme');
      await vi.waitFor(() => expect(photosCalls()).toBe(2), { timeout: 4000 });
      await fixture.whenStable();
      fixture.detectChanges();
      expect(component.activeKind()).toBe('meme');
      expect(emptyMessages(host)).toEqual(['junk.empty_kind']);
    });
  });
});


describe('JunkSweepComponent HTTP, owner and recovery boundaries', () => {
  let fixture: ComponentFixture<JunkSweepComponent>;
  let component: any;
  let http: HttpTestingController;
  let identity: WritableSignal<string>;
  let isEdition: WritableSignal<boolean>;
  let journal: { record: Mock };
  let snack: { open: Mock };
  let dialog: { open: Mock };
  let navigationGate: Subject<boolean>;
  let navigationEntered: () => void;

  const photo = (index: number, kind = 'screenshot') => ({
    path: `/queue/${index}.jpg`, filename: `${index}.jpg`, junk_kind: kind, aggregate: 10 - index / 1000,
  });
  const paths = () => component.photos().map((candidate: { path: string }) => candidate.path);
  const host = () => fixture.nativeElement as HTMLElement;
  const expectPage = (page: number, kind = 'any'): TestRequest => http.expectOne(request =>
    request.url === '/api/photos' && request.params.get('page') === String(page)
      && request.params.get('per_page') === '48' && request.params.get('junk_kind') === kind
      && request.params.has('type') && request.params.get('type') === '');
  const reply = (request: TestRequest, queue: ReturnType<typeof photo>[], page = 1) => request.flush({
    photos: queue.slice((page - 1) * 48, page * 48), total: queue.length,
    total_pages: Math.max(1, Math.ceil(queue.length / 48)), page,
  });

  beforeEach(() => {
    TestBed.resetTestingModule();
    identity = signal('owner-a');
    isEdition = signal(true);
    journal = { record: vi.fn() };
    snack = { open: vi.fn() };
    dialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };
    navigationGate = new Subject<boolean>();
    navigationEntered = () => undefined;
    TestBed.configureTestingModule({
      imports: [JunkSweepComponent],
      providers: [
        provideHttpClient(), provideHttpClientTesting(), provideRouter([
          { path: 'junk', children: [] }, { path: 'leaving', children: [], canActivate: [() => {
            navigationEntered(); return navigationGate;
          }] },
        ]),
        { provide: AuthService, useValue: { identity, isEdition } },
        { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
        { provide: MatSnackBar, useValue: snack },
        { provide: MatDialog, useValue: dialog },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    try {
      http.verify();
    } finally {
      TestBed.resetTestingModule();
    }
  });

  function start(): TestRequest {
    fixture = TestBed.createComponent(JunkSweepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/filter_options/junk_kinds').flush({ junk_kinds: [['screenshot', 2000], ['meme', 1]] });
    return expectPage(1);
  }

  async function boot(queue: ReturnType<typeof photo>[]): Promise<void> {
    reply(start(), queue);
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function loadEveryPage(queue: ReturnType<typeof photo>[]): Promise<void> {
    await boot(queue);
    for (let page = 2; page <= Math.ceil(queue.length / 48); page++) {
      const pending = component.loadMore();
      reply(expectPage(page), queue, page);
      await pending;
    }
  }

  it('keeps an initial read failure visible until Retry successfully loads candidates', async () => {
    start().flush({ detail: 'temporary read refusal' }, { status: 503, statusText: 'Unavailable' });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(host().querySelector('[data-junk-load-error]')).not.toBeNull();
    expect(host().textContent).not.toContain('junk.empty');
    host().querySelector<HTMLButtonElement>('[data-junk-retry]')!.click();
    reply(expectPage(1), [photo(1)]);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(paths()).toEqual(['/queue/1.jpg']);
    expect(host().querySelector('[data-junk-load-error]')).toBeNull();
  });

  it('retries the failed append page without skipping it or losing existing cards', async () => {
    const queue = Array.from({ length: 120 }, (_, index) => photo(index));
    await boot(queue);
    const more = component.loadMore();
    expectPage(2).flush({ detail: 'temporary read refusal' }, { status: 503, statusText: 'Unavailable' });
    await more;
    fixture.detectChanges();
    expect(paths()).toEqual(queue.slice(0, 48).map(candidate => candidate.path));
    expect(host().querySelector('[data-junk-load-error]')).not.toBeNull();
    const retry = component.retryLoad();
    reply(expectPage(2), queue, 2);
    await retry;
    expect(paths()).toEqual(queue.slice(0, 96).map(candidate => candidate.path));
    http.expectNone(request => request.url === '/api/photos' && request.params.get('page') === '3');
  });

  it('loads every shifted candidate after Keep using at most the boundary and following page', async () => {
    const queue = Array.from({ length: 120 }, (_, index) => photo(index));
    await boot(queue);
    const kept = component.keep(queue[0]);
    const write = http.expectOne('/api/photo/clear_junk');
    expect(write.request.body).toEqual({ photo_path: queue[0].path });
    write.flush({ success: true });
    await kept;
    const remaining = queue.slice(1);
    const more = component.loadMore();
    reply(expectPage(1), remaining);
    // Settle load's response continuation, then loadMore's next-page continuation.
    await Promise.resolve();
    await Promise.resolve();
    reply(expectPage(2), remaining, 2);
    await more;
    expect(paths()).toEqual(remaining.slice(0, 96).map(candidate => candidate.path));
    expect(paths()).toContain(queue[48].path);
    http.expectNone(request => request.url === '/api/photos');
  });

  it.each(['keep', 'reject'])('does not restore a failed old-kind %s into the new kind', async action => {
    const old = photo(1, 'meme');
    const current = photo(2);
    await boot([old, current]);
    const pending = component[action](old);
    const write = http.expectOne(action === 'keep' ? '/api/photo/clear_junk' : '/api/photos/batch_reject');
    const selected = component.selectKind('screenshot');
    reply(expectPage(1, 'screenshot'), [current]);
    await selected;
    write.flush({ detail: 'write refused' }, { status: 409, statusText: 'Conflict' });
    await pending;
    expect(paths()).toEqual([current.path]);
    expect(component.total()).toBe(1);
    expect(journal.record).not.toHaveBeenCalled();
  });

  it('refreshes a matching new kind after an old-view decision settles instead of replaying its rollback', async () => {
    const old = photo(1, 'meme');
    const current = photo(2);
    await boot([old, current]);
    const selected = component.selectKind('meme');
    reply(expectPage(1, 'meme'), [old]);
    await selected;
    const pending = component.keep(old);
    const write = http.expectOne('/api/photo/clear_junk');
    const all = component.selectKind('any');
    reply(expectPage(1), [old, current]);
    await all;
    write.flush({ success: true });
    await Promise.resolve();
    reply(expectPage(1), [current]);
    await pending;
    expect(paths()).toEqual([current.path]);
    expect(component.total()).toBe(1);
  });

  it('allows only one bulk confirmation and blocks conflicting decisions while its request runs', async () => {
    const queue = [photo(1), photo(2)];
    await boot(queue);
    const confirmation = new Subject<boolean>();
    dialog.open.mockReturnValueOnce({ afterClosed: () => confirmation });
    const cancelled = component.rejectAllShown();
    await component.rejectAllShown();
    expect(dialog.open).toHaveBeenCalledTimes(1);
    http.expectNone('/api/photos/batch_reject');
    confirmation.next(false);
    confirmation.complete();
    await cancelled;
    expect(component.bulkBusy()).toBe(false);

    const bulk = component.rejectAllShown();
    await Promise.resolve();
    const request = http.expectOne('/api/photos/batch_reject');
    expect(request.request.body).toEqual({ photo_paths: queue.map(candidate => candidate.path) });
    await component.keep(queue[0]);
    await component.reject(queue[1]);
    await component.rejectAllShown();
    http.expectNone('/api/photo/clear_junk');
    http.expectNone('/api/photos/batch_reject');
    request.flush({ success: true, count: 2 });
    await Promise.resolve();
    reply(expectPage(1), []);
    await bulk;
    expect(paths()).toEqual([]);
    expect(component.bulkBusy()).toBe(false);
    expect(journal.record).toHaveBeenCalledWith('junk', queue.map(candidate => candidate.path), { action: 'reject', count: 2 });
  });

  it('does not submit a confirmation captured under an earlier account', async () => {
    await boot([photo(1)]);
    const confirmation = new Subject<boolean>();
    dialog.open.mockReturnValueOnce({ afterClosed: () => confirmation });
    const bulk = component.rejectAllShown();
    identity.set('owner-b');
    fixture.detectChanges();
    http.expectOne('/api/filter_options/junk_kinds').flush({ junk_kinds: [] });
    reply(expectPage(1), []);
    confirmation.next(true);
    confirmation.complete();
    await bulk;
    await fixture.whenStable();
    http.expectNone('/api/photos/batch_reject');
    expect(paths()).toEqual([]);
  });

  it('stops later bulk chunks after the component is destroyed', async () => {
    const queue = Array.from({ length: 1001 }, (_, index) => photo(index));
    await loadEveryPage(queue);
    const bulk = component.rejectAllShown();
    await Promise.resolve();
    const first = http.expectOne('/api/photos/batch_reject');
    expect(first.request.body.photo_paths).toHaveLength(1000);
    fixture.destroy();
    first.flush({ success: true, count: 1000 });
    await bulk;
    http.expectNone('/api/photos/batch_reject');
    http.expectNone('/api/photos');
  });

  it('stops later chunks at navigation start and recovers after a guarded navigation is cancelled', async () => {
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/junk');
    const queue = Array.from({ length: 1001 }, (_, index) => photo(index));
    await loadEveryPage(queue);
    const bulk = component.rejectAllShown();
    await Promise.resolve();
    const first = http.expectOne('/api/photos/batch_reject');
    const entered = new Promise<void>(resolve => { navigationEntered = resolve; });
    const navigation = router.navigateByUrl('/leaving');
    await entered;
    expect(fixture.componentRef.hostView.destroyed).toBe(false);
    first.flush({ success: true, count: 1000 });
    await bulk;
    http.expectNone('/api/photos/batch_reject');
    await component.keep(queue[1000]);
    http.expectNone('/api/photo/clear_junk');

    navigationGate.next(false); navigationGate.complete();
    expect(await navigation).toBe(false);
    await Promise.resolve();
    http.expectOne('/api/filter_options/junk_kinds').flush({ junk_kinds: [['screenshot', 1]] });
    reply(expectPage(1), [queue[1000]]);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(paths()).toEqual([queue[1000].path]);
    const resumed = component.keep(queue[1000]);
    http.expectOne('/api/photo/clear_junk').flush({ success: true });
    await resumed;
    expect(paths()).toEqual([]);
    http.expectNone('/api/photos/batch_reject');
  });

  it('does not issue a later old-account chunk or overwrite the new account queue', async () => {
    const queue = Array.from({ length: 1001 }, (_, index) => photo(index));
    await loadEveryPage(queue);
    const bulk = component.rejectAllShown();
    await Promise.resolve();
    const first = http.expectOne('/api/photos/batch_reject');
    identity.set('owner-b');
    fixture.detectChanges();
    http.expectOne('/api/filter_options/junk_kinds').flush({ junk_kinds: [['screenshot', 1]] });
    const other = photo(2000);
    reply(expectPage(1), [other]);
    first.flush({ success: true, count: 1000 });
    await bulk;
    await fixture.whenStable();
    expect(paths()).toEqual([other.path]);
    expect(component.total()).toBe(1);
    http.expectNone('/api/photos/batch_reject');
    expect(journal.record).not.toHaveBeenCalled();
  });

  it('refuses a new decision immediately when identity changes, before effects clear old cards', async () => {
    const queue = [photo(1)];
    await boot(queue);
    identity.set('owner-b');
    await component.keep(queue[0]);
    http.expectNone('/api/photo/clear_junk');
    fixture.detectChanges();
    http.expectOne('/api/filter_options/junk_kinds').flush({ junk_kinds: [] });
    reply(expectPage(1), []);
    await fixture.whenStable();
    expect(paths()).toEqual([]);
  });

  it('renders discoverable named Keep/Reject controls with an explicit non-delete reject glyph', async () => {
    await boot([photo(1)]);
    const keep = host().querySelector<HTMLButtonElement>('[data-junk-keep]')!;
    const reject = host().querySelector<HTMLButtonElement>('[data-junk-reject]')!;
    expect(keep.textContent).toContain('junk.keep');
    expect(reject.textContent).toContain('junk.reject');
    expect(reject.querySelector('mat-icon')!.textContent).toBe('block');
    expect(keep.disabled).toBe(false);
    expect(reject.disabled).toBe(false);
  });

  it('reports a failed Keep decision accurately and restores the candidate', async () => {
    await boot([photo(1), photo(2)]);
    const keep = host().querySelector<HTMLButtonElement>('[data-junk-keep]')!;
    keep.focus(); keep.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/clear_junk');
    request.flush({ detail: 'write failed' }, { status: 500, statusText: 'Failure' });
    await fixture.whenStable(); fixture.detectChanges();
    expect(snack.open).toHaveBeenCalledWith('junk.decision_error', expect.anything(), expect.anything());
    expect(paths()).toContain('/queue/1.jpg');
  });

  it('moves focus to the next card after Keep succeeds', async () => {
    await boot([photo(1), photo(2)]);
    const keep = host().querySelector<HTMLButtonElement>('[data-junk-keep]')!;
    keep.focus(); keep.click(); fixture.detectChanges();
    http.expectOne('/api/photo/clear_junk').flush({ success: true });
    await fixture.whenStable(); fixture.detectChanges();
    expect(document.activeElement?.getAttribute('aria-label')).toContain('2.jpg');
  });

  it('preserves native modified, repeating and modal Z keystrokes', async () => {
    await boot([photo(1)]);
    for (const options of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { repeat: true }, { isComposing: true }]) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', bubbles: true, ...options }));
      expect(component.loupeActive()).toBe(false);
    }
    const modal = document.createElement('div');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    document.body.append(modal);
    try {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', bubbles: true }));
      expect(component.loupeActive()).toBe(false);
    } finally {
      modal.remove();
    }
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', bubbles: true }));
    expect(component.loupeActive()).toBe(true);
  });
});
