import { FilterValueFormatPipe, ModifierValueFormatPipe, WeightIconPipe, WeightLabelKeyPipe } from './comparison.pipes';

describe('WeightIconPipe', () => {
  const pipe = new WeightIconPipe();

  it('returns known icon for aesthetic_percent', () => {
    expect(pipe.transform('aesthetic_percent')).toBe('auto_awesome');
  });

  it('returns fallback icon for unknown key', () => {
    expect(pipe.transform('unknown_key')).toBe('tune');
  });
});

describe('WeightLabelKeyPipe', () => {
  const pipe = new WeightLabelKeyPipe();

  it('produces i18n key for a _percent key', () => {
    expect(pipe.transform('aesthetic_percent')).toBe('comparison.dim.aesthetic');
  });

  it('handles keys without _percent suffix', () => {
    expect(pipe.transform('bonus')).toBe('comparison.dim.bonus');
  });
});

describe('FilterValueFormatPipe', () => {
  const pipe = new FilterValueFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null, 'iso_min')).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined, 'f_stop_min')).toBe('');
  });

  it('returns empty string for NaN', () => {
    expect(pipe.transform(NaN, 'iso_min')).toBe('');
  });

  describe('shutter speed', () => {
    it('formats fast shutter speed as fraction', () => {
      expect(pipe.transform(0.001, 'shutter_speed_min')).toBe('1/1000');
      expect(pipe.transform(0.002, 'shutter_speed_max')).toBe('1/500');
      expect(pipe.transform(0.01, 'shutter_speed_min')).toBe('1/100');
    });

    it('formats slow shutter speed in seconds', () => {
      expect(pipe.transform(1, 'shutter_speed_min')).toBe('1.0s');
      expect(pipe.transform(2, 'shutter_speed_max')).toBe('2.0s');
      expect(pipe.transform(30, 'shutter_speed_min')).toBe('30.0s');
    });

    it('returns empty for zero or negative', () => {
      expect(pipe.transform(0, 'shutter_speed_min')).toBe('');
      expect(pipe.transform(-1, 'shutter_speed_min')).toBe('');
    });
  });

  describe('f-stop', () => {
    it('formats as f/ prefix', () => {
      expect(pipe.transform(1.4, 'f_stop_min')).toBe('f/1.4');
      expect(pipe.transform(2.8, 'f_stop_max')).toBe('f/2.8');
    });

    it('formats integer apertures without decimal', () => {
      expect(pipe.transform(2, 'f_stop_min')).toBe('f/2');
      expect(pipe.transform(8, 'f_stop_max')).toBe('f/8');
    });
  });

  describe('focal length', () => {
    it('formats with mm suffix', () => {
      expect(pipe.transform(50, 'focal_length_min')).toBe('50mm');
      expect(pipe.transform(200, 'focal_length_max')).toBe('200mm');
    });

    it('rounds fractional values', () => {
      expect(pipe.transform(85.5, 'focal_length_min')).toBe('86mm');
    });
  });

  describe('ISO', () => {
    it('formats with ISO prefix', () => {
      expect(pipe.transform(100, 'iso_min')).toBe('ISO 100');
      expect(pipe.transform(6400, 'iso_max')).toBe('ISO 6,400');
    });
  });

  describe('face ratio', () => {
    it('formats as percentage', () => {
      expect(pipe.transform(0.05, 'face_ratio_min')).toBe('5%');
      expect(pipe.transform(0.8, 'face_ratio_max')).toBe('80%');
    });
  });

  describe('luminance', () => {
    it('formats as percentage', () => {
      expect(pipe.transform(0.15, 'luminance_min')).toBe('15%');
      expect(pipe.transform(1.0, 'luminance_max')).toBe('100%');
    });
  });

  describe('face count', () => {
    it('formats as integer', () => {
      expect(pipe.transform(2, 'face_count_min')).toBe('2');
      expect(pipe.transform(10, 'face_count_max')).toBe('10');
    });
  });

  it('returns empty string for unknown key', () => {
    expect(pipe.transform(42, 'unknown_field')).toBe('');
  });
});

describe('ModifierValueFormatPipe', () => {
  const pipe = new ModifierValueFormatPipe();

  it('returns empty string for null', () => {
    expect(pipe.transform(null, 'bonus')).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined, 'bonus')).toBe('');
  });

  it('returns empty string for NaN', () => {
    expect(pipe.transform(NaN, 'bonus')).toBe('');
  });

  describe('bonus', () => {
    it('formats positive bonus with + sign', () => {
      expect(pipe.transform(1.5, 'bonus')).toBe('+1.5 pts');
    });

    it('formats negative bonus with - sign', () => {
      expect(pipe.transform(-2.0, 'bonus')).toBe('-2.0 pts');
    });

    it('formats zero bonus with + sign', () => {
      expect(pipe.transform(0, 'bonus')).toBe('+0.0 pts');
    });
  });

  describe('noise_tolerance_multiplier', () => {
    it('formats as percentage', () => {
      expect(pipe.transform(1.0, 'noise_tolerance_multiplier')).toBe('100%');
      expect(pipe.transform(0.3, 'noise_tolerance_multiplier')).toBe('30%');
      expect(pipe.transform(0, 'noise_tolerance_multiplier')).toBe('0%');
      expect(pipe.transform(2.0, 'noise_tolerance_multiplier')).toBe('200%');
    });
  });

  describe('_clipping_multiplier', () => {
    it('formats as multiplier', () => {
      expect(pipe.transform(1.0, '_clipping_multiplier')).toBe('1.0x');
      expect(pipe.transform(1.5, '_clipping_multiplier')).toBe('1.5x');
      expect(pipe.transform(0, '_clipping_multiplier')).toBe('0.0x');
    });
  });

  it('returns empty string for unknown key', () => {
    expect(pipe.transform(42, 'unknown_modifier')).toBe('');
  });
});
