import { Injectable, signal, computed } from '@angular/core';

export interface Theme {
  id: string;
  label: string;
  swatch: string;
}

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly STORAGE_KEY = 'facet_theme';

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

  readonly accentColor = computed(() => {
    const current = this.theme();
    return this.THEMES.find(t => t.id === current)?.swatch ?? '#ff6600';
  });

  constructor() {
    this.applyClass(this.theme());
  }

  setTheme(id: string): void {
    this.applyClass(id);
    this.theme.set(id);
    localStorage.setItem(this.STORAGE_KEY, id);
  }

  private loadSaved(): string {
    return localStorage.getItem(this.STORAGE_KEY) ?? '';
  }

  private applyClass(id: string): void {
    const el = document.documentElement;
    for (const t of this.THEMES) {
      if (t.id) el.classList.remove(t.id);
    }
    if (id) el.classList.add(id);
  }
}
