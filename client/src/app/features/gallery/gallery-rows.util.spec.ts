import {
  DETAILS_ESTIMATE_PX,
  FALLBACK_ASPECT,
  GalleryRow,
  MOBILE_MIN_CARD_WIDTH_PX,
  MOBILE_MIN_COLUMNS,
  aspectOf,
  buildGridRows,
  buildMosaicRows,
  gridColumnCount,
  totalRowsHeight,
  windowRange,
} from './gallery-rows.util';
import { Photo } from '../../shared/models/photo.model';

function photo(i: number, w = 1600, h = 1200): Photo {
  return { path: `/v/p${i}.jpg`, image_width: w, image_height: h } as Photo;
}

/** A row whose fabricated dimensions were cleared: it carries only the aspect
 *  the thumbnail-sized pair had (a thumbnail is scaled, not cropped). */
function clearedPhoto(i: number, aspect: number | null): Photo {
  return {
    path: `/v/c${i}.jpg`,
    image_width: null, image_height: null, image_aspect: aspect,
  } as Photo;
}

function photos(n: number): Photo[] {
  return Array.from({ length: n }, (_, i) => photo(i));
}

describe('aspectOf', () => {
  it('prefers the recorded pixel dimensions', () => {
    expect(aspectOf(photo(0, 1600, 1200))).toBeCloseTo(4 / 3, 6);
  });

  it('falls back to the aspect a cleared row kept', () => {
    expect(aspectOf(clearedPhoto(0, 427 / 640))).toBeCloseTo(0.667, 3);
  });

  it('never lets the kept aspect override real dimensions', () => {
    const conflicted = { ...photo(0, 1000, 2000), image_aspect: 4 / 3 } as Photo;
    expect(aspectOf(conflicted)).toBeCloseTo(0.5, 6);
  });

  it('uses the neutral default only when nothing is known', () => {
    expect(aspectOf(clearedPhoto(0, null))).toBe(FALLBACK_ASPECT);
    expect(aspectOf({ path: '/v/x.jpg' } as Photo)).toBe(FALLBACK_ASPECT);
  });

  it('ignores a non-positive aspect rather than dividing by it', () => {
    expect(aspectOf(clearedPhoto(0, 0))).toBe(FALLBACK_ASPECT);
    expect(aspectOf(clearedPhoto(1, -1))).toBe(FALLBACK_ASPECT);
  });
});

// The regression this guards: 42,676 rows had their fabricated dimensions
// cleared, 8,965 of them portrait. With only the landscape default left, every
// one of those got a 4:3 tile — and the card image is `object-cover`, so the
// frame was cropped top and bottom, not merely boxed oddly.
describe('a cleared row keeps its orientation', () => {
  it('sizes a portrait mosaic tile taller than it is wide', () => {
    const rows = buildMosaicRows([clearedPhoto(0, 427 / 640)], 1200, 200, 8);
    expect(rows[0].height).toBe(200);
    expect(rows[0].widths[0]).toBeLessThan(rows[0].height);
  });

  it('sizes a landscape mosaic tile wider than it is tall', () => {
    const rows = buildMosaicRows([clearedPhoto(0, 640 / 427)], 1200, 200, 8);
    expect(rows[0].widths[0]).toBeGreaterThan(rows[0].height);
  });

  it('packs a portrait row with more tiles than a landscape one', () => {
    const portrait = buildMosaicRows(
      Array.from({ length: 12 }, (_, i) => clearedPhoto(i, 2 / 3)), 1200, 200, 8);
    const landscape = buildMosaicRows(
      Array.from({ length: 12 }, (_, i) => clearedPhoto(i, 3 / 2)), 1200, 200, 8);
    expect(portrait[0].photos.length).toBeGreaterThan(landscape[0].photos.length);
  });

  it('gives a single-column grid cell a portrait height', () => {
    const rows = buildGridRows([clearedPhoto(0, 2 / 3)], 150, 168, 8, true);
    expect(rows[0].height).toBe(Math.round(150 / (2 / 3)));
    expect(rows[0].height).toBeGreaterThan(150);
  });

  it('still falls back to landscape when no aspect was kept either', () => {
    const rows = buildMosaicRows([clearedPhoto(0, null)], 1200, 200, 8);
    expect(rows[0].widths[0]).toBe(Math.floor(FALLBACK_ASPECT * 200));
  });
});

