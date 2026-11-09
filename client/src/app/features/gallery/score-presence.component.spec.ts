import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { By } from '@angular/platform-browser';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatSelect } from '@angular/material/select';
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
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ] });
    router = TestBed.inject(Router);
    await router.navigateByUrl('/');
    fixture = TestBed.createComponent(ScorePresenceComponent);
    fixture.componentRef.setInput('metrics', [{ minKey: 'min_sharpness', labelKey: 'Sharpness' }, { minKey: 'min_face_quality', labelKey: 'Face quality' }]);
    fixture.detectChanges();
    root = fixture.nativeElement;
  });

  function pick(id: string, value: string): void {
    const select = fixture.debugElement.query(By.css(`#${id}`)).injector.get(MatSelect);
    select.open(); fixture.detectChanges();
    select.options.find(option => option.value === value)!._getHostElement().click();
    fixture.detectChanges();
  }
  const choose = (mode: string) => pick('measurement-policy-mode', mode);

  it('applies per-metric policies in read-only browsing without changing bounds or other fields', () => {
    filters.update(current => ({ ...current, min_sharpness: '2', max_sharpness: '4', camera: 'Alpha' }));
    fixture.detectChanges();
    choose('include_missing');
    expect(update).toHaveBeenCalledExactlyOnceWith('score_presence', '{"min_sharpness":"include_missing"}');
    expect(filters()).toMatchObject({ min_sharpness: '2', max_sharpness: '4', camera: 'Alpha' });
    pick('measurement-policy-metric', 'min_face_quality');
    choose('missing_only');
    expect(JSON.parse(filters().score_presence)).toEqual({ min_sharpness: 'include_missing', min_face_quality: 'missing_only' });
    const mode = root.querySelector('#measurement-policy-mode')!;
    expect(mode.tagName).toBe('MAT-SELECT');
    expect(root.querySelector('select')).toBeNull();
    const labelledBy = mode.getAttribute('aria-labelledby')!.split(' ').map(id => document.getElementById(id)?.textContent ?? '').join(' ');
    expect(labelledBy).toContain('gallery.measurements.policy');
    expect(mode.getAttribute('aria-describedby')).toContain('measurement-policy-help');
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

  it('allows clearing an invalid policy and applies measured-only after repair', async () => {
    filters.update(current => ({ ...current, score_presence: '{invalid' }));
    fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBeTruthy();
    root.querySelector<HTMLButtonElement>('[data-clear-measurements]')!.click();
    await fixture.whenStable(); TestBed.tick();
    expect(update).toHaveBeenLastCalledWith('score_presence', '');
    expect(document.activeElement).toBe(root.querySelector('#measurement-policy-mode'));
    choose('measured_only');
    expect(update).toHaveBeenLastCalledWith('score_presence', '{"min_sharpness":"measured_only"}');
  });
  it('shows the stored policy again when a choice is refused', () => {
    token = 'rotated'; choose('missing_only');
    expect(update).not.toHaveBeenCalled();
    expect(fixture.debugElement.query(By.css('#measurement-policy-mode')).injector.get(MatSelect).value).toBe('');
  });

  it('moves focus to the policy select when the clear button leaves the DOM', async () => {
    filters.update(current => ({ ...current, score_presence: '{"min_sharpness":"measured_only"}' }));
    fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-clear-measurements]')!.click();
    await fixture.whenStable(); TestBed.tick();
    expect(root.querySelector('[data-clear-measurements]')).toBeNull();
    expect(document.activeElement).toBe(root.querySelector('#measurement-policy-mode'));
  });

  it('refuses unknown modes, unrecognized metrics and changes while the policy is invalid', () => {
    const component = fixture.componentInstance as unknown as { apply(mode: string): void };
    component.apply('unknown');
    expect(update).not.toHaveBeenCalled();
    fixture.componentRef.setInput('metrics', [{ minKey: 'not_a_metric', labelKey: 'Unknown' }]);
    fixture.detectChanges(); component.apply('measured_only');
    expect(update).not.toHaveBeenCalled();
    fixture.componentRef.setInput('metrics', [{ minKey: 'min_sharpness', labelKey: 'Sharpness' }]);
    filters.update(current => ({ ...current, score_presence: '{invalid' })); fixture.detectChanges();
    component.apply('measured_only');
    expect(update).not.toHaveBeenCalled();
  });

});
