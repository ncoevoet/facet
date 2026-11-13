import { ExifCodePipe } from './exif-code.pipe';

describe('ExifCodePipe', () => {
  const pipe = new ExifCodePipe();

  it('maps flash from bit 0 only', () => {
    expect(pipe.transform(0, 'flash')).toBe('tooltip.flash_off');
    expect(pipe.transform(1, 'flash')).toBe('tooltip.flash_fired');
    expect(pipe.transform(25, 'flash')).toBe('tooltip.flash_fired');
    expect(pipe.transform(24, 'flash')).toBe('tooltip.flash_off');
  });

  it('maps white balance codes', () => {
    expect(pipe.transform(0, 'whiteBalance')).toBe('tooltip.white_balance_auto');
    expect(pipe.transform(1, 'whiteBalance')).toBe('tooltip.white_balance_manual');
  });

  it('maps metering codes', () => {
    expect(pipe.transform(5, 'metering')).toBe('tooltip.metering_pattern');
    expect(pipe.transform(255, 'metering')).toBe('tooltip.metering_other');
    expect(pipe.transform(0, 'metering')).toBe('tooltip.metering_unknown');
  });

  it('falls back to the raw number for an unmapped code', () => {
    expect(pipe.transform(9, 'metering')).toBe('9');
    expect(pipe.transform(7, 'whiteBalance')).toBe('7');
  });

  it('returns an empty string for null or undefined', () => {
    expect(pipe.transform(null, 'flash')).toBe('');
    expect(pipe.transform(undefined, 'metering')).toBe('');
  });
});