describe('gridColumnCount', () => {
  it('matches CSS auto-fill column math', () => {
    // width 1000, card 168, gap 8 -> floor(1008 / 176) = 5
    expect(gridColumnCount(1000, 168, 8)).toBe(5);
  });

  it('never returns less than one column on desktop', () => {
    expect(gridColumnCount(100, 400, 8)).toBe(1);
    expect(gridColumnCount(0, 168, 8)).toBe(1);
  });

  it('floors to MOBILE_MIN_COLUMNS off desktop, even when the natural count is lower', () => {
    // width 374 (390px viewport minus gallery padding), card 168, gap 8 -> natural floor(382/176)=2, floored to 3
    expect(gridColumnCount(374, 168, 8, false)).toBe(MOBILE_MIN_COLUMNS);
  });

  it('does not floor on desktop for the same inputs', () => {
    expect(gridColumnCount(374, 168, 8, true)).toBe(2);
  });

  it('lets a smaller card width exceed the mobile floor', () => {
    // width 374, card 80, gap 8 -> floor(382/88)=4, already above the floor
    expect(gridColumnCount(374, 80, 8, false)).toBe(4);
  });

  it('floors zero-width viewports off desktop too', () => {
    expect(gridColumnCount(0, 168, 8, false)).toBe(MOBILE_MIN_COLUMNS);
  });

  // The density slider is only a control if some width it offers changes the
  // answer. On a 390px phone the shipped 120px minimum does not: the floor eats
  // the whole travel.
  describe('mobile card-width floor', () => {
    const PHONE_WIDTH = 374;
    const GAP = 8;

    it('collapses every stop of the shipped slider onto the column floor', () => {
      for (const cardWidth of [120, 168, 300, 400]) {
        expect(gridColumnCount(PHONE_WIDTH, cardWidth, GAP, false)).toBe(MOBILE_MIN_COLUMNS);
      }
    });

    it('clears the floor at MOBILE_MIN_CARD_WIDTH_PX, so the slider adds a column', () => {
      expect(gridColumnCount(PHONE_WIDTH, MOBILE_MIN_CARD_WIDTH_PX, GAP, false))
        .toBeGreaterThan(MOBILE_MIN_COLUMNS);
      // floor((374 + 8) / (72 + 8)) = 4
      expect(gridColumnCount(PHONE_WIDTH, MOBILE_MIN_CARD_WIDTH_PX, GAP, false)).toBe(4);
    });

    it('rows the phone grid four across at that width', () => {
      const rows = buildGridRows(photos(9), PHONE_WIDTH, MOBILE_MIN_CARD_WIDTH_PX, GAP, true, false);
      expect(rows.map(r => r.photos.length)).toEqual([4, 4, 1]);
    });
  });
});

describe('buildGridRows', () => {
  it('chunks photos into rows of the column count', () => {
    const rows = buildGridRows(photos(12), 1000, 168, 8, true);
    expect(rows.map(r => r.photos.length)).toEqual([5, 5, 2]);
    expect(rows.map(r => r.startIndex)).toEqual([0, 5, 10]);
  });

  it('hideDetails rows are square cells with exact offsets', () => {
    const rows = buildGridRows(photos(10), 1000, 168, 8, true);
    const cellW = (1000 - 4 * 8) / 5;
    expect(rows[0].height).toBe(Math.round(cellW));
    expect(rows[1].offset).toBe(rows[0].height + 8);
    expect(rows[0].widths).toEqual(Array(5).fill(Math.floor(cellW)));
  });

  it('details-on rows add the estimate to the tallest image', () => {
    const tallAndWide = [photo(0, 1000, 2000), photo(1, 2000, 1000)];
    const rows = buildGridRows(tallAndWide, 1000, 400, 8, false);
    const cellW = (1000 - 8) / 2;
    expect(rows[0].height).toBe(Math.round(cellW / 0.5) + DETAILS_ESTIMATE_PX);
  });

  it('a single natural column uses aspect-ratio height', () => {
    // width 150 < cardMinW 168 -> naturally floors to 1 column, full-width cell
    const rows = buildGridRows([photo(0, 1000, 500)], 150, 168, 8, true);
    expect(rows[0].height).toBe(Math.round(150 / 2));
  });

  it('floors to MOBILE_MIN_COLUMNS off desktop instead of collapsing to one column', () => {
    const rows = buildGridRows([photo(0, 1000, 500)], 390, 168, 8, true, false);
    expect(rows[0].widths).toEqual([124]);
    expect(rows[0].height).toBe(125);
  });

  it('offsets are strictly increasing', () => {
    const rows = buildGridRows(photos(50), 1200, 168, 8, true);
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i].offset).toBeGreaterThan(rows[i - 1].offset);
    }
  });
});

