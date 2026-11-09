import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import en from '../../../../../i18n/translations/en.json';
import fr from '../../../../../i18n/translations/fr.json';
import de from '../../../../../i18n/translations/de.json';
import es from '../../../../../i18n/translations/es.json';
import italian from '../../../../../i18n/translations/it.json';
import pt from '../../../../../i18n/translations/pt.json';
import zh from '../../../../../i18n/translations/zh.json';
import contract from '../../core/agent/ui-tools.schema.json';
import { I18nService } from '../../core/services/i18n.service';
import { DEFAULT_FILTERS, SMART_ALBUM_EXCLUDE_KEYS } from './gallery-filters.util';
import { galleryFilterLabel } from './gallery-filter-label.pipe';
import { AlbumRuleValuePipe } from './album-rule-value.pipe';
import { GalleryStore } from './gallery.store';

function translated(bundle: object, key: string): string {
  let value: unknown = bundle;
  for (const part of key.split('.')) value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
  return typeof value === 'string' ? value : key;
}

describe('Shared filter label coverage', () => {
  it('uses concise field labels rather than sidebar explanations in previews and chips', () => {
    for (const key of ['blinks_only', 'duplicates_only', 'hide_brackets', 'hide_panoramas']) {
      expect(galleryFilterLabel(key, value => translated(en, value))).toBe(
        en.gallery.criteria.field_labels[key as keyof typeof en.gallery.criteria.field_labels]);
    }
  });

  it.each(Object.entries({ en, fr, de, es, it: italian, pt, zh }))('names every persisted and proposed field using existing %s translations', (_lang, bundle) => {
    const proposed = contract.tools.find(tool => tool.name === 'ui_set_gallery_filters')!.inputSchema.properties.patch!.properties!;
    const keys = new Set([...Object.keys(DEFAULT_FILTERS).filter(key => !SMART_ALBUM_EXCLUDE_KEYS.has(key)), ...Object.keys(proposed)]);
    for (const key of keys) {
      const label = galleryFilterLabel(key, translationKey => {
        const value = translated(bundle, translationKey);
        expect(value, `${key}: ${translationKey}`).not.toBe(translationKey);
        return value;
      });
      expect(label, key).not.toBe(key);
      expect(label.trim(), key).not.toBe('');
    }
  });
});

describe('Sort direction label', () => {
  it('names the field rather than the toggle control', () => {
    expect(galleryFilterLabel('sort_direction', value => translated(en, value))).toBe(en.gallery.sort_direction);
  });
});

describe('Typed album rule values', () => {
  const persons = signal([{ id: 7, name: 'Alice', face_count: 3 }, { id: 8, name: null, face_count: 1 }]);
  const make = (bundle: object) => {
    TestBed.configureTestingModule({ providers: [
      { provide: I18nService, useValue: { t: (key: string, params?: Record<string, unknown>) => translated(bundle, key).replace('{id}', String(params?.['id'])) } },
      { provide: GalleryStore, useValue: { persons } },
    ] });
    return TestBed.runInInjectionContext(() => new AlbumRuleValuePipe());
  };

  it('resolves a person id to the cached name and falls back to Person #id', () => {
    const pipe = make(en);
    expect(pipe.transform('7', 'person_id')).toBe('Alice');
    expect(pipe.transform('8', 'person_id')).toBe('Person #8');
    expect(pipe.transform('99', 'person_id')).toBe('Person #99');
  });

  it('translates known choices only and preserves literal or unknown values', () => {
    const bundle = signal<object>(fr);
    TestBed.configureTestingModule({ providers: [
      { provide: I18nService, useValue: { t: (key: string) => translated(bundle(), key) } },
      { provide: GalleryStore, useValue: { persons: signal([]) } },
    ] });
    const pipe = TestBed.runInInjectionContext(() => new AlbumRuleValuePipe());
    for (const key of ['camera', 'lens', 'tag', 'search', 'path_prefix']) {
      for (const value of ['true', 'false', 'gallery.camera', 'albums.title']) expect(pipe.transform(value, key)).toBe(value);
    }
    expect(pipe.transform('true', 'favorites_only')).toBe(fr.organization_history.yes);
    expect(pipe.transform('false', 'favorites_only')).toBe(fr.organization_history.no);
    expect(pipe.transform('kept', 'review_status')).toBe(fr.gallery.sidebar.review.values.kept);
    expect(pipe.transform('portrait', 'type')).toBe(fr.category_names.portrait);
    for (const key of ['type', 'sort', 'sort_direction', 'review_status']) expect(pipe.transform('custom-value', key)).toBe('custom-value');
    expect(pipe.transform('2024-03-01', 'date_from')).toBe('01/03/2024');
    bundle.set(en);
    expect(pipe.transform('true', 'favorites_only')).toBe(en.organization_history.yes);
    expect(pipe.transform('portrait', 'type')).toBe(en.category_names.portrait);
  });
});
