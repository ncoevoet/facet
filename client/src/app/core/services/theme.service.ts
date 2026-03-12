import { Injectable, signal, computed } from '@angular/core';

function hexToHsl(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (max === g) h = ((b - r) / d + 2) / 6;
  else h = ((r - g) / d + 4) / 6;
  return [h * 360, s, l];
}

function hslToHex(h: number, s: number, l: number): string {
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

export interface Theme {
  id: string;
  label: string;
  swatch: string;
}

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly STORAGE_KEY = 'facet_theme';
  private readonly DARK_MODE_KEY = 'facet_dark_mode';

  readonly THEMES: Theme[] = [
    { id: '', label: 'Orange', swatch: '#ff6600' },
    { id: 'theme-green', label: 'Green', swatch: '#22c55e' },
    { id: 'theme-blue', label: 'Blue', swatch: '#3b82f6' },
    { id: 'theme-cyan', label: 'Cyan', swatch: '#06b6d4' },
    { id: 'theme-violet', label: 'Violet', swatch: '#8b5cf6' },
    { id: 'theme-rose', label: 'Rose', swatch: '#f43f5e' },
    { id: 'theme-red', label: 'Red', swatch: '#ef4444' },
    { id: 'theme-yellow', label: 'Yellow', swatch: '#eab308' },
    { id: 'theme-magenta', label: 'Magenta', swatch: '#d946ef' },
    { id: 'theme-azure', label: 'Azure', swatch: '#0ea5e9' },
  ];

  readonly theme = signal(this.loadSaved());
  readonly darkMode = signal(this.loadDarkMode());

  readonly accentColor = computed(() => {
    const current = this.theme();
    return this.THEMES.find(t => t.id === current)?.swatch ?? '#ff6600';
  });

  readonly complementaryColor = computed(() => {
    const [h, s, l] = hexToHsl(this.accentColor());
    return hslToHex((h + 180) % 360, s, l);
  });

  constructor() {
    this.applyClass(this.theme());
    this.applyDarkMode(this.darkMode());

    // Listen for system preference changes when no explicit user choice is saved
    if (localStorage.getItem(this.DARK_MODE_KEY) === null) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (localStorage.getItem(this.DARK_MODE_KEY) === null) {
          this.darkMode.set(e.matches);
          this.applyDarkMode(e.matches);
        }
      });
    }
  }

  setTheme(id: string): void {
    this.applyClass(id);
    this.theme.set(id);
    localStorage.setItem(this.STORAGE_KEY, id);
  }

  toggleDarkMode(): void {
    const dark = !this.darkMode();
    this.darkMode.set(dark);
    localStorage.setItem(this.DARK_MODE_KEY, String(dark));
    this.applyDarkMode(dark);
  }

  private loadSaved(): string {
    return localStorage.getItem(this.STORAGE_KEY) ?? '';
  }

  private loadDarkMode(): boolean {
    const stored = localStorage.getItem(this.DARK_MODE_KEY);
    if (stored !== null) return stored === 'true';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  private applyDarkMode(dark: boolean): void {
    document.documentElement.classList.toggle('light-mode', !dark);
  }

  private applyClass(id: string): void {
    const el = document.documentElement;
    for (const t of this.THEMES) {
      if (t.id) el.classList.remove(t.id);
    }
    if (id) el.classList.add(id);
  }
}