describe('buildMosaicRows', () => {
  it('rows fill the container width exactly (last photo absorbs rounding)', () => {
    const rows = buildMosaicRows(photos(20), 1200, 200, 8);
    for (const row of rows.slice(0, -1)) {
      const used = row.widths!.reduce((a, b) => a + b, 0) + (row.widths!.length - 1) * 8;
      expect(used).toBe(1200);
    }
  });

  it('startIndex is continuous across rows', () => {
    const rows = buildMosaicRows(photos(23), 1200, 200, 8);
    let expected = 0;
    for (const row of rows) {
      expect(row.startIndex).toBe(expected);
      expected += row.photos.length;
    }
    expect(expected).toBe(23);
  });

  it('full rows are at most the target height', () => {
    const rows = buildMosaicRows(photos(20), 1200, 200, 8);
    for (const row of rows.slice(0, -1)) {
      expect(row.height).toBeLessThanOrEqual(200);
    }
  });

  it('last incomplete row keeps the target height', () => {
    const rows = buildMosaicRows(photos(1), 1200, 200, 8);
    expect(rows[0].height).toBe(200);
    expect(rows[0].widths![0]).toBe(Math.floor((1600 / 1200) * 200));
  });

  it('returns empty for zero width or no photos', () => {
    expect(buildMosaicRows([], 1200, 200, 8)).toEqual([]);
    expect(buildMosaicRows(photos(3), 0, 200, 8)).toEqual([]);
  });
});

describe('windowRange', () => {
  const rows: GalleryRow[] = Array.from({ length: 100 }, (_, i) => ({
    photos: [], widths: [], height: 192, offset: i * 200, startIndex: i * 5,
  }));

  it('top of list shows the first rows', () => {
    const { first, last } = windowRange(rows, 0, 800, 0);
    expect(first).toBe(0);
    expect(last).toBe(4); // rows at offsets 0..800
  });

  it('middle window straddles the scroll position', () => {
    const { first, last } = windowRange(rows, 5000, 800, 0);
    expect(rows[first].offset + rows[first].height).toBeGreaterThanOrEqual(5000);
    expect(rows[last].offset).toBeLessThanOrEqual(5800);
    expect(first).toBeLessThanOrEqual(25);
    expect(last).toBeGreaterThanOrEqual(28);
  });

  it('bottom of list clamps to the final row', () => {
    const { first, last } = windowRange(rows, 19_900, 800, 0);
    expect(last).toBe(99);
    expect(first).toBeLessThanOrEqual(99);
  });

  it('overscan extends both directions', () => {
    const base = windowRange(rows, 5000, 800, 0);
    const padded = windowRange(rows, 5000, 800, 1000);
    expect(padded.first).toBeLessThan(base.first);
    expect(padded.last).toBeGreaterThan(base.last);
  });

  it('empty rows yield an empty range', () => {
    expect(windowRange([], 0, 800, 0)).toEqual({ first: 0, last: -1 });
  });

  it('single row is always visible', () => {
    const single = [{ photos: [], widths: [], height: 100, offset: 0, startIndex: 0 }];
    expect(windowRange(single, 0, 800, 0)).toEqual({ first: 0, last: 0 });
  });
});

describe('totalRowsHeight', () => {
  it('is the bottom edge of the last row', () => {
    const rows = buildGridRows(photos(12), 1000, 168, 8, true);
    const last = rows[rows.length - 1];
    expect(totalRowsHeight(rows)).toBe(last.offset + last.height);
  });

  it('is zero for no rows', () => {
    expect(totalRowsHeight([])).toBe(0);
  });
});
