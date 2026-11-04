import { AuthService } from '../../core/services/auth.service';
import { galleryPresentation } from './gallery-presentation.util';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, signal, TemplateRef } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { By } from '@angular/platform-browser';
import { MatMenuTrigger } from '@angular/material/menu';
import { Event, NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { GalleryViewControlsComponent } from './gallery-view-controls.component';
import { GalleryStore, DEFAULT_FILTERS, ViewerConfig } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';

afterEach(() => TestBed.resetTestingModule());

@Component({ imports: [NgTemplateOutlet], template: '<ng-container [ngTemplateOutlet]="template" [ngTemplateOutletContext]="context" />' })
class RehostedControls {
  template: TemplateRef<unknown> | null = null;
  context: { $implicit?: unknown } = {};
}

describe('GalleryViewControlsComponent', () => {
    function render(config: { features?: { show_my_taste?: boolean; show_rating_controls?: boolean }; sort_options_grouped?: ViewerConfig['sort_options_grouped'] } | null = null) {
    const navigation = new Subject<Event>();
    const edition = signal(false);
    const store = {
      filters: signal({ ...DEFAULT_FILTERS }), config: signal(config),
      pinnedPaths: signal<string[] | null>(null), filterDrawerOpen: signal(true), activeFilterCount: signal(0),
      slideshowActive: signal(false), setFilterDrawerOpen: vi.fn(), updateFilter: vi.fn(), setUserSort: vi.fn(() => Promise.resolve()),
      galleryMode: signal('grid'), setGalleryMode: vi.fn(), cardWidth: signal(168), applyDisplayPreset: vi.fn(() => Promise.resolve()),
    };
    TestBed.configureTestingModule({
      imports: [GalleryViewControlsComponent],
      providers: [
        { provide: AuthService, useValue: { isEdition: edition, status: signal({ user_id: 'editor' }), identity: () => 'editor', token: 'fixture' } },
        { provide: Router, useValue: { events: navigation } },
        { provide: GalleryStore, useValue: store },
        { provide: I18nService, useValue: { t: vi.fn((k: string, vars?: Record<string, string | number>) => vars ? `${k}(${Object.values(vars).join(',')})` : k), translations: signal({}) } },
      ],
    });
    const fixture = TestBed.createComponent(GalleryViewControlsComponent);
    fixture.detectChanges();
    return { fixture, root: fixture.nativeElement as HTMLElement, store, navigation, edition };
  }

  it('renders primary layouts and the secondary List action from the same guarded owner', () => {
    const { fixture, root, store, navigation } = render();
    const primary = TestBed.createComponent(RehostedControls);
    primary.componentInstance.template = fixture.componentInstance.layoutControls()!;
    primary.componentInstance.context = { $implicit: fixture.componentInstance.primaryLayouts };
    primary.detectChanges();
    for (const [mode, label] of [['grid', I18N.gallery.layout_grid], ['mosaic', I18N.gallery.layout_mosaic], ['list', I18N.gallery.layout_list]]) {
      const host = mode === 'list' ? root : primary.nativeElement as HTMLElement;
      const button = host.querySelector<HTMLButtonElement>(`[data-gallery-layout="${mode}"]`)!;
      expect(button.getAttribute('aria-label')).toBe(label);
      store.galleryMode.set(mode); fixture.detectChanges(); primary.detectChanges();
      expect(button.getAttribute('aria-pressed')).toBe('true');
      button.click();
      expect(store.setGalleryMode).toHaveBeenLastCalledWith(mode);
    }
    store.setGalleryMode.mockClear();
    navigation.next(new NavigationStart(1, '/persons'));
    root.querySelector<HTMLButtonElement>('[data-gallery-layout="list"]')!.click();
    primary.nativeElement.querySelector('[data-gallery-layout="grid"]').click();
    expect(store.setGalleryMode).not.toHaveBeenCalled();
  });

    it('moves primary and filter controls into a different host without duplicating commands', () => {
      const { fixture, root, store } = render();
      fixture.componentRef.setInput('portPrimary', true);
      fixture.componentRef.setInput('portFilters', true); fixture.detectChanges();
      expect(root.querySelector('[data-collection-sort]')).toBeNull();
      expect(root.querySelector('[aria-label="gallery.filters"]')).toBeNull();
      const primary = TestBed.createComponent(RehostedControls);
      primary.componentInstance.template = fixture.componentInstance.primaryControls()!;
      primary.detectChanges();
      expect(primary.nativeElement.querySelectorAll('[data-collection-sort]')).toHaveLength(1);
      const filters = TestBed.createComponent(RehostedControls);
      filters.componentInstance.template = fixture.componentInstance.filterControls()!;
      filters.detectChanges();
      filters.nativeElement.querySelector('button').click();
      expect(store.setFilterDrawerOpen).toHaveBeenCalledExactlyOnceWith(false);
      fixture.componentInstance.setActive(false);
      filters.nativeElement.querySelector('button').click();
      expect(store.setFilterDrawerOpen).toHaveBeenCalledTimes(1);
    });

    it('does not unlock commands when an older navigation finishes', () => {
      const { root, store, navigation } = render();
      const list = root.querySelector<HTMLButtonElement>('[data-gallery-layout=list]')!;
      navigation.next(new NavigationStart(2, '/photo'));
      navigation.next(new NavigationStart(3, '/photo'));
      navigation.next(new NavigationEnd(2, '/photo', '/photo')); list.click();
      expect(store.setGalleryMode).not.toHaveBeenCalled();
      navigation.next(new NavigationEnd(3, '/photo', '/photo')); list.click();
      expect(store.setGalleryMode).toHaveBeenCalledExactlyOnceWith('list');
    });

    it('selects metadata list as presentation only and refuses parked-navigation commands', () => {
      const { fixture, root, store, navigation } = render();
      const filters = store.filters(); const pinned = store.pinnedPaths();
      const list = root.querySelector<HTMLButtonElement>('[data-gallery-layout=list]')!;
      expect(list).not.toBeNull(); list.click();
      expect(store.setGalleryMode).toHaveBeenCalledExactlyOnceWith('list');
      expect(store.filters()).toBe(filters); expect(store.pinnedPaths()).toBe(pinned);
      expect(store.updateFilter).not.toHaveBeenCalled(); expect(store.setUserSort).not.toHaveBeenCalled();
      navigation.next(new NavigationStart(1, '/photo')); list.click();
      expect(store.setGalleryMode).toHaveBeenCalledTimes(1); fixture.destroy();
    });

    const sortButtons = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="menu"]'))
      .filter(el => el.getAttribute('aria-label')?.startsWith(`${I18N.gallery.sort_current}(`));
    const sortLabel = (key: string) => `${I18N.gallery.sort_current}(${key})`;
    const byLabel = (root: HTMLElement, key: string) => root.querySelectorAll(`button[aria-label="${key}"]`);
    const menuItems = () => Array.from(document.querySelectorAll<HTMLElement>('.mat-mdc-menu-panel [role="menuitemradio"]'));
    const iconOf = (el: Element) => el.querySelector('mat-icon')?.textContent?.trim();
    const openMenu = async (fixture: ComponentFixture<GalleryViewControlsComponent>, button: HTMLButtonElement) => {
      button.click();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
    };

    it('owns the session-only review navigation choice without modifying the collection or presets', () => {
      const { fixture, root, store, edition } = render({ features: { show_rating_controls: true } });
      expect(root.querySelector('[data-review-advance]')).toBeNull();
      edition.set(true); fixture.detectChanges();
      const checkbox = root.querySelector<HTMLInputElement>('[data-review-advance]')!;
      expect(checkbox.checked).toBe(false);
      checkbox.click(); fixture.detectChanges();
      expect(TestBed.inject(GalleryReviewNavigationService).enabled()).toBe(true);
      expect(store.updateFilter).not.toHaveBeenCalled();
      expect(store.applyDisplayPreset).not.toHaveBeenCalled();
      fixture.componentInstance.setActive(false);
      checkbox.click();
      expect(TestBed.inject(GalleryReviewNavigationService).enabled()).toBe(true);
      expect(checkbox.checked).toBe(true);
    });

    it('offers display-only task presets in pinned lists and blocks captured commands while parked', async () => {
      const { fixture, root, store } = render();
      store.pinnedPaths.set(['/fixed']);
      fixture.detectChanges();
      await openMenu(fixture, root.querySelector<HTMLButtonElement>('[data-display-presets]')!);
      const organize = document.querySelector<HTMLButtonElement>('[data-display-preset="organize"]')!;
      expect(organize).not.toBeNull();
      organize.click();
      expect(store.applyDisplayPreset).toHaveBeenCalledWith('organize', expect.any(Boolean));
      expect(store.updateFilter).not.toHaveBeenCalled();
      store.applyDisplayPreset.mockClear();
      fixture.componentInstance.setActive(false);
      organize.click();
      expect(store.applyDisplayPreset).not.toHaveBeenCalled();
    });

    it.each([[true, 'grid', false], [false, 'grid', true], [true, 'mosaic', true], [true, 'list', true]] as const)(
      'enables tile fit only for detail-less grids (%s, %s)', async (hideDetails, mode, disabled) => {
        const { fixture, root, store } = render();
        store.filters.update(filters => ({ ...filters, hide_details: hideDetails }));
        store.galleryMode.set(mode);
        fixture.detectChanges();
        await openMenu(fixture, root.querySelector<HTMLButtonElement>('[data-display-presets]')!);
        expect(document.querySelector<HTMLButtonElement>('[data-tile-fit]')!.disabled).toBe(disabled);
      },
    );


    it('shows the sort button, sort direction and filter toggle (one control group) otherwise', () => {
      const { root } = render();
      expect(sortButtons(root)).toHaveLength(1);
      expect(byLabel(root, I18N.gallery.sort_desc)).toHaveLength(1);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(1);
      expect(byLabel(root, I18N.ui.buttons.filters)).toHaveLength(0);
      expect(byLabel(root, I18N.ui.filters.search)).toHaveLength(0);
    });

    it('changes sort direction and refuses the action for a pinned collection', () => {
      const { fixture, root, store } = render();
      const direction = root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.gallery.sort_desc}"]`)!;
      direction.click();
      expect(store.updateFilter).toHaveBeenCalledExactlyOnceWith('sort_direction', 'ASC');
      store.updateFilter.mockClear(); store.pinnedPaths.set(['/fixed']); fixture.detectChanges();
      direction.click(); expect(store.updateFilter).not.toHaveBeenCalled();
      fixture.destroy();
    });

    it('keeps direction and filter controls immediately after sort in DOM order', () => {
      const { root } = render();
      const [sort] = sortButtons(root);
      expect(sort.nextElementSibling?.getAttribute('aria-label')).toBe(I18N.gallery.sort_desc);
      expect(sort.nextElementSibling?.nextElementSibling?.getAttribute('aria-label')).toBe(I18N.gallery.filters);
    });

    it('shows the current sort icon and labels the button "Sort by: <current label>"', () => {
      const { fixture, root, store } = render();
      for (const button of sortButtons(root)) {
        expect(iconOf(button)).toBe('leaderboard');
        expect(button.getAttribute('aria-label')).toBe(sortLabel(I18N.gallery.sort_aggregate));
      }
      store.filters.update(filters => ({ ...filters, sort: 'aesthetic_iaa' }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        expect(iconOf(button)).toBe('IAA');
        expect(button.querySelector('mat-icon')?.classList.contains('!font-sans')).toBe(true);
        expect(button.getAttribute('aria-label')).toBe(sortLabel('sort_options.aesthetic_iaa'));
      }
    });

    it.each(['constructor', 'toString', '__proto__'])('keeps an unknown %s sort label a string rather than reading Object.prototype', sort => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        expect(button.getAttribute('aria-label')).toBe(sortLabel(`sort_options.${sort}`));
      }
    });

    it('gives model labels centered markers and accessible sort names', () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort: 'deqa_score' }));
      fixture.detectChanges();
      for (const button of sortButtons(root)) {
        const icon = button.querySelector('mat-icon')!;
        expect(icon.textContent?.trim()).toBe('DeQA');
        expect(icon.classList.contains('!w-8')).toBe(true);
        expect(icon.classList.contains('text-center')).toBe(true);
        expect(icon.classList.contains('!m-0')).toBe(true);
        expect(icon.getAttribute('aria-hidden')).toBe('true');
        expect(button.getAttribute('aria-label')).toBe(sortLabel('sort_options.deqa_score'));
      }
    });

    it('lists the fallback sorts with icons, marks the current one and runs the saved-sort handler on click', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      const items = menuItems();
      expect(items.map(item => item.textContent?.replace(iconOf(item) ?? '', '').replace('check', '').trim())).toEqual([
        I18N.gallery.sort_aggregate, I18N.gallery.sort_aesthetic, I18N.gallery.sort_date,
      ]);
      expect(items.map(item => iconOf(item))).toEqual(['leaderboard', '✦', 'event']);
      expect(items.map(item => item.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
      expect(items.map(item => !!Array.from(item.querySelectorAll('mat-icon')).find(i => i.textContent?.trim() === 'check'))).toEqual([true, false, false]);
      items[2].click();
      expect(store.setUserSort).toHaveBeenLastCalledWith('date_taken');
      fixture.detectChanges();
      await fixture.whenStable();
      expect(menuItems()).toHaveLength(0);
    });

    it('labels a sort the menu does not list with its own label, never a raw sort_options key', () => {
      const { fixture, root, store } = render();
      for (const [sort, labelKey] of [
        ['top_picks_score', I18N.photo_types.top_picks],
        ['learned_score', I18N.gallery.sort_my_taste],
        ['relevance', I18N.gallery.sort_relevance],
      ] as const) {
        store.filters.update(filters => ({ ...filters, sort }));
        fixture.detectChanges();
        for (const button of sortButtons(root)) expect(button.getAttribute('aria-label')).toBe(sortLabel(labelKey));
      }
    });

    it('moves the check to the current sort', async () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, sort: 'aesthetic' }));
      fixture.detectChanges();
      await openMenu(fixture, sortButtons(root)[0]);
      expect(menuItems().map(item => item.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false']);
    });

    it('does not reload when the already-current sort is picked again', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      menuItems()[0].click();
      expect(store.setUserSort).not.toHaveBeenCalled();
    });

    it('lists configured groups under non-interactive headers, with conditional sorts and model labels', async () => {
      const { fixture, root, store } = render({
        features: { show_my_taste: true },
        sort_options_grouped: {
          General: [
            { column: 'date_taken', label: 'Date Taken' },
            { column: 'aesthetic_iaa', label: 'Aesthetic IAA' },
            { column: 'qrealign_score', label: 'Q-ReAlign' },
          ],
          'Face Metrics': [{ column: 'future_metric', label: 'Future metric' }],
        },
      });
      store.filters.update(filters => ({ ...filters, semanticQuery: 'sunset' }));
      fixture.detectChanges();
      await openMenu(fixture, sortButtons(root)[0]);
      const items = menuItems();
      expect(items.map(item => iconOf(item))).toEqual(['search', 'psychology', 'event', 'IAA', 'Q-R', 'sort']);
      const panel = items[0].closest('.mat-mdc-menu-panel')!;
      const groups = Array.from(panel.querySelectorAll('[role="group"]'));
      const headers = groups.map(group => document.getElementById(group.getAttribute('aria-labelledby')!)?.textContent?.trim());
      expect(headers).toEqual(['sort_groups.general', 'sort_groups.face_metrics']);
      expect(groups.map(group => group.querySelectorAll('[role="menuitemradio"]').length)).toEqual([3, 1]);
      for (const item of items) expect(item.querySelector('mat-icon')?.getAttribute('aria-hidden')).toBe('true');
      items[3].click();
      expect(store.setUserSort).toHaveBeenLastCalledWith('aesthetic_iaa');
    });

    it('offers the tooltip modes as one shared radio menu with the current mode checked', async () => {
      const { fixture, root, store } = render();
      store.filters.update(filters => ({ ...filters, tooltip_mode: 'click' }));
      fixture.detectChanges();
      const triggers = Array.from(byLabel(root, I18N.gallery.tooltip_mode.label)) as HTMLButtonElement[];
      expect(triggers).toHaveLength(1);
      const menus = fixture.debugElement.queryAll(By.directive(MatMenuTrigger))
        .filter(d => triggers.includes(d.nativeElement as HTMLButtonElement))
        .map(d => d.injector.get(MatMenuTrigger).menu);
      expect(menus[0]).toBeDefined();
      await openMenu(fixture, triggers[0]);
      const items = menuItems();
      expect(items.map(item => item.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false']);
      expect(items.map(item => item.textContent?.includes('check'))).toEqual([false, true, false]);
      items[2].click();
      expect(store.updateFilter).toHaveBeenCalledWith('tooltip_mode', 'off');
    });

    it.each([true, false])('reads pointer hover capability (%s) and cleans up listeners', canHover => {
      const mql = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() };
      const hoverMql = { matches: canHover, addEventListener: vi.fn(), removeEventListener: vi.fn() };
      const originalMatchMedia = window.matchMedia.bind(window);
      const query = vi.spyOn(window, 'matchMedia').mockImplementation(value =>
        value === '(hover: hover)' ? hoverMql as unknown as MediaQueryList
          : value === '(min-width: 768px)' ? mql as unknown as MediaQueryList : originalMatchMedia(value),
      );
      try {
        const { fixture } = render();
        const controls = fixture.componentInstance as unknown as { canHoverAtAll: () => boolean; canUseHoverTooltips: () => boolean };
        expect(query).toHaveBeenCalledWith('(min-width: 768px)');
        expect(query).toHaveBeenCalledWith('(hover: hover)');
        expect(controls.canHoverAtAll()).toBe(canHover);
        expect(controls.canUseHoverTooltips()).toBe(true);
        expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function));
        const handler = mql.addEventListener.mock.calls[0][1];
        const hoverHandler = hoverMql.addEventListener.mock.calls[0][1];
        TestBed.resetTestingModule();
        expect(mql.removeEventListener).toHaveBeenCalledWith('change', handler);
        expect(hoverMql.removeEventListener).toHaveBeenCalledWith('change', hoverHandler);
      } finally {
        query.mockRestore();
      }
    });

    it('greys the hover trigger out on a pure touch device at any width', async () => {
      const { fixture, root, store } = render();
      const capability = fixture.componentInstance as unknown as {
        tooltipCapable: { setMatches(value: boolean): void };
        hoverCapable: { setMatches(value: boolean): void };
      };
      store.filters.update(filters => ({ ...filters, tooltip_mode: 'off' }));
      capability.tooltipCapable.setMatches(true);
      capability.hoverCapable.setMatches(false);
      fixture.detectChanges();
      await openMenu(fixture, byLabel(root, I18N.gallery.tooltip_mode.label)[0] as HTMLButtonElement);
      const hover = () => menuItems()[0] as HTMLButtonElement;
      expect(hover().disabled).toBe(true);
      hover().click();
      expect(store.updateFilter).not.toHaveBeenCalled();
      capability.hoverCapable.setMatches(true);
      fixture.detectChanges();
      expect(hover().disabled).toBe(false);
      // An already-selected Hover stays selectable, so the saved trigger is never silently replaced.
      capability.hoverCapable.setMatches(false);
      store.filters.update(filters => ({ ...filters, tooltip_mode: 'hover' }));
      fixture.detectChanges();
      expect(hover().disabled).toBe(false);
      (menuItems()[1] as HTMLButtonElement).click();
      expect(store.updateFilter).toHaveBeenLastCalledWith('tooltip_mode', 'click');
    });

    it('greys the side panel hover activation out on a pure touch device', async () => {
      const { fixture, root, store } = render();
      const capability = fixture.componentInstance as unknown as {
        railCapable: { setMatches(value: boolean): void };
        hoverCapable: { setMatches(value: boolean): void };
      };
      capability.railCapable.setMatches(true);
      capability.hoverCapable.setMatches(false);
      store.filters.update(filters => ({ ...filters, tooltip_mode: 'panel', panel_activation: 'click' }));
      fixture.detectChanges();
      await openMenu(fixture, byLabel(root, I18N.gallery.tooltip_mode.label)[0] as HTMLButtonElement);
      const activationTrigger = Array.from(document.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-panel button'))
        .find(button => button.textContent?.includes(I18N.gallery.panel_activation.label))!;
      await openMenu(fixture, activationTrigger);
      const panels = document.querySelectorAll('.mat-mdc-menu-panel');
      const activation = Array.from(panels[panels.length - 1].querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
      expect(activation.map(item => item.disabled)).toEqual([true, false, false]);
      activation[2].click();
      expect(store.updateFilter).toHaveBeenLastCalledWith('panel_activation', 'both');
    });

    it('toggles the refinement panel without changing collection predicates', () => {
      const { fixture, root, store } = render();
      const filters = store.filters();
      store.setFilterDrawerOpen.mockImplementation(open => store.filterDrawerOpen.set(open));
      const button = byLabel(root, I18N.gallery.filters)[0] as HTMLButtonElement;
      expect(button.getAttribute('aria-expanded')).toBe('true');
      button.click(); fixture.detectChanges();
      expect(button.getAttribute('aria-expanded')).toBe('false');
      expect(store.filters()).toBe(filters);
      expect(store.updateFilter).not.toHaveBeenCalled();
    });

    it('closes its menu on parking, refuses stale commands, then resumes the same commands', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      const trigger = fixture.debugElement.queryAll(By.directive(MatMenuTrigger))
        .find(d => d.nativeElement === sortButtons(root)[0])!.injector.get(MatMenuTrigger);
      expect(trigger.menuOpen).toBe(true);
      fixture.componentInstance.setActive(false);
      expect(trigger.menuOpen).toBe(false);
      const commands = fixture.componentInstance as unknown as {
        onSortChange(sort: string): void; toggleSortDirection(): void;
        toggleFilters(): void; toggleSlideshow(): void;
        setPresentationFilter(key: string, value: string): void;
      };
      commands.onSortChange('date_taken');
      commands.toggleSortDirection();
      commands.toggleFilters();
      commands.toggleSlideshow();
      commands.setPresentationFilter('tooltip_mode', 'off');
      expect(store.setUserSort).not.toHaveBeenCalled();
      expect(store.updateFilter).not.toHaveBeenCalled();
      expect(store.setFilterDrawerOpen).not.toHaveBeenCalled();
      expect(store.slideshowActive()).toBe(false);
      fixture.componentInstance.setActive(true);
      commands.onSortChange('date_taken');
      commands.toggleFilters();
      commands.toggleSlideshow();
      expect(store.setUserSort).toHaveBeenCalledExactlyOnceWith('date_taken');
      expect(store.setFilterDrawerOpen).toHaveBeenCalledExactlyOnceWith(false);
      expect(store.slideshowActive()).toBe(true);
    });

    it('refuses a captured inspection menu item after parking and accepts it after return', async () => {
      const { fixture, root, store } = render();
      const trigger = byLabel(root, I18N.gallery.tooltip_mode.label)[0] as HTMLButtonElement;
      await openMenu(fixture, trigger);
      const off = menuItems().find(item => item.textContent?.includes(I18N.gallery.tooltip_mode.off))!;
      expect(off).toBeTruthy();
      fixture.componentInstance.setActive(false);
      off.click();
      expect(store.updateFilter).not.toHaveBeenCalled();
      fixture.componentInstance.setActive(true);
      await openMenu(fixture, trigger);
      menuItems().find(item => item.textContent?.includes(I18N.gallery.tooltip_mode.off))!.click();
      expect(store.updateFilter).toHaveBeenCalledExactlyOnceWith('tooltip_mode', 'off');
    });

    it('blocks pending and redirected navigation, then resumes after rejection, error or completion', () => {
      const { fixture, store, navigation } = render();
      const commands = fixture.componentInstance as unknown as { onSortChange(sort: string): void; toggleFilters(): void };
      navigation.next(new NavigationStart(1, '/photo'));
      commands.onSortChange('date_taken');
      expect(store.setUserSort).not.toHaveBeenCalled();
      navigation.next(new NavigationCancel(1, '/photo', 'redirect', NavigationCancellationCode.Redirect));
      commands.onSortChange('date_taken');
      expect(store.setUserSort).not.toHaveBeenCalled();
      navigation.next(new NavigationStart(2, '/photo'));
      navigation.next(new NavigationCancel(2, '/photo', 'guard', NavigationCancellationCode.GuardRejected));
      commands.onSortChange('date_taken');
      expect(store.setUserSort).toHaveBeenCalledExactlyOnceWith('date_taken');
      navigation.next(new NavigationStart(3, '/photo'));
      commands.toggleFilters();
      expect(store.setFilterDrawerOpen).not.toHaveBeenCalled();
      navigation.next(new NavigationError(3, '/photo', new Error('unavailable')));
      commands.toggleFilters();
      expect(store.setFilterDrawerOpen).toHaveBeenCalledExactlyOnceWith(false);
      navigation.next(new NavigationStart(4, '/?sort=aesthetic'));
      navigation.next(new NavigationEnd(4, '/?sort=aesthetic', '/?sort=aesthetic'));
      commands.onSortChange('aesthetic');
      expect(store.setUserSort).toHaveBeenLastCalledWith('aesthetic');
      navigation.next(new NavigationStart(5, '/photo'));
      navigation.next(new NavigationCancel(5, '/photo', 'redirect', NavigationCancellationCode.Redirect));
      navigation.next(new NavigationSkipped(6, '/', 'same URL'));
      commands.onSortChange('date_taken');
      expect(store.setUserSort).toHaveBeenLastCalledWith('date_taken');
    });

    it('rechecks an exact pinned list before accepting a previously opened sort choice', async () => {
      const { fixture, root, store } = render();
      await openMenu(fixture, sortButtons(root)[0]);
      store.pinnedPaths.set(['/a.jpg']);
      const command = fixture.componentInstance as unknown as { onSortChange(sort: string): void };
      command.onSortChange('date_taken');
      expect(store.setUserSort).not.toHaveBeenCalled();
      store.pinnedPaths.set(null);
      command.onSortChange('date_taken');
      expect(store.setUserSort).toHaveBeenCalledExactlyOnceWith('date_taken');
    });

    it('hides them all while pinned, and brings them back when the pin clears', () => {
      const { fixture, root, store } = render();
      store.pinnedPaths.set(['/a.jpg']);
      fixture.detectChanges();
      expect(sortButtons(root)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.sort_desc)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(0);
      expect(byLabel(root, I18N.ui.buttons.filters)).toHaveLength(0);
      expect(byLabel(root, I18N.ui.filters.search)).toHaveLength(0);
      expect(byLabel(root, I18N.gallery.scan_action)).toHaveLength(0);
      expect(byLabel(root, I18N.slideshow.start).length).toBeGreaterThan(0);
      expect(byLabel(root, I18N.gallery.tooltip_mode.label).length).toBeGreaterThan(0);
      store.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(sortButtons(root)).toHaveLength(1);
      expect(byLabel(root, I18N.gallery.filters)).toHaveLength(1);
      expect(store.setFilterDrawerOpen).not.toHaveBeenCalled();
    });
    it.each([false, true])('marks the active preset, resets it and offers the dock only on desktop (%s)', async dock => {
      const { fixture, root, store } = render();
      const controls = fixture.componentInstance as unknown as { railCapable: { setMatches(value: boolean): void } };
      controls.railCapable.setMatches(dock);
      const preset = galleryPresentation('review', dock);
      store.filters.update(filters => ({ ...filters, ...preset }));
      store.galleryMode.set(preset.mode); store.cardWidth.set(preset.cardWidth); fixture.detectChanges();
      await openMenu(fixture, root.querySelector<HTMLButtonElement>('[data-display-presets]')!);
      const review = document.querySelector<HTMLButtonElement>('[data-display-preset="review"]')!;
      expect(review.getAttribute('aria-checked')).toBe('true');
      expect(iconOf(review)).toBe('check');
      document.querySelector<HTMLButtonElement>('[data-reset-display]')!.click();
      expect(store.applyDisplayPreset).toHaveBeenCalledExactlyOnceWith('default', dock);
      await openMenu(fixture, root.querySelector<HTMLButtonElement>(`[aria-label="${I18N.gallery.tooltip_mode.label}"]`)!);
      const labels = menuItems().map(item => item.textContent);
      expect(labels.some(label => label?.includes(I18N.gallery.tooltip_mode.panel))).toBe(dock);
    });

  });
