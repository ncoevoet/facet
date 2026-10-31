import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { GalleryStore } from './gallery.store';
import { StackDialogComponent } from './stack-dialog.component';
import { stackDialogConfig } from './stack-dialog.config';
import { firstValueFrom } from 'rxjs';

@Component({ template: '<button>Open editor</button>' })
class HostComponent {}
const source = { id: 'source', revision: 7, editable: true, cover_path: '/a.jpg',
  members: ['/a.jpg', '/b.jpg', '/c.jpg'].map((path, position) => ({ path, position })) };
const preview = { selected_paths: ['/a.jpg', '/d.jpg'], mode: 'combine', paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'],
  cover_path: '/a.jpg', source_stacks: [source], unstacked_paths: ['/d.jpg'],
  affected_paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'], expected_state: 'a'.repeat(64) };

describe('shared regroup editor through Material, Router and HTTP', () => {
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let register: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;
  let fixture: ReturnType<typeof TestBed.createComponent<HostComponent>>;
  const root = () => document.querySelector<HTMLElement>('app-stack-dialog')!;
  const button = (selector: string) => root().querySelector<HTMLButtonElement>(selector)!;
  const render = async () => { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); };
  beforeEach(() => {
    identity = signal('alice'); edition = signal(true); register = vi.fn(); refresh = vi.fn(async () => undefined);
    TestBed.configureTestingModule({ providers: [provideHttpClient(withXhr()), provideHttpClientTesting(),
      provideRouter([{ path: 'away', component: HostComponent }]),
      { provide: AuthService, useValue: { identity, isEdition: edition } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string, params?: Record<string, unknown>) => key + (params ? ' ' + JSON.stringify(params) : '') } },
      { provide: GalleryStore, useValue: { pinnedPaths: signal(null), refreshPaths: refresh, restoreSelection: vi.fn() } },
      { provide: UndoService, useValue: { register } },
    ] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(HostComponent); fixture.detectChanges();
  });
  afterEach(() => {
    try { http.verify({ ignoreCancelled: true }); }
    finally { TestBed.inject(MatDialog).closeAll(); fixture.destroy(); TestBed.resetTestingModule(); }
  });
  async function open() {
    (fixture.nativeElement as HTMLElement).querySelector('button')!.focus();
    const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ paths: ['/a.jpg', '/d.jpg'] }));
    fixture.detectChanges();
    const request = http.expectOne('/api/stacks/regroup/preview');
    expect(request.request.body).toEqual({ selected_paths: ['/a.jpg', '/d.jpg'], mode: 'combine' });
    request.flush(preview); await render();
    return ref;
  }
  it('discloses expanded members, browses separately from cover and applies one authoritative mutation with Undo', async () => {
    const ref = await open();
    expect(root().textContent).toContain('stacks.regroup_extra');
    expect(root().querySelectorAll('[data-stack-tile]')).toHaveLength(4);
    button('[data-stack-focus="/b.jpg"]').click(); await render();
    expect(root().querySelector<HTMLImageElement>('[data-stack-preview]')!.src).toContain('size=1920');
    expect(ref.componentInstance.editor().cover()).toBe('/a.jpg');
    button('[data-stack-cover="/d.jpg"]').click();
    button('[data-stack-remove="/b.jpg"]').click(); await render();
    button('[data-stack-save]').click();
    const apply = http.expectOne('/api/stacks/regroup/apply');
    expect(apply.request.body).toEqual({ selected_paths: ['/a.jpg', '/d.jpg'], mode: 'combine',
      paths: ['/a.jpg', '/c.jpg', '/d.jpg'], cover_path: '/d.jpg', expected_state: preview.expected_state });
    apply.flush({ stack: source, undo: { entry_id: 31 }, changed: true, affected_paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'] });
    await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toEqual([expect.objectContaining({ kind: 'stack', paths: preview.affected_paths })]);
    expect(register).toHaveBeenCalledTimes(1); expect(refresh).toHaveBeenCalledTimes(1);
    const undo = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/31/revert').flush({ changed: 4 }); await undo;
    expect(TestBed.inject(UserActivityJournal).since().items.at(-1)?.value).toBe('undo');
    expect(refresh).toHaveBeenCalledTimes(2);
  });
  it('switches to selected-only without saving and previews residual source membership', async () => {
    await open(); button('[data-stack-mode="selected"]').click();
    const request = http.expectOne('/api/stacks/regroup/preview');
    expect(request.request.body).toEqual({ selected_paths: ['/a.jpg', '/d.jpg'], mode: 'selected' });
    request.flush({ ...preview, mode: 'selected', paths: ['/a.jpg', '/d.jpg'] }); await render();
    expect(root().querySelectorAll('[data-stack-tile]')).toHaveLength(2);
    expect(root().querySelector('[data-stack-source]')!.textContent).toContain('stacks.regroup_retained');
    expect(root().querySelector('[data-stack-source]')!.textContent).toContain('"count":2');
    expect(root().querySelector('[data-stack-source-summary]')!.textContent).toContain('{"combined":0,"retained":1,"unstacked":0}');
    http.expectNone('/api/stacks/regroup/apply');
  });
  it('refreshes a stale preview retaining exclusions, cover and order, appending only new members', async () => {
    await open();
    button('[data-stack-remove="/b.jpg"]').click();
    button('[data-stack-cover="/d.jpg"]').click();
    const tile = button('[data-stack-focus="/d.jpg"]').closest('li')!;
    tile.querySelector<HTMLButtonElement>('button[aria-label^="stacks.move_up"]')!.click();
    button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({}, { status: 409, statusText: 'Conflict' }); await render();
    expect(button('[data-stack-save]').disabled).toBe(true);
    button('[data-stack-retry]').click();
    http.expectOne('/api/stacks/regroup/preview').flush({ ...preview,
      paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/e.jpg', '/d.jpg'], expected_state: 'b'.repeat(64) }); await render();
    expect([...root().querySelectorAll('[data-stack-focus]')].map(node => node.getAttribute('data-stack-focus'))).toEqual(['/a.jpg', '/d.jpg', '/c.jpg', '/e.jpg']);
    button('[data-stack-save]').click();
    const request = http.expectOne('/api/stacks/regroup/apply');
    expect(request.request.body).toEqual({ selected_paths: ['/a.jpg', '/d.jpg'], mode: 'combine',
      paths: ['/a.jpg', '/d.jpg', '/c.jpg', '/e.jpg'], cover_path: '/d.jpg', expected_state: 'b'.repeat(64) });
    request.flush({ stack: source, undo: null, changed: true, affected_paths: [...preview.affected_paths, '/e.jpg'] }); await render();
  });
  it('retries transport failures with the same reviewed draft and never journals a failed write', async () => {
    await open(); button('[data-stack-cover="/d.jpg"]').click(); button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({}, { status: 503, statusText: 'Unavailable' }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    expect(root().textContent).toContain('stacks.regroup_retry');
    button('[data-stack-retry]').click();
    const retry = http.expectOne('/api/stacks/regroup/apply'); expect(retry.request.body.cover_path).toBe('/d.jpg');
    retry.flush({ stack: source, undo: null, changed: true, affected_paths: preview.affected_paths }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(1);
  });
  it('closes an unchanged regroup without journal, refresh, revision bump or Undo', async () => {
    await open(); const revision = TestBed.inject(PhotoStackService).revision();
    button('[data-stack-save]').click();
    http.expectOne('/api/stacks/regroup/apply').flush({ stack: source, undo: null, changed: false, affected_paths: preview.affected_paths }); await render();
    expect(root()).toBeNull();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    expect(register).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
    expect(TestBed.inject(PhotoStackService).revision()).toBe(revision);
  });
  it('cancels an obsolete policy read so it cannot restore the previous candidate set', async () => {
    const ref = await open(); button('[data-stack-mode="selected"]').click();
    const old = http.expectOne('/api/stacks/regroup/preview');
    button('[data-stack-mode="combine"]').click();
    expect(old.cancelled).toBe(true);
    http.expectOne('/api/stacks/regroup/preview').flush(preview); await render();
    expect(ref.componentInstance.editor().paths()).toEqual(preview.paths);
    expect(button('[data-stack-mode="combine"]').getAttribute('aria-pressed')).toBe('true');
  });
  it.each(['identity', 'edition', 'navigation'])('ignores an in-flight successful write after %s changes', async change => {
    await open(); const revision = TestBed.inject(PhotoStackService).revision();
    button('[data-stack-save]').click();
    const request = http.expectOne('/api/stacks/regroup/apply');
    if (change === 'identity') identity.set('bob');
    else if (change === 'edition') edition.set(false);
    else await TestBed.inject(Router).navigateByUrl('/away');
    request.flush({ stack: source, undo: { entry_id: 31 }, changed: true, affected_paths: preview.affected_paths }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items.filter(item => item.kind === 'stack')).toHaveLength(0);
    expect(register).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
    expect(TestBed.inject(PhotoStackService).revision()).toBe(revision);
  });
  it.each(['identity', 'edition'])('ignores preview completion immediately after %s changes before an effect runs', async change => {
    const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ paths: preview.selected_paths }));
    const instance = ref.componentInstance.editor(); fixture.detectChanges();
    const request = http.expectOne('/api/stacks/regroup/preview');
    if (change === 'identity') identity.set('bob'); else edition.set(false);
    const closed = firstValueFrom(ref.afterClosed());
    request.flush(preview); await render(); await closed;
    expect(instance.paths()).toEqual([]); expect(instance.ready()).toBe(false);
    expect(root()).toBeNull();
  });
  it.each(['escape', 'backdrop'])('restores focus on %s dismissal and cancels pending preview work', async dismissal => {
    const opener = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('button')!; opener.focus();
    const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ paths: preview.selected_paths }));
    fixture.detectChanges(); const request = http.expectOne('/api/stacks/regroup/preview'); await render();
    const closed = firstValueFrom(ref.afterClosed());
    if (dismissal === 'escape') document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
    else document.querySelector<HTMLElement>('.cdk-overlay-backdrop')!.click();
    await closed; await render();
    expect(request.cancelled).toBe(true); expect(document.activeElement).toBe(opener); expect(root()).toBeNull();
  });
  it('uses arrows only for the current editor and keeps typing, IME, modifiers and native activation intact', async () => {
    const ref = await open(); const tile = button('[data-stack-focus="/a.jpg"]'); tile.focus();
    const key = (init: KeyboardEventInit, target: HTMLElement = tile) => {
      const event = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event); return event;
    };
    for (const init of [{ isComposing: true }, { keyCode: 229 }, { ctrlKey: true }, { altKey: true }, { metaKey: true }, { shiftKey: true }, { key: 'Enter' }, { key: ' ' }]) {
      expect(key(init).defaultPrevented).toBe(false); expect(ref.componentInstance.editor().focused()).toBe('/a.jpg');
    }
    const input = document.createElement('input'); root().appendChild(input);
    expect(key({}, input).defaultPrevented).toBe(false); input.remove();
    expect(key({}).defaultPrevented).toBe(true); await render();
    expect(ref.componentInstance.editor().focused()).toBe('/b.jpg'); expect(ref.componentInstance.editor().cover()).toBe('/a.jpg');
    expect(document.activeElement).toBe(button('[data-stack-focus="/b.jpg"]'));
    const urls = [...root().querySelectorAll<HTMLImageElement>('img')].map(img => new URL(img.src));
    expect(urls.filter(url => url.searchParams.get('size') === '1920')).toHaveLength(1);
    expect(urls.filter(url => url.searchParams.get('size') === '640')).toHaveLength(4);
    expect(urls.every(url => url.pathname === '/thumbnail')).toBe(true);
    const upper = TestBed.inject(MatDialog).open(HostComponent); await render();
    key({}, document.body); expect(ref.componentInstance.editor().focused()).toBe('/b.jpg'); upper.close(); await render();
  });
  it('retains strict remove-to-unstack, then enters regroup only on explicit cross-stack Add selected', async () => {
    const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id, selectedPaths: ['/d.jpg'] }));
    fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
    button('[data-stack-remove="/b.jpg"]').click(); await render();
    button('[data-stack-add]').click();
    const check = http.expectOne('/api/stacks/regroup/preview');
    expect(check.request.body.selected_paths).toEqual(['/a.jpg', '/c.jpg', '/d.jpg']);
    check.flush({ ...preview, selected_paths: ['/a.jpg', '/c.jpg', '/d.jpg'], paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg', '/e.jpg'],
      source_stacks: [source, { ...source, id: 'other', cover_path: '/d.jpg', members: [{ path: '/d.jpg', position: 0 }, { path: '/e.jpg', position: 1 }] }] }); await render();
    expect(ref.componentInstance.editor().paths()).toEqual(['/a.jpg', '/c.jpg', '/d.jpg', '/e.jpg']);
    expect(root().textContent).toContain('stacks.regroup_policy');
    button('[data-stack-save]').click();
    const apply = http.expectOne('/api/stacks/regroup/apply'); expect(apply.request.body.paths).not.toContain('/b.jpg');
    apply.flush({ stack: source, undo: null, changed: true, affected_paths: [...preview.affected_paths, '/e.jpg'] }); await render();
    http.expectNone(request => request.method === 'PUT');
  });
  it.each([[403, 'unavailable'], [404, 'unavailable'], [422, 'regroup_limit'], [503, 'error']] as const)('shows an actionable %i preview refusal', async (status, key) => {
    TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ paths: preview.selected_paths }));
    fixture.detectChanges(); http.expectOne('/api/stacks/regroup/preview').flush({}, { status, statusText: 'Failed' }); await render();
    expect(root().querySelector('[role="alert"]')!.textContent).toContain('stacks.' + key);
    http.expectNone('/api/stacks/regroup/apply');
  });

  it('retries a failed Add selected without discarding strict edits or loading the stored stack again', async () => {
    const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id, selectedPaths: ['/d.jpg'] }));
    fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
    button('[data-stack-cover="/c.jpg"]').click(); button('[data-stack-remove="/b.jpg"]').click(); await render();
    button('[data-stack-add]').click();
    http.expectOne('/api/stacks/regroup/preview').flush({}, { status: 503, statusText: 'Unavailable' }); await render();
    button('[data-stack-retry]').click();
    const retry = http.expectOne('/api/stacks/regroup/preview');
    expect(retry.request.body.selected_paths).toEqual(['/a.jpg', '/c.jpg', '/d.jpg']);
    retry.flush({ ...preview, paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'], source_stacks: [source] }); await render();
    expect(ref.componentInstance.editor().paths()).toEqual(['/a.jpg', '/c.jpg', '/d.jpg']);
    expect(ref.componentInstance.editor().cover()).toBe('/c.jpg');
    http.expectNone('/api/stacks/source');
  });

  it('keeps keyboard focus inside the filmstrip when removing the focused photo', async () => {
    await open(); button('[data-stack-focus="/b.jpg"]').click(); await render();
    const remove = button('[data-stack-remove="/b.jpg"]'); remove.focus(); remove.click(); await render();
    expect(document.activeElement).toBe(button('[data-stack-focus="/c.jpg"]'));
  });

  it('keeps expanded companions out of explicit selection after Add, remove, Add and selected-only', async () => {
    TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id, selectedPaths: ['/d.jpg'] }));
    fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
    const explicit = ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'];
    const combined = { ...preview, selected_paths: explicit, paths: [...explicit, '/e.jpg'],
      source_stacks: [source, { ...source, id: 'other', cover_path: '/d.jpg', members: [{ path: '/d.jpg', position: 0 }, { path: '/e.jpg', position: 1 }] }] };
    button('[data-stack-add]').click();
    const first = http.expectOne('/api/stacks/regroup/preview'); expect(first.request.body.selected_paths).toEqual(explicit);
    first.flush(combined); await render();
    button('[data-stack-remove="/d.jpg"]').click(); await render();
    button('[data-stack-add]').click();
    const second = http.expectOne('/api/stacks/regroup/preview'); expect(second.request.body.selected_paths).toEqual(explicit);
    second.flush(combined); await render();
    button('[data-stack-mode="selected"]').click();
    const selected = http.expectOne('/api/stacks/regroup/preview'); expect(selected.request.body.selected_paths).toEqual(explicit);
    selected.flush({ ...combined, mode: 'selected', paths: explicit }); await render();
    expect([...root().querySelectorAll('[data-stack-focus]')].map(node => node.getAttribute('data-stack-focus'))).toEqual(explicit);
    expect(root().textContent).toContain('stacks.regroup_counts {"selected":4,"effective":4}');
    button('[data-stack-save]').click();
    const apply = http.expectOne('/api/stacks/regroup/apply');
    expect(apply.request.body.selected_paths).toEqual(explicit); expect(apply.request.body.paths).toEqual(explicit);
    apply.flush({ stack: source, undo: null, changed: true, affected_paths: combined.paths }); await render();
  });
  it.each([false, true])('retries failed Unstack as DELETE for a dirty=%s draft and journals exactly one success', async dirty => {
    TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id }));
    fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
    if (dirty) button('[data-stack-cover="/c.jpg"]').click();
    [...root().querySelectorAll<HTMLButtonElement>('button')].find(node => node.textContent?.trim() === 'stacks.unstack')!.click();
    const initial = http.expectOne('/api/stacks/source?expected_revision=7'); expect(initial.request.method).toBe('DELETE');
    initial.flush({}, { status: 503, statusText: 'Unavailable' }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    button('[data-stack-retry]').click();
    const retry = http.expectOne('/api/stacks/source?expected_revision=7'); expect(retry.request.method).toBe('DELETE');
    http.expectNone(request => request.method === 'PUT');
    retry.flush({ stack: null, undo: { entry_id: 42 } }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toEqual([expect.objectContaining({ kind: 'stack', value: 'unstack', paths: ['/a.jpg', '/b.jpg', '/c.jpg'] })]);
    expect(register).toHaveBeenCalledTimes(1); expect(refresh).toHaveBeenCalledTimes(1);
    const undo = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/42/revert').flush({ changed: 3 }); await undo;
    expect(refresh).toHaveBeenCalledTimes(2);
  });
  it('marks the selected policy as pressed and keeps the check icon on the pressed button', async () => {
    await open();
    const combine = button('[data-stack-mode="combine"]'); const selected = button('[data-stack-mode="selected"]');
    expect(combine.querySelector('mat-icon')?.textContent?.trim()).toBe('check');
    expect(combine.getAttribute('aria-pressed')).toBe('true');
    expect(selected.getAttribute('aria-pressed')).toBe('false');
    selected.click(); http.expectOne('/api/stacks/regroup/preview').flush({ ...preview, mode: 'selected', paths: preview.selected_paths }); await render();
    expect(selected.querySelector('mat-icon')?.textContent?.trim()).toBe('check');
    expect(selected.getAttribute('aria-pressed')).toBe('true');
    expect(combine.getAttribute('aria-pressed')).toBe('false');
    expect(button('[data-stack-mode="selected"]')).toBe(selected);
  });
  it('shows a concise source-effects summary before the large preview with details collapsed', async () => {
    await open();
    const summary = root().querySelector('[data-stack-source-summary]')!;
    expect(summary).not.toBeNull();
    expect(summary.textContent).toContain('stacks.regroup_summary {"combined":1,"retained":0,"unstacked":0}');
    expect(summary.compareDocumentPosition(root().querySelector('[data-stack-preview]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(root().querySelector('details')?.open).toBe(false);
    root().querySelector('summary')!.click(); await render();
    expect(root().querySelector('details')?.open).toBe(true);
    expect(root().querySelector('[data-stack-source]')?.textContent).toContain('stacks.regroup_absorbed');
  });

  it('refreshes stale Unstack membership instead of retrying a write without a new review', async () => {
    TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id }));
    fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
    [...root().querySelectorAll<HTMLButtonElement>('button')].find(node => node.textContent?.trim() === 'stacks.unstack')!.click();
    http.expectOne('/api/stacks/source?expected_revision=7').flush({}, { status: 409, statusText: 'Conflict' }); await render();
    button('[data-stack-retry]').click();
    const refresh = http.expectOne('/api/stacks/source'); expect(refresh.request.method).toBe('GET');
    refresh.flush({ ...source, revision: 8 }); await render();
    http.expectNone(request => request.method !== 'GET');
    expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
    expect(register).not.toHaveBeenCalled();
  });

  it.each([['unstack', 503], ['unstack', 409], ['save', 503], ['save', 409]] as const)(
    'retries only the failed member read after %s fails with %i', async (action, status) => {
      const ref = TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ stackId: source.id }));
      fixture.detectChanges(); http.expectOne('/api/stacks/source').flush(source); await render();
      if (action === 'save') {
        button('[data-stack-cover="/c.jpg"]').click(); button('[data-stack-save]').click();
      } else {
        [...root().querySelectorAll<HTMLButtonElement>('button')].find(node => node.textContent?.trim() === 'stacks.unstack')!.click();
      }
      const write = http.expectOne(request => request.method === (action === 'save' ? 'PUT' : 'DELETE'));
      write.flush({}, { status, statusText: 'Failed' }); await render();
      if (status === 409) {
        button('[data-stack-retry]').click();
        http.expectOne('/api/stacks/source').flush({ ...source, revision: 8 }); await render();
      }
      button('button[aria-label^="stacks.open_member"]').click();
      http.expectOne(request => request.url === '/api/photo' && request.params.get('path') === '/a.jpg')
        .flush({}, { status: 503, statusText: 'Read failed' }); await render();
      // Moving focus must not change which failed read Retry recovers.
      button('[data-stack-focus="/b.jpg"]').click(); await render();
      button('[data-stack-retry]').click();
      const read = http.expectOne(request => request.url === '/api/photo' && request.params.get('path') === '/a.jpg');
      expect(read.request.method).toBe('GET');
      http.expectNone(request => request.method !== 'GET');
      read.flush({}, { status: 503, statusText: 'Read failed again' }); await render();
      const navigate = vi.spyOn(TestBed.inject(PhotoStackService), 'navigateMember').mockResolvedValue(true);
      button('[data-stack-retry]').click();
      http.expectOne(request => request.url === '/api/photo' && request.params.get('path') === '/a.jpg').flush({ path: '/a.jpg' });
      await render();
      expect(navigate).toHaveBeenCalledWith('/a.jpg', { path: '/a.jpg' }, expect.any(Function), false);
      expect(TestBed.inject(UserActivityJournal).since().items).toHaveLength(0);
      expect(register).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
      expect(ref.componentInstance).toBeNull();
    });

  it.each([false, true])('journals the actual final contributors after excluding a source (contributes=%s)', async contributes => {
    TestBed.inject(MatDialog).open(StackDialogComponent, stackDialogConfig({ paths: ['/a.jpg', '/d.jpg', '/e.jpg'] }));
    fixture.detectChanges();
    http.expectOne('/api/stacks/regroup/preview').flush({ ...preview,
      selected_paths: ['/a.jpg', '/d.jpg', '/e.jpg'], paths: [...preview.paths, '/e.jpg'],
      affected_paths: [...preview.paths, '/e.jpg'], unstacked_paths: ['/d.jpg', '/e.jpg'] }); await render();
    for (const path of contributes ? ['/b.jpg', '/c.jpg'] : ['/a.jpg', '/b.jpg', '/c.jpg']) {
      button(`[data-stack-remove="${path}"]`).click(); await render();
    }
    button('[data-stack-save]').click();
    const request = http.expectOne('/api/stacks/regroup/apply');
    const affected = contributes ? [...preview.paths, '/e.jpg'] : ['/d.jpg', '/e.jpg'];
    expect(request.request.body.paths).toEqual(contributes ? ['/a.jpg', '/d.jpg', '/e.jpg'] : ['/d.jpg', '/e.jpg']);
    request.flush({ stack: source, undo: { entry_id: 77 }, changed: true, affected_paths: affected }); await render();
    expect(TestBed.inject(UserActivityJournal).since().items).toEqual([
      expect.objectContaining({ kind: 'stack', value: contributes ? 'update' : 'create', paths: affected }),
    ]);
    expect(refresh).toHaveBeenCalledTimes(1); expect(register).toHaveBeenCalledTimes(1);
  });

});
