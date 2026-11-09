import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { AssessmentPhoto, PhotoAssessmentComponent } from './photo-assessment.component';

describe('PhotoAssessmentComponent', () => {
  function render(photo: AssessmentPhoto) {
    TestBed.configureTestingModule({
      imports: [PhotoAssessmentComponent],
      providers: [{ provide: I18nService, useValue: { t: (key: string, params?: Record<string, unknown>) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } }],
    });
    const fixture = TestBed.createComponent(PhotoAssessmentComponent);
    fixture.componentRef.setInput('photo', photo);
    fixture.componentRef.setInput('range', { min: 0, max: 10, buckets: [1, 1] });
    fixture.detectChanges();
    return fixture;
  }

  it('shows missing and non-finite evidence as unavailable without a rank, preserving actual zero scores', () => {
    const fixture = render({ aggregate: null, aesthetic: 0, tech_sharpness: NaN, comp_score: null, face_quality: undefined });
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('summary')?.textContent).toContain('photo_detail.assessment.unavailable');
    expect(el.querySelector('summary')?.textContent).toContain('"available":1,"total":4');
    expect(el.querySelectorAll('dd')[0].textContent).toContain('0.0');
    expect(Array.from(el.querySelectorAll('dd')).slice(1).every(row => row.textContent?.includes('photo_detail.assessment.unavailable'))).toBe(true);
    expect(el.querySelector('app-metric-rank')).toBeNull();
    fixture.componentRef.setInput('photo', { aggregate: 0, aesthetic: 0 });
    fixture.detectChanges();
    expect(el.querySelector('summary')?.textContent).toContain('0.0');
    expect(el.querySelector('app-metric-rank')).not.toBeNull();
  });

  it('counts only measurements present in the smaller review feed and discloses a group suggestion separately', () => {
    const fixture = render({ aggregate: 7, aesthetic: 8, tech_sharpness: null });
    fixture.componentRef.setInput('groupPick', true);
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('summary')?.textContent).toContain('"available":1,"total":2');
    expect(el.querySelectorAll('dt')).toHaveLength(2);
    expect(el.textContent).toContain('photo_detail.assessment.group_pick_help');
    expect(el.textContent).not.toContain('photo_detail.assessment.explanation');
    expect(el.textContent).not.toContain('photo_detail.assessment.unavailable_help');
    expect(el.querySelector('app-context-help')).not.toBeNull();
  });
  it('distinguishes a current model decline from unknown missing evidence and real zero', () => {
    const fixture = render({ aggregate: 7, face_quality_iqa: null,
      assessment_states: { face_quality_iqa: 'not_applicable' } });
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('dd')?.textContent).toContain('photo_detail.assessment.not_applicable');
    expect(el.querySelector('dd span')?.getAttribute('title')).toBe('photo_detail.assessment.face_iqa_declined_help');
    fixture.componentRef.setInput('photo', { aggregate: 7, face_quality_iqa: null });
    fixture.detectChanges();
    expect(el.querySelector('dd')?.textContent).toContain('photo_detail.assessment.unavailable');
    fixture.componentRef.setInput('photo', { aggregate: 7, face_quality_iqa: 0,
      assessment_states: { face_quality_iqa: 'not_applicable' } });
    fixture.detectChanges();
    expect(el.querySelector('dd')?.textContent).toContain('0.0');
    expect(el.querySelector('dd')?.textContent).not.toContain('photo_detail.assessment.not_applicable');
  });

  it('drops the face measurement when the photo has no face, and keeps it otherwise', () => {
    const fixture = render({ aggregate: 7, aesthetic: 8, face_quality: null, face_count: 0 });
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('summary')?.textContent).toContain('"total":1');
    expect(el.textContent).not.toContain('tooltip.face_quality');
    fixture.componentRef.setInput('photo', { aggregate: 7, aesthetic: 8, face_quality: 6, face_count: 2 });
    fixture.detectChanges();
    expect(el.querySelector('summary')?.textContent).toContain('"total":2');
    expect(el.textContent).toContain('tooltip.face_quality');
  });

  it('renders no explain button unless explainable, and never inside the summary', () => {
    const fixture = render({ aggregate: 7, aesthetic: 8 });
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-explain-score]')).toBeNull();
    fixture.componentRef.setInput('explainable', true);
    fixture.detectChanges();
    const button = el.querySelector<HTMLButtonElement>('[data-explain-score]')!;
    expect(button).not.toBeNull();
    expect(button.closest('summary')).toBeNull();
    expect(button.closest('details')).toBeNull();
    expect(button.getAttribute('aria-label')).toBe('critique.title');
    // The summary keeps clear of the help and explain icons beside it.
    expect(el.querySelector('summary')?.className).toContain('pe-16');
  });

  it('emits explain when the button is clicked', () => {
    const fixture = render({ aggregate: 7 });
    fixture.componentRef.setInput('explainable', true);
    fixture.detectChanges();
    const spy = vi.fn();
    fixture.componentInstance.explain.subscribe(spy);
    fixture.nativeElement.querySelector('[data-explain-score]').click();
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
