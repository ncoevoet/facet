import { MarkTonePipe } from './mark-tone.pipe';

describe('MarkTonePipe', () => {
  const pipe = new MarkTonePipe();

  it('gives each feature its own colour', () => {
    const tones = ['quality', 'taste', 'moment', 'memories', 'smart'].map(t => pipe.transform(t));
    expect(tones.every(Boolean)).toBe(true);
    expect(new Set(tones).size).toBe(tones.length);
  });

  it('colours the icon-table keys that draw the mark like their feature', () => {
    expect(pipe.transform('aesthetic')).toBe(pipe.transform('quality'));
    expect(pipe.transform('aesthetic_percent')).toBe(pipe.transform('quality'));
    expect(pipe.transform('gallery.sidebar.moments')).toBe(pipe.transform('moment'));
  });

  it('leaves everything else uncoloured', () => {
    expect(pipe.transform('composition_percent')).toBe('');
    expect(pipe.transform(null)).toBe('');
  });
});
