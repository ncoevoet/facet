import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { TagGroupsComponent } from './tag-groups.component';
import { GalleryStore } from './gallery.store';
import { DEFAULT_FILTERS, GalleryFilters } from './gallery-filters.util';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

@Component({ template: '' })
class EmptyPage {}

describe('rendered literal tag rule editor', () => {
  let fixture: ComponentFixture<TagGroupsComponent>;
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
    update = vi.fn((key: 'tag_groups', value: string) => {
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
    fixture = TestBed.createComponent(TagGroupsComponent);
    fixture.detectChanges();
    root = fixture.nativeElement;
    root.querySelector('details')!.open = true;
  });

  function input(value: string): HTMLInputElement {
    const element = root.querySelector<HTMLInputElement>('[data-tag-rule-input]')!;
    element.value = value; element.dispatchEvent(new Event('input', { bubbles: true })); fixture.detectChanges();
    return element;
  }

  function add(value: string): void {
    input(value);
    root.querySelector<HTMLButtonElement>('[data-tag-rule-add]')!.click(); fixture.detectChanges();
  }

  it('uses three labeled native groups and preserves a comma name literally in read-only browsing', () => {
    const radios = root.querySelectorAll<HTMLInputElement>('input[type=radio]');
    expect([...radios].map(radio => radio.value)).toEqual(['any', 'all', 'none']);
    expect(radios[0].closest('fieldset')!.querySelector('legend')!.textContent).toContain('gallery.tag_groups.add_to');
    add('coast,ridge');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["coast,ridge"]}');
    expect(root.querySelector('bdi')!.textContent).toBe('coast,ridge');
    expect(root.querySelector('datalist option')!.getAttribute('value')).toBe('coast,ridge');
    expect(root.querySelector('label[for="tag-rule-input"]')).toBeTruthy();
  });

  it('combines groups, removes one literal rule and returns focus before its button disappears', () => {
    add('coast,ridge');
    root.querySelector<HTMLInputElement>('input[value=all]')!.click(); add('夜景');
    root.querySelector<HTMLInputElement>('input[value=none]')!.click(); add('"OR"');
    expect(JSON.parse(filters().tag_groups)).toEqual({ any: ['coast,ridge'], all: ['夜景'], none: ['"OR"'] });
    root.querySelector<HTMLButtonElement>('li button')!.click(); fixture.detectChanges();
    expect(JSON.parse(filters().tag_groups)).toEqual({ all: ['夜景'], none: ['"OR"'] });
    expect(document.activeElement).toBe(root.querySelector('[data-tag-rule-input]'));
  });

  it('announces invalid names and recovers invalid saved rules with a single clear', () => {
    add('x'.repeat(201));
    expect(update).not.toHaveBeenCalled();
    expect(root.querySelector('[data-tag-rule-input]')!.getAttribute('aria-describedby')).toBe('tag-rule-error');
    expect(root.querySelector('#tag-rule-error')!.getAttribute('role')).toBe('alert');
    filters.update(current => ({ ...current, tag_groups: '{"any":true}' })); fixture.detectChanges();
    expect(root.querySelector('[data-tag-rule-input]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-tag-rule-clear]')!.click(); fixture.detectChanges();
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '');
    expect(document.activeElement).toBe(root.querySelector('summary'));
  });

  it('does not add while Enter is repeating or composing a tag name', () => {
    const element = input('夜景');
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }));
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true }));
    expect(update).not.toHaveBeenCalled();
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); fixture.detectChanges();
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["夜景"]}');
  });

  it('refuses a pending navigation and permits a fresh command after the real router cancels it', async () => {
    const navigation = router.navigateByUrl('/photo');
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf('function'));
    input('during navigation').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(update).not.toHaveBeenCalled();
    resolveNavigation(false); await navigation; fixture.detectChanges();
    add('after cancellation');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["after cancellation"]}');
  });

  it('refuses a command under a rotated token until fresh status establishes the session', () => {
    input('old draft'); token = 'rotated';
    root.querySelector<HTMLButtonElement>('[data-tag-rule-add]')!.click();
    expect(update).not.toHaveBeenCalled();
    status.set({ user_id: 'alice' }); fixture.detectChanges();
    expect(root.querySelector<HTMLInputElement>('[data-tag-rule-input]')!.value).toBe('');
    add('new session');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["new session"]}');
  });

  it('recovers when a real route guard redirects back to the same gallery URL', async () => {
    const navigation = router.navigateByUrl('/photo');
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf('function'));
    resolveNavigation(router.parseUrl('/'));
    await navigation; fixture.detectChanges();
    expect(router.url).toBe('/');
    add('after skipped redirect');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["after skipped redirect"]}');
  });
});
