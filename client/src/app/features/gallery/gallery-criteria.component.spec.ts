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
import { GALLERY_REVISIT } from '../../core/gallery-reuse.strategy';
import { KeywordHierarchyLabels } from './keyword-hierarchy-labels.service';
function createCriteria(edition = false) {
 const navigation = new Subject<Event>();
 const filtersSignal=signal<GalleryFilters>({...DEFAULT_FILTERS});
 const personsSignal=signal<{id:number;name:string|null}[]>([]);
 const mockStore={filters:filtersSignal, persons:personsSignal, config:signal<any>(null), pinnedPaths:signal<string[]|null>(null), currentAlbum:signal(null), temporaryReviewQueue:signal(null), gpsLocationName:signal(''), updateFilter:vi.fn(),updateFilters:vi.fn(),resetFilters:vi.fn()};
 const mockRouter={events:navigation,navigate:vi.fn(),navigateByUrl:vi.fn()};
 const authStatus=signal<object|null>(null);
 const api = { get: vi.fn(() => of([])), post: vi.fn(() => of({})) };
 TestBed.configureTestingModule({imports:[GalleryCriteriaComponent],providers:[
 {provide:GalleryStore,useValue:mockStore},{provide:Router,useValue:mockRouter},
 {provide:AuthService,useValue:{isEdition:()=>edition,identity:()=> 'test',status:authStatus,token:null}},
 {provide:ApiService,useValue:api},
 {provide:MatDialog,useValue:{open:vi.fn(()=>({afterClosed:()=>of(null)}))}},
 {provide:MatSnackBar,useValue:{open:vi.fn()}},
 {provide:I18nService,useValue:{t:(key:string)=>key,translations:signal({}),lang:signal('en')}},
 ]});
 const fixture=TestBed.createComponent(GalleryCriteriaComponent);
 return {app:fixture.componentInstance,fixture,filtersSignal,personsSignal,mockStore,mockRouter,navigation,api,authStatus};
}
afterEach(()=>TestBed.resetTestingModule());
describe('zero-star quick refinement', () => {
 it('sets and clears only the two star bounds atomically and refuses parked commands', () => {
  const {app,fixture,filtersSignal,mockStore,navigation}=createCriteria(); fixture.detectChanges();
  const button=fixture.nativeElement.querySelector('[data-quick-zero-stars]') as HTMLButtonElement;
  button.click();
  expect(mockStore.updateFilters).toHaveBeenLastCalledWith({min_star_rating:'0',max_star_rating:'0'});
  expect(mockStore.updateFilter).not.toHaveBeenCalled();
  filtersSignal.set({...DEFAULT_FILTERS,camera:'Canon',min_star_rating:'0',max_star_rating:'0'});fixture.detectChanges();
  expect(button.getAttribute('aria-pressed')).toBe('true');
  button.click();expect(mockStore.updateFilters).toHaveBeenLastCalledWith({min_star_rating:'',max_star_rating:''});
  mockStore.updateFilters.mockClear();
  navigation.next(new NavigationStart(1,'/persons'));button.click();expect(mockStore.updateFilters).not.toHaveBeenCalled();
  app.setActive(false);button.click();expect(mockStore.updateFilters).not.toHaveBeenCalled();
 });
});
describe('recent collection visits',()=>{
 it('lets Escape leave a closed inner disclosure so the enclosing mobile menu can close',()=>{
  const {fixture}=createCriteria();fixture.detectChanges();
  const root=fixture.nativeElement as HTMLElement;
  const details=root.querySelector<HTMLDetailsElement>('details')!;
  const summary=details.querySelector<HTMLElement>('summary')!;
  const outerEscape=vi.fn();root.addEventListener('keydown',outerEscape);
  summary.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  expect(outerEscape).toHaveBeenCalledOnce();
  outerEscape.mockClear();details.open=true;
  summary.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  expect(details.open).toBe(false);
  expect(outerEscape).not.toHaveBeenCalled();
  summary.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  expect(outerEscape).toHaveBeenCalledOnce();
 });
 it('does not duplicate a query already visible in the collection search, while retaining other criteria',()=>{
  const {fixture,filtersSignal}=createCriteria();
  fixture.componentRef.setInput('searchPresented',true);
  filtersSignal.update(filters=>({...filters,search:'coast'}));fixture.detectChanges();
  const root=fixture.nativeElement as HTMLElement;
  expect(root.querySelector('[data-active-criteria]')).toBeNull();
  filtersSignal.update(filters=>({...filters,tag:'birds'}));fixture.detectChanges();
  expect(root.querySelector('[data-active-criteria]')?.textContent).toContain('birds');
  expect(root.querySelector('[data-active-criteria]')?.textContent).not.toContain('coast');
 });
 it('records completed collection navigation and restores its exact query without requiring editing',()=>{
  const {fixture,navigation,mockRouter,authStatus}=createCriteria(false);
  authStatus.set({authenticated:true});
  fixture.detectChanges();
  navigation.next(new NavigationStart(1,'/?tag=forest&min_score=0&max_score=8&sort=date_taken'));
  navigation.next(new NavigationEnd(1,'/?tag=forest','/?tag=forest&min_score=0&max_score=8&sort=date_taken'));
  fixture.detectChanges();
  const root=fixture.nativeElement as HTMLElement;
  const details=root.querySelector<HTMLDetailsElement>('[data-recent-collections]')!;
  details.open=true;
  const button=details.querySelector<HTMLButtonElement>('[data-recent-visit]')!;
  expect(button.textContent).toContain('forest');
  button.click();
  expect(mockRouter.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/?max_score=8&min_score=0&sort=date_taken&tag=forest',{info:GALLERY_REVISIT,onSameUrlNavigation:'reload'});
  expect(details.open).toBe(false);
 });

 it('does not record cancelled visits or allow a captured history action while parked or after logout',()=>{
  const {app,fixture,navigation,mockRouter,authStatus}=createCriteria();
  authStatus.set({authenticated:true});fixture.detectChanges();
  navigation.next(new NavigationEnd(1,'/?tag=first','/?tag=first'));fixture.detectChanges();
  const root=fixture.nativeElement as HTMLElement;
  const button=root.querySelector<HTMLButtonElement>('[data-recent-visit]')!;
  navigation.next(new NavigationStart(2,'/?tag=cancelled'));
  navigation.next(new NavigationCancel(2,'/?tag=cancelled','cancelled',NavigationCancellationCode.GuardRejected));
  fixture.detectChanges();
  expect(root.querySelectorAll('[data-recent-visit]')).toHaveLength(1);
  app.setActive(false);button.click();
  expect(mockRouter.navigateByUrl).not.toHaveBeenCalled();
  app.setActive(true);authStatus.set(null);button.click();
  expect(mockRouter.navigateByUrl).not.toHaveBeenCalled();
  fixture.detectChanges();
  expect(root.querySelector('[data-recent-collections]')).toBeNull();
 });
});
describe('activeFilterChips', () => {;
    it('resolves keyword labels at rendering after token-only changes even when the criteria array is cached', () => {
      const { app, fixture, filtersSignal, authStatus } = createCriteria();
      authStatus.set({ authenticated: true });
      const id = '11111111-1111-4111-8111-111111111111';
      filtersSignal.set({ ...DEFAULT_FILTERS, keyword_branch: id });
      TestBed.inject(KeywordHierarchyLabels).remember([{ id, segments: ['Private', 'Family'] }]);
      const readNames = vi.spyOn(TestBed.inject(KeywordHierarchyLabels), 'names');
      fixture.detectChanges();
      const cached = (app as any).activeFilterChips();
      expect(fixture.nativeElement.querySelector('[data-active-criteria]').textContent).toContain('Private › Family');
      Object.assign(TestBed.inject(AuthService), { token: 'rotated-only' });
      expect(TestBed.inject(KeywordHierarchyLabels).names()).toEqual({});
      const callsBefore = readNames.mock.calls.length;
      fixture.detectChanges();
      expect(readNames.mock.calls.length, 'render must execute the impure label guard').toBeGreaterThan(callsBefore);
      expect((app as any).activeFilterChips()).toBe(cached);
      expect(fixture.nativeElement.querySelector('[data-active-criteria]').textContent).not.toContain('Private › Family');
      expect(fixture.nativeElement.textContent).not.toContain('Private › Family');
      expect(fixture.nativeElement.querySelector('[data-active-criteria] [title]')?.getAttribute('title')).not.toBe('Private › Family');
      expect(fixture.nativeElement.querySelector('[data-active-criteria]').textContent).toContain(I18N.keyword_hierarchy.unavailable);
    });

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

  it('shows literal metadata values and ALL-person logic without writing filters or duplicating editable person owners', () => {
    const {fixture, filtersSignal, personsSignal, mockStore}=createCriteria();
    personsSignal.set([{id:1,name:'Alice'},{id:2,name:'Bob'}]);
    filtersSignal.update(f=>({...f,search:'red OR blue',tag:'coast, ridge',camera:'Example Camera',person_id:'1,2',min_score:'0',max_score:'8'}));
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    const details=root.querySelector<HTMLDetailsElement>('[data-match-logic]')!;
    expect(details).not.toBeNull(); details.open=true;
    expect(details.querySelector('[data-logic-row="search"]')?.textContent).toContain('red OR blue');
    expect(details.querySelector('[data-logic-row="tag"]')?.textContent).toContain('coast, ridge');
    expect(details.querySelector('[data-logic-row="min_score"]')?.textContent).toContain('0–8');
    expect(details.querySelector('[data-logic-people]')?.textContent).toContain(I18N.gallery.criteria.logic.all_people);
    expect(details.querySelector('[data-logic-people]')?.textContent).toContain('Alice');
    expect(details.querySelector('[data-logic-people]')?.textContent).toContain('Bob');
    expect(details.querySelectorAll('app-person-filter-chip')).toHaveLength(0);
    expect(root.querySelectorAll('app-person-filter-chip')).toHaveLength(2);
    expect(details.querySelector('[data-logic-text]')).not.toBeNull();
    expect(details.querySelector('[data-logic-tag]')).not.toBeNull();
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
  });

  it('closes Match logic with Escape focus recovery and removes its metadata when parking or navigating', async () => {
    const {app,fixture,filtersSignal,navigation}=createCriteria();
    filtersSignal.update(f=>({...f,search:'private term'})); fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    let details=root.querySelector<HTMLDetailsElement>('[data-match-logic]')!;
    details.open=true; details.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    expect(details.open).toBe(false);
    expect(details.ownerDocument.activeElement).toBe(details.querySelector('summary'));
    details.open=true;
    navigation.next(new NavigationStart(1,'/photo')); fixture.detectChanges();
    expect(details.open).toBe(false);
    expect(root.querySelector('[data-match-logic]')).toBeNull();
    navigation.next(new NavigationEnd(2,'/photo','/photo')); fixture.detectChanges();
    details=root.querySelector<HTMLDetailsElement>('[data-match-logic]')!;
    expect(details.open).toBe(false); details.open=true;
    app.setActive(false); fixture.detectChanges();
    expect(details.open).toBe(false);
    expect(root.querySelector('[data-match-logic]')).toBeNull();
    app.setActive(true); fixture.detectChanges();
    expect(root.querySelector('[data-match-logic]')).not.toBeNull();
  });

  it('separates working smart criteria, manual membership and hidden metric values', () => {
    const {fixture, filtersSignal, mockStore}=createCriteria();
    mockStore.config.set({unavailable_metrics:['liqe_score']});
    filtersSignal.update(f=>({...f,min_liqe:'4',burst_group_id:'12'})); fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-logic-hidden]')?.textContent).toContain(I18N.gallery.criteria.logic.hidden_values);
    expect(root.querySelector('[data-logic-set]')).not.toBeNull();
    expect(root.querySelector('[data-logic-row="min_liqe"]')).toBeNull();
    mockStore.currentAlbum.set({id:1,name:'Smart',is_smart:true,smart_filter_json:'{}'} as any); fixture.detectChanges();
    expect(root.querySelector('[data-logic-album]')?.textContent).toContain(I18N.gallery.criteria.logic.smart_album);
    mockStore.currentAlbum.set({id:1,name:'Manual',is_smart:false,smart_filter_json:null} as any); fixture.detectChanges();
    expect(root.querySelector('[data-logic-album]')?.textContent).toContain(I18N.gallery.criteria.logic.manual_album);
  });

  it('labels retained Similar Photos criteria as paused and never promises album or metadata matching', () => {
    const {fixture,filtersSignal,personsSignal,mockStore}=createCriteria();
    personsSignal.set([{id:1,name:'Alice'}]);
    mockStore.currentAlbum.set({id:9,name:'Manual',is_smart:false,smart_filter_json:null} as any);
    filtersSignal.update(f=>({...f,similar_to:'/source.jpg',album_id:'9',camera:'Alpha',search:'holiday',person_id:'1',hide_rejected:true}));
    fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    const details=root.querySelector<HTMLDetailsElement>('[data-match-logic]')!;
    expect(details.textContent).toContain(I18N.gallery.criteria.logic.similar_paused);
    expect(details.querySelector('[data-logic-row="camera"]')?.textContent).toContain('Alpha');
    expect(details.querySelector('[data-logic-people]')?.textContent).toContain(I18N.gallery.criteria.logic.paused_people);
    expect(details.querySelector('[data-logic-album]')).toBeNull();
    expect(details.querySelector('[data-logic-text]')).toBeNull();
    expect(root.querySelector('[data-query-explanation]')?.textContent).toContain(I18N.gallery.criteria.logic.similar_help);
    expect(root.querySelector('[data-active-criteria]')?.textContent).not.toContain('Alpha');
    expect(root.querySelector('[data-active-criteria]')?.textContent).not.toContain('holiday');
    expect(root.querySelector('[data-visibility-summary]')).toBeNull();
    expect(details.textContent).toContain(I18N.gallery.criteria.logic.paused_visibility);
    filtersSignal.update(f=>({...f,similar_to:''})); fixture.detectChanges();
    expect(root.querySelector('[data-active-criteria]')?.textContent).toContain('Alpha');
    expect(root.querySelector('[data-visibility-summary]')).not.toBeNull();
  });

  it('separates configured photo-type defaults from the AND list of explicit working values', () => {
    const {fixture,filtersSignal}=createCriteria();
    filtersSignal.update(f=>({...f,type:'portrait',min_face_count:'0'})); fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-logic-type]')?.textContent).toContain(I18N.gallery.criteria.logic.type_defaults);
    expect(root.querySelector('[data-logic-row="type"]')).toBeNull();
    expect(root.querySelector('[data-logic-row="min_face_count"]')?.textContent).toContain('≥0');
  });

  it('shows ANY-person semantics in both the active group and Match logic while preserving individual removal', () => {
    const {fixture,filtersSignal,personsSignal,mockStore}=createCriteria();
    personsSignal.set([{id:1,name:'Alice'},{id:2,name:'Bob'}]);
    filtersSignal.update(f=>({...f,person_id:'1,2',person_match:'any'})); fixture.detectChanges();
    const root=fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-person-match-summary]')?.textContent).toContain(I18N.gallery.people_match.any);
    expect(root.querySelector('[data-logic-people]')?.textContent).toContain(I18N.gallery.criteria.logic.any_people);
    expect(root.querySelectorAll('app-person-filter-chip')).toHaveLength(2);
    (fixture.componentInstance as any).clearFilterChip({id:'person_1',clearKeys:['person_1']});
    expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('person_id','2');
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
  it('renders measurement, tag, location, sequence, search and album criteria with their exact removal targets', () => {
    const { fixture, app, filtersSignal, mockStore } = createCriteria();
    mockStore.currentAlbum.set({ id: 9, name: 'Weekend' } as any);
    mockStore.gpsLocationName.set('Park');
    filtersSignal.set({ ...DEFAULT_FILTERS, album_id: '9', semanticQuery: 'red boat', search_threshold: '60',
      score_presence: '{"min_sharpness":"missing_only"}', min_sharpness: '4',
      tag_groups: '{"all":["coast"],"any":["ridge"],"none":["rain"]}',
      gps_lat: '0.5', gps_lng: '12.3', gps_radius_km: '5', sequence_override: 'pending' });
    fixture.detectChanges();
    const chips = (app as any).activeFilterChips() as { id: string; value: string; clearKeys: string[] }[];
    const chip = (id: string) => chips.find(row => row.id === id)!;
    expect(chip('album')).toMatchObject({ value: 'Weekend', clearKeys: ['album_id'] });
    expect(chip('semanticQuery').value).toBe('red boat');
    expect(chip('search_threshold').value).toBe('60%');
    expect(chip('score_presence').value).toContain(I18N.gallery.measurements.missing_only);
    expect(chips.some(row => row.id === 'min_sharpness')).toBe(false);
    expect(chip('tag_groups').value).toContain('"coast"');
    expect(chip('tag_groups').value).toContain('"rain"');
    expect(chip('gps')).toMatchObject({ value: 'Park — 5 km', clearKeys: ['gps_lat', 'gps_lng', 'gps_radius_km'] });
    expect(chip('sequence_override').value).toBe('gallery.sequence_override.pending');
    (app as any).clearFilterChip(chip('gps'));
    expect(mockStore.updateFilters).toHaveBeenCalledExactlyOnceWith({ gps_lat: '', gps_lng: '', gps_radius_km: '' });
    expect(fixture.nativeElement.querySelector('[data-active-criteria]').textContent).toContain('Weekend');
    filtersSignal.update(current => ({ ...current, score_presence: 'bad json', tag_groups: 'bad json', album_id: '99', gps_radius_km: '' }));
    mockStore.currentAlbum.set(null); mockStore.gpsLocationName.set(''); fixture.detectChanges();
    const next = (app as any).activeFilterChips() as { id: string; value: string }[];
    expect(next.find(row => row.id === 'album')?.value).toBe('#99');
    expect(next.find(row => row.id === 'score_presence')?.value).toBe(I18N.gallery.measurements.invalid);
    expect(next.find(row => row.id === 'tag_groups')?.value).toBe(I18N.gallery.tag_groups.invalid);
    expect(next.find(row => row.id === 'gps')?.value).toBe('0.50, 12.30');
  });

  it.each(['favorites', 'undecided', 'kept', 'rejected'] as const)('toggles %s refinements without changing unrelated fields', command => {
    const { app, fixture, filtersSignal, mockStore } = createCriteria(); fixture.detectChanges();
    const key = command === 'favorites' ? 'favorites_only' : 'review_status';
    (app as any).quickFilter(command);
    expect(mockStore.updateFilter).toHaveBeenLastCalledWith(key, command === 'favorites' ? true : command);
    filtersSignal.update(current => ({ ...current, [key]: command === 'favorites' ? true : command, camera: 'Alpha' }));
    fixture.detectChanges(); (app as any).quickFilter(command);
    expect(mockStore.updateFilter).toHaveBeenLastCalledWith(key, command === 'favorites' ? false : '');
    expect(filtersSignal().camera).toBe('Alpha');
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
    app.setActive(false); mockStore.updateFilter.mockClear(); (app as any).quickFilter(command);
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
  });

});
