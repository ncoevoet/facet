import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  FacesForPathPipe, FacePoorExpressionPipe, FaceRingClassPipe, FaceDimmedPipe,
  WeightRemainingPipe, SortIconPipe, CategoryIconPipe, CullProfileIconPipe,
  CullPreviewUrlPipe, SubjectForPathPipe, SubjectRingClassPipe, EvOffsetPipe,
  GroupOverridePipe, PeakingOverlayPipe, FrameViewBoxPipe, GridLinesPipe,
  KeySubjectForPathPipe, IsKeyFacePipe, peakingEdgeOverlay,
  peakingGradientField, peakingThreshold, paintPeakingField,
  loadFrameImage, computePeakingOverlay, computePooledPeakingOverlays,
  KEY_SUBJECT_COORDINATE_SPACE,
  CullingGroup, CullingFace, CullingSubject, FaceThresholds, FrameSize, KeySubject,
} from './burst-culling.pipes';

const subject = (overrides: Partial<CullingSubject> = {}): CullingSubject => ({
  path: '/p.jpg', has_subject: true, crop: 'data:image/jpeg;base64,x',
  subject_sharpness: null, subject_prominence: null,
  crop_sharpness: 100, crop_sharpness_score: 10, ...overrides,
});

const keySubject = (overrides: Partial<KeySubject> = {}): KeySubject => ({
  path: '/p.jpg', kind: 'person', coordinate_space: KEY_SUBJECT_COORDINATE_SPACE,
  image_width: 4000, image_height: 3000, bbox: [0.5, 0.1, 0.7, 0.3], center: [0.6, 0.2],
  area_ratio: 0.04, centrality: 0.5, score: 0.8,
  face_id: 7, face_index: 0, person_id: 3, person_name: 'Alice',
  subject_sharpness: null, subject_prominence: null,
  subject_placement: null, bg_separation: null, ...overrides,
});

const group = (overrides: Partial<CullingGroup> = {}): CullingGroup => ({
  group_id: 1, type: 'burst', reason: '', photos: [], best_path: '', count: 0, ...overrides,
});

describe('IsKeptPipe', () => {
  const pipe = new IsKeptPipe();

  it('returns true when path is in the kept set for the burst', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(true);
  });

  it('returns false when path is not in the kept set', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(false);
  });

  it('returns false when burst_id has no entry', () => {
    expect(pipe.transform('/photo1.jpg', new Map(), 99)).toBe(false);
  });
});

describe('IsDecidedPipe', () => {
  const pipe = new IsDecidedPipe();

  it('returns true when burst has selections and path is not kept', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(true);
  });

  it('returns false when path is kept', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });

  it('returns false when burst has no entry', () => {
    expect(pipe.transform('/photo1.jpg', new Map(), 1)).toBe(false);
  });

  it('returns false when kept set is empty', () => {
    const map = new Map<number, Set<string>>([[1, new Set<string>()]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });
});

describe('IsConfirmedPipe', () => {
  const pipe = new IsConfirmedPipe();

  it('returns true when group is confirmed', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Set(['1_burst']))).toBe(true);
  });

  it('returns false when group is not confirmed', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Set(['1_burst']))).toBe(false);
  });

  it('distinguishes between burst and similar types', () => {
    const confirmed = new Set(['1_burst']);
    expect(pipe.transform(group({ type: 'burst' }), confirmed)).toBe(true);
    expect(pipe.transform(group({ type: 'similar' }), confirmed)).toBe(false);
  });
});

describe('IsPassingPipe', () => {
  const pipe = new IsPassingPipe();

  it('returns true when group is in passingGroups', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Map([['1_burst', 4]]))).toBe(true);
  });

  it('returns false when group is not in passingGroups', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Map([['1_burst', 4]]))).toBe(false);
  });
});

describe('PassCountdownPipe', () => {
  const pipe = new PassCountdownPipe();

  it('returns the countdown value for a group in passingGroups', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Map([['1_burst', 3]]))).toBe(3);
  });

  it('returns 0 for a group not in passingGroups', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Map([['1_burst', 3]]))).toBe(0);
  });
});

describe('FacesForPathPipe', () => {
  const pipe = new FacesForPathPipe();

  it('returns the faces for a known path', () => {
    const faces: CullingFace[] = [{ id: 1, face_index: 0 }];
    const map = new Map<string, CullingFace[]>([['/p.jpg', faces]]);
    expect(pipe.transform('/p.jpg', map)).toBe(faces);
  });

  it('returns an empty array for an unknown path', () => {
    expect(pipe.transform('/missing.jpg', new Map())).toEqual([]);
  });
});

