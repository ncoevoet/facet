import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
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
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
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
  });

  const row = (id: string) => root.querySelector<HTMLElement>(`[data-tag-rule-row="${id}"]`)!;
  const overlay = () => TestBed.inject(OverlayContainer).getContainerElement();

  function input(value: string, id = 'any'): HTMLInputElement {
    const element = row(id).querySelector<HTMLInputElement>('[data-tag-rule-input]')!;
    element.focus();
    element.value = value; element.dispatchEvent(new Event('input', { bubbles: true })); fixture.detectChanges();
    return element;
  }

  function key(element: HTMLElement, name: string, keyCode: number, init: KeyboardEventInit = {}): void {
    const event = new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true, ...init });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    element.dispatchEvent(event); fixture.detectChanges();
  }

  function add(value: string, id = 'any'): void {
    key(input(value, id), 'Enter', 13);
  }

  it('gives each group its own labelled chip row and preserves a comma name literally in read-only browsing', () => {
    expect([...root.querySelectorAll<HTMLElement>('[data-tag-rule-row]')].map(element => element.dataset['tagRuleRow'])).toEqual(['any', 'all', 'none']);
    expect(row('all').querySelector('mat-label')!.textContent).toContain('gallery.tag_groups.all');
    expect(root.querySelector('input[type=radio], datalist, [data-tag-rule-add]')).toBeNull();
    add('coast,ridge');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["coast,ridge"]}');
    expect(row('any').querySelector('mat-chip-row bdi')!.textContent).toBe('coast,ridge');
    expect(row('any').querySelector<HTMLInputElement>('[data-tag-rule-input]')!.value).toBe('');
    expect(row('any').querySelector('[data-tag-rule-input]')!.getAttribute('aria-describedby')).toContain('tag-rule-hint');
    expect(root.querySelector('#tag-rule-hint')!.textContent).toContain('gallery.tag_groups.hint');
  });

  it('shows a visible Enter hint that every rule input is described by', () => {
    const hint = root.querySelector<HTMLElement>('#tag-rule-enter')!;
    expect(hint.textContent).toContain('gallery.tag_groups.enter_hint');
    expect(hint.classList.contains('sr-only')).toBe(false);
    for (const id of ['any', 'all', 'none']) {
      expect(row(id).querySelector('[data-tag-rule-input]')!.getAttribute('aria-describedby')!.split(' ')).toContain('tag-rule-enter');
    }
  });

  it('trims surrounding whitespace from a new tag rule', () => {
    add('  coast  ');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["coast"]}');
  });

  it('combines groups and removes one literal rule with its chip remove button, keeping focus in that row', async () => {
    add('coast,ridge');
    add('夜景', 'all');
    add('"OR"', 'none');
    expect(JSON.parse(filters().tag_groups)).toEqual({ any: ['coast,ridge'], all: ['夜景'], none: ['"OR"'] });
    const remove = row('any').querySelector<HTMLButtonElement>('mat-chip-row button[matChipRemove]')!;
    expect(remove.getAttribute('aria-label')).toBe('gallery.tag_groups.remove');
    remove.focus(); remove.click(); fixture.detectChanges();
    await fixture.whenStable(); fixture.detectChanges();
    expect(JSON.parse(filters().tag_groups)).toEqual({ all: ['夜景'], none: ['"OR"'] });
    expect(document.activeElement).toBe(row('any').querySelector('[data-tag-rule-input]'));
  });

  it('suggests known tags for a row and adds a picked one to that row only', () => {
    const element = input('coa', 'all');
    const option = overlay().querySelector<HTMLElement>('mat-option')!;
    expect(option.textContent).toContain('coast,ridge');
    option.click(); fixture.detectChanges();
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"all":["coast,ridge"]}');
    expect(element.value).toBe('');
  });

  it('adds only the highlighted suggestion, not the typed text, when Enter picks it', () => {
    const element = input('coa');
    key(element, 'ArrowDown', 40);
    key(element, 'Enter', 13);
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["coast,ridge"]}');
  });

  it('keeps the typed text in the box when a picked suggestion is refused at the rule limit', () => {
    const full = { none: Array.from({ length: 50 }, (_, index) => `t${index}`) };
    filters.update(current => ({ ...current, tag_groups: JSON.stringify(full) })); fixture.detectChanges();
    const element = input('coa');
    overlay().querySelector<HTMLElement>('mat-option')!.click(); fixture.detectChanges();
    expect(update).not.toHaveBeenCalled();
    expect(element.value).toBe('coa');
  });

  it('closes its suggestion list when asked to, for a gallery parking behind a photo', () => {
    input('coa');
    expect(overlay().querySelector('mat-option')).not.toBeNull();
    fixture.componentInstance.closeOverlays(); fixture.detectChanges();
    expect(overlay().querySelector('mat-option')).toBeNull();
  });

  it('clears every rule and returns focus to the first row', async () => {
    add('coast');
    root.querySelector<HTMLButtonElement>('[data-tag-rule-clear]')!.click(); fixture.detectChanges();
    await fixture.whenStable();
    expect(filters().tag_groups).toBe('');
    expect(document.activeElement).toBe(row('any').querySelector('[data-tag-rule-input]'));
    // Focus lands on the row without popping its suggestion list open again.
    expect(row('any').querySelector('[data-tag-rule-input]')!.getAttribute('aria-expanded')).toBe('false');
    expect(overlay().querySelector('mat-option')).toBeNull();
  });

  it('announces invalid names and recovers invalid saved rules with a single clear', async () => {
    add('x'.repeat(201));
    expect(update).not.toHaveBeenCalled();
    expect(row('any').querySelector('[data-tag-rule-input]')!.getAttribute('aria-describedby')).toContain('tag-rule-error');
    expect(row('all').querySelector('[data-tag-rule-input]')!.getAttribute('aria-describedby')).not.toContain('tag-rule-error');
    expect(row('any').querySelector('[data-tag-rule-input]')!.getAttribute('aria-invalid')).toBe('true');
    expect(row('all').querySelector('[data-tag-rule-input]')!.hasAttribute('aria-invalid')).toBe(false);
    expect(root.querySelector('#tag-rule-error')!.getAttribute('role')).toBe('alert');
    filters.update(current => ({ ...current, tag_groups: '{"any":true}' })); fixture.detectChanges();
    expect(root.querySelector('[data-tag-rule-input]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-tag-rule-clear]')!.click(); fixture.detectChanges();
    await fixture.whenStable();
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '');
    expect(document.activeElement).toBe(row('any').querySelector('[data-tag-rule-input]'));
    // The refusal left with the rules it was about, so the rebuilt row is not announced as invalid.
    expect(root.querySelector('#tag-rule-error')).toBeNull();
    expect(row('any').querySelector('[data-tag-rule-input]')!.hasAttribute('aria-invalid')).toBe(false);
  });

  it('does not add while Enter is repeating or composing a tag name', () => {
    const element = input('夜景');
    key(element, 'Enter', 229, { isComposing: true });
    key(element, 'Enter', 13, { repeat: true });
    expect(update).not.toHaveBeenCalled();
    key(element, 'Enter', 13);
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["夜景"]}');
  });

  it('refuses a pending navigation and permits a fresh command after the real router cancels it', async () => {
    const navigation = router.navigateByUrl('/photo');
    await vi.waitFor(() => expect(resolveNavigation).toBeTypeOf('function'));
    key(input('during navigation'), 'Enter', 13);
    expect(update).not.toHaveBeenCalled();
    resolveNavigation(false); await navigation; fixture.detectChanges();
    add('after cancellation');
    expect(update).toHaveBeenCalledExactlyOnceWith('tag_groups', '{"any":["after cancellation"]}');
  });

  it('refuses a command under a rotated token until fresh status establishes the session', () => {
    const draft = input('old draft'); token = 'rotated';
    key(draft, 'Enter', 13);
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
