import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationCancel, NavigationEnd, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { KeywordTreeComponent } from './keyword-tree.component';
import { KeywordHierarchyLabels } from './keyword-hierarchy-labels.service';
import { GalleryStore } from './gallery.store';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

describe('Explicit keyword hierarchy browsing', () => {
  let fixture: ComponentFixture<KeywordTreeComponent>;
  let http: HttpTestingController;
  let events: Subject<NavigationStart | NavigationCancel | NavigationEnd>;
  let owner: ReturnType<typeof signal<{ user: string }>>;
  let token: string;
  let updateFilter: ReturnType<typeof vi.fn>;
  const root = '11111111-1111-4111-8111-111111111111';
  const domestic = '22222222-2222-4222-8222-222222222222';
  const wild = '33333333-3333-4333-8333-333333333333';
  const wildRoot = '44444444-4444-4444-8444-444444444444';
  const tree = { nodes: [
    { id: root, parent_id: null, name: 'Animals', segments: ['Animals'], direct_count: 2, branch_count: 3 },
    { id: domestic, parent_id: root, name: 'Cat', segments: ['Animals', 'Cat'], direct_count: 1, branch_count: 1 },
    { id: wildRoot, parent_id: null, name: 'Wild', segments: ['Wild'], direct_count: 0, branch_count: 2 },
    { id: wild, parent_id: wildRoot, name: 'Cat', segments: ['Wild', 'Cat'], direct_count: 2, branch_count: 2 },
  ] };

  function build(edition = false): void {
    token = 'a'; owner = signal({ user: 'alice' }); events = new Subject(); updateFilter = vi.fn();
    TestBed.configureTestingModule({ imports: [KeywordTreeComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), ApiService,
      { provide: AuthService, useValue: { status: owner, identity: computed(() => owner().user), isEdition: () => edition, get token() { return token; } } },
      { provide: Router, useValue: { url: '/', events } },
      { provide: GalleryStore, useValue: { filters: signal({ keyword_branch: '' }), updateFilter,
        selectedPaths: signal(new Set(['/photo.jpg'])), excludedPaths: signal(new Set()), viewScopeSelected: signal(false), pinnedPaths: signal(null),
        selectionCount: signal(1), currentAlbum: signal(null), filterKey: (value: unknown) => JSON.stringify(value),
        pathsInView: vi.fn().mockResolvedValue(['/photo.jpg']), refreshPaths: vi.fn().mockResolvedValue(undefined) } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
    ] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(KeywordTreeComponent); fixture.detectChanges();
  }
  async function beginOpen() {
    const panel = fixture.nativeElement.querySelector('[data-keyword-tree]') as HTMLDetailsElement;
    const toggled = new Promise<void>(resolve => panel.addEventListener('toggle', () => resolve(), { once: true }));
    panel.querySelector<HTMLElement>('summary')!.click(); await toggled;
    expect(panel.open).toBe(true); expect(fixture.componentInstance.opened()).toBe(true);
    return http.expectOne('/api/manual_tags/hierarchy');
  }
  async function open(): Promise<void> {
    (await beginOpen()).flush(tree);
    await fixture.whenStable(); fixture.detectChanges();
  }
  afterEach(() => { fixture.destroy(); http.verify(); });

  it('loads lazily, expands native branch controls and filters full distinct paths without writes', async () => {
    build(); http.expectNone(() => true); await open();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.querySelectorAll('[data-keyword-branch]')).toHaveLength(2);
    page.querySelector<HTMLButtonElement>('[data-keyword-expand]')!.click(); fixture.detectChanges();
    expect(page.querySelectorAll('[data-keyword-branch]')).toHaveLength(3);
    fixture.componentInstance.expand(wildRoot); fixture.detectChanges();
    expect(page.textContent).toContain('Animals › Cat'); expect(page.textContent).toContain('Wild › Cat');
    Array.from(page.querySelectorAll<HTMLButtonElement>('[data-keyword-branch]')).find(button => button.textContent?.includes('Animals › Cat'))!.click();
    expect(updateFilter).toHaveBeenCalledExactlyOnceWith('keyword_branch', domestic);
    expect(TestBed.inject(KeywordHierarchyLabels).names()[domestic]).toBe('Animals › Cat');
    http.expectNone(request => request.method !== 'GET');
  });

  it('keeps the tree open and focused when selecting a branch updates the gallery URL', async () => {
    build(); await open();
    document.body.appendChild(fixture.nativeElement);
    const filters = TestBed.inject(GalleryStore).filters;
    updateFilter.mockImplementation((_key: string, value: string) => {
      events.next(new NavigationStart(4, '/?keyword_branch=' + value));
      filters.update(current => ({ ...current, keyword_branch: value }));
      events.next(new NavigationEnd(4, '/?keyword_branch=' + value, '/?keyword_branch=' + value));
    });
    const panel = fixture.nativeElement.querySelector('[data-keyword-tree]') as HTMLDetailsElement;
    const button = fixture.nativeElement.querySelector('[data-keyword-branch]') as HTMLButtonElement;
    button.focus(); button.click(); fixture.detectChanges();
    expect(panel.open).toBe(true);
    expect(document.activeElement).toBe(button);
    expect(fixture.componentInstance.opened()).toBe(true);
    http.expectNone('/api/manual_tags/hierarchy');
    filters.update(current => ({ ...current, page: 2 }));
    fixture.detectChanges();
    http.expectNone('/api/manual_tags/hierarchy');
    fixture.nativeElement.remove();
  });

  it('refuses old credential commands and cancels parked reads without adopting another account', async () => {
    build(); await open(); token = 'rotated';
    expect(TestBed.inject(KeywordHierarchyLabels).names()).toEqual({});
    fixture.componentInstance.filter(domestic);
    expect(updateFilter).not.toHaveBeenCalled();
    fixture.componentInstance.toggle(true);
    const read = http.expectOne('/api/manual_tags/hierarchy');
    events.next(new NavigationStart(7, '/persons')); fixture.detectChanges();
    expect(read.cancelled).toBe(true);
    fixture.componentInstance.toggle(true);
    http.expectNone('/api/manual_tags/hierarchy');
    events.next(new NavigationCancel(7, '/persons', 'cancelled')); fixture.detectChanges();
    owner.set({ user: 'bob' }); fixture.detectChanges();
    expect(TestBed.inject(KeywordHierarchyLabels).names()).toEqual({});
    fixture.componentInstance.filter(domestic); expect(updateFilter).not.toHaveBeenCalled();
  });

  it('recovers a read failure and gives Escape to the disclosure with focus return', async () => {
    build();
    (await beginOpen()).flush({}, { status: 503, statusText: 'unavailable' });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
    const retry = fixture.componentInstance.load(); http.expectOne('/api/manual_tags/hierarchy').flush(tree); await retry; fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeNull();
    const trigger = fixture.nativeElement.querySelector('summary') as HTMLElement;
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    input.focus(); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); fixture.detectChanges();
    expect((fixture.nativeElement.querySelector('[data-keyword-tree]') as HTMLDetailsElement).open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(fixture.componentInstance.opened()).toBe(false);
    http.expectNone(request => request.method !== 'GET');
  });

  it('opens the inline editor from its native control, previews before Apply and returns focus after close and success', async () => {
    build(true); await open();
    const page = fixture.nativeElement as HTMLElement;
    const manage = page.querySelector<HTMLButtonElement>('[data-hierarchy-manage]')!;
    manage.click(); await fixture.whenStable(); fixture.detectChanges();
    const close = page.querySelector<HTMLButtonElement>('[data-hierarchy-editor] button')!;
    close.click(); fixture.detectChanges();
    expect(document.activeElement).toBe(manage);
    manage.click(); await fixture.whenStable(); fixture.detectChanges();
    const preview = page.querySelector<HTMLButtonElement>('[data-hierarchy-preview]')!;
    expect(preview.disabled).toBe(true);
    const name = page.querySelector<HTMLInputElement>('[data-hierarchy-name]')!;
    name.value = 'Wildlife'; name.dispatchEvent(new Event('input')); fixture.detectChanges();
    preview.click();
    const read = http.expectOne('/api/manual_tags/hierarchy/preview');
    expect(read.request.body).toEqual({ action: 'rename', node_id: root, name: 'Wildlife' });
    http.expectNone('/api/manual_tags/hierarchy/apply');
    read.flush({ request: read.request.body, paths: ['/photo.jpg'], before_path: ['Animals'], after_path: ['Wildlife'],
      new_assignments: 0, removed_assignments: 0, updated_assignments: 1, definition_change: true, preview_token: 'signed', expires_at: 9999999999 });
    await fixture.whenStable(); fixture.detectChanges();
    const apply = page.querySelector<HTMLButtonElement>('[data-hierarchy-apply]')!;
    expect(document.activeElement).toBe(apply);
    apply.click(); http.expectOne('/api/manual_tags/hierarchy/apply').flush({
      success: true, node_id: root, target_photos: 1, affected_photos: 1, changed_assignments: 1 });
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    http.expectOne('/api/manual_tags/hierarchy').flush(tree);
    await fixture.whenStable(); fixture.detectChanges();
    expect(page.querySelector('[data-hierarchy-editor]')).toBeNull();
    expect(document.activeElement).toBe(page.querySelector('[data-keyword-tree] > summary'));
    expect(page.textContent).toContain('keyword_hierarchy.edit.changed');
  });

  it('refreshes tree labels after an accepted rename settles after the editor closes', async () => {
    build(true); await open();
    const page = fixture.nativeElement as HTMLElement;
    const manage = page.querySelector<HTMLButtonElement>('[data-hierarchy-manage]')!;
    manage.click(); await fixture.whenStable(); fixture.detectChanges();
    const name = page.querySelector<HTMLInputElement>('[data-hierarchy-name]')!;
    name.value = 'Wildlife'; name.dispatchEvent(new Event('input')); fixture.detectChanges();
    page.querySelector<HTMLButtonElement>('[data-hierarchy-preview]')!.click();
    const read = http.expectOne('/api/manual_tags/hierarchy/preview');
    read.flush({ request: read.request.body, paths: ['/photo.jpg'], before_path: ['Animals'], after_path: ['Wildlife'],
      new_assignments: 0, removed_assignments: 0, updated_assignments: 1, definition_change: true, preview_token: 'signed', expires_at: 9999999999 });
    await fixture.whenStable(); fixture.detectChanges();
    page.querySelector<HTMLButtonElement>('[data-hierarchy-apply]')!.click();
    const write = http.expectOne('/api/manual_tags/hierarchy/apply');
    page.querySelector<HTMLButtonElement>('[data-hierarchy-editor] button')!.click(); fixture.detectChanges();
    expect(page.querySelector('[data-hierarchy-editor]')).toBeNull();
    write.flush({ success: true, node_id: root, target_photos: 1, affected_photos: 1, changed_assignments: 1 });
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    const refreshed = { nodes: tree.nodes.map(node => node.id === root ? { ...node, name: 'Wildlife', segments: ['Wildlife'] } : node) };
    const refresh = http.expectOne('/api/manual_tags/hierarchy');
    fixture.detectChanges();
    expect(document.activeElement).toBe(manage);
    expect(TestBed.inject(KeywordHierarchyLabels).names()).toEqual({});
    refresh.flush(refreshed);
    await fixture.whenStable(); fixture.detectChanges();
    expect(page.textContent).toContain('Wildlife');
    expect(TestBed.inject(KeywordHierarchyLabels).names()[root]).toBe('Wildlife');
    expect(document.activeElement).toBe(manage);
  });
});
