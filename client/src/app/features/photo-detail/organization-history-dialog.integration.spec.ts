import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import type { components } from '../../core/api/schema';
import { AuthService, AuthStatus } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { OrganizationHistoryDialogComponent } from './organization-history-dialog.component';

type Entry = components['schemas']['OrganizationEntry'];
const messages = {
  preview_action: 'Review restore…', limits_title: 'What history can restore', limits: 'Up to 50 recent entries.', reload: 'Reload history', restore_preview: 'Restore {count} photo', restore_preview_plural: 'Restore {count} photos', superseded: 'Superseded by a later change', restore_boundary: 'Conflicts restore nothing.',
  title: 'Organization history', hint: 'History belongs to this account.', gps: 'Location', date: 'Capture date',
  review: 'Review', logical_review: 'Grouped photo review', revert: 'Revert this entry', reverted: 'Already reverted', empty: 'No available history entries.',
  success: 'Photos restored: {count}', error: 'Could not load or restore history.',
  conflict: 'Photos changed since this action. Nothing was restored.',
  unavailable: 'This entry is no longer available. Nothing was restored.',
  photo_count: 'Photos: {count}', part: 'Part {part} of {parts}: {count} photos.',
  latitude: 'Latitude', longitude: 'Longitude', manual_gps: 'Manual location', capture_date: 'Capture date',
  manual_date: 'Manual date', stars: 'Stars', favorite: 'Favorite', rejected: 'Rejected', kept: 'Kept',
  yes: 'Yes', no: 'No', unknown: 'Unknown', field: 'Field',
  entry_action: '{action} · {kind} · {date} · #{id}',
};
const translations = { organization_history: messages, capture_date: { before: 'Before', after: 'After' },
  dialog: { close: 'Close' }, ui: { labels: { loading: 'Loading...' }, buttons: { cancel: 'Cancel' } }, culling: { lightbox: { undecided: 'Undecided' } } };
const entry = (overrides: Partial<Entry> = {}): Entry => ({
  id: 901, kind: 'gps', created_at: '2026-10-24T10:11:00', part: 1, parts: 1, reverted: false, superseded: false,
  changes: [{ path: '/history/a.jpg', before: [null, 2, 0], after: [3, 4, 1], revision: 5 }], ...overrides,
});