describe('SubjectForPathPipe', () => {
  const pipe = new SubjectForPathPipe();

  it('returns the subject for a known path', () => {
    const s = subject();
    const map = new Map<string, CullingSubject>([['/p.jpg', s]]);
    expect(pipe.transform('/p.jpg', map)).toBe(s);
  });

  it('returns null for an unknown path', () => {
    expect(pipe.transform('/missing.jpg', new Map())).toBeNull();
  });
});

describe('KeySubjectForPathPipe', () => {
  const pipe = new KeySubjectForPathPipe();

  it('returns the key subject for a known path', () => {
    const k = keySubject();
    const map = new Map<string, KeySubject>([['/p.jpg', k]]);
    expect(pipe.transform('/p.jpg', map)).toBe(k);
  });

  it('returns null for an unknown path', () => {
    expect(pipe.transform('/missing.jpg', new Map())).toBeNull();
  });
});

describe('IsKeyFacePipe', () => {
  const pipe = new IsKeyFacePipe();
  const face = (id: number): CullingFace => ({ id, face_index: 0 });

  it('matches the face the key subject resolved to', () => {
    expect(pipe.transform(face(7), keySubject({ face_id: 7 }))).toBe(true);
  });

  it('does not match any other face of the same photo', () => {
    expect(pipe.transform(face(8), keySubject({ face_id: 7 }))).toBe(false);
  });

  // A saliency box has no face to badge, and neither does an unresolved photo.
  it('matches nothing for a subject or an unresolved photo', () => {
    expect(pipe.transform(face(7), keySubject({ kind: 'subject', face_id: null }))).toBe(false);
    expect(pipe.transform(face(7), keySubject({ kind: 'none', face_id: null }))).toBe(false);
    expect(pipe.transform(face(7), null)).toBe(false);
  });
});

describe('SubjectRingClassPipe', () => {
  const pipe = new SubjectRingClassPipe();

  it('rings the sharpest tier green', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 10 }))).toBe('ring-green-500');
  });

  it('rings the mid tier amber', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 6 }))).toBe('ring-amber-500');
  });

  it('rings the softest tier red', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 2 }))).toBe('ring-red-500');
  });

  it('is neutral when no score is available', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: null }))).toBe('ring-white/20');
  });
});

describe('WeightRemainingPipe', () => {
  const pipe = new WeightRemainingPipe();

  it('returns remaining count against the configured threshold', () => {
    const stats = { category_breakdown: [{ category: 'portrait', count: 12 }], min_comparisons_for_optimization: 50 };
    expect(pipe.transform('portrait', stats)).toBe(38);
  });

  it('returns the full threshold when the category has no comparisons yet', () => {
    const stats = { category_breakdown: [{ category: 'street', count: 3 }], min_comparisons_for_optimization: 20 };
    expect(pipe.transform('portrait', stats)).toBe(20);
  });

  it('returns 0 (ready) once the threshold is met', () => {
    const stats = { category_breakdown: [{ category: 'portrait', count: 60 }], min_comparisons_for_optimization: 50 };
    expect(pipe.transform('portrait', stats)).toBe(0);
  });

  it('falls back to the default threshold of 50 when unset', () => {
    expect(pipe.transform('portrait', { category_breakdown: [] })).toBe(50);
  });

  it('returns 0 when category or stats are missing', () => {
    expect(pipe.transform(null, { min_comparisons_for_optimization: 50 })).toBe(0);
    expect(pipe.transform('portrait', null)).toBe(0);
  });
});

const face = (overrides: Partial<CullingFace> = {}): CullingFace =>
  ({ id: 1, face_index: 0, ...overrides });

const thresholds: FaceThresholds = { eyes_closed_max: 4.0, poor_expression_min: 4.0 };

describe('FacePoorExpressionPipe', () => {
  const pipe = new FacePoorExpressionPipe();

  it('returns true when expression_score is below the server threshold', () => {
    expect(pipe.transform(face({ expression_score: 2 }), thresholds)).toBe(true);
  });

  it('returns false when expression_score is at or above the threshold', () => {
    expect(pipe.transform(face({ expression_score: 4 }), thresholds)).toBe(false);
  });

  it('returns false when expression_score is absent', () => {
    expect(pipe.transform(face(), thresholds)).toBe(false);
  });

  it('returns false when thresholds have not loaded yet', () => {
    expect(pipe.transform(face({ expression_score: 2 }), null)).toBe(false);
  });
});

