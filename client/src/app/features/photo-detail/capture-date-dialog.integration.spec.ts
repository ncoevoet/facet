import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService, AuthStatus } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { CaptureDateDialogComponent, CaptureDateDialogData, PREVIEW_DEBOUNCE_MS } from './capture-date-dialog.component';

const translations = { capture_date: { title: 'Correct capture date',
  invalid: 'Choose a nonzero shift of at most 366 days; select at most 1000 photos.',
  counts: '{changed} changed · {skipped} skipped', photo: 'Photo', before: 'Before', after: 'After',
  error: 'Could not complete the action.', preview: 'Preview', apply: 'Apply correction ({count})', use_file: 'Use file date',
  mode_shift: 'Shift by', mode_exact: 'Set exact time', mode: 'Correction mode', direction: 'Direction', earlier: 'Earlier', later: 'Later',
  days: 'Days', hours: 'Hours', minutes: 'Minutes', seconds: 'Seconds', unit_d: 'd', unit_h: 'h', unit_min: 'min', unit_s: 's',
  quick: 'Quick adjust', summary_earlier: '{amount} earlier', summary_later: '{amount} later',
  exact_label: 'Correct date and time of the reference photo', reference: 'Reference photo:',
  exact_label_set: 'Capture date and time', invalid_set: 'Enter a valid date and time.', summary_set: 'Set to {amount}' },
  gallery: { no_capture_date: 'No capture date' },
  ui: { buttons: { cancel: 'Cancel' } } };
const preview = { changed: 1, skipped: 2, samples: [
  { path: '/photo.jpg', old_date: '2024:01:01 00:00:00', new_date: '2023:12:31 23:58:30' },
], preview_token: 'first-token' };

