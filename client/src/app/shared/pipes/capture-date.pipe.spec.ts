import { TestBed } from '@angular/core/testing';
import { CaptureDatePipe } from './capture-date.pipe';
import { I18nService } from '../../core/services/i18n.service';

describe('CaptureDatePipe', () => {
  let pipe: CaptureDatePipe;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [CaptureDatePipe, I18nService] });
    TestBed.inject(I18nService).locale.set('en');
    pipe = TestBed.inject(CaptureDatePipe);
  });

  it.each([
    ['2026:10:31 23:05:42', 'Oct 31, 2026 23:05'],
    ['2026-10-31T23:05:42Z', 'Oct 31, 2026 23:05'],
    ['2026-10-31T23:05:42+05:30', 'Oct 31, 2026 23:05'],
    ['2024:02:29', 'Feb 29, 2024'],
  ])('formats the recorded calendar fields of %s in the viewer locale, without timezone conversion', (source, expected) => {
    expect(pipe.transform(source)).toBe(expected);
  });

  it('renders the zh date the way Chinese writes it', () => {
    TestBed.inject(I18nService).locale.set('zh');
    expect(pipe.transform('2026:10:31 23:05:42')).toBe('2026年10月31日 23:05');
    expect(pipe.transform('2024:02:29')).toBe('2024年2月29日');
    TestBed.inject(I18nService).locale.set('en');
  });

  it('re-renders when the locale changes, without shifting the recorded fields', () => {
    TestBed.inject(I18nService).locale.set('de');
    expect(pipe.transform('2026:10:31 23:05:42')).toBe('31. Okt. 2026 23:05');
    TestBed.inject(I18nService).locale.set('en');
  });

  it.each(['unknown', '2026:02:29', '2026:13:01', '2026:10:31 24:05:00'])('preserves unsupported or invalid capture values: %s', value => {
    expect(pipe.transform(value)).toBe(value);
  });

  it('keeps missing metadata empty', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