describe('FaceRingClassPipe', () => {
  const pipe = new FaceRingClassPipe();

  it('returns red when eyes_open_score is at or below eyes_closed_max', () => {
    expect(pipe.transform(face({ eyes_open_score: 4, smile_score: 8 }), thresholds)).toBe('ring-red-500');
  });

  it('returns orange when eyes are fine but smile_score is below poor_expression_min', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 2 }), thresholds)).toBe('ring-orange-500');
  });

  it('prioritizes red (eyes closed) over orange (poor smile)', () => {
    expect(pipe.transform(face({ eyes_open_score: 1, smile_score: 1 }), thresholds)).toBe('ring-red-500');
  });

  it('returns green when both signals are above their cutoffs', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 7 }), thresholds)).toBe('ring-green-500');
  });

  it('returns green when only one signal is present and fine', () => {
    expect(pipe.transform(face({ eyes_open_score: 8 }), thresholds)).toBe('ring-green-500');
  });

  it('returns neutral when both signals are missing (turned head)', () => {
    expect(pipe.transform(face(), thresholds)).toBe('ring-white/20');
  });

  it('returns neutral when thresholds have not loaded yet', () => {
    expect(pipe.transform(face({ eyes_open_score: 1 }), null)).toBe('ring-white/20');
  });
});

describe('FaceDimmedPipe', () => {
  const pipe = new FaceDimmedPipe();

  it('never dims when both sliders are at 0 (filter off)', () => {
    expect(pipe.transform(face({ eyes_open_score: 1, smile_score: 1 }), 0, 0)).toBe(false);
  });

  it('keeps faces below the eyes slider bright and dims the rest', () => {
    expect(pipe.transform(face({ eyes_open_score: 3 }), 5, 0)).toBe(false);
    expect(pipe.transform(face({ eyes_open_score: 8 }), 5, 0)).toBe(true);
  });

  it('keeps faces below the smile slider bright and dims the rest', () => {
    expect(pipe.transform(face({ smile_score: 2 }), 0, 5)).toBe(false);
    expect(pipe.transform(face({ smile_score: 8 }), 0, 5)).toBe(true);
  });

  it('stays bright when below either of two active sliders', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 2 }), 5, 5)).toBe(false);
  });

  it('dims faces with no signals while a slider is active', () => {
    expect(pipe.transform(face(), 5, 0)).toBe(true);
  });
});

describe('SortIconPipe', () => {
  const pipe = new SortIconPipe();

  it('maps each known sort mode to its icon', () => {
    expect(pipe.transform('easiest')).toBe('bolt');
    expect(pipe.transform('redundant')).toBe('content_copy');
    expect(pipe.transform('best')).toBe('star');
    expect(pipe.transform('recent')).toBe('schedule');
    expect(pipe.transform('needs_comparisons')).toBe('compare_arrows');
    expect(pipe.transform('chronological')).toBe('history');
  });

  it('falls back to the generic sort icon for an unknown mode', () => {
    expect(pipe.transform('whatever')).toBe('sort');
  });
});

describe('EvOffsetPipe', () => {
  const pipe = new EvOffsetPipe();

  it('signs the offset so the rung of the ladder is readable', () => {
    expect(pipe.transform(2)).toBe('+2 EV');
    expect(pipe.transform(-2)).toBe('−2 EV');
    expect(pipe.transform(0)).toBe('0 EV');
  });

  it('rounds a third-stop offset to one decimal', () => {
    expect(pipe.transform(1.33)).toBe('+1.3 EV');
    expect(pipe.transform(-1.96)).toBe('−2 EV');
  });

  it('renders nothing for a frame outside any bracket', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform(NaN)).toBe('');
  });
});