describe('Capture-date dialog rendered controls and HTTP', () => {
  let fixture: ComponentFixture<CaptureDateDialogComponent>;
  let http: HttpTestingController;
  let root: HTMLElement;
  let closed: Subject<void>;
  let dialog: { close: ReturnType<typeof vi.fn>; disableClose: boolean; beforeClosed: () => Subject<void> };
  let store: { refreshPaths: ReturnType<typeof vi.fn>; patchPhoto: ReturnType<typeof vi.fn> };
  const PREVIEW_URL = '/api/photos/capture_date/preview';
  const single: CaptureDateDialogData = { paths: ['/photo.jpg'], count: 1, manuallySet: true, reference: { path: '/photo.jpg', date: '2024:01:01 00:00:00' } };

  async function create(data: CaptureDateDialogData = single) {
    TestBed.resetTestingModule();
    closed = new Subject<void>();
    dialog = { close: vi.fn(), disableClose: false, beforeClosed: () => closed };
    store = { refreshPaths: vi.fn(), patchPhoto: vi.fn() };
    TestBed.configureTestingModule({ imports: [CaptureDateDialogComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), provideRouter([]),
      { provide: MAT_DIALOG_DATA, useValue: data }, { provide: MatDialogRef, useValue: dialog },
      { provide: GalleryStore, useValue: store },
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
    fixture = TestBed.createComponent(CaptureDateDialogComponent);
    root = fixture.nativeElement;
    fixture.detectChanges();
    await fixture.whenStable();
  }

  function button(label: string): HTMLButtonElement {
    const found = [...root.querySelectorAll('button')].find(item => item.textContent?.trim() === label);
    expect(found, label).toBeDefined();
    return found!;
  }
  function applyButton(): HTMLButtonElement {
    return [...root.querySelectorAll('button')].find(item => item.textContent?.trim().startsWith('Apply correction'))!;
  }
  function unit(name: string): HTMLInputElement { return root.querySelector(`input[data-unit="${name}"]`)!; }
  async function type(input: HTMLInputElement, value: string) {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
  }
  /** Renders and lets ngModel write its values, staying well inside the preview debounce so
   *  consecutive edits coalesce into one request the way a user's quick typing does. */
  async function settle() { fixture.detectChanges(); await new Promise(resolve => setTimeout(resolve)); fixture.detectChanges(); }
  /** The debounced auto-preview: waits for its request rather than clicking anything. */
  async function nextPreview() { return vi.waitFor(() => http.expectOne(PREVIEW_URL)); }
  async function flushPreview(body: object = preview) { const request = await nextPreview(); request.flush(body); await settle(); return request; }
  /** Proves no preview request goes out, waiting past the debounce. */
  async function noPreview() { await new Promise(resolve => setTimeout(resolve, PREVIEW_DEBOUNCE_MS + 100)); http.expectNone(PREVIEW_URL); }
  afterEach(() => { try { http?.verify(); } finally { TestBed.resetTestingModule(); } });

  it('previews the default one-hour shift on open, with no Preview button to click', async () => {
    await create();
    expect(unit('hours').value).toBe('1');
    expect(root.querySelector('[data-direction="later"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('[data-summary]')?.textContent?.trim()).toBe('1 h later');
    expect(root.querySelector('[data-reference]')?.textContent).toContain('2024:01:01 00:00:00 → 2024:01:01 01:00:00');
    expect([...root.querySelectorAll('button')].some(item => item.textContent?.trim() === 'Preview')).toBe(false);
    const request = await flushPreview();
    expect(request.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], offset_seconds: 3600 });
    expect(applyButton().textContent?.trim()).toBe('Apply correction (1)');
  });

  it.each([
    ['empty hours', 'hours', ''], ['fractional hours', 'hours', '0.5'], ['negative hours', 'hours', '-1'],
    ['all zero', 'hours', '0'], ['beyond 366 days', 'days', '367'],
  ])('associates %s with its rendered explanation and sends nothing', async (_, name, value) => {
    await create(); await flushPreview();
    await type(unit(name), value);
    for (const field of ['days', 'hours', 'minutes', 'seconds']) {
      expect(unit(field).getAttribute('aria-invalid')).toBe('true');
      expect(unit(field).getAttribute('aria-describedby')).toBe('capture-date-offset-error');
    }
    const error = root.querySelector('#capture-date-offset-error');
    expect(error?.getAttribute('role')).toBe('alert');
    expect(error?.textContent).toContain(translations.capture_date.invalid);
    expect(root.querySelector('table')).toBeNull();
    expect(applyButton().disabled).toBe(true);
    await noPreview();
  });

  it.each([['later', 31622400], ['earlier', -31622400]])('sends the inclusive 366-day boundary %s as %i seconds', async (direction, expected) => {
    await create(); await flushPreview();
    await type(unit('hours'), '0'); await type(unit('days'), '366');
    (root.querySelector(`[data-direction="${direction}"]`) as HTMLButtonElement).click(); await settle();
    const request = await flushPreview({ ...preview, changed: 0, samples: [] });
    expect(request.request.body.offset_seconds).toBe(expected);
    expect(applyButton().disabled).toBe(true);
  });

  it('combines direction and unit fields into one debounced request and renders the samples', async () => {
    await create(); await flushPreview();
    await type(unit('hours'), '0'); await type(unit('minutes'), '1'); await type(unit('seconds'), '30');
    (root.querySelector('[data-direction="earlier"]') as HTMLButtonElement).click(); await settle();
    expect(root.querySelector('[data-summary]')?.textContent?.trim()).toBe('1 min 30 s earlier');
    expect(root.querySelector('[data-reference]')?.textContent).toContain('→ 2023:12:31 23:58:30');
    const request = await flushPreview();
    expect(request.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], offset_seconds: -90 });
    expect(root.querySelector('[role="status"]')?.textContent).toContain('1 changed · 2 skipped');
    const headers = [...root.querySelectorAll('thead th')];
    expect(headers.map(item => item.textContent?.trim())).toEqual(['Photo', 'Before', 'After']);
    expect(headers.map(item => item.getAttribute('scope'))).toEqual(['col', 'col', 'col']);
    expect([...root.querySelectorAll('tbody td')].map(item => item.textContent?.trim())).toEqual([
      '/photo.jpg', '2024:01:01 00:00:00', '2023:12:31 23:58:30',
    ]);
    expect(applyButton().disabled).toBe(false);
    await type(unit('seconds'), '0');
    expect(root.querySelector('table')).toBeNull();
    expect(applyButton().disabled).toBe(true);
    await flushPreview();
  });

  it('aborts a preview still in flight when the shift changes', async () => {
    await create();
    const first = await nextPreview();
    await type(unit('hours'), '2');
    expect(first.cancelled).toBe(true);
    expect((await flushPreview()).request.body.offset_seconds).toBe(7200);
  });

  it('quick buttons add to the current shift and can cross into the other direction', async () => {
    await create(); await flushPreview();
    (root.querySelector('[data-quick="3600"]') as HTMLButtonElement).click(); await settle();
    expect(unit('hours').value).toBe('2');
    (root.querySelector('[data-quick="-86400"]') as HTMLButtonElement).click(); await settle();
    expect(root.querySelector('[data-direction="earlier"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(unit('hours').value).toBe('22');
    expect((await flushPreview()).request.body.offset_seconds).toBe(-79200);
  });

  it('derives the shift from an exact time for the reference photo and carries it back', async () => {
    await create(); await flushPreview();
    (root.querySelector('[data-mode="exact"]') as HTMLButtonElement).click(); await settle();
    const exact = root.querySelector('input[data-exact]') as HTMLInputElement;
    expect(exact.value).toBe('2024-01-01T01:00');
    await flushPreview();
    await type(exact, '2023-12-31T22:30:15');
    expect(root.querySelector('[data-summary]')?.textContent?.trim()).toBe('1 h 29 min 45 s earlier');
    expect((await flushPreview()).request.body.offset_seconds).toBe(-5385);
    (root.querySelector('[data-mode="shift"]') as HTMLButtonElement).click(); await settle();
    expect([unit('days').value, unit('hours').value, unit('minutes').value, unit('seconds').value]).toEqual(['0', '1', '29', '45']);
    expect(root.querySelector('[data-direction="earlier"]')?.getAttribute('aria-pressed')).toBe('true');
    await flushPreview();
  });

  it.each([
    ['the reference time itself', '2024-01-01T00:00'], ['a cleared field', ''], ['a time 367 days away', '2025-01-02T00:00'],
  ])('rejects %s in exact mode with its explanation and sends nothing', async (_, value) => {
    await create(); await flushPreview();
    (root.querySelector('[data-mode="exact"]') as HTMLButtonElement).click(); await settle();
    await flushPreview();
    const exact = root.querySelector('input[data-exact]') as HTMLInputElement;
    await type(exact, value);
    expect(exact.getAttribute('aria-invalid')).toBe('true');
    expect(exact.getAttribute('aria-describedby')).toBe('capture-date-offset-error');
    expect(root.querySelector('#capture-date-offset-error')?.textContent).toContain(translations.capture_date.invalid);
    expect(root.querySelector('[data-reference]')?.textContent).toContain('→ —');
    expect(applyButton().disabled).toBe(true);
    await noPreview();
  });

  it('clamps a quick adjustment at the 366-day limit', async () => {
    await create(); await flushPreview();
    await type(unit('hours'), '0'); await type(unit('days'), '366');
    (root.querySelector('[data-quick="86400"]') as HTMLButtonElement).click(); await settle();
    expect([unit('days').value, unit('hours').value]).toEqual(['366', '0']);
    expect((await flushPreview({ ...preview, changed: 0, samples: [] })).request.body.offset_seconds).toBe(31622400);
  });

  it('offers an absolute exact-time mode without a dated reference photo, opening in Shift for several photos', async () => {
    await create({ paths: ['/a.jpg', '/b.jpg'], count: 2, reference: null }); await flushPreview();
    expect(root.querySelector('[data-mode="shift"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('[data-reference]')).toBeNull();
    (root.querySelector('[data-mode="exact"]') as HTMLButtonElement).click(); await settle();
    expect(root.querySelector('label')?.textContent).toContain('Capture date and time');
    await type(root.querySelector('input[data-exact]') as HTMLInputElement, '2024-05-06T07:08:09');
    expect((await flushPreview()).request.body).toEqual({ photo_paths: ['/a.jpg', '/b.jpg'], exclude: [], set_date: '2024-05-06T07:08:09' });
  });

  it('opens one undated photo in Exact, sends set_date and labels the missing old date', async () => {
    await create({ paths: ['/photo.jpg'], count: 1, reference: null });
    expect(root.querySelector('[data-mode="exact"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('#capture-date-offset-error')?.textContent).toContain('Enter a valid date and time.');
    await noPreview();
    await type(root.querySelector('input[data-exact]') as HTMLInputElement, '2024-05-06T07:08:09');
    expect(root.querySelector('[data-summary]')?.textContent?.trim()).toBe('Set to 2024:05:06 07:08:09');
    const request = await flushPreview({ changed: 1, skipped: 0, preview_token: 't',
      samples: [{ path: '/photo.jpg', old_date: null, new_date: '2024:05:06 07:08:09' }] });
    expect(request.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], set_date: '2024-05-06T07:08:09' });
    const cells = [...root.querySelectorAll('tbody td')].map(td => td.textContent?.trim());
    expect(cells).toEqual(['/photo.jpg', 'No capture date', '2024:05:06 07:08:09']);
  });

  it.each([['a space', '2024-01-01 00:00:00'], ['a T', '2024-01-01T00:00:00']])(
    'reads an ISO-stored reference date written with %s, as the server does', async (_, date) => {
      await create({ ...single, reference: { path: '/photo.jpg', date } }); await flushPreview();
      (root.querySelector('[data-mode="exact"]') as HTMLButtonElement).click(); await settle();
      expect((root.querySelector('input[data-exact]') as HTMLInputElement).value).toBe('2024-01-01T01:00');
      await flushPreview();
    });

  it.each([
    ['an impossible day', '2024:04:31 00:00:00'], ['an impossible hour', '2024:01:01 24:00:00'],
    ['trailing text', '2024:01:01 00:00:00+02:00'], ['a date-only value', '2024-01-01'],
  ])('treats a reference date with %s as undated, as the server skips it', async (_, date) => {
    await create({ ...single, reference: { path: '/photo.jpg', date } });
    expect(root.querySelector('[data-mode="exact"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('[data-reference]')).toBeNull();
    await noPreview();
  });

  it('renders preview failure and retries through its Preview button without publishing edits', async () => {
    await create();
    (await nextPreview()).flush({}, { status: 503, statusText: 'Unavailable' }); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(unit('hours').disabled).toBe(false);
    expect(applyButton().disabled).toBe(true);
    button('Preview').click(); fixture.detectChanges();
    await flushPreview();
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(applyButton().disabled).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(dialog.close).not.toHaveBeenCalled();
  });

  it('clears a conflicting preview and requires a new token before the rendered apply can succeed', async () => {
    await create(); await flushPreview();
    await type(unit('hours'), '0'); await type(unit('minutes'), '1'); await type(unit('seconds'), '30');
    (root.querySelector('[data-direction="earlier"]') as HTMLButtonElement).click(); await settle();
    await flushPreview();
    applyButton().click(); fixture.detectChanges();
    expect(dialog.disableClose).toBe(true);
    await vi.waitFor(() => expect(unit('hours').disabled).toBe(true));
    const apply = http.expectOne('/api/photos/capture_date/apply');
    expect(apply.request.body.preview_token).toBe('first-token');
    apply.flush({}, { status: 409, statusText: 'Conflict' }); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(root.querySelector('table')).toBeNull();
    expect(applyButton().disabled).toBe(true); expect(dialog.disableClose).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(store.refreshPaths).not.toHaveBeenCalled();
    await noPreview();
    button('Preview').click();
    await flushPreview({ ...preview, preview_token: 'retry-token' });
    applyButton().click();
    const retry = http.expectOne('/api/photos/capture_date/apply');
    expect(retry.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], offset_seconds: -90, preview_token: 'retry-token' });
    retry.flush({ changed: 1 }); await settle();
    expect(store.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { date_taken: preview.samples[0].new_date, date_manually_set: 1 });
    expect(store.refreshPaths).toHaveBeenCalledWith(null);
    expect(dialog.close).toHaveBeenCalledWith({ date_taken: preview.samples[0].new_date, date_manually_set: 1 });
  });

  it('renders reset failure, restores controls and publishes only the successful reset retry', async () => {
    await create(); await flushPreview();
    button('Use file date').click(); fixture.detectChanges();
    expect(dialog.disableClose).toBe(true);
    await vi.waitFor(() => expect(unit('hours').disabled).toBe(true));
    const reset = http.expectOne('/api/photo/capture_date?path=%2Fphoto.jpg');
    expect(reset.request.method).toBe('DELETE');
    reset.flush({}, { status: 500, statusText: 'Unreadable' }); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(button('Use file date').disabled).toBe(false); expect(dialog.disableClose).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(store.refreshPaths).not.toHaveBeenCalled();
    button('Use file date').click();
    http.expectOne('/api/photo/capture_date?path=%2Fphoto.jpg').flush({ date_taken: null, date_manually_set: 0 }); await settle();
    expect(store.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { date_taken: null, date_manually_set: 0 });
    expect(dialog.close).toHaveBeenCalledWith({ date_taken: null, date_manually_set: 0 });
  });

  it('never previews an oversized selection and hides reset when unavailable', async () => {
    await create({ paths: [], count: 1001, filters: { review_status: 'kept' }, manuallySet: false });
    expect([...root.querySelectorAll('button')].some(item => item.textContent?.trim() === 'Use file date')).toBe(false);
    expect(unit('hours').getAttribute('aria-invalid')).toBe('true');
    expect(applyButton().disabled).toBe(true);
    await noPreview();
  });
});
