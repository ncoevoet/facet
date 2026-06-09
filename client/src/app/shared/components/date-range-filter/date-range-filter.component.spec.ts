import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { DateRangeFilterComponent } from './date-range-filter.component';

@Component({
  selector: 'app-drf-host',
  imports: [DateRangeFilterComponent],
  template: `
    <app-date-range-filter
      [from]="from()" [to]="to()"
      (fromChange)="lastFrom = $event" (toChange)="lastTo = $event" />
  `,
})
class HostComponent {
  from = signal('2024-01-01');
  to = signal('2024-12-31');
  lastFrom = '';
  lastTo = '';
}

describe('DateRangeFilterComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  const mockI18n = {
    t: vi.fn((key: string) => key),
    currentLang: vi.fn(() => 'en'),
    locale: vi.fn(() => 'en'),
    translations: vi.fn(() => ({})),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HostComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    }).compileComponents();
    fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
  });

  function dateInputs(): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[type="date"]'));
  }

  it('renders two date inputs', () => {
    expect(dateInputs().length).toBe(2);
  });

  it('reflects the from/to values', () => {
    const [from, to] = dateInputs();
    expect(from.value).toBe('2024-01-01');
    expect(to.value).toBe('2024-12-31');
  });

  it('emits fromChange when the first input changes', () => {
    const [from] = dateInputs();
    from.value = '2025-06-01';
    from.dispatchEvent(new Event('change'));
    expect(fixture.componentInstance.lastFrom).toBe('2025-06-01');
  });

  it('emits toChange when the second input changes', () => {
    const [, to] = dateInputs();
    to.value = '2025-07-15';
    to.dispatchEvent(new Event('change'));
    expect(fixture.componentInstance.lastTo).toBe('2025-07-15');
  });
});