describe('CullProfileIconPipe', () => {
  const pipe = new CullProfileIconPipe();

  it('maps each shipped profile to its icon', () => {
    expect(pipe.transform('balanced')).toBe('balance');
    expect(pipe.transform('wedding')).toBe('favorite');
    expect(pipe.transform('sports')).toBe('directions_run');
    expect(pipe.transform('concert')).toBe('music_note');
    expect(pipe.transform('wildlife')).toBe('pets');
  });

  it('falls back to the theatre mask for unknown / empty profiles', () => {
    expect(pipe.transform('custom_preset')).toBe('theaters');
    expect(pipe.transform('')).toBe('theaters');
    expect(pipe.transform(null)).toBe('theaters');
    expect(pipe.transform(undefined)).toBe('theaters');
  });
});

describe('CategoryIconPipe', () => {
  const pipe = new CategoryIconPipe();
  const ICONS = (CategoryIconPipe as unknown as { ICONS: Record<string, string> }).ICONS;

  it('maps known categories to sensible distinct icons', () => {
    expect(pipe.transform('portrait')).toBe('person');
    expect(pipe.transform('landscape')).toBe('landscape');
    expect(pipe.transform('sports')).toBe('sports_soccer');
    expect(pipe.transform('golden_hour')).toBe('wb_twilight');
    expect(pipe.transform('urban')).toBe('location_city');
    expect(pipe.transform('human_others')).toBe('people');
  });

  it('falls back to the generic category icon for unknown / empty values', () => {
    expect(pipe.transform('user_defined_genre')).toBe('category');
    expect(pipe.transform('')).toBe('category');
    expect(pipe.transform(null)).toBe('category');
    expect(pipe.transform(undefined)).toBe('category');
  });

  it('assigns a pairwise-distinct icon to every mapped category', () => {
    const icons = Object.values(ICONS);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it('never reuses the generic fallback icon for a mapped category', () => {
    expect(Object.values(ICONS)).not.toContain('category');
  });
});

describe('CullPreviewUrlPipe', () => {
  const pipe = new CullPreviewUrlPipe();

  it('builds the cull_preview endpoint URL with encoded path and style', () => {
    expect(pipe.transform('/a/b c.jpg', 'Velvia look'))
      .toBe('/api/photo/cull_preview?path=%2Fa%2Fb+c.jpg&style=Velvia+look');
  });
});

describe('GroupOverridePipe', () => {
  const pipe = new GroupOverridePipe();
  const group = (overrides: (string | null)[]): CullingGroup => ({
    group_id: 1, type: 'panorama', reason: '3 frames', best_path: '/p0.jpg', count: 3,
    photos: overrides.map((sequence_override, i) => ({
      path: `/p${i}.jpg`, filename: `p${i}.jpg`, aggregate: 5, aesthetic: 5,
      tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: null,
      burst_score: 5, sequence_override,
    })),
  });

  it('reports nothing for an uncorrected set', () => {
    expect(pipe.transform(group([null, null, null]))).toBe('');
  });

  it('reports the correction carried by the frames', () => {
    expect(pipe.transform(group(['suppressed', 'suppressed', 'suppressed']))).toBe('suppressed');
  });

  // A set is corrected whole, but the feed can serve a partially-overlapping
  // set after a re-run renumbered the groups; one corrected frame still means
  // the user has said something about this set, and the chip must show it.
  it('reports a correction carried by only some frames', () => {
    expect(pipe.transform(group([null, 'hdr_panorama', null]))).toBe('hdr_panorama');
  });
});

describe('peakingEdgeOverlay', () => {
  /** A grey frame with a hard vertical edge at `edgeX` (left dark, right bright). */
  const frameWithEdge = (w: number, h: number, edgeX: number): Uint8ClampedArray => {
    const data = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const p = (y * w + x) * 4;
        const v = x < edgeX ? 0 : 255;
        data[p] = data[p + 1] = data[p + 2] = v;
        data[p + 3] = 255;
      }
    }
    return data;
  };

  /** Defocus stand-in: a horizontal box blur, which spreads a step into a ramp
   *  whose gradient is the step divided by the window -- exactly how a defocused
   *  edge loses gradient. */
  const boxBlurX = (
    data: Uint8ClampedArray, w: number, h: number, radius: number,
  ): Uint8ClampedArray => {
    const out = new Uint8ClampedArray(data.length);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let sum = 0;
        for (let k = -radius; k <= radius; k++) {
          const sx = Math.min(w - 1, Math.max(0, x + k));
          sum += data[(y * w + sx) * 4];
        }
        const v = sum / (2 * radius + 1);
        const p = (y * w + x) * 4;
        out[p] = out[p + 1] = out[p + 2] = v;
        out[p + 3] = 255;
      }
    }
    return out;
  };

  /** A deterministic noise field: every pixel is a strong edge, so the coverage
   *  cap -- and only the cap -- decides how much gets painted. */
  const noiseFrame = (w: number, h: number): Uint8ClampedArray => {
    const data = new Uint8ClampedArray(w * h * 4);
    let seed = 42;
    for (let i = 0; i < w * h; i++) {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      const p = i * 4;
      data[p] = data[p + 1] = data[p + 2] = seed % 256;
      data[p + 3] = 255;
    }
    return data;
  };

  const litCount = (out: Uint8ClampedArray): number => {
    let count = 0;
    for (let p = 3; p < out.length; p += 4) {
      if (out[p] > 0) count += 1;
    }
    return count;
  };

  const litColumns = (out: Uint8ClampedArray, w: number, h: number): Set<number> => {
    const columns = new Set<number>();
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (out[(y * w + x) * 4 + 3] > 0) columns.add(x);
      }
    }
    return columns;
  };

  it('paints the edge and nothing else', () => {
    const w = 16, h = 16;
    const out = peakingEdgeOverlay(frameWithEdge(w, h, 8), w, h);
    // The Sobel window straddles the transition, so the two columns either side
    // of it light up -- and only those.
    expect(litColumns(out, w, h)).toEqual(new Set([7, 8]));
  });

  it('paints the edge opaque red so it reads over any frame', () => {
    const w = 16, h = 16;
    const out = peakingEdgeOverlay(frameWithEdge(w, h, 8), w, h);
    const p = (2 * w + 8) * 4;
    expect([out[p], out[p + 1], out[p + 2], out[p + 3]]).toEqual([255, 32, 32, 255]);
  });

  // The threshold is absolute: a frame whose gradients never reach the floor is
  // out of focus and reads as out of focus, instead of being handed the same
  // share of red a sharp frame gets by construction.
  it('paints nothing on a frame with no edges at all', () => {
    const w = 16, h = 16;
    const flat = new Uint8ClampedArray(w * h * 4).fill(128);
    const out = peakingEdgeOverlay(flat, w, h);
    expect(litColumns(out, w, h).size).toBe(0);
  });

  // The point of an absolute floor: coverage ranks the two frames the way a
  // culler would. A relative threshold inverted this -- the blurred copy, judged
  // against its own weaker gradients, glowed more than the frame it came from.
  it('paints at least as much of a sharp frame as of a blurred copy of it', () => {
    const w = 64, h = 64;
    const sharp = frameWithEdge(w, h, 32);
    const blurred = boxBlurX(sharp, w, h, 12);
    expect(litCount(peakingEdgeOverlay(sharp, w, h)))
      .toBeGreaterThanOrEqual(litCount(peakingEdgeOverlay(blurred, w, h)));
  });

  it('leaves a defocused frame unpainted while its sharp original lights up', () => {
    const w = 64, h = 64;
    const sharp = frameWithEdge(w, h, 32);
    expect(litCount(peakingEdgeOverlay(sharp, w, h))).toBeGreaterThan(0);
    expect(litCount(peakingEdgeOverlay(boxBlurX(sharp, w, h, 12), w, h))).toBe(0);
  });

  // The cap is the relief valve, not the driver: a frame that is edge everywhere
  // (foliage, fabric, noise) must not end up entirely red.
  it('caps how much of an edge-everywhere frame is painted', () => {
    const w = 64, h = 64;
    const out = peakingEdgeOverlay(noiseFrame(w, h), w, h);
    const coverage = litCount(out) / ((w - 2) * (h - 2));
    expect(coverage).toBeGreaterThan(0);
    expect(coverage).toBeLessThanOrEqual(0.15);
  });

  it('returns a clear overlay for a frame too small to convolve', () => {
    const out = peakingEdgeOverlay(new Uint8ClampedArray(2 * 2 * 4).fill(255), 2, 2);
    expect(out.every(v => v === 0)).toBe(true);
  });

  /**
   * Two frames of one subject, side by side, are read by how much red each
   * carries -- which only says anything when one rule painted them both.
   *
   * The content below is the case that broke it: both frames are edge
   * everywhere, so each on its own hits the coverage cap and is handed the same
   * 15% share, and the pair reads as two identical fields of red however
   * different their detail actually is.
   */
  describe('pooled thresholding (compare mode)', () => {
    /** The same noise field at two contrasts: two frames of one subject, one
     *  carrying more detail, both edge everywhere so the cap -- not the floor --
     *  decides how much of each is painted. */
    const detailAt = (w: number, h: number, contrast: number): Uint8ClampedArray => {
      const data = new Uint8ClampedArray(w * h * 4);
      let seed = 42;
      for (let i = 0; i < w * h; i++) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        const p = i * 4;
        data[p] = data[p + 1] = data[p + 2] = 128 + ((seed % 256) - 128) * contrast;
        data[p + 3] = 255;
      }
      return data;
    };

    const W = 64, H = 64;
    const sharp = detailAt(W, H, 1);
    const soft = detailAt(W, H, 0.5);

    it('gives both frames the same paint when each is thresholded on its own', () => {
      const ratio = litCount(peakingEdgeOverlay(sharp, W, H))
        / litCount(peakingEdgeOverlay(soft, W, H));
      expect(ratio).toBeGreaterThan(0.9);
      expect(ratio).toBeLessThan(1.1);
    });

    it('lets the sharper frame carry visibly more red under one pooled threshold', () => {
      const fields = [sharp, soft].map(f => peakingGradientField(f, W, H));
      const threshold = peakingThreshold(fields);

      const painted = fields.map(field => litCount(paintPeakingField(field, threshold)));

      expect(painted[0] / painted[1]).toBeGreaterThan(1.5);
    });

    it('caps the pair, not each frame, so the pooled paint stays bounded', () => {
      const fields = [sharp, soft].map(f => peakingGradientField(f, W, H));
      const threshold = peakingThreshold(fields);

      const painted = fields.reduce(
        (sum, field) => sum + litCount(paintPeakingField(field, threshold)), 0);

      expect(painted / (fields[0].area + fields[1].area)).toBeLessThanOrEqual(0.15);
    });

    it('keeps the absolute floor, so a pair of soft frames stays dark', () => {
      const flat = new Uint8ClampedArray(W * H * 4).fill(128);
      const fields = [flat, flat].map(f => peakingGradientField(f, W, H));

      const threshold = peakingThreshold(fields);
      expect(threshold).toBe(24);
      expect(litCount(paintPeakingField(fields[0], threshold))).toBe(0);
    });

    it('is the same answer as the single-frame path when there is one frame', () => {
      const field = peakingGradientField(sharp, W, H);
      expect(litCount(paintPeakingField(field, peakingThreshold([field]))))
        .toBe(litCount(peakingEdgeOverlay(sharp, W, H)));
    });
  });
});

