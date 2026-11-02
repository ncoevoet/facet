import { MarkTonePipe } from './mark-tone.pipe';
import { SortOptionIconPipe } from './sort-option-icon.pipe';

describe('SortOptionIconPipe', () => {
  const pipe = new SortOptionIconPipe();

  it('returns a model label for model columns', () => {
    expect(pipe.transform('aesthetic_iaa')).toEqual({ text: 'IAA', classes: '!font-sans !text-[11px] !font-semibold !leading-6' });
  });

  it('returns an icon ligature for mapped columns', () => {
    expect(pipe.transform('date_taken')).toEqual({ text: 'event', classes: '' });
  });

  it('draws the aesthetic sort with the quality mark in its colour, never the AI sparkle', () => {
    expect(pipe.transform('aesthetic')).toEqual({ text: '✦', classes: new MarkTonePipe().transform('quality') });
  });

  it('falls back to sort for unknown columns', () => {
    expect(pipe.transform('unknown')).toEqual({ text: 'sort', classes: '' });
  });

  it('does not resolve Object.prototype members', () => {
    expect(pipe.transform('constructor')).toEqual({ text: 'sort', classes: '' });
    expect(pipe.transform('toString')).toEqual({ text: 'sort', classes: '' });
  });
});