describe('Organization history rendered controls and HTTP', () => {
  let fixture: ComponentFixture<OrganizationHistoryDialogComponent>;
  let http: HttpTestingController;
  let root: HTMLElement;
  let dialog: { close: ReturnType<typeof vi.fn>; beforeClosed: () => Subject<void> };
  let store: { refreshPaths: ReturnType<typeof vi.fn> };

  async function settle() { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); }
  async function create(entries: Entry[] = [entry()], loadError = false) {
    http?.verify();
    TestBed.resetTestingModule();
    const closed = new Subject<void>();
    dialog = { close: vi.fn(), beforeClosed: () => closed };
    store = { refreshPaths: vi.fn() };
    TestBed.configureTestingModule({ imports: [OrganizationHistoryDialogComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), provideRouter([]),
      { provide: MatDialogRef, useValue: dialog }, { provide: GalleryStore, useValue: store },
    ] });
    http = TestBed.inject(HttpTestingController);
    const status: AuthStatus = { authenticated: true, multi_user: true, edition_enabled: true,
      edition_authenticated: true, edition_password_required: true, login_password_required: true,
      user_id: 'alice', user_role: 'user', display_name: 'Alice', features: {}, download_profiles: [] };
    TestBed.inject(AuthService).status.set(status);
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('en');
    const loaded = i18n.load();
    http.expectOne('/api/i18n/en').flush(translations);
    await loaded;
    fixture = TestBed.createComponent(OrganizationHistoryDialogComponent);
    root = fixture.nativeElement;
    fixture.detectChanges();
    expect(root.querySelector('[role="status"]')?.textContent).toContain('Loading...');
    const request = http.expectOne('/api/organization_history');
    expect(request.request.method).toBe('GET');
    if (loadError) request.flush({}, { status: 503, statusText: 'Unavailable' });
    else request.flush({ entries });
    await settle();
  }
  function sections(): HTMLElement[] { return [...root.querySelectorAll<HTMLElement>('mat-dialog-content > section')]; }
  function revert(index = 0): HTMLButtonElement { return sections()[index].querySelector('button[aria-label]')!; }
  async function applyRestore() {
    revert().click(); await settle();
    (root.querySelector('[data-history-apply]') as HTMLButtonElement).click();
    await settle();
  }
  function assertNoRestore() {
    expect(store.refreshPaths).not.toHaveBeenCalled();
    expect(fixture.componentInstance.wasRestored()).toBe(false);
    expect(fixture.componentInstance.changed()).toBeNull();
  }
  afterEach(() => { try { http?.verify(); } finally { TestBed.resetTestingModule(); } });

  it('renders grouped review values and requires an explicit restore confirmation', async () => {
    await create([entry({ kind: 'logical_review', changes: [{ path: '/history/a.CR2', before: [5, 0, 0, 1], after: [3, 0, 1, 0], revision: 4 }] })]);
    expect(root.textContent).toContain('Grouped photo review');
    const details = sections()[0].querySelector('details')!;
    details.open = true; details.dispatchEvent(new Event('toggle')); await settle();
    expect(root.textContent).toContain('Stars');
    expect(root.textContent).toContain('/history/a.CR2');
    revert().click(); await settle();
    http.expectNone('/api/organization_history/901/revert');
    expect(root.querySelector('[data-history-preview]')).not.toBeNull();
  });

  it('previews and cancels a restore without writing, then explicitly applies the captured entry', async () => {
    await create();
    revert().click(); await settle();
    expect(root.querySelector('[data-history-preview]')?.textContent).toContain('Restore 1 photo');
    expect(revert().compareDocumentPosition(root.querySelector('[data-history-preview]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    http.expectNone(request => request.method === 'POST');
    const cancel = [...root.querySelectorAll('[data-history-preview] button')].find(button => button.textContent?.trim() === 'Cancel') as HTMLButtonElement;
    cancel.click(); await settle();
    expect(root.querySelector('[data-history-preview]')).toBeNull();
    http.expectNone(request => request.method === 'POST');
    await applyRestore();
    http.expectOne('/api/organization_history/901/revert').flush({}, { status: 409, statusText: 'Conflict' });
    await settle();
    expect(sections()[0].querySelector('[role=alert]')?.textContent).toContain(messages.conflict);
    assertNoRestore();
  });

  it('gives same-kind and same-minute entries distinct accessible action names', async () => {
    await create([entry(), entry({ id: 902 })]);
    const names = sections().map(section => section.querySelector('button')!.getAttribute('aria-label'));
    expect(names[0]).toBe('Review restore… · Location · 24/10/2026 10:11 · #901');
    expect(names[1]).toBe('Review restore… · Location · 24/10/2026 10:11 · #902');
    expect(new Set(names).size).toBe(2);
    expect(sections().map(section => section.querySelector('h3')?.textContent?.trim()))
      .toEqual(['Location · 24/10/2026 10:11', 'Location · 24/10/2026 10:11']);
    http.expectNone(request => request.method === 'POST');
  });

  for (const [kind, before, after, labels, values] of [
    ['gps', [null, 2, 0], [3, 4, 1], ['Latitude', 'Longitude', 'Manual location'], ['Unknown', '3', '2', '4', 'No', 'Yes']],
    ['date', ['2024:01:01 00:00:00', 0], ['2024:01:01 00:01:00', 1], ['Capture date', 'Manual date'], ['2024:01:01 00:00:00', '2024:01:01 00:01:00', 'No', 'Yes']],
    ['review', [4, 0, 0, 1], [0, 0, 1, 0], ['Stars', 'Favorite', 'Rejected', 'Kept'], ['4', '0', 'No', 'No', 'No', 'Yes', 'Yes', 'No']],
  ] as const) {
    it(`renders ${kind} values under named column and row headers after expansion`, async () => {
      await create([entry({ kind, changes: [{ path: '/history/a.jpg', before: [...before], after: [...after], revision: 5 }] })]);
      expect(root.querySelector('table')).toBeNull();
      const details = sections()[0].querySelector('details')!;
      expect(details.querySelector('summary')?.textContent?.trim()).toBe('Before → After');
      details.open = true;
      details.dispatchEvent(new Event('toggle'));
      await settle();
      const headers = [...root.querySelectorAll('thead th')];
      expect(headers.map(header => header.textContent?.trim())).toEqual(['Field', 'Before', 'After']);
      expect(headers.map(header => header.getAttribute('scope'))).toEqual(['col', 'col', 'col']);
      const rows = [...root.querySelectorAll('tbody th')];
      expect(rows.map(header => header.textContent?.trim())).toEqual(labels);
      expect(rows.every(header => header.getAttribute('scope') === 'row')).toBe(true);
      expect([...root.querySelectorAll('tbody td')].map(cell => cell.textContent?.trim())).toEqual(values);
      details.open = false;
      details.dispatchEvent(new Event('toggle'));
      await settle();
      expect(root.querySelector('table')).toBeNull();
      http.expectNone(request => request.method === 'POST');
    });
  }

  it('renders a list failure without writing and loads again when reopened', async () => {
    await create([], true);
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(messages.error);
    assertNoRestore();
    expect(sections()).toHaveLength(0);
    expect(root.textContent).not.toContain(messages.empty);
    (root.querySelector('[data-history-reload]') as HTMLButtonElement).click();
    http.expectOne('/api/organization_history').flush({ entries: [entry()] });
    await settle();
    expect(sections()).toHaveLength(1);
    expect(root.querySelector('[role=alert]')).toBeNull();
    const close = [...root.querySelectorAll('button')].find(button => button.textContent?.trim() === 'Close')!;
    close.click();
    expect(dialog.close).toHaveBeenCalled();
    await create([entry()]);
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(sections()).toHaveLength(1);
    assertNoRestore();
  });

  it('disables only already-reverted entries and never posts their clicks', async () => {
    await create([entry({ reverted: true }), entry({ id: 902 })]);
    expect(revert().disabled).toBe(true);
    expect(revert().textContent).toContain('Already reverted');
    expect(revert(1).disabled).toBe(false);
    revert().click();
    http.expectNone(request => request.method === 'POST');
    assertNoRestore();
  });

  it('disables a superseded entry and says why, without posting', async () => {
    await create([entry({ superseded: true }), entry({ id: 902 })]);
    expect(revert().disabled).toBe(true);
    expect(sections()[0].textContent).toContain('Superseded by a later change');
    expect(sections()[1].textContent).not.toContain('Superseded by a later change');
    expect(revert(1).disabled).toBe(false);
    revert().click();
    http.expectNone(request => request.method === 'POST');
  });

  it('links the superseded note to the disabled Restore button, with a unique id per entry', async () => {
    await create([entry({ superseded: true }), entry({ id: 902, superseded: true }), entry({ id: 903 })]);
    const notes = [...root.querySelectorAll<HTMLElement>('[data-history-superseded]')];
    expect(notes).toHaveLength(2);
    expect(new Set(notes.map(note => note.id)).size).toBe(2);
    expect(revert(0).getAttribute('aria-describedby')).toBe(notes[0].id);
    expect(revert(1).getAttribute('aria-describedby')).toBe(notes[1].id);
    expect(revert(2).hasAttribute('aria-describedby')).toBe(false);
  });

  it('picks the singular or plural restore preview by the number of photos', async () => {
    const two = [{ path: '/a.jpg', before: [null, 2, 0], after: [3, 4, 1], revision: 5 }, { path: '/b.jpg', before: [null, 2, 0], after: [3, 4, 1], revision: 5 }];
    await create([entry({ id: 902, changes: two }), entry()]);
    revert(0).click(); await settle();
    expect(root.querySelector('[data-history-preview]')?.textContent).toContain('Restore 2 photos');
    revert(1).click(); await settle();
    expect(root.querySelector('[data-history-preview]')?.textContent).toContain('Restore 1 photo');
    expect(root.querySelector('[data-history-preview]')?.textContent).not.toContain('Restore 1 photos');
  });

  it('shows the review decision only when it changed', async () => {
    const same = { path: '/same.jpg', before: [0, 0, 0, 0], after: [4, 1, 0, 0], revision: 5 };
    const flipped = { path: '/flip.jpg', before: [0, 0, 0, 0], after: [0, 0, 1, 0], revision: 5 };
    await create([entry({ id: 910, kind: 'review', changes: [same, flipped] })]);
    const details = root.querySelectorAll('details')[1] as HTMLDetailsElement;
    details.open = true; details.dispatchEvent(new Event('toggle')); await settle();
    const lines = [...root.querySelectorAll('p')].filter(p => p.textContent?.includes('Review:'));
    expect(lines).toHaveLength(1);
  });

  for (const [status, message] of [[404, messages.unavailable], [409, messages.conflict], [500, messages.error]] as const) {
    it(`renders the ${status} refusal without announcing a restore or refreshing the gallery`, async () => {
      await create();
      await applyRestore();
      expect(revert().disabled).toBe(true);
      const request = http.expectOne('/api/organization_history/901/revert');
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual({});
      request.flush({}, { status, statusText: 'Refused' });
      await settle();
      expect(root.querySelector('[role="alert"]')?.textContent).toContain(message);
      expect(revert().disabled).toBe(false);
      assertNoRestore();
      http.expectNone('/api/organization_history');
    });
  }

  it('retries a failed restore, refreshes once, and reloads the inverse and reverted entries', async () => {
    await create();
    await applyRestore();
    http.expectOne('/api/organization_history/901/revert').flush({}, { status: 500, statusText: 'Refused' });
    await settle();
    assertNoRestore();
    await applyRestore();
    http.expectOne('/api/organization_history/901/revert').flush({ changed: 1 });
    await settle();
    expect(store.refreshPaths.mock.calls).toEqual([[null]]);
    expect(sections()).toHaveLength(0);
    expect(root.textContent).toContain('Loading...');
    http.expectOne('/api/organization_history').flush({ entries: [entry({ id: 903 }), entry({ reverted: true })] });
    await settle();
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(root.querySelector('[role="status"]')?.textContent).toContain('Photos restored: 1');
    expect(fixture.componentInstance.wasRestored()).toBe(true);
    expect(revert().disabled).toBe(false);
    expect(revert(1).disabled).toBe(true);
    expect(revert(1).textContent).toContain('Already reverted');
    expect(dialog.close).not.toHaveBeenCalled();
  });
});
