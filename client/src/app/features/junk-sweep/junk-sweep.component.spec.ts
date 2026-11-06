import type { Mock } from 'vitest';
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

  function createComponent(
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
      post: vi.fn(() => of({})),
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
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MatDialog, useValue: mockDialog },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
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
    mockApi.post.mockReturnValueOnce(of({})).mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.rejectAllShown();
    expect(journal.record).toHaveBeenCalledTimes(1);
    const [, partialPaths, partialValue] = journal.record.mock.calls[0];
    expect(partialPaths).toEqual(many.slice(0, 1000).map(p => p.path));
    expect(partialValue).toEqual({ action: 'reject', count: 1000, partial: true });
  });

  it('after a partial reject-all failure, drops the kind badges by exactly the chunks that landed, without re-reading them', async () => {
    const many = Array.from({ length: 1500 }, (_, i) => ({
      path: `/p/j${i}.jpg`, filename: `j${i}.jpg`, junk_kind: i < 1000 ? 'meme' : 'screenshot', aggregate: 1.0,
    }));
    createComponent(
      { photos: many, total: 1500, total_pages: 32, page: 1, has_more: true },
      of({ junk_kinds: [['meme', 1000], ['screenshot', 500]] }),
    );
    await component.ngOnInit();
    const kindsReads = () => mockApi.get.mock.calls.filter(([url]) => (url as string).includes('junk_kinds')).length;
    const before = kindsReads();
    mockApi.post.mockReturnValueOnce(of({})).mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.rejectAllShown();

    expect(component.kinds()).toEqual([['meme', 0], ['screenshot', 500]]);
    expect(kindsReads()).toBe(before);
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
      createComponent(...args);
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

    it('counts down as a card is rejected from its hover button', async () => {
      const { fixture, host } = await render();
      const rejectButtons = [...host.querySelectorAll<HTMLButtonElement>('button[aria-label="junk.reject"]')];
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

    it('drops the previous kind\'s count when the new kind fails to load', async () => {
      const { fixture, host } = await render(defaultFirstPage, of(kindsList), () => throwError(() => new Error('boom')));
      await component.selectKind('meme');
      fixture.detectChanges();
      expect(countChip(host)!.textContent).toContain('"count":0');
      expect(emptyMessages(host)).toEqual(['junk.empty_kind']);
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
