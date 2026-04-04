import { TestBed } from '@angular/core/testing';
import { TranslatePipe } from './translate.pipe';
import { I18nService } from '../../core/services/i18n.service';

describe('TranslatePipe', () => {
  let pipe: TranslatePipe;
  let i18nMock: { t: jest.Mock; locale: jest.Mock };

  beforeEach(() => {
    i18nMock = { t: jest.fn(), locale: jest.fn().mockReturnValue('en') };

    TestBed.configureTestingModule({
      providers: [
        TranslatePipe,
        { provide: I18nService, useValue: i18nMock },
      ],
    });

    pipe = TestBed.inject(TranslatePipe);
  });

  it('delegates to I18nService.t()', () => {
    i18nMock.t.mockReturnValue('Hello');

    const result = pipe.transform('greeting');

    expect(i18nMock.t).toHaveBeenCalledWith('greeting', undefined);
    expect(result).toBe('Hello');
  });

  it('passes vars through to I18nService.t()', () => {
    i18nMock.t.mockReturnValue('Hello Alice');

    const vars = { name: 'Alice', count: 3 };
    const result = pipe.transform('greeting', vars);

    expect(i18nMock.t).toHaveBeenCalledWith('greeting', vars);
    expect(result).toBe('Hello Alice');
  });

  it('returns key when I18nService returns key (no translation)', () => {
    i18nMock.t.mockReturnValue('missing.key');

    const result = pipe.transform('missing.key');

    expect(i18nMock.t).toHaveBeenCalledWith('missing.key', undefined);
    expect(result).toBe('missing.key');
  });
});
