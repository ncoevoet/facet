import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { DateRangeFilterComponent } from './date-range-filter.component';

@Component({
  selector: 'app-drf-host',
  imports: [DateRangeFilterComponent],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <app-date-range-filter
      [from]="from()" [to]="to()" [fromClass]="fromClass()" [toClass]="toClass()"
      (fromChange)="onFrom($event)" (toChange)="onTo($event)" />
  `,
})
class HostComponent {
  from = signal('2024-01-01');
  to = signal('2024-12-31');
  fromClass = signal('w-44');
  toClass = signal('');
  lastFrom = '';
  lastTo = '';

  // Mirrors the real consumers, which write the emitted values back into the
  // signals bound to [from]/[to].
  onFrom(value: string): void {
    this.from.set(value);
    this.lastFrom = value;
  }

  onTo(value: string): void {
    this.to.set(value);
    this.lastTo = value;
  }
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

  it('pulls the other bound along to keep the range ordered', () => {
    // Setting "from" past "to" must move "to" along: an inverted range would
    // silently produce an empty result in every consumer, indistinguishable
    // from "no photos".
    const inputs = dateInputs();
    inputs[0].value = '2025-06-01';
    inputs[0].dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(fixture.componentInstance.lastFrom).toBe('2025-06-01');
    expect(fixture.componentInstance.lastTo).toBe('2025-06-01');
    expect((inputs[1] as HTMLInputElement).value).toBe('2025-06-01');
  });

  it('pulls "from" back when "to" is set before it', () => {
    const inputs = dateInputs();
    inputs[1].value = '2023-03-01';
    inputs[1].dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(fixture.componentInstance.lastTo).toBe('2023-03-01');
    expect(fixture.componentInstance.lastFrom).toBe('2023-03-01');
    expect((inputs[0] as HTMLInputElement).value).toBe('2023-03-01');
  });

  it('sizes both Material fields from fromClass and falls back to it for the to field', () => {
    const fields = () => Array.from(fixture.nativeElement.querySelectorAll('mat-form-field')) as HTMLElement[];
    fixture.componentInstance.fromClass.set('w-40'); fixture.detectChanges();
    expect(fields().every(field => field.classList.contains('w-40'))).toBe(true);
    fixture.componentInstance.toClass.set('w-36'); fixture.detectChanges();
    expect(fields()[1].classList.contains('w-36')).toBe(true);
  });

  it('has no compact native-input branch', () => {
    expect('compact' in fixture.debugElement.children[0].componentInstance).toBe(false);
  });
});
