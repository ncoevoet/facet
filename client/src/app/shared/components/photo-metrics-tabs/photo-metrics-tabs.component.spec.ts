import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatTabGroup } from '@angular/material/tabs';
import { PhotoMetricsTabsComponent } from './photo-metrics-tabs.component';
import { MetricsTabState } from '../../../core/services/metrics-tab-state.service';
import { I18nService } from '../../../core/services/i18n.service';
import type { Photo } from '../../models/photo.model';
import { makePhoto } from '../../../../testing/photo.fixture';

const TAB_KEY = 'facet_photo_detail_tab';
const NO_EXIF = { camera_model: null, lens_model: null, focal_length: null, f_stop: null, shutter_speed: null, iso: null };

describe('PhotoMetricsTabsComponent', () => {
  let fixture: ComponentFixture<PhotoMetricsTabsComponent>;

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.removeItem(TAB_KEY);
  });

  function render(photo: Photo): void {
    TestBed.configureTestingModule({
      imports: [PhotoMetricsTabsComponent],
      providers: [{ provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}), locale: signal('en') } }],
    });
    fixture = TestBed.createComponent(PhotoMetricsTabsComponent);
    fixture.componentRef.setInput('photo', photo);
    fixture.componentRef.setInput('histogramHeight', 80);
    fixture.detectChanges();
  }

  function showPhoto(photo: Photo): void {
    fixture.componentRef.setInput('photo', photo);
    fixture.detectChanges();
  }

  const selectedIndex = () => fixture.debugElement.query(By.directive(MatTabGroup)).componentInstance.selectedIndex;

  it('shows the EXIF tab for a photo whose only file fact is its size', () => {
    render(makePhoto({ ...NO_EXIF, file_size: 1234 }));
    expect(fixture.nativeElement.querySelector('app-photo-metric-section[kind="exif"]')).not.toBeNull();
    expect(selectedIndex()).toBe(0);
  });

  it('threads explainable to the assessment and re-emits its explain click', () => {
    render(makePhoto({ camera_model: 'X100V' }));
    expect(fixture.nativeElement.querySelector('[data-explain-score]')).toBeNull();
    fixture.componentRef.setInput('explainable', true);
    fixture.detectChanges();
    const spy = vi.fn();
    fixture.componentInstance.explain.subscribe(spy);
    fixture.nativeElement.querySelector('[data-explain-score]').click();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('opens the EXIF tab when the stored tab is unknown', () => {
    localStorage.setItem(TAB_KEY, 'bogus');
    render(makePhoto({ camera_model: 'X100V' }));
    expect(TestBed.inject(MetricsTabState).tab()).toBe('exif');
    expect(selectedIndex()).toBe(0);
  });

  it('keeps the same tab by name when a photo without EXIF drops the EXIF tab', () => {
    localStorage.setItem(TAB_KEY, 'technical');
    render(makePhoto({ camera_model: 'X100V' }));
    expect(selectedIndex()).toBe(3);
    showPhoto(makePhoto(NO_EXIF));
    expect(selectedIndex()).toBe(2);
  });

  it('does not overwrite a remembered EXIF tab while showing a photo that has none', async () => {
    localStorage.setItem(TAB_KEY, 'exif');
    render(makePhoto({ camera_model: 'X100V' }));
    showPhoto(makePhoto(NO_EXIF));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(localStorage.getItem(TAB_KEY)).toBe('exif');
    showPhoto(makePhoto({ camera_model: 'X100V' }));
    expect(selectedIndex()).toBe(0);
  });

  it('keeps EXIF chosen elsewhere while this panel shows a photo without any', async () => {
    localStorage.setItem(TAB_KEY, 'technical');
    render(makePhoto(NO_EXIF));
    TestBed.inject(MetricsTabState).select('exif');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(TestBed.inject(MetricsTabState).tab()).toBe('exif');
    expect(localStorage.getItem(TAB_KEY)).toBe('exif');
  });

  it('remembers a tab the user picks', async () => {
    render(makePhoto({ camera_model: 'X100V' }));
    (fixture.nativeElement.querySelectorAll('[role="tab"]')[2] as HTMLElement).click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(TestBed.inject(MetricsTabState).tab()).toBe('composition');
    expect(localStorage.getItem(TAB_KEY)).toBe('composition');
  });

  it('still switches the tab when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    render(makePhoto({ camera_model: 'X100V' }));
    const state = TestBed.inject(MetricsTabState);
    expect(state.tab()).toBe('exif');
    state.select('histogram');
    expect(state.tab()).toBe('histogram');
  });
});
