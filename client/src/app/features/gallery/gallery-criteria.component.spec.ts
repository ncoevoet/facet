import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationStart, Router, Event } from '@angular/router';
import { of, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { GalleryCriteriaComponent } from './gallery-criteria.component';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
function createCriteria(edition = false) {
 const navigation = new Subject<Event>();
 const filtersSignal=signal<GalleryFilters>({...DEFAULT_FILTERS});
 const personsSignal=signal<{id:number;name:string|null}[]>([]);
 const mockStore={filters:filtersSignal, persons:personsSignal, config:signal<any>(null), pinnedPaths:signal<string[]|null>(null), currentAlbum:signal(null), gpsLocationName:signal(''), updateFilter:vi.fn(),updateFilters:vi.fn(),resetFilters:vi.fn()};
 const mockRouter={events:navigation,navigate:vi.fn()};
 const api = { get: vi.fn(() => of([])), post: vi.fn(() => of({})) };
 TestBed.configureTestingModule({imports:[GalleryCriteriaComponent],providers:[
 {provide:GalleryStore,useValue:mockStore},{provide:Router,useValue:mockRouter},
 {provide:AuthService,useValue:{isEdition:()=>edition,identity:()=> 'test',status:()=>null}},
 {provide:ApiService,useValue:api},
 {provide:MatDialog,useValue:{open:vi.fn(()=>({afterClosed:()=>of(null)}))}},
 {provide:MatSnackBar,useValue:{open:vi.fn()}},
 {provide:I18nService,useValue:{t:(key:string)=>key,translations:signal({}),lang:signal('en')}},
 ]});
 const fixture=TestBed.createComponent(GalleryCriteriaComponent);
 return {app:fixture.componentInstance,fixture,filtersSignal,personsSignal,mockStore,mockRouter,navigation,api};
}
afterEach(()=>TestBed.resetTestingModule());
describe('activeFilterChips', () => {;

    it('returns empty array when no active filters', () => {
      const { app } = createCriteria();
      expect((app as any).activeFilterChips()).toEqual([]);
    });

    it('produces chip for active tag filter', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, tag: 'nature' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'tag');
      expect(chip).toBeDefined();
      expect(chip?.value).toBe('nature');
    });

    it('produces chip for active search filter', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, search: 'paris' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'search');
      expect(chip?.value).toBe('paris');
    });

    it('produces chip for active camera filter', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, camera: 'Canon R5' });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'camera' && c.value === 'Canon R5')).toBe(true);
    });

    it('produces one chip per person in comma-separated person_id', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      const personChips = (app as any).activeFilterChips().filter((c: any) => c.id.startsWith('person_'));
      expect(personChips).toHaveLength(3);
      expect(personChips.map((c: any) => c.id)).toEqual(['person_1', 'person_2', 'person_3']);
    });

    it('uses person name when available', () => {
      const { app, filtersSignal, personsSignal } = createCriteria();
      personsSignal.set([{ id: 1, name: 'Alice' }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_1');
      expect(chip?.value).toBe('Alice');
    });

    it('falls back to #pid when person name is null', () => {
      const { app, filtersSignal, personsSignal } = createCriteria();
      personsSignal.set([{ id: 2, name: null }]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '2' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_2');
      expect(chip?.value).toBe('#2');
    });

    it('falls back to #pid when person is not in persons list', () => {
      const { app, filtersSignal, personsSignal } = createCriteria();
      personsSignal.set([]);
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '99' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'person_99');
      expect(chip?.value).toBe('#99');
    });

    it('shows min–max format when both range bounds are set', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '6', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('6–9');
    });

    it('shows ≥min format when only min bound is set', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '7', max_score: '' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≥7');
    });

    it('shows ≤max format when only max bound is set', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '', max_score: '8' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.value).toBe('≤8');
    });

    it('range chip clearKeys includes both min and max keys', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score');
      expect(chip?.clearKeys).toEqual(['min_score', 'max_score']);
    });

    it('produces chip for favorites_only = true', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, favorites_only: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(true);
    });

    it('does not produce chip for favorites_only = false', () => {
      const { app } = createCriteria();
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'favorites_only')).toBe(false);
    });

    it('produces chip for is_monochrome = true', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, is_monochrome: true });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'is_monochrome')).toBe(true);
    });

    it('shows the manual-face review filter only while it is active', () => {
      const { app, filtersSignal } = createCriteria();
      expect((app as any).activeFilterChips().some((chip: { id: string }) => chip.id === 'manual_faces_need_review')).toBe(false);
      filtersSignal.update(filters => ({ ...filters, manual_faces_need_review: true }));
      expect((app as any).activeFilterChips()).toContainEqual({
        id: 'manual_faces_need_review', labelKey: I18N.gallery.manual_faces_need_review,
        value: '', clearKeys: ['manual_faces_need_review'],
      });
      filtersSignal.update(filters => ({ ...filters, manual_faces_need_review: false }));
      expect((app as any).activeFilterChips().some((chip: { id: string }) => chip.id === 'manual_faces_need_review')).toBe(false);
    });

    it('topiq chip uses gallery.topiq_range (not aesthetic_range)', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', max_topiq: '' });
      const topiqChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_topiq');
      expect(topiqChip?.labelKey).toBe('gallery.topiq_range');
    });

    it('aesthetic chip uses gallery.aesthetic_range', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_aesthetic: '5', max_aesthetic: '' });
      const aestheticChip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_aesthetic');
      expect(aestheticChip?.labelKey).toBe('gallery.aesthetic_range');
    });

    it('topiq and aesthetic chips have distinct label keys', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_topiq: '5', min_aesthetic: '5', max_topiq: '', max_aesthetic: '' });
      const chips = (app as any).activeFilterChips();
      const topiq = chips.find((c: any) => c.id === 'min_topiq');
      const aesthetic = chips.find((c: any) => c.id === 'min_aesthetic');
      expect(topiq?.labelKey).not.toBe(aesthetic?.labelKey);
    });
  });
