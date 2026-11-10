import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { OverlayContainer } from '@angular/cdk/overlay';
import { Subject } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { MetricDistributionComponent } from './metric-distribution.component';

describe('On-demand metric distributions', () => {
  const identity = signal('reader');
  let reads: {params: unknown; response: Subject<any>}[];
  let get: ReturnType<typeof vi.fn>;
  const result = (max = 10) => ({distribution: {column: 'aesthetic', min: 0, max, buckets: [1, 1]}, count: 2});
  function setup() {
    const fixture = TestBed.createComponent(MetricDistributionComponent);
    fixture.componentRef.setInput('column', 'aesthetic'); fixture.componentRef.setInput('label', 'Aesthetic');
    fixture.componentRef.setInput('value', 7); fixture.componentRef.setInput('category', 'portrait');
    fixture.detectChanges();
    const trigger = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const open = () => { trigger.click(); fixture.detectChanges(); TestBed.tick(); };
    return {fixture, trigger, overlay, open};
  }
  beforeEach(() => {
    identity.set('reader'); reads = [];
    get = vi.fn((_url: string, params: unknown) => {
      const response = new Subject<any>(); reads.push({params, response}); return response;
    });
    TestBed.configureTestingModule({imports: [MetricDistributionComponent], providers: [
      {provide: ApiService, useValue: {get}}, {provide: AuthService, useValue: {identity}},
      {provide: I18nService, useValue: {t: (key: string) => key, translations: () => ({})}},
    ]});
  });

  it('loads only when opened and marks the current score in the requested scope', () => {
    const {fixture, overlay, open} = setup();
    expect(get).not.toHaveBeenCalled(); open();
    expect(get).toHaveBeenCalledWith('/stats/metric_distribution', {column: 'aesthetic'});
    reads[0].response.next(result()); fixture.detectChanges();
    expect(overlay.querySelector('app-metric-sparkline')).not.toBeNull();
    expect(overlay.querySelector('[role="group"] button[aria-pressed="true"]')?.textContent).toContain('library');
    fixture.destroy();
  });

  it('shows the localized category name on the scope button and in the rank label, never the raw id', () => {
    const {fixture, overlay, open} = setup();
    TestBed.inject(I18nService).t = (key: string, vars?: Record<string, unknown>) => key === 'category_names.portrait' ? 'Portrait FR'
      : vars?.['scope'] ? `${key}|${vars['scope']}` : key;
    open();
    const scopeButtons = overlay.querySelectorAll<HTMLButtonElement>('[role="group"] button');
    expect(scopeButtons[1].textContent).toContain('Portrait FR');
    scopeButtons[1].click(); fixture.detectChanges();
    reads[reads.length - 1].response.next(result()); fixture.detectChanges();
    expect(overlay.querySelector('app-metric-rank [role="img"]')?.getAttribute('aria-label')).toContain('|Portrait FR');
    fixture.destroy();
  });

  it('cancels previous category/account requests and ignores their completions', () => {
    const {fixture, overlay, open} = setup(); open();
    (overlay.querySelectorAll('[role="group"] button')[1] as HTMLButtonElement).click(); fixture.detectChanges();
    expect(reads[0].response.observed).toBe(false);
    expect(reads[1].params).toEqual({column: 'aesthetic', category: 'portrait'});
    fixture.componentRef.setInput('category', 'landscape'); fixture.detectChanges();
    expect(reads[1].response.observed).toBe(false);
    expect(reads[2].params).toEqual({column: 'aesthetic', category: 'landscape'});
    identity.set('another'); fixture.detectChanges();
    expect(reads[2].response.observed).toBe(false);
    reads[2].response.next(result(999)); reads[3].response.next(result(5)); fixture.detectChanges();
    expect((fixture.componentInstance as any).range().max).toBe(5);
    fixture.destroy();
  });

  it('retries a failed read and cancels it when dismissed', () => {
    const {fixture, trigger, overlay, open} = setup(); open();
    reads[0].response.error(new Error('offline')); fixture.detectChanges();
    expect(overlay.querySelector('[role="alert"]')).not.toBeNull();
    [...overlay.querySelectorAll('button')].find(button => button.textContent?.includes('retry'))!.click(); fixture.detectChanges();
    expect(reads).toHaveLength(2);
    overlay.querySelector<HTMLButtonElement>('header button')!.click(); fixture.detectChanges();
    expect(reads[1].response.observed).toBe(false);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fixture.destroy();
  });
});
