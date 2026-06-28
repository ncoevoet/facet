import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

export interface LanguageInfo {
  code: string;
  name: string;
}

@Injectable({ providedIn: 'root' })
export class I18nService {
  private http = inject(HttpClient);

  private readonly COOKIE_KEY = 'facet_lang';
  private readonly _translations = signal<Record<string, unknown>>({});
  private readonly _languages = signal<LanguageInfo[]>([]);

  readonly translations = this._translations.asReadonly();
  /** Supported languages (code + native name), fetched from /api/i18n/languages. */
  readonly languages = this._languages.asReadonly();
  readonly locale = signal<string>(this.detectLocale());
  readonly isLoaded = computed(() => Object.keys(this._translations()).length > 0);

  /** Fetch the supported-language list (data-driven switcher). */
  async loadLanguages(): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.http.get<{ languages: LanguageInfo[]; default: string }>('/api/i18n/languages'),
      );
      const langs = data?.languages ?? [];
      this._languages.set(langs);
      // Drop an unsupported auto-detected locale (e.g. browser 'ja' with no bundle).
      const codes = langs.map(l => l.code);
      if (codes.length && !codes.includes(this.locale())) {
        this.locale.set(data?.default ?? 'en');
      }
    } catch {
      // Switcher will simply have no entries; English content still loads.
    }
  }

  /** Load translations for current locale */
  async load(): Promise<void> {
    const lang = this.locale();
    try {
      const data = await firstValueFrom(this.http.get<Record<string, unknown>>(`/api/i18n/${lang}`));
      this._translations.set(data ?? {});
    } catch {
      // Fallback to English
      if (lang !== 'en') {
        try {
          const data = await firstValueFrom(this.http.get<Record<string, unknown>>('/api/i18n/en'));
          this._translations.set(data ?? {});
        } catch {
          // Both failed — use empty translations, keys will show as-is
        }
      }
    }
  }

  /** Translate a key using dot notation */
  t(key: string, vars?: Record<string, string | number>): string {
    const value = this.getNestedValue(this._translations(), key);
    if (value === null || value === undefined) return key;

    let result = String(value);
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        result = result.replaceAll(`{${k}}`, String(v));
      }
    }
    return result;
  }

  /** Switch language */
  async setLocale(lang: string): Promise<void> {
    this.locale.set(lang);
    document.cookie = `${this.COOKIE_KEY}=${lang};max-age=${365 * 24 * 60 * 60};SameSite=Lax;path=/`;
    await this.load();
  }

  private detectLocale(): string {
    // Cookie is written only by setLocale (always a supported code), so trust it.
    const match = document.cookie.match(new RegExp(`${this.COOKIE_KEY}=([^;]+)`));
    if (match) return match[1];

    // Browser language as a candidate; loadLanguages() resets it to the default
    // if no bundle exists for it.
    const browserLang = navigator.language?.split('-')[0];
    return browserLang || 'en';
  }

  private getNestedValue(obj: Record<string, unknown>, keyPath: string): unknown {
    const keys = keyPath.split('.');
    let value: unknown = obj;
    for (const key of keys) {
      if (value && typeof value === 'object' && key in (value as Record<string, unknown>)) {
        value = (value as Record<string, unknown>)[key];
      } else {
        return null;
      }
    }
    return value;
  }
}
