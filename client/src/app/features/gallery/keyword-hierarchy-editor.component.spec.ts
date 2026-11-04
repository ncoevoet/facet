import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { KeywordHierarchyEditorComponent } from './keyword-hierarchy-editor.component';
import { GalleryStore, DEFAULT_FILTERS } from './gallery.store';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

describe('Captured hierarchy editor', () => {
  let fixture: ComponentFixture<KeywordHierarchyEditorComponent>;
  let http: HttpTestingController;
  let token: string;
  let events: Subject<NavigationStart>;
  let owner: ReturnType<typeof signal<{ name: string; edition: boolean }>>;
  let selection: ReturnType<typeof signal<Set<string>>>;
  let excluded: ReturnType<typeof signal<Set<string>>>;
  let view: ReturnType<typeof signal<boolean>>;
  let filters: ReturnType<typeof signal<typeof DEFAULT_FILTERS>>;
  let pathsInView: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;
  const id = '11111111-1111-4111-8111-111111111111';
  const node = { id, name: 'Cat', segments: ['Animals', 'Cat'], parent_id: null, direct_count: 1, branch_count: 1 };
  const result = { success: true, node_id: id, target_photos: 2, affected_photos: 2, changed_assignments: 2 };

  function build(create = false): void {
    token = 'a'; owner = signal({ name: 'alice', edition: true }); events = new Subject();
    selection = signal(new Set(['/a.jpg', '/b.jpg'])); excluded = signal(new Set<string>()); view = signal(false); filters = signal({ ...DEFAULT_FILTERS });
    pathsInView = vi.fn().mockResolvedValue(['/a.jpg', '/offscreen.jpg']); refresh = vi.fn().mockResolvedValue(undefined);
    TestBed.configureTestingModule({ imports: [KeywordHierarchyEditorComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), ApiService,
      { provide: Router, useValue: { url: '/', events } },
      { provide: AuthService, useValue: { status: owner, identity: computed(() => owner().name), isEdition: computed(() => owner().edition), get token() { return token; } } },
      { provide: GalleryStore, useValue: { filters, selectedPaths: selection, excludedPaths: excluded, viewScopeSelected: view, pinnedPaths: signal(null),
        selectionCount: computed(() => view() ? 12 : selection().size), currentAlbum: signal(null),
        filterKey: (value: unknown) => JSON.stringify(value), pathsInView, refreshPaths: refresh } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
    ] });
    http = TestBed.inject(HttpTestingController); fixture = TestBed.createComponent(KeywordHierarchyEditorComponent);
    fixture.componentRef.setInput('node', create ? null : node); fixture.componentRef.setInput('nodes', [node]); fixture.detectChanges();
  }
  async function capture(action: 'assign' | 'remove' | 'rename' = 'assign') {
    const component = fixture.componentInstance; component.setAction(action);
    if (action === 'rename') component.name.set('Kitten');
    const pending = component.preview(); await Promise.resolve();
    const request = http.expectOne('/api/manual_tags/hierarchy/preview');
    const plan = { request: request.request.body, paths: request.request.body.paths ?? ['/a.jpg'],
      before_path: ['Animals', 'Cat'], after_path: action === 'rename' ? ['Animals', 'Kitten'] : ['Animals', 'Cat'], new_assignments: 2, removed_assignments: 0,
      updated_assignments: 0, definition_change: false, preview_token: 'signed', expires_at: 9999999999 };
    request.flush(plan); await pending; fixture.detectChanges(); return plan;
  }
  afterEach(() => { fixture.destroy(); http.verify(); });

  it('previews captured explicit targets without mutation, then applies the authoritative request and preserves newer selection', async () => {
    build(); const plan = await capture();
    expect(plan.request).toEqual({ action: 'assign', node_id: id, paths: ['/a.jpg', '/b.jpg'] });
    http.expectNone('/api/manual_tags/hierarchy/apply');
    const settled = vi.fn(); fixture.componentInstance.changed.subscribe(settled);
    const pending = fixture.componentInstance.apply();
    const write = http.expectOne('/api/manual_tags/hierarchy/apply');
    expect(write.request.body).toEqual({ ...plan.request, preview_token: 'signed' });
    const newer = new Set(['/new-selection.jpg']); selection.set(newer); fixture.detectChanges();
    write.flush(result); await pending;
    expect(selection()).toBe(newer); expect(refresh).toHaveBeenCalledExactlyOnceWith(plan.paths);
    expect(settled).toHaveBeenCalledExactlyOnceWith(result);
  });

  it('resolves whole-view membership before preview and refuses changed exclusions during that read', async () => {
    build(); view.set(true); fixture.detectChanges();
    let release!: (paths: string[]) => void;
    pathsInView.mockReturnValue(new Promise<string[]>(resolve => { release = resolve; }));
    const component = fixture.componentInstance; component.setAction('assign');
    const stale = component.preview(); excluded.set(new Set(['/a.jpg'])); release(['/offscreen.jpg']); await stale;
    http.expectNone('/api/manual_tags/hierarchy/preview');
    pathsInView.mockResolvedValue(['/offscreen.jpg', '/folded.jpg']);
    const pending = component.preview(); await Promise.resolve();
    const read = http.expectOne('/api/manual_tags/hierarchy/preview');
    expect(read.request.body.paths).toEqual(['/offscreen.jpg', '/folded.jpg']);
    expect(read.request.body.filters).toBeUndefined();
    read.flush({ request: read.request.body, paths: read.request.body.paths, before_path: ['Animals', 'Cat'], after_path: ['Animals', 'Cat'],
      new_assignments: 2, removed_assignments: 0, updated_assignments: 0, definition_change: false, preview_token: 'signed', expires_at: 9999999999 });
    await pending;
  });

  it('creates a literal multilevel path through native controls and applies only the reviewed normalized request', async () => {
    build(true);
    const page = fixture.nativeElement as HTMLElement;
    const levels = page.querySelector<HTMLTextAreaElement>('[data-hierarchy-levels]')!;
    levels.value = ' Animals \n Cat / Kitten | Pet'; levels.dispatchEvent(new Event('input')); fixture.detectChanges();
    page.querySelector<HTMLButtonElement>('[data-hierarchy-preview]')!.click(); await Promise.resolve();
    const preview = http.expectOne('/api/manual_tags/hierarchy/preview');
    expect(preview.request.body.segments).toEqual([' Animals ', ' Cat / Kitten | Pet']);
    expect(preview.request.body.paths).toEqual(['/a.jpg', '/b.jpg']);
    const normalized = { action: 'create_assign', paths: ['/a.jpg', '/b.jpg'], segments: ['Animals', 'Cat / Kitten | Pet'] };
    preview.flush({ request: normalized, paths: normalized.paths, before_path: null, after_path: normalized.segments,
      new_assignments: 2, removed_assignments: 0, updated_assignments: 0, definition_change: null, preview_token: 'signed', expires_at: 9999999999 });
    await fixture.whenStable(); fixture.detectChanges();
    expect(page.textContent).toContain('Animals › Cat / Kitten | Pet');
    http.expectNone('/api/manual_tags/hierarchy/apply');
    page.querySelector<HTMLButtonElement>('[data-hierarchy-apply]')!.click();
    const write = http.expectOne('/api/manual_tags/hierarchy/apply');
    expect(write.request.body).toEqual({ ...normalized, preview_token: 'signed' });
    write.flush(result); await fixture.whenStable();
    expect(refresh).toHaveBeenCalledExactlyOnceWith(['/a.jpg', '/b.jpg']);
  });

  it('refuses retargeted selection and live credential changes before Apply', async () => {
    build(); await capture(); selection.set(new Set(['/other.jpg']));
    await fixture.componentInstance.apply(); http.expectNone('/api/manual_tags/hierarchy/apply');
    await capture(); token = 'rotated'; await fixture.componentInstance.apply();
    http.expectNone('/api/manual_tags/hierarchy/apply');
  });

  it('keeps uncertain writes disabled until the editor is replaced and requests a fresh view read', async () => {
    build(); await capture();
    const pending = fixture.componentInstance.apply();
    http.expectOne('/api/manual_tags/hierarchy/apply').flush({}, { status: 503, statusText: 'unknown' }); await pending; fixture.detectChanges();
    expect(fixture.componentInstance.uncertain()).toBe(true);
    await fixture.componentInstance.apply(); await fixture.componentInstance.preview();
    http.expectNone('/api/manual_tags/hierarchy/apply'); http.expectNone('/api/manual_tags/hierarchy/preview');
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('lets an accepted update settle after destruction and repairs the captured paths', async () => {
    build(); await capture(); const component = fixture.componentInstance;
    const pending = component.apply(); const write = http.expectOne('/api/manual_tags/hierarchy/apply');
    fixture.destroy(); write.flush(result); await pending;
    expect(refresh).toHaveBeenCalledExactlyOnceWith(['/a.jpg', '/b.jpg']);
  });

  it('suppresses foreign-user repair when an accepted old-owner response settles', async () => {
    build(); await capture();
    const pending = fixture.componentInstance.apply(); const write = http.expectOne('/api/manual_tags/hierarchy/apply');
    owner.set({ name: 'bob', edition: true }); fixture.detectChanges();
    write.flush(result); await pending;
    expect(refresh).not.toHaveBeenCalled();
  });

  it('cancels preview reads when navigation parks the editor', async () => {
    build(); fixture.componentInstance.name.set('Kitten');
    const pending = fixture.componentInstance.preview(); await Promise.resolve();
    const read = http.expectOne('/api/manual_tags/hierarchy/preview');
    events.next(new NavigationStart(1, '/persons')); fixture.detectChanges();
    expect(read.cancelled).toBe(true); await pending;
    expect(fixture.componentInstance.plan()).toBeNull();
  });

  it('filters self, descendants and cycles from move parents and previews the chosen parent', async () => {
    build(); const component = fixture.componentInstance;
    const other = { ...node, id: 'other', name: 'Other', segments: ['Other'] };
    fixture.componentRef.setInput('nodes', [node, other,
      { ...node, id: 'child', parent_id: id }, { ...node, id: 'cycle-a', parent_id: 'cycle-b' },
      { ...node, id: 'cycle-b', parent_id: 'cycle-a' }]); fixture.detectChanges();
    expect(component.parents().map(parent => parent.id)).toEqual(['other']);
    component.setAction('move'); component.parent.set('other');
    const pending = component.preview();
    const request = http.expectOne('/api/manual_tags/hierarchy/preview');
    expect(request.request.body).toEqual({ action: 'move', node_id: id, parent_id: 'other' });
    request.flush({ request: request.request.body, paths: [], before_path: node.segments, after_path: ['Other', 'Cat'],
      preview_token: 'move', expires_at: 9999999999 }); await pending;
    component.setAction('delete_branch');
    const deleting = component.preview(); const deletion = http.expectOne('/api/manual_tags/hierarchy/preview');
    expect(deletion.request.body).toEqual({ action: 'delete_branch', node_id: id });
    deletion.flush({ request: deletion.request.body, paths: [], preview_token: 'delete', expires_at: 9999999999 }); await deleting;
  });

  it('refuses expired previews and handles definite write rejection without recovery reads', async () => {
    build(); const plan = await capture(); plan.expires_at = 1;
    await fixture.componentInstance.apply(); http.expectNone('/api/manual_tags/hierarchy/apply');
    expect(fixture.componentInstance.plan()).toBeNull();
    await capture(); const pending = fixture.componentInstance.apply();
    http.expectOne('/api/manual_tags/hierarchy/apply').flush({}, { status: 409, statusText: 'Changed' }); await pending;
    expect(fixture.componentInstance.uncertain()).toBe(false);
    expect(fixture.componentInstance.plan()).toBeNull(); expect(refresh).not.toHaveBeenCalled();
  });

  it('refreshes membership rather than only changed rows when a keyword branch is active', async () => {
    build(); filters.update(current => ({ ...current, keyword_branch: id })); fixture.detectChanges();
    await capture(); const pending = fixture.componentInstance.apply();
    http.expectOne('/api/manual_tags/hierarchy/apply').flush(result); await pending;
    expect(refresh).toHaveBeenCalledExactlyOnceWith(null);
  });
});
