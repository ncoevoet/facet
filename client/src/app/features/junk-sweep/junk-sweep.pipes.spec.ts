import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { JunkKindLabelPipe, JunkKindIconPipe } from './junk-sweep.pipes';
import { I18nService } from '../../core/services/i18n.service';

describe('JunkKindLabelPipe', () => {
  let pipe: JunkKindLabelPipe;
  let i18nMock: { t: Mock; translations: Mock };
  let currentTranslations: Record<string, unknown>;

  beforeEach(() => {
    currentTranslations = { en: true };
    i18nMock = {
      t: vi.fn(),
      translations: vi.fn(() => currentTranslations),
    };

    TestBed.configureTestingModule({
      providers: [
        JunkKindLabelPipe,
        { provide: I18nService, useValue: i18nMock },
      ],
    });

    pipe = TestBed.inject(JunkKindLabelPipe);
  });

  it.each(['screenshot', 'document', 'receipt', 'meme', 'slide'])(
    'returns the translated label for the known kind "%s"',
    kind => {
      i18nMock.t.mockReturnValue(`Translated ${kind}`);

      const result = pipe.transform(kind);

      expect(i18nMock.t).toHaveBeenCalledWith(`junk.kinds.${kind}`);
      expect(result).toBe(`Translated ${kind}`);
    },
  );

  it('falls back to the raw kind when the translation is missing (i18n returns the key)', () => {
    i18nMock.t.mockImplementation((key: string) => key);

    const result = pipe.transform('mystery_kind');

    expect(result).toBe('mystery_kind');
  });

  it('returns an empty string for a null kind', () => {
    expect(pipe.transform(null)).toBe('');
    expect(i18nMock.t).not.toHaveBeenCalled();
  });

  it('returns an empty string for an undefined kind', () => {
    expect(pipe.transform(undefined)).toBe('');
    expect(i18nMock.t).not.toHaveBeenCalled();
  });

  it('returns an empty string for an empty-string kind', () => {
    expect(pipe.transform('')).toBe('');
    expect(i18nMock.t).not.toHaveBeenCalled();
  });

  it('memoises repeated transforms for the same kind+translations', () => {
    i18nMock.t.mockReturnValue('Translated screenshot');

    pipe.transform('screenshot');
    pipe.transform('screenshot');
    pipe.transform('screenshot');

    expect(i18nMock.t).toHaveBeenCalledTimes(1);
  });

  it('recomputes when the translations object reference changes', () => {
    i18nMock.t.mockReturnValueOnce('Translated screenshot').mockReturnValueOnce('Capture d\'écran');

    expect(pipe.transform('screenshot')).toBe('Translated screenshot');

    currentTranslations = { fr: true };

    expect(pipe.transform('screenshot')).toBe('Capture d\'écran');
    expect(i18nMock.t).toHaveBeenCalledTimes(2);
  });

  it('recomputes when the kind changes', () => {
    i18nMock.t.mockReturnValueOnce('Translated screenshot').mockReturnValueOnce('Translated document');

    expect(pipe.transform('screenshot')).toBe('Translated screenshot');
    expect(pipe.transform('document')).toBe('Translated document');

    expect(i18nMock.t).toHaveBeenCalledTimes(2);
  });
});

describe('JunkKindIconPipe', () => {
  const pipe = new JunkKindIconPipe();

  it('maps the "any" filter sentinel to the generic filter icon', () => {
    expect(pipe.transform('any')).toBe('filter_alt');
  });

  it.each([
    ['screenshot', 'screenshot'],
    ['document', 'description'],
    ['receipt', 'receipt_long'],
    ['meme', 'mood'],
    ['slide', 'slideshow'],
  ])('maps known kind "%s" to icon "%s"', (kind, icon) => {
    expect(pipe.transform(kind)).toBe(icon);
  });

  it('falls back to the generic image icon for an unknown kind', () => {
    expect(pipe.transform('mystery_kind')).toBe('image');
  });

  it('falls back to the generic image icon for a null kind', () => {
    expect(pipe.transform(null)).toBe('image');
  });

  it('falls back to the generic image icon for an undefined kind', () => {
    expect(pipe.transform(undefined)).toBe('image');
  });

  it('falls back to the generic image icon for an empty-string kind', () => {
    expect(pipe.transform('')).toBe('image');
  });
});
