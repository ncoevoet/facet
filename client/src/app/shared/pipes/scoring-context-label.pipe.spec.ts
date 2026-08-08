import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ScoringContextLabelPipe } from './scoring-context-label.pipe';
import { I18nService } from '../../core/services/i18n.service';

describe('ScoringContextLabelPipe', () => {
  let pipe: ScoringContextLabelPipe;
  let i18nMock: { t: Mock };

  beforeEach(() => {
    i18nMock = { t: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        ScoringContextLabelPipe,
        { provide: I18nService, useValue: i18nMock },
      ],
    });

    pipe = TestBed.inject(ScoringContextLabelPipe);
  });

  it('returns the translated label when the lookup resolves', () => {
    i18nMock.t.mockReturnValue('Action & Stage');

    const result = pipe.transform({ name: 'action_stage', label_key: 'comparison.context.action_stage' });

    expect(i18nMock.t).toHaveBeenCalledWith('comparison.context.action_stage');
    expect(result).toBe('Action & Stage');
  });

  it('falls back to the context name when the lookup misses (I18nService returns the key unchanged)', () => {
    i18nMock.t.mockImplementation((key: string) => key);

    const result = pipe.transform({ name: 'dance_comp', label_key: 'comparison.context.dance_comp' });

    expect(result).toBe('dance_comp');
  });
});
