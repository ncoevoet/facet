import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationCancel, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoLogicalAssetComponent } from './photo-logical-asset.component';

describe('PhotoLogicalAssetComponent', () => {
  const context = { asset: null, can_group: true, candidates: [
    { path: '/shot.jpg', name: 'shot.jpg', kind: 'jpeg' }, { path: '/shot.CR2', name: 'shot.CR2', kind: 'raw' },
  ] };
  const members = [
    { path: '/shot.jpg', name: 'shot.jpg', star_rating: 5, is_kept: true, is_rejected: false, is_favorite: false },
    { path: '/shot.CR2', name: 'shot.CR2', star_rating: 2, is_kept: false, is_rejected: true, is_favorite: false },
  ];
  const plan = { preview_token: 'signed-plan', expires_at: 9999999999, operation: 'create', primary_path: '/shot.jpg',
    members, review_conflicts: ['star_rating'], preserves_file_metadata: true };
  let http: HttpTestingController;
  let auth: { status: ReturnType<typeof signal<object | null>>; token: string; isEdition: ReturnType<typeof signal<boolean>> };
  let events: Subject<NavigationStart | NavigationCancel>;
  beforeEach(() => {
    auth = { status: signal<object | null>({ user_id: 'alice' }), token: 'alice-token', isEdition: signal(true) };
    events = new Subject();
    TestBed.configureTestingModule({ imports: [PhotoLogicalAssetComponent], providers: [
      provideHttpClient(), provideHttpClientTesting(),
      { provide: AuthService, useValue: auth }, { provide: Router, useValue: { events } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });
  function render() {
    const fixture = TestBed.createComponent(PhotoLogicalAssetComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/shot.jpg' })); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    // Inline in the open Related files panel: it reads as soon as it renders, so "open" only settles the view.
    return { fixture, root, open: () => fixture.detectChanges() };
  }
  function choose(root: HTMLElement) {
    const checkbox = root.querySelectorAll<HTMLInputElement>('input[type=checkbox]')[1];
    checkbox.click();
    const primary = root.querySelector<HTMLInputElement>('input[type=radio][value="/shot.jpg"]')!;
    primary.click();
  }

  it('reads as soon as it shows and requires an explicit primary, review and conflict acknowledgment before Apply', () => {
    const { fixture, root, open } = render();
    document.body.appendChild(root);
    expect(root.querySelector('details, summary')).toBeNull(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    const review = root.querySelector<HTMLButtonElement>('[data-review-group]')!;
    expect(review.disabled).toBe(true);
    choose(root); fixture.detectChanges(); expect(review.disabled).toBe(false); review.click();
    const request = http.expectOne('/api/logical_assets/preview');
    expect(request.request.body).toEqual({ operation: 'create', paths: ['/shot.jpg', '/shot.CR2'], primary_path: '/shot.jpg' });
    request.flush(plan); fixture.detectChanges();
    const apply = root.querySelector<HTMLButtonElement>('[data-apply-group]')!;
    expect(apply.disabled).toBe(true);
    root.querySelector<HTMLInputElement>('[data-conflict-ack]')!.click(); fixture.detectChanges(); apply.focus(); apply.click();
    const applied = vi.fn(); fixture.componentInstance.applied.subscribe(applied);
    const write = http.expectOne('/api/logical_assets/apply');
    expect(write.request.body).toEqual({ change: request.request.body, preview_token: 'signed-plan', acknowledge_review_conflicts: true });
    write.flush({ asset_id: 'a'.repeat(32), revision: 1, dissolved: false });
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush({ asset: { asset_id: 'a'.repeat(32), revision: 1, primary_path: '/shot.jpg', members }, candidates: [], can_group: false });
    fixture.detectChanges(); expect(root.textContent).toContain('logical_assets.updated');
    expect(document.activeElement).toBe(root.querySelector('[data-logical-asset] h4'));
    root.remove();
    expect(applied).toHaveBeenCalledExactlyOnceWith({ operation: 'create', assetId: 'a'.repeat(32), primaryPath: '/shot.jpg', members: ['/shot.jpg', '/shot.CR2'] });
  });

  it('invalidates a preview when file or primary choices change', () => {
    const { fixture, root, open } = render(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    choose(root); fixture.detectChanges(); root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    http.expectOne('/api/logical_assets/preview').flush(plan); fixture.detectChanges();
    root.querySelector<HTMLInputElement>('input[type=radio][value="/shot.CR2"]')!.click(); fixture.detectChanges();
    expect(root.querySelector('[data-group-preview]')).toBeNull();
    http.expectNone('/api/logical_assets/apply');
  });

  it('cancels obsolete reads and previews on navigation or account changes', () => {
    const { fixture, root, open } = render(); open();
    const old = http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg');
    events.next(new NavigationStart(1, '/other')); fixture.detectChanges(); expect(old.cancelled).toBe(true);
    events.next(new NavigationCancel(1, '/other', 'cancelled')); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    choose(root); fixture.detectChanges(); root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    const preview = http.expectOne('/api/logical_assets/preview');
    auth.status.set({ user_id: 'bob' }); auth.token = 'bob-token'; fixture.detectChanges();
    expect(preview.cancelled).toBe(true); expect(root.querySelector('[data-group-preview]')).toBeNull();
    // Still shown, so it reads the new account's state afresh.
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    expect(root.querySelectorAll('input[type=checkbox]:checked')).toHaveLength(1);
  });

  it('never retries an uncertain Apply; reloads current state for another deliberate review', () => {
    const { fixture, root, open } = render(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    choose(root); fixture.detectChanges(); root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    http.expectOne('/api/logical_assets/preview').flush({ ...plan, review_conflicts: [] }); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-apply-group]')!.click();
    http.expectOne('/api/logical_assets/apply').flush({}, { status: 503, statusText: 'Uncertain' });
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    expect(root.textContent).toContain('logical_assets.apply_error'); expect(root.querySelector('[data-group-preview]')).toBeNull();
    http.expectNone('/api/logical_assets/apply');
  });

  it('reviews a primary change and ungrouping against the current captured revision', () => {
    const { fixture, root, open } = render(); open();
    const asset = { asset_id: 'a'.repeat(32), revision: 7, primary_path: '/shot.jpg', members };
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush({ asset, candidates: [], can_group: false }); fixture.detectChanges();
    root.querySelector<HTMLInputElement>('input[type=radio][value="/shot.CR2"]')!.click(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    const primary = http.expectOne('/api/logical_assets/preview');
    expect(primary.request.body).toEqual({ operation: 'primary', asset_id: asset.asset_id, revision: 7, primary_path: '/shot.CR2' });
    primary.flush({ ...plan, operation: 'primary', primary_path: '/shot.CR2', review_conflicts: [] }); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-review-ungroup]')!.click();
    const dissolve = http.expectOne('/api/logical_assets/preview');
    expect(dissolve.request.body).toEqual({ operation: 'dissolve', asset_id: asset.asset_id, revision: 7 });
    dissolve.flush({ ...plan, operation: 'dissolve', primary_path: null, review_conflicts: [] }); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-apply-group]')!.click();
    const write = http.expectOne('/api/logical_assets/apply');
    expect(write.request.body.change.operation).toBe('dissolve');
    write.flush({ asset_id: asset.asset_id, revision: null, dissolved: true });
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    expect(root.querySelector('[data-group-preview]')).toBeNull();
  });

  it('removes Apply when edition is locked while a preview is displayed', () => {
    const { fixture, root, open } = render(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    choose(root); fixture.detectChanges(); root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    http.expectOne('/api/logical_assets/preview').flush(plan); fixture.detectChanges();
    auth.isEdition.set(false); fixture.detectChanges();
    expect(root.querySelector('[data-apply-group]')).toBeNull();
    expect(root.querySelector<HTMLInputElement>('[data-conflict-ack]')!.disabled).toBe(true);
    http.expectNone('/api/logical_assets/apply');
  });

  it('shows group state to readers without exposing mutation controls', () => {
    auth.isEdition.set(false);
    const { fixture, root, open } = render(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush({ asset: { asset_id: 'a'.repeat(32), revision: 1, primary_path: '/shot.jpg', members }, candidates: [], can_group: false }); fixture.detectChanges();
    expect(root.textContent).toContain('shot.CR2'); expect(root.querySelector('[data-review-group]')).toBeNull();
    expect(root.querySelector('[data-review-ungroup]')).toBeNull();
  });

  it('recovers from a failed context read and a refused preview without writing', () => {
    const { fixture, root, open } = render(); open();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush({}, { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges(); expect(root.textContent).toContain('logical_assets.load_error');
    root.querySelector<HTMLButtonElement>('button')!.click();
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush(context); fixture.detectChanges();
    choose(root); fixture.detectChanges(); root.querySelector<HTMLButtonElement>('[data-review-group]')!.click();
    http.expectOne('/api/logical_assets/preview').flush({}, { status: 409, statusText: 'Changed' });
    fixture.detectChanges(); expect(root.textContent).toContain('logical_assets.review_error');
    expect(root.querySelector('[data-group-preview]')).toBeNull();
    http.expectNone('/api/logical_assets/apply');
  });

  it('requires both RAW and JPEG and caps selection at sixteen files', () => {
    const { fixture, root, open } = render(); open();
    const candidates = [context.candidates[0], ...Array.from({ length: 18 }, (_, index) => ({
      path: `/shot-${index}.CR2`, name: `shot-${index}.CR2`, kind: 'raw',
    }))];
    http.expectOne('/api/logical_assets/by-photo?path=/shot.jpg').flush({ ...context, candidates }); fixture.detectChanges();
    root.querySelector<HTMLInputElement>('input[type=radio]')!.click(); fixture.detectChanges();
    const review = root.querySelector<HTMLButtonElement>('[data-review-group]')!;
    expect(review.disabled).toBe(true);
    for (const checkbox of root.querySelectorAll<HTMLInputElement>('input[type=checkbox]')) { checkbox.click(); fixture.detectChanges(); }
    expect(review.disabled).toBe(false);
    expect(root.querySelectorAll('input[type=checkbox]:checked')).toHaveLength(16);
    expect(root.textContent).toContain('logical_assets.member_limit');
    review.click();
    const request = http.expectOne('/api/logical_assets/preview');
    expect(request.request.body.paths).toHaveLength(16);
    request.flush({ ...plan, review_conflicts: [] });
  });
});