describe('clearFilterChip', () => {
    it('clears the manual-face review flag as a boolean and preserves other filters', () => {
      const { app, filtersSignal, mockStore } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, manual_faces_need_review: true, person_id: '7', min_score: '5' });
      mockStore.updateFilters.mockImplementation((updates: Partial<GalleryFilters>) => {
        filtersSignal.update(filters => ({ ...filters, ...updates }));
      });
      const chip = (app as any).activeFilterChips().find((item: { id: string }) => item.id === 'manual_faces_need_review');
      expect(chip).toBeDefined();
      (app as any).clearFilterChip(chip);
      expect(mockStore.updateFilters).toHaveBeenCalledExactlyOnceWith({ 'manual_faces_need_review': false });
      expect(filtersSignal()).toMatchObject({ manual_faces_need_review: false, person_id: '7', min_score: '5' });
      expect((app as any).activeFilterChips().map((item: { id: string }) => item.id)).toEqual(['person_7', 'min_score']);
    });
    it('removes one person without affecting other person ids', () => {
      const { app, filtersSignal, mockStore } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '1,2,3' });
      (app as any).clearFilterChip({ id: 'person_2', clearKeys: ['person_2'] });
      expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('person_id', '1,3');
    });

    it('sets person_id to empty string when last person is removed', () => {
      const { app, filtersSignal, mockStore } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, person_id: '5' });
      (app as any).clearFilterChip({ id: 'person_5', clearKeys: ['person_5'] });
      expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('person_id', '');
    });

    it('calls updateFilters with false for favorites_only', () => {
      const { app, mockStore } = createCriteria();
      (app as any).clearFilterChip({ id: 'favorites_only', clearKeys: ['favorites_only'] });
      expect(mockStore.updateFilters).toHaveBeenCalledWith({ 'favorites_only': false });
    });

    it('calls updateFilters with false for is_monochrome', () => {
      const { app, mockStore } = createCriteria();
      (app as any).clearFilterChip({ id: 'is_monochrome', clearKeys: ['is_monochrome'] });
      expect(mockStore.updateFilters).toHaveBeenCalledWith({ 'is_monochrome': false });
    });

    it('calls updateFilters with empty string for string filters', () => {
      const { app, mockStore } = createCriteria();
      (app as any).clearFilterChip({ id: 'tag', clearKeys: ['tag'] });
      expect(mockStore.updateFilters).toHaveBeenCalledWith({ 'tag': '' });
    });

    it('calls updateFilters for both min and max keys of a range chip', () => {
      const { app, filtersSignal, mockStore } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_score: '5', max_score: '9' });
      const chip = (app as any).activeFilterChips().find((c: any) => c.id === 'min_score')!;
      (app as any).clearFilterChip(chip);
      expect(mockStore.updateFilters).toHaveBeenCalledExactlyOnceWith({ min_score: '', max_score: '' });
    });
  });
describe('activeFilterChips with unavailable metrics', () => {
    it('shows a LIQE chip in default mode', () => {
      const { app, filtersSignal } = createCriteria();
      filtersSignal.set({ ...DEFAULT_FILTERS, min_liqe: '4' });
      expect((app as any).activeFilterChips().some((c: any) => c.id === 'min_liqe')).toBe(true);
    });

    it('skips chips for metrics the licensing policy hides', () => {
      const { app, filtersSignal, mockStore } = createCriteria();
      (mockStore.config as any).set({ unavailable_metrics: ['liqe_score', 'aesthetic_iaa'] });
      filtersSignal.set({ ...DEFAULT_FILTERS, min_liqe: '4', min_aesthetic_iaa: '5', min_score: '6' });
      const ids = (app as any).activeFilterChips().map((c: any) => c.id);
      expect(ids).toContain('min_score');
      expect(ids).not.toContain('min_liqe');
      expect(ids).not.toContain('min_aesthetic_iaa');
    });
  });

