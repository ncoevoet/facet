import { TestBed } from '@angular/core/testing';
import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  let service: ThemeService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(ThemeService);
  });

  describe('accentColor', () => {
    it('returns orange swatch by default', () => {
      expect(service.accentColor()).toBe('#ff6600');
    });

    it('returns swatch for a named theme', () => {
      service.setTheme('theme-blue');
      expect(service.accentColor()).toBe('#3b82f6');
    });
  });

  describe('complementaryColor', () => {
    it('returns the hue+180 complement of orange (#ff6600 → #0099ff)', () => {
      service.setTheme('');
      expect(service.complementaryColor()).toBe('#0099ff');
    });

    it('returns the hue+180 complement of green (#22c55e → #c52289)', () => {
      service.setTheme('theme-green');
      expect(service.complementaryColor()).toBe('#c52289');
    });

    it('returns the hue+180 complement of blue (#3b82f6 → #f6af3b)', () => {
      service.setTheme('theme-blue');
      expect(service.complementaryColor()).toBe('#f6af3b');
    });

    it('complementaryColor updates reactively when theme changes', () => {
      service.setTheme('theme-violet');
      const c1 = service.complementaryColor();
      service.setTheme('theme-blue');
      const c2 = service.complementaryColor();
      expect(c1).not.toBe(c2);
      service.setTheme('');
      expect(service.complementaryColor()).toBe('#0099ff');
    });

    it('produces a valid hex string for every built-in theme', () => {
      for (const theme of service.THEMES) {
        service.setTheme(theme.id);
        expect(service.complementaryColor()).toMatch(/^#[0-9a-f]{6}$/);
      }
    });
  });
});