/**
 * The raster pipeline above `peakingEdgeOverlay` -- `loadFrameImage`,
 * `computePeakingOverlay`, `computePooledPeakingOverlays`, and the private
 * `rasterPeakingFrame` they share -- has no coverage anywhere: every component
 * spec mocks these wrappers rather than exercising them. jsdom implements
 * neither image loading nor a working 2d canvas context, so both are stubbed
 * per test rather than globally, to keep the fakes local to what each
 * scenario needs.
 */
describe('the focus-peaking raster pipeline', () => {
  /** A loadable Image stand-in: `src` fires `onload`/`onerror` synchronously
   *  (jsdom never fires either on its own), so no test needs to await a real
   *  decode. `fails` picks onerror by source string, for the multi-frame
   *  pooled case where only one of several sources should fail. */
  function stubImage(
    naturalWidth: number, naturalHeight: number, fails: (src: string) => boolean = () => false,
  ): void {
    class FakeImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      naturalWidth = naturalWidth;
      naturalHeight = naturalHeight;
      width = 0;
      height = 0;
      private _src = '';
      set src(value: string) {
        this._src = value;
        if (fails(value)) this.onerror?.();
        else this.onload?.();
      }
      get src(): string {
        return this._src;
      }
    }
    vi.stubGlobal('Image', FakeImage);
  }

  /** A 2d context stand-in sized off whatever the source set on the real
   *  (jsdom-backed) canvas element, so it stays correct however
   *  `rasterPeakingFrame` scales the frame. jsdom's own `getContext` returns
   *  null with no `canvas` npm package installed (none is), so every
   *  raster-path test needs this regardless of that default. */
  function stubWorkingCanvas(dataUrl: string): void {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
      function (this: HTMLCanvasElement, kind: string) {
        if (kind !== '2d') return null;
        return {
          drawImage: vi.fn(),
          getImageData: (_x: number, _y: number, w: number, h: number) =>
            ({ data: new Uint8ClampedArray(w * h * 4) }),
          createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4) }),
          putImageData: vi.fn(),
        } as unknown as CanvasRenderingContext2D;
      } as unknown as typeof HTMLCanvasElement.prototype.getContext,
    );
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(dataUrl);
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe('loadFrameImage', () => {
    it('resolves with the image once it loads', async () => {
      stubImage(100, 80);
      await expect(loadFrameImage('/p.jpg')).resolves.toBeInstanceOf(Image);
    });

    it('rejects naming the source once the browser fails to load it', async () => {
      stubImage(100, 80, () => true);
      await expect(loadFrameImage('/broken.jpg')).rejects.toThrow('cannot load /broken.jpg');
    });
  });

  describe('computePeakingOverlay (raster -> data URL)', () => {
    it('rasters a loaded frame into the PNG data URL its canvas produced', async () => {
      stubImage(100, 80);
      stubWorkingCanvas('data:image/png;base64,FAKE');
      await expect(computePeakingOverlay('/p.jpg')).resolves.toBe('data:image/png;base64,FAKE');
    });

    it('returns null for a frame with no natural dimensions', async () => {
      stubImage(0, 0);
      stubWorkingCanvas('data:image/png;base64,unused');
      await expect(computePeakingOverlay('/p.jpg')).resolves.toBeNull();
    });

    it('returns null when the canvas cannot produce a 2d context', async () => {
      stubImage(100, 80);
      vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
      await expect(computePeakingOverlay('/p.jpg')).resolves.toBeNull();
    });

    it('returns null when the source fails to load', async () => {
      stubImage(100, 80, () => true);
      stubWorkingCanvas('data:image/png;base64,unused');
      await expect(computePeakingOverlay('/broken.jpg')).rejects.toThrow('cannot load /broken.jpg');
    });
  });

  describe('computePooledPeakingOverlays', () => {
    it('drops a frame that fails to load instead of failing the whole batch', async () => {
      stubImage(100, 80, src => src.includes('broken'));
      stubWorkingCanvas('data:image/png;base64,FAKE');

      const overlays = await computePooledPeakingOverlays(['/a.jpg', '/broken.jpg', '/b.jpg']);

      expect(overlays.size).toBe(2);
      expect(overlays.get('/a.jpg')).toBe('data:image/png;base64,FAKE');
      expect(overlays.get('/b.jpg')).toBe('data:image/png;base64,FAKE');
      expect(overlays.has('/broken.jpg')).toBe(false);
    });

    it('returns an empty map rather than throwing when every frame fails', async () => {
      stubImage(100, 80, () => true);
      stubWorkingCanvas('data:image/png;base64,unused');

      const overlays = await computePooledPeakingOverlays(['/a.jpg', '/b.jpg']);

      expect(overlays.size).toBe(0);
    });
  });
});