describe('collection criteria ownership and full disclosure', () => {
  it('destroys an editable person chip when navigation begins and recreates it without its old editor on return', async () => {
    const {fixture,filtersSignal,personsSignal,navigation,api}=createCriteria(true);
    personsSignal.set([{id:1,name:'Alice'}]);
    filtersSignal.update(f=>({...f,person_id:'1'}));
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('app-person-filter-chip')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-person-name-edit]')!.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(root.querySelector('[data-person-name-input]')).not.toBeNull();
    const save=root.querySelector<HTMLButtonElement>('[data-person-name-save]')!;
    navigation.next(new NavigationStart(1,'/photo'));
    fixture.detectChanges();
    expect(root.querySelector('app-person-filter-chip')).toBeNull();
    save.click();
    expect(api.post).not.toHaveBeenCalled();
    navigation.next(new NavigationEnd(2,'/','/'));
    fixture.detectChanges();
    expect(root.querySelector('app-person-filter-chip')).not.toBeNull();
    expect(root.querySelector('[data-person-name-input]')).toBeNull();
  });
  it('closes quick disclosures and blocks captured commands while parked or navigating, then reactivates', () => {
    const {app,fixture,mockStore,navigation}=createCriteria();
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    const details=root.querySelector<HTMLDetailsElement>('details')!;
    const favorites=details.querySelector<HTMLButtonElement>('button')!;
    details.open=true;
    app.setActive(false);
    expect(details.open).toBe(false);
    favorites.click();
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
    app.setActive(true);
    favorites.click();
    expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('favorites_only',true);
    mockStore.updateFilter.mockClear();
    details.open=true;
    navigation.next(new NavigationStart(1,'/?tag=other'));
    expect(details.open).toBe(false);
    favorites.click();
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
    navigation.next(new NavigationCancel(1,'/?tag=other','redirect',NavigationCancellationCode.Redirect));
    favorites.click();
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
    navigation.next(new NavigationEnd(2,'/','/'));
    favorites.click();
    expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('favorites_only',true);
  });

  it('discloses a fixed list and refuses query changes from stale criteria callbacks', () => {
    const {app,fixture,mockStore}=createCriteria();
    mockStore.pinnedPaths.set(['/fixed']);
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-criteria-pinned]')?.textContent).toContain(I18N.gallery.criteria.pinned);
    expect(root.querySelector('details')).toBeNull();
    (app as any).quickFilter('kept');
    (app as any).clearFilterChip({id:'tag',clearKeys:['tag']});
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
  });

  it('renders decision, type, missing location and clipping criteria with a named atomic clear', () => {
    const {fixture,filtersSignal,mockStore}=createCriteria();
    filtersSignal.update(f=>({...f,review_status:'kept',type:'portrait',no_gps:'1',min_channel_clip_shadow:'0',max_channel_clip_shadow:'10'}));
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-active-criteria]')?.textContent).toContain(I18N.gallery.sidebar.review.decision);
    expect(root.textContent).toContain(I18N.gallery.criteria.no_location);
    expect(root.textContent).toContain(I18N.gallery.channel_clip_shadow_range);
    const button=root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.gallery.criteria.remove}"]`)!;
    expect(button).not.toBeNull();
    const clip=Array.from(root.querySelectorAll<HTMLButtonElement>('[data-active-criteria] button')).find(b=>b.parentElement?.textContent?.includes(I18N.gallery.channel_clip_shadow_range))!;
    clip.click();
    expect(mockStore.updateFilters).toHaveBeenCalledExactlyOnceWith({min_channel_clip_shadow:'',max_channel_clip_shadow:''});
  });

  it('shows only effective visibility rules and formats camera-local date boundaries', () => {
    const {app,filtersSignal}=createCriteria();
    filtersSignal.update(f=>({...f,hide_blinks:true,hide_bursts:true,hide_rejected:true,review_status:'kept',blinks_only:true,date_from:'2026-10-31',date_to:'2026-11-02'}));
    expect((app as any).visibilityRules()).toEqual([]);
    const date=(app as any).activeFilterChips().find((chip:any)=>chip.id==='date_from');
    expect(date.value).toBe('31/10/2026–02/11/2026');
    filtersSignal.update(f=>({...f,blinks_only:false}));
    expect((app as any).visibilityRules().some((rule:any)=>rule.id==='hide_bursts')).toBe(true);
    expect((app as any).visibilityRules().some((rule:any)=>rule.id==='hide_rejected')).toBe(false);
    filtersSignal.update(f=>({...f,show_rejected:true}));
    expect((app as any).visibilityRules()).toEqual([]);
  });

  it('shows visual search semantics in the page text alongside exact text criteria', () => {
    const {fixture,filtersSignal}=createCriteria();
    filtersSignal.update(f=>({...f,semanticQuery:'red boat',search:'holiday'}));
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-query-explanation]')?.textContent).toContain(I18N.gallery.criteria.ranked_help);
    expect(root.querySelector('[data-active-criteria]')?.textContent).toContain('red boat');
    expect(root.querySelector('[data-active-criteria]')?.textContent).toContain('holiday');
  });
});
