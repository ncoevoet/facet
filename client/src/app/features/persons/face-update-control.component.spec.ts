import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { provideRouter, Router, NavigationStart, NavigationCancel, NavigationCancellationCode, NavigationEnd } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ScanService } from '../../core/services/scan.service';
import { I18nService } from '../../core/services/i18n.service';
import { FaceUpdateControlComponent } from './face-update-control.component';

@Component({ template: '' }) class OtherPage {}
const preview = { eligible_photos: 12, model: 'arcface_buffalo_l', mode: 'missing', automatic_faces: 0, assigned_faces: 0, manual_faces: 0, pending_person_matches: 0 };
const receipt = { job_id: 'a'.repeat(32), model: preview.model, mode: 'missing', refreshed_faces: 0, removed_faces: 0, refused: 0, repaired_people: 0, state: 'running', stop_requested: false,
  total: 12, processed: 3, added_faces: 4, empty: 1, skipped: 0, failed: 0, error_code: null,
  created_at: '2026-11-01 20:00:00', started_at: '2026-11-01 20:00:01', finished_at: null, controlled_by_worker: false };

describe('FaceUpdateControlComponent', () => {
  async function render() {
    const api: { get: Mock; post: Mock } = {
      get: vi.fn((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [] : receipt)),
      post: vi.fn((_url: string, body: { job_id: string }) => of({ ...receipt, job_id: body.job_id })),
    };
    const auth = { identity: signal('alice'), status: signal({ user_id: 'alice' }), isEdition: signal(true), token: 'token-a' };
    const scan = { canLaunch: signal(true) };
    TestBed.configureTestingModule({ imports: [FaceUpdateControlComponent], providers: [
      provideRouter([{ path: 'persons', component: OtherPage }, { path: 'elsewhere', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth }, { provide: ScanService, useValue: scan },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    await TestBed.inject(Router).navigateByUrl('/persons?tab=matches');
    const fixture = TestBed.createComponent(FaceUpdateControlComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement; document.body.appendChild(root);
    const settle = async () => { await fixture.whenStable(); fixture.detectChanges(); };
    const open = async () => { root.querySelector<HTMLButtonElement>('[data-update-faces]')!.click(); await settle(); };
    const dispose = () => { fixture.destroy(); root.remove(); };
    return { fixture, root, api, auth, scan, open, settle, dispose };
  }

  it('opens a read-only scope preview and starts exactly the confirmed request without automatic match review', async () => {
    const { fixture, root, api, open, settle, dispose } = await render();
    const review = vi.fn(); fixture.componentInstance.reviewRequested.subscribe(review);
    expect(api.get).not.toHaveBeenCalled(); expect(root.querySelector('section')).toBeNull();
    await open();
    expect(root.textContent).toContain('"count":12'); expect(api.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith('/scan/faces/start', { job_id: expect.stringMatching(/^[a-f0-9]{32}$/), expected_model: preview.model, mode: 'missing', confirm: true });
    expect(root.querySelector('[data-face-update-receipt]')?.textContent).toContain('"processed":3,"total":12');
    expect(root.textContent).toContain('persons.face_update.recorded_only'); expect(review).not.toHaveBeenCalled();
    api.get.mockReturnValueOnce(of({ ...receipt, job_id: api.post.mock.calls[0][1].job_id, state: 'completed', processed: 12 }));
    root.querySelector<HTMLButtonElement>('[data-read-face-status]')!.click(); await settle();
    expect(review).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-review-updated-faces]')!.click(); expect(review).toHaveBeenCalledOnce();
    dispose();
  });

  it('keeps superseded and older navigation completions blocked until the owning navigation settles', async () => {
    const { root, api, open, settle, dispose } = await render();
    const events = TestBed.inject(Router).events as Subject<unknown>;
    events.next(new NavigationStart(100, '/elsewhere'));
    events.next(new NavigationCancel(100, '/elsewhere', 'superseded', NavigationCancellationCode.SupersededByNewNavigation));
    await open(); expect(api.get).not.toHaveBeenCalled();
    events.next(new NavigationStart(101, '/persons'));
    events.next(new NavigationEnd(100, '/persons', '/persons'));
    await open(); expect(api.get).not.toHaveBeenCalled();
    events.next(new NavigationEnd(101, '/persons', '/persons'));
    await settle(); await open(); await settle();
    expect(api.get).toHaveBeenCalled(); expect(root.querySelector('section')).not.toBeNull();
    dispose();
  });

  it('shows a running job instead of a new start preview when reopened', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open();
    root.querySelector('section')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [receipt] : receipt));
    await open();
    expect(root.querySelector('[data-face-update-receipt]')?.textContent).toContain('"processed":3,"total":12');
    expect(root.querySelector('[data-start-faces]')).toBeNull(); expect(api.post).not.toHaveBeenCalled();
    dispose();
  });

  it('recovers an uncertain start by retrying exactly the same request identity', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open(); api.post.mockReturnValueOnce(throwError(() => new Error('response lost')));
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(root.textContent).toContain('persons.face_update.start_unknown'); expect(api.post).toHaveBeenCalledTimes(1);
    expect(root.querySelector('[data-start-faces]')).toBeNull();
    const body = api.post.mock.calls[0][1];
    root.querySelector<HTMLButtonElement>('[data-retry-face-start]')!.click(); await settle();
    expect(api.post).toHaveBeenNthCalledWith(2, '/scan/faces/start', body);
    expect(root.querySelector('[data-retry-face-start]')).toBeNull(); dispose();
  });

  it('does not publish a late start or resume its controls after navigation', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open(); const pending = new Subject(); api.post.mockReturnValueOnce(pending);
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click();
    const id = api.post.mock.calls[0][1].job_id;
    await TestBed.inject(Router).navigateByUrl('/elsewhere');
    pending.next({ ...receipt, job_id: id }); pending.complete(); await settle();
    expect(root.querySelector('section')).toBeNull(); expect(api.post).toHaveBeenCalledTimes(1);
    expect(root.querySelector<HTMLButtonElement>('[data-update-faces]')?.disabled).toBe(true); dispose();
  });

  it('confirms Stop for the selected job and reads back uncertainty before another stop', async () => {
    const { root, api, open, settle, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [receipt] : receipt));
    await open(); root.querySelector<HTMLDetailsElement>('details')!.open = true;
    root.querySelector<HTMLButtonElement>('details button')!.click(); await settle();
    root.querySelector<HTMLButtonElement>('[data-stop-faces]')!.click(); await settle();
    expect(api.post).not.toHaveBeenCalled();
    api.post.mockReturnValueOnce(throwError(() => new Error('stop response lost')));
    root.querySelector<HTMLButtonElement>('[data-confirm-stop-faces]')!.click(); await settle();
    expect(api.post).toHaveBeenCalledWith(`/scan/faces/jobs/${receipt.job_id}/cancel`, { job_id: receipt.job_id, confirm: true });
    expect(root.textContent).toContain('persons.face_update.stop_unknown');
    expect(root.querySelector<HTMLButtonElement>('[data-stop-faces]')?.disabled).toBe(true);
    api.get.mockReturnValueOnce(of({ ...receipt, stop_requested: true }));
    root.querySelector<HTMLButtonElement>('[data-read-face-status]')!.click(); await settle();
    expect(root.textContent).toContain('persons.face_update.stop_requested'); expect(root.querySelector('[data-stop-faces]')).toBeNull(); dispose();
  });

  it('refuses a captured Stop when the token rotates before confirmation', async () => {
    const { root, api, auth, open, settle, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [receipt] : receipt));
    await open(); root.querySelector<HTMLDetailsElement>('details')!.open = true;
    root.querySelector<HTMLButtonElement>('details button')!.click(); await settle();
    root.querySelector<HTMLButtonElement>('[data-stop-faces]')!.click(); await settle();
    auth.token = 'rotated'; root.querySelector<HTMLButtonElement>('[data-confirm-stop-faces]')!.click(); await settle();
    expect(api.post).not.toHaveBeenCalled(); dispose();
  });

  it('closes with Escape and returns focus to the actual Material button element', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open();
    root.querySelector('section')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle(); expect(root.querySelector('section')).toBeNull();
    expect(document.activeElement).toBe(root.querySelector('[data-update-faces]')); expect(api.post).not.toHaveBeenCalled(); dispose();
  });

  it('exposes a new scope after a known first-request refusal instead of leaving recovery stuck', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open(); api.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 409 })));
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(root.textContent).toContain('persons.face_update.start_refused');
    expect(root.querySelector('[data-retry-face-start]')).toBeNull();
    expect(root.querySelector<HTMLButtonElement>('[data-face-update-overview]')?.disabled).toBe(false); dispose();
  });


  it('cancels stop preview with Escape and returns focus without writing', async () => {
    const { root, api, open, settle, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [receipt] : receipt));
    await open(); root.querySelector<HTMLDetailsElement>('details')!.open = true;
    root.querySelector<HTMLButtonElement>('details button')!.click(); await settle();
    root.querySelector<HTMLButtonElement>('[data-stop-faces]')!.click(); await settle();
    root.querySelector('section')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle(); expect(root.querySelector('[data-stop-faces-preview]')).toBeNull();
    expect(root.querySelector('section')).not.toBeNull(); expect(document.activeElement).toBe(root.querySelector('[data-stop-faces]'));
    expect(api.post).not.toHaveBeenCalled(); dispose();
  });

  it('cleans the owned polling timer and refuses its stale callback after reopening', async () => {
    const { fixture, root, api, open, settle, dispose } = await render();
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const clears = vi.spyOn(globalThis, 'clearTimeout');
    await open(); api.post.mockImplementationOnce((_url, body) => of({ ...receipt, job_id: body.job_id, controlled_by_worker: true }));
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click();
    // Do not wait for Zone stability while the deliberately live poll timer is owned.
    await Promise.resolve(); fixture.detectChanges();
    const index = timers.mock.calls.findIndex(call => call[1] === 2000);
    expect(index).toBeGreaterThanOrEqual(0);
    const callback = timers.mock.calls[index][0] as () => void;
    const handle = timers.mock.results[index].value;
    root.querySelector('section')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle(); expect(clears).toHaveBeenCalledWith(handle);
    await open(); const reads = api.get.mock.calls.length;
    callback(); await settle(); expect(api.get).toHaveBeenCalledTimes(reads);
    dispose(); timers.mockRestore(); clears.mockRestore();
  });


  it('opens and starts on an HTTP LAN Crypto surface without randomUUID', async () => {
    const realCrypto = globalThis.crypto;
    vi.stubGlobal('crypto', { getRandomValues: (values: Uint8Array<ArrayBuffer>) => realCrypto.getRandomValues(values) });
    try {
      const { root, api, open, settle, dispose } = await render();
      await open(); expect(root.querySelector('[data-start-faces]')).not.toBeNull();
      root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
      expect(api.post).toHaveBeenCalledWith('/scan/faces/start', expect.objectContaining({ job_id: expect.stringMatching(/^[a-f0-9]{32}$/) }));
      dispose();
    } finally { vi.unstubAllGlobals(); }
  });


  it('shows refreshed removed and refused counts for an explicitly selected re-detection receipt', async () => {
    const { root, api, open, settle, dispose } = await render();
    const redetect = { ...receipt, mode: 'redetect', state: 'partial', refreshed_faces: 2, removed_faces: 1, refused: 3 };
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [redetect] : redetect));
    await open(); root.querySelector<HTMLDetailsElement>('details')!.open = true;
    root.querySelector<HTMLButtonElement>('details button')!.click(); await settle();
    expect(root.querySelector('[data-face-update-receipt]')?.textContent).toContain('persons.face_update.redetect_receipt');
    expect(root.querySelector('[data-face-update-receipt]')?.textContent).toContain('"refreshed":2,"removed":1,"refused":3');
    expect(api.post).not.toHaveBeenCalled(); dispose();
  });


  it('starts a distinct repair-only request when there are pending matches but no detection targets', async () => {
    const { root, api, open, settle, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? { ...preview, eligible_photos: 0, pending_person_matches: 2 } : []));
    await open();
    expect(root.querySelector<HTMLButtonElement>('[data-start-faces]')?.disabled).toBe(false);
    expect(root.querySelector('[data-start-faces]')?.textContent).toContain('persons.face_update.repair_matches');
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(api.post).toHaveBeenCalledWith('/scan/faces/start', expect.objectContaining({ mode: 'repair', confirm: true }));
    dispose();
  });


  it('requires a mode-specific re-detection preview before its separately named Start action', async () => {
    const { root, api, open, settle, dispose } = await render();
    await open();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? { ...preview, mode: 'redetect', eligible_photos: 3, automatic_faces: 6, assigned_faces: 4, manual_faces: 1 } : []));
    root.querySelector<HTMLButtonElement>('[data-redetect-faces]')!.click(); await settle();
    expect(api.get).toHaveBeenCalledWith('/scan/faces/preview', { mode: 'redetect' });
    expect(root.textContent).toContain('"automatic":6,"assigned":4,"manual":1');
    expect(root.querySelector('[data-start-faces]')?.textContent).toContain('persons.face_update.redetect_start');
    expect(api.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(api.post).toHaveBeenCalledWith('/scan/faces/start', expect.objectContaining({ mode: 'redetect', confirm: true }));
    dispose();
  });

  it('reads bounded problem receipts and opens source photos separately without writes', async () => {
    const { root, api, open, settle, dispose } = await render();
    const partial = { ...receipt, mode: 'redetect', state: 'partial', refused: 2 };
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [partial] : partial));
    await open(); root.querySelector<HTMLDetailsElement>('details')!.open = true;
    root.querySelector<HTMLButtonElement>('details button')!.click(); await settle();
    api.get.mockReturnValueOnce(of({ items: [{ path: '/one.jpg', state: 'refused', error_code: 'faces_changed' }], total: 2, next_after: '/one.jpg' }));
    root.querySelector<HTMLButtonElement>('[data-read-face-problems]')!.click(); await settle();
    expect(api.get).toHaveBeenLastCalledWith(`/scan/faces/jobs/${receipt.job_id}/items`, { limit: 48 });
    expect(root.textContent).toContain('persons.face_update.problem_changed');
    const source = root.querySelector<HTMLAnchorElement>('a');
    expect(source?.getAttribute('target')).toBe('_blank'); expect(source?.getAttribute('href')).toContain('path=%2Fone.jpg');
    api.get.mockReturnValueOnce(of({ items: [{ path: '/two.jpg', state: 'refused', error_code: 'confirmed_face_not_matched' }], total: 2, next_after: null }));
    root.querySelector<HTMLButtonElement>('[data-more-face-problems]')!.click(); await settle();
    expect(root.querySelectorAll('a')).toHaveLength(2); expect(root.textContent).toContain('persons.face_update.problem_unmatched');
    expect(api.post).not.toHaveBeenCalled(); dispose();
  });

  it('clears private panel state when processing permission is lost', async () => {
    const { root, scan, open, settle, dispose } = await render();
    await open(); scan.canLaunch.set(false); await settle();
    expect(root.querySelector('section')).toBeNull(); expect(root.querySelector('[data-update-faces]')).toBeNull(); dispose();
  });

  it('rejects a preview for a different processing mode', async () => {
    const { root, api, open, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? { ...preview, mode: 'redetect' } : []));
    await open(); expect(root.querySelector('[data-start-faces]')).toBeNull();
    expect(root.textContent).toContain('persons.face_update.read_error');
    expect(api.post).not.toHaveBeenCalled(); dispose();
  });

  it('keeps the original request recoverable when Start returns another receipt', async () => {
    const { root, api, open, settle, dispose } = await render(); await open();
    api.post.mockReturnValueOnce(of({ ...receipt, job_id: 'wrong-receipt' }));
    root.querySelector<HTMLButtonElement>('[data-start-faces]')!.click(); await settle();
    expect(root.querySelector('[data-face-update-receipt]')).toBeNull();
    expect(root.querySelector('[data-retry-face-start]')).not.toBeNull();
    const request = api.post.mock.calls[0][1];
    root.querySelector<HTMLButtonElement>('[data-retry-face-start]')!.click(); await settle();
    expect(api.post).toHaveBeenLastCalledWith('/scan/faces/start', request); dispose();
  });

  it('refuses another job from status and Stop responses without replacing the selected receipt', async () => {
    const { root, api, open, settle, dispose } = await render();
    api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [receipt] : receipt));
    await open();
    api.get.mockReturnValueOnce(of({ ...receipt, job_id: 'wrong', processed: 999 }));
    root.querySelector<HTMLButtonElement>('[data-read-face-status]')!.click(); await settle();
    expect(root.textContent).not.toContain('"processed":999');
    root.querySelector<HTMLButtonElement>('[data-stop-faces]')!.click(); await settle();
    api.post.mockReturnValueOnce(of({ ...receipt, job_id: 'wrong', processed: 999 }));
    root.querySelector<HTMLButtonElement>('[data-confirm-stop-faces]')!.click(); await settle();
    expect(api.post).toHaveBeenCalledWith(`/scan/faces/jobs/${receipt.job_id}/cancel`, { job_id: receipt.job_id, confirm: true });
    expect(root.textContent).toContain('persons.face_update.stop_unknown');
    expect(root.textContent).not.toContain('"processed":999'); dispose();
  });

  it('polls a live worker receipt and stops scheduling after completion', async () => {
    const { root, api, open, settle, dispose } = await render();
    const realTimeout = globalThis.setTimeout;
    let poll: (() => void) | null = null;
    const timer = vi.spyOn(globalThis, 'setTimeout').mockImplementation((callback, delay, ...args) => {
      if (delay === 2000) { poll = callback as () => void; return 0 as unknown as ReturnType<typeof setTimeout>; }
      return realTimeout(callback, delay, ...args);
    });
    try {
      api.get.mockImplementation((url: string) => of(url.endsWith('/preview') ? preview : url.endsWith('/jobs') ? [{ ...receipt, controlled_by_worker: true }] : receipt));
      await open(); expect(poll).toBeTypeOf('function');
      api.get.mockReturnValueOnce(of({ ...receipt, state: 'completed', processed: 12, controlled_by_worker: true }));
      const callback = poll!; poll = null; callback(); await settle();
      expect(api.get).toHaveBeenLastCalledWith(`/scan/faces/jobs/${receipt.job_id}`);
      expect(root.querySelector('[data-face-update-receipt]')?.textContent).toContain('"processed":12,"total":12');
      expect(poll).toBeNull();
    } finally { dispose(); timer.mockRestore(); }
  });
});
