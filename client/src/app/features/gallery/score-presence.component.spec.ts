import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { ScorePresenceComponent } from './score-presence.component';
import { GalleryStore } from './gallery.store';
import { DEFAULT_FILTERS, GalleryFilters } from './gallery-filters.util';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

@Component({ template: '' })
class EmptyPage {}

describe('rendered measurement policies', () => {
  let fixture: ComponentFixture<ScorePresenceComponent>;
  let router: Router;
  let root: HTMLElement;
  let token: string;
  let resolveNavigation: (allow: boolean | UrlTree) => void;
  const identity = signal('alice');
  const status = signal<unknown>({ user_id: 'alice' });
  const filters = signal<GalleryFilters>({ ...DEFAULT_FILTERS });
  let update: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    resolveNavigation = undefined!;
    token = 'initial'; identity.set('alice'); status.set({ user_id: 'alice' });
    filters.set({ ...DEFAULT_FILTERS });
    update = vi.fn((key: 'score_presence', value: string) => {
      filters.update(current => ({ ...current, [key]: value }));
      return Promise.resolve();
    });
    TestBed.configureTestingModule({ providers: [
      provideRouter([
        { path: '', component: EmptyPage },
        { path: 'photo', component: EmptyPage, canActivate: [() => new Promise<boolean | UrlTree>(resolve => { resolveNavigation = resolve; })] },
      ]),
      { provide: GalleryStore, useValue: { filters, tags: signal([{ value: 'coast,ridge', count: 2 }]), updateFilter: update } },
      { provide: AuthService, useValue: { identity, status, isEdition: () => false, get token() { return token; } } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), currentLang: signal('en') } },
    ] });
    router = TestBed.inject(Router);
    await router.navigateByUrl('/');
    fixture = TestBed.createComponent(ScorePresenceComponent);
    fixture.componentRef.setInput('metrics', [{ minKey: 'min_sharpness', labelKey: 'Sharpness' }, { minKey: 'min_face_quality', labelKey: 'Face quality' }]);
    fixture.detectChanges();
    root = fixture.nativeElement;
    root.querySelector('details')!.open = true;
  });

  function choose(mode: string): void {
    const select = root.querySelector<HTMLSelectElement>('#measurement-policy-mode')!;
    select.value = mode; select.dispatchEvent(new Event('change', { bubbles: true })); fixture.detectChanges();
  }

  it('applies per-metric policies in read-only browsing without changing bounds or other fields', () => {
    filters.update(current => ({ ...current, min_sharpness: '2', max_sharpness: '4', camera: 'Alpha' }));
    fixture.detectChanges();
    choose('include_missing');
    expect(update).toHaveBeenCalledExactlyOnceWith('score_presence', '{"min_sharpness":"include_missing"}');
    expect(filters()).toMatchObject({ min_sharpness: '2', max_sharpness: '4', camera: 'Alpha' });
    const metric = root.querySelector<HTMLSelectElement>('#measurement-policy-metric')!;
    metric.value = 'min_face_quality'; metric.dispatchEvent(new Event('change', { bubbles: true })); fixture.detectChanges();
    choose('missing_only');
    expect(JSON.parse(filters().score_presence)).toEqual({ min_sharpness: 'include_missing', min_face_quality: 'missing_only' });
    expect(root.querySelector('label[for="measurement-policy-mode"]')).toBeTruthy();
    expect(root.querySelector('#measurement-policy-mode')?.getAttribute('aria-describedby')).toBe('measurement-policy-help');
    choose('');
    expect(JSON.parse(filters().score_presence)).toEqual({ min_sharpness: 'include_missing' });
  });

  it('refuses stale tokens, pending navigation and parked commands, and recovers after cancellation', async () => {
    token = 'rotated'; choose('missing_only'); expect(update).not.toHaveBeenCalled();
    status.set({ user_id: 'alice' }); fixture.detectChanges();
    const nav = router.navigateByUrl('/photo');
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf('function'));
    choose('missing_only'); expect(update).not.toHaveBeenCalled();
    resolveNavigation(false); await nav; fixture.detectChanges();
    choose('missing_only'); expect(update).toHaveBeenCalledTimes(1);
    resolveNavigation = undefined!;
    const next = router.navigateByUrl('/photo');
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf('function'));
    resolveNavigation(true); await next; fixture.detectChanges();
    choose('measured_only'); expect(update).toHaveBeenCalledTimes(1);
  });

  it('allows clearing an invalid policy and applies measured-only after repair', () => {
    filters.update(current => ({ ...current, score_presence: '{invalid' }));
    fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBeTruthy();
    root.querySelector<HTMLButtonElement>('button')!.click();
    fixture.detectChanges();
    expect(update).toHaveBeenLastCalledWith('score_presence', '');
    choose('measured_only');
    expect(update).toHaveBeenLastCalledWith('score_presence', '{"min_sharpness":"measured_only"}');
  });
});
