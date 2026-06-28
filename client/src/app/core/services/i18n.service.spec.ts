import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { I18nService } from './i18n.service';

describe('I18nService', () => {
  let service: I18nService;
  let httpTesting: HttpTestingController;

  const mockTranslations: Record<string, unknown> = {
    common: {
      hello: 'Hello',
      greeting: 'Hello {name}, welcome to {app}!',
      nested: {
        deep: 'Deep value',
      },
    },
    photos: {
      count: '{count} photos',
    },
  };

  beforeEach(() => {
    // Clear facet_lang cookie
    document.cookie = 'facet_lang=;max-age=0;path=/';

    TestBed.configureTestingModule({
      providers: [I18nService, provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(I18nService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTesting.verify();
    // Restore cookie state
    document.cookie = 'facet_lang=;max-age=0;path=/';
  });

  describe('initial state', () => {
    it('should have isLoaded as false initially', () => {
      expect(service.isLoaded()).toBe(false);
    });

    it('should default locale to en when no cookie or matching browser language', () => {
      expect(['en', 'fr', 'de', 'it', 'es']).toContain(service.locale());
    });
  });

  describe('t()', () => {
    it('should return the key when translations are not loaded', () => {
      expect(service.t('common.hello')).toBe('common.hello');
    });

    it('should return nested value with dot notation', async () => {
      const loadPromise = service.load();
      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);
      await loadPromise;

      expect(service.t('common.hello')).toBe('Hello');
    });

    it('should return deeply nested value', async () => {
      const loadPromise = service.load();
      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);
      await loadPromise;

      expect(service.t('common.nested.deep')).toBe('Deep value');
    });

    it('should return the key when the path does not exist', async () => {
      const loadPromise = service.load();
      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);
      await loadPromise;

      expect(service.t('nonexistent.key')).toBe('nonexistent.key');
    });

    it('should substitute variables in translation', async () => {
      const loadPromise = service.load();
      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);
      await loadPromise;

      expect(service.t('common.greeting', { name: 'Alice', app: 'Facet' })).toBe(
        'Hello Alice, welcome to Facet!',
      );
    });

    it('should substitute numeric variables', async () => {
      const loadPromise = service.load();
      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);
      await loadPromise;

      expect(service.t('photos.count', { count: 42 })).toBe('42 photos');
    });
  });

  describe('load()', () => {
    it('should fetch translations for current locale', async () => {
      const loadPromise = service.load();

      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      expect(req.request.method).toBe('GET');
      req.flush(mockTranslations);

      await loadPromise;
      expect(service.isLoaded()).toBe(true);
    });

    it('should fall back to English on error when locale is not en', async () => {
      service.locale.set('fr');

      const loadPromise = service.load();

      // First request for 'fr' fails
      const frReq = httpTesting.expectOne('/api/i18n/fr');
      frReq.flush('Not Found', { status: 404, statusText: 'Not Found' });

      // Allow microtask to process so fallback request fires
      await Promise.resolve();

      // Should fall back to English
      const enReq = httpTesting.expectOne('/api/i18n/en');
      enReq.flush(mockTranslations);

      await loadPromise;
      expect(service.isLoaded()).toBe(true);
    });

    it('should not fall back when locale is already en', async () => {
      service.locale.set('en');

      const loadPromise = service.load();

      const req = httpTesting.expectOne('/api/i18n/en');
      req.flush('Server Error', { status: 500, statusText: 'Server Error' });

      await loadPromise;
      // No fallback request should be made
      httpTesting.expectNone('/api/i18n/en');
      expect(service.isLoaded()).toBe(false);
    });

    it('should handle null response gracefully', async () => {
      const loadPromise = service.load();

      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(null);

      await loadPromise;
      // null coalesces to {} so isLoaded is false
      expect(service.isLoaded()).toBe(false);
    });
  });

  describe('setLocale()', () => {
    it('should update the locale signal', async () => {
      const setPromise = service.setLocale('fr');

      const req = httpTesting.expectOne('/api/i18n/fr');
      req.flush(mockTranslations);

      await setPromise;
      expect(service.locale()).toBe('fr');
    });

    it('should write the locale to a cookie', async () => {
      const setPromise = service.setLocale('fr');

      const req = httpTesting.expectOne('/api/i18n/fr');
      req.flush(mockTranslations);

      await setPromise;
      expect(document.cookie).toContain('facet_lang=fr');
    });

    it('should reload translations for the new locale', async () => {
      const setPromise = service.setLocale('fr');

      const req = httpTesting.expectOne('/api/i18n/fr');
      expect(req.request.method).toBe('GET');
      req.flush(mockTranslations);

      await setPromise;
      expect(service.isLoaded()).toBe(true);
    });
  });

  describe('isLoaded', () => {
    it('should be false when no translations are loaded', () => {
      expect(service.isLoaded()).toBe(false);
    });

    it('should be true after translations are loaded', async () => {
      const loadPromise = service.load();

      const req = httpTesting.expectOne(`/api/i18n/${service.locale()}`);
      req.flush(mockTranslations);

      await loadPromise;
      expect(service.isLoaded()).toBe(true);
    });
  });

  describe('detectLocale (via constructor)', () => {
    it('should use cookie value when facet_lang cookie is set', () => {
      document.cookie = 'facet_lang=fr;path=/';

      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [I18nService, provideHttpClient(), provideHttpClientTesting()],
      });
      const newService = TestBed.inject(I18nService);
      const newHttp = TestBed.inject(HttpTestingController);

      expect(newService.locale()).toBe('fr');

      newHttp.verify();
    });

    it('resets an unsupported locale to the default after loadLanguages()', async () => {
      document.cookie = 'facet_lang=ja;path=/';

      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [I18nService, provideHttpClient(), provideHttpClientTesting()],
      });
      const newService = TestBed.inject(I18nService);
      const newHttp = TestBed.inject(HttpTestingController);

      // detectLocale trusts the cookie synchronously (it is only ever written
      // by setLocale with a supported code)...
      expect(newService.locale()).toBe('ja');

      // ...and loadLanguages() drops it once it learns 'ja' has no bundle.
      const p = newService.loadLanguages();
      const req = newHttp.expectOne('/api/i18n/languages');
      req.flush({
        languages: [{ code: 'en', name: 'English' }, { code: 'pt', name: 'Português' }],
        default: 'en',
      });
      await p;
      expect(newService.locale()).toBe('en');

      newHttp.verify();
    });
  });

  describe('loadLanguages()', () => {
    it('populates the languages signal with {code, name} entries', async () => {
      const p = service.loadLanguages();
      const req = httpTesting.expectOne('/api/i18n/languages');
      expect(req.request.method).toBe('GET');
      req.flush({
        languages: [{ code: 'en', name: 'English' }, { code: 'pt', name: 'Português' }],
        default: 'en',
      });
      await p;
      expect(service.languages().map(l => l.code)).toEqual(['en', 'pt']);
    });
  });
});
