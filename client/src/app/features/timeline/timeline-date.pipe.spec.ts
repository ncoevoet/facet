import { TimelineDatePipe } from './timeline-date.pipe';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

describe('TimelineDatePipe', () => {
  const locale = signal('en');
  let pipe: TimelineDatePipe;
  beforeEach(() => {
    locale.set('en');
    TestBed.configureTestingModule({ providers: [{ provide: I18nService, useValue: {
      locale,
      t: (_key: string, params: { week: number; year: string }) => `${locale() === 'de' ? 'Woche' : 'Week'} ${params.week}, ${params.year}`,
    } }] });
    pipe = TestBed.runInInjectionContext(() => new TimelineDatePipe());
  });

  it('should return empty string for empty input', () => {
    expect(pipe.transform('')).toBe('');
  });

  describe('day format (YYYY-MM-DD)', () => {
    it('should format a day date as a full date string', () => {
      const result = pipe.transform('2024-06-15');
      expect(result).toContain('2024');
      expect(result).toContain('15');
    });

    it('should handle January dates', () => {
      const result = pipe.transform('2025-01-01');
      expect(result).toContain('2025');
      expect(result).toContain('1');
    });
  });

  describe('week format (YYYY-Www)', () => {
    it('should format as "Week N, YYYY"', () => {
      expect(pipe.transform('2025-W46')).toBe('Week 46, 2025');
    });

    it('should strip leading zeros from week number', () => {
      expect(pipe.transform('2025-W01')).toBe('Week 1, 2025');
    });

    it('should handle week 52', () => {
      expect(pipe.transform('2024-W52')).toBe('Week 52, 2024');
    });

    it('uses the viewer language for week labels', () => {
      locale.set('de');
      expect(pipe.transform('2025-W01')).toBe('Woche 1, 2025');
    });
  });

  describe('month format (YYYY-MM)', () => {
    it('updates month names when the viewer language changes', () => {
      locale.set('de');
      expect(pipe.transform('2025-01')).toContain('Januar');
      locale.set('fr');
      expect(pipe.transform('2025-01')).toContain('janvier');
    });
    it('should format November as month name + year', () => {
      const result = pipe.transform('2025-11');
      expect(result).toContain('November');
      expect(result).toContain('2025');
    });

    it('should format January as month name + year', () => {
      const result = pipe.transform('2025-01');
      expect(result).toContain('January');
      expect(result).toContain('2025');
    });

    it('should format June as month name + year', () => {
      const result = pipe.transform('2024-06');
      expect(result).toContain('June');
      expect(result).toContain('2024');
    });
  });
});
