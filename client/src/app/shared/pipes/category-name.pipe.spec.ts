import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { CategoryNamePipe } from './category-name.pipe';
import { I18nService } from '../../core/services/i18n.service';

describe('CategoryNamePipe', () => {
  let pipe: CategoryNamePipe;
  let i18nMock: { t: Mock };

  beforeEach(() => {
    i18nMock = { t: vi.fn((key: string) => key) };
    TestBed.configureTestingModule({ providers: [CategoryNamePipe, { provide: I18nService, useValue: i18nMock }] });
    pipe = TestBed.inject(CategoryNamePipe);
  });

  it('translates a scoring category through category_names', () => {
    i18nMock.t.mockImplementation((key: string) => key === 'category_names.portrait_bw' ? 'Portrait N&B' : key);
    expect(pipe.transform('portrait_bw')).toBe('Portrait N&B');
  });

  it('maps top_picks to its photo type key', () => {
    i18nMock.t.mockImplementation((key: string) => key === 'photo_types.top_picks' ? 'Meilleures photos' : key);
    expect(pipe.transform('top_picks')).toBe('Meilleures photos');
  });

  it('falls back to the raw id when there is no translation, and to empty for nothing', () => {
    expect(pipe.transform('custom_cat')).toBe('custom_cat');
    expect(pipe.transform(null)).toBe('');
  });
});