describe('PeakingOverlayPipe', () => {
  const pipe = new PeakingOverlayPipe();

  it('returns the overlay generated for the frame', () => {
    expect(pipe.transform('/p.jpg', new Map([['/p.jpg', 'data:image/png;base64,x']])))
      .toBe('data:image/png;base64,x');
  });

  it('returns null while the frame has no overlay', () => {
    expect(pipe.transform('/p.jpg', new Map())).toBeNull();
  });
});

describe('FrameViewBoxPipe', () => {
  const pipe = new FrameViewBoxPipe();

  it('builds the viewBox from the frame size', () => {
    const sizes = new Map<string, FrameSize>([['/p.jpg', { w: 6000, h: 4000 }]]);
    expect(pipe.transform('/p.jpg', sizes)).toBe('0 0 6000 4000');
  });

  it('returns null until the frame has been measured', () => {
    expect(pipe.transform('/p.jpg', new Map())).toBeNull();
  });
});

describe('GridLinesPipe', () => {
  const pipe = new GridLinesPipe();

  it('draws nothing when the grid is off', () => {
    expect(pipe.transform('')).toEqual([]);
  });

  it('draws the rule of thirds', () => {
    expect(pipe.transform('thirds')).toEqual(['33.333%', '66.667%']);
  });

  it('draws the golden ratio', () => {
    expect(pipe.transform('golden')).toEqual(['38.197%', '61.803%']);
  });
});
