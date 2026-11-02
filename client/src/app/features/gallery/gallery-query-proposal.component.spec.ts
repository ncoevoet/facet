import { computed, signal } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { GalleryQueryProposalComponent } from './gallery-query-proposal.component';
import { GalleryStore, DEFAULT_FILTERS } from './gallery.store';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ViewActionRegistry } from '../../core/agent/view-action-registry.service';

describe('User-owned query proposal', () => {
  let fixture: ComponentFixture<GalleryQueryProposalComponent>;
  let actions: ViewActionRegistry;
  let events: Subject<NavigationStart>;
  let filters: ReturnType<typeof signal<typeof DEFAULT_FILTERS>>;
  let selected: ReturnType<typeof signal<Set<string>>>;
  let wholeView: ReturnType<typeof signal<boolean>>;
  let apply: ReturnType<typeof vi.fn>;
  let token: string;
  let owner: ReturnType<typeof signal<{ name: string }>>;

  function build(): void {
    token = 'initial'; owner = signal({ name: 'alice' }); events = new Subject();
    filters = signal({ ...DEFAULT_FILTERS, camera: 'Canon' }); selected = signal(new Set(['/a.jpg'])); wholeView = signal(false);
    apply = vi.fn(async updates => { filters.update(current => ({ ...current, ...updates, page: 1 })); });
    TestBed.configureTestingModule({ imports: [GalleryQueryProposalComponent], providers: [
      { provide: Router, useValue: { url: '/', events } },
      { provide: AuthService, useValue: { identity: computed(() => owner().name), status: owner, get token() { return token; } } },
      { provide: GalleryStore, useValue: { filters, config: signal({}), currentAlbum: signal(null), pinnedPaths: signal(null), selectedPaths: selected,
        viewScopeSelected: wholeView, filterKey: (value: unknown) => JSON.stringify(value), updateFilters: apply, loadError: signal(false),
        previewFilters: (updates: unknown) => ({ ...filters(), ...updates as object, page: 1 }) } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
    ] });
    fixture = TestBed.createComponent(GalleryQueryProposalComponent); fixture.componentRef.setInput('active', true); fixture.detectChanges();
    actions = TestBed.inject(ViewActionRegistry);
  }
  async function propose(unrepresented: string[] = []): Promise<void> {
    await actions.get('gallery_filter_proposal')!({ patch: { date_from: '2024-03-01', tag: 'Birds' }, replace: false,
      proposal: { source_query: 'birds last spring except videos', unrepresented }, reset: {}, normalize: (patch: unknown) => patch });
    await fixture.whenStable(); fixture.detectChanges();
  }
  afterEach(() => fixture.destroy());

  it('uses shared metric names and units with explicit input-label associations', async () => {
    build();
    await actions.get('gallery_filter_proposal')!({ patch: { min_dynamic_range: 6, max_focal_length: 85, min_face_ratio: 0.2 },
      proposal: { source_query: 'dynamic range and lens', unrepresented: [] }, replace: false,
      reset: {}, normalize: (patch: unknown) => patch });
    await fixture.whenStable(); fixture.detectChanges();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.textContent).toContain('gallery.dynamic_range (EV) ≥');
    expect(page.textContent).toContain('gallery.focal_range (mm) ≤');
    expect(page.textContent).toContain('gallery.proposal.fraction');
    const label = page.querySelector<HTMLLabelElement>('label[for="query-proposal-min_dynamic_range"]')!;
    expect(label.control?.id).toBe('query-proposal-min_dynamic_range');
    expect(apply).not.toHaveBeenCalled();
  });

  it('shows an editable interpretation without changing the gallery and applies a corrected date only on the user action', async () => {
    build(); const before = filters(); await propose();
    expect(apply).not.toHaveBeenCalled(); expect(filters()).toBe(before);
    const page = fixture.nativeElement as HTMLElement;
    expect(page.textContent).toContain('birds last spring except videos');
    const date = page.querySelector<HTMLInputElement>('input[type="date"]')!;
    date.value = '2025-03-01'; date.dispatchEvent(new Event('input')); fixture.detectChanges();
    const newer = new Set(['/new.jpg']); selected.set(newer);
    page.querySelector<HTMLButtonElement>('[data-apply-query-proposal]')!.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(apply).toHaveBeenCalledExactlyOnceWith({ date_from: '2025-03-01', tag: 'Birds' });
    expect(selected()).toBe(newer); expect(page.querySelector('[data-query-proposal]')).toBeNull();
  });

  it('requires acknowledgement for untranslated clauses and refuses retargeting a whole-view selection', async () => {
    build(); await propose(['except videos']);
    const page = fixture.nativeElement as HTMLElement;
    const button = page.querySelector<HTMLButtonElement>('[data-apply-query-proposal]')!;
    expect(button.disabled).toBe(true); expect(page.textContent).toContain('except videos');
    const checkbox = page.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    checkbox.checked = true; checkbox.dispatchEvent(new Event('change')); wholeView.set(true); fixture.detectChanges();
    expect(button.disabled).toBe(true); await fixture.componentInstance.apply(); expect(apply).not.toHaveBeenCalled();
    wholeView.set(false); fixture.detectChanges(); button.click(); await fixture.whenStable();
    expect(apply).toHaveBeenCalledOnce();
  });

  it('refuses a stale query or live token, cancels on navigation and unregisters when parked', async () => {
    build(); await propose();
    filters.update(value => ({ ...value, camera: 'Nikon' })); await fixture.componentInstance.apply();
    expect(apply).not.toHaveBeenCalled();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('gallery.proposal.changed');
    await propose(); token = 'rotated'; await fixture.componentInstance.apply(); expect(apply).not.toHaveBeenCalled();
    await propose(); events.next(new NavigationStart(1, '/persons')); fixture.detectChanges();
    expect(fixture.componentInstance.proposal()).toBeNull();
    await expect(propose()).rejects.toMatchObject({ code: 'no_active_view' });
    fixture.componentRef.setInput('active', false); fixture.detectChanges();
    expect(actions.get('gallery_filter_proposal')).toBeUndefined();
  });
});
