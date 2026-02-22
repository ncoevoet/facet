import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Pipe, PipeTransform } from '@angular/core';
import { GearChartCardComponent, GearItem } from './gear-chart-card.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Pipe({
  name: 'translate',
  standalone: true
})
class MockTranslatePipe implements PipeTransform {
  transform(value: string): string {
    return `trans_${value}`;
  }
}

describe('GearChartCardComponent', () => {
  let component: GearChartCardComponent;
  let fixture: ComponentFixture<GearChartCardComponent>;

  const mockItems: GearItem[] = [
    {
      name: 'Lens A',
      count: 10,
      avg_score: 5.5,
      avg_aesthetic: 5.5,
      avg_sharpness: 5.5,
      avg_composition: 5.5,
      avg_exposure: 5.5,
      avg_color: 5.5,
      avg_iso: 100,
      avg_f_stop: 2.8,
      avg_focal_length: 50,
      avg_face_count: 1,
      avg_monochrome: 0.5,
      avg_dynamic_range: 10.5,
      history: [{ date: '2024-01-01', count: 5 }]
    },
    {
      name: 'Lens B',
      count: 20,
      avg_score: 8.5,
      avg_aesthetic: 8.5,
      avg_sharpness: 8.5,
      avg_composition: 8.5,
      avg_exposure: 8.5,
      avg_color: 8.5,
      avg_iso: 200,
      avg_f_stop: 4.0,
      avg_focal_length: 85,
      avg_face_count: 2,
      avg_monochrome: 0.1,
      avg_dynamic_range: 12.0,
      history: [{ date: '2024-02-01', count: 10 }]
    }
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GearChartCardComponent, NoopAnimationsModule],
    })
    .overrideComponent(GearChartCardComponent, {
      remove: { imports: [TranslatePipe] },
      add: { imports: [MockTranslatePipe] }
    })
    .compileComponents();

    fixture = TestBed.createComponent(GearChartCardComponent);
    component = fixture.componentInstance;

    // Mock localStorage
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation((key: string) => {
      if (key === 'gear_metric_stats.test_title') return 'avg_score';
      return null;
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});

    // Set required inputs
    fixture.componentRef.setInput('titleKey', 'stats.test_title');
    fixture.componentRef.setInput('items', mockItems);
    fixture.componentRef.setInput('loading', false);
    fixture.componentRef.setInput('color', '#ff0000');
  });

  it('should create the component and restore metric from localStorage', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
    expect((component as any).selectedMetric()).toBe('avg_score');
  });

  it('should sort items correctly by count (default)', () => {
    fixture.detectChanges();
    const sorted = (component as any).sortedItems();
    expect(sorted.length).toBe(2);
    expect(sorted[0].name).toBe('Lens B'); // count 20 > count 10
  });

  it('should re-sort when metric changes to avg_score', () => {
    fixture.detectChanges();
    (component as any).selectedMetric.set('avg_score');
    fixture.detectChanges();

    const sorted = (component as any).sortedItems();
    expect(sorted[0].name).toBe('Lens B'); // avg_score 8.5 > 5.5
  });

  it('should sort correctly for usage_timeline metric', () => {
    fixture.detectChanges();
    (component as any).selectedMetric.set('usage_timeline');
    fixture.detectChanges();

    // Usage timeline defaults to sorting by count to show top N
    const sorted = (component as any).sortedItems();
    expect(sorted[0].name).toBe('Lens B');
  });

});
