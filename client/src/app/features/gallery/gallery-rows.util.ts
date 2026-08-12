import { Photo } from '../../shared/models/photo.model';

/**
 * Unified row model for the windowed (virtualized) gallery.
 *
 * Both display modes reduce to a list of measurable rows: mosaic rows carry
 * per-photo justified widths, grid rows use equal cells (widths = null).
 * Deterministic offsets make scroll windowing and restoration exact.
 */
export interface GalleryRow {
  photos: Photo[];
  /** Per-photo pixel widths (justified for mosaic, equal cells for grid). */
  widths: number[];
  height: number;
  /** Y offset of the row's top relative to the rows container. */
  offset: number;
  /** Index of the row's first photo within the full photo list. */
  startIndex: number;
}

/** Estimated height of the details block under a card (filename/EXIF/tags). */
export const DETAILS_ESTIMATE_PX = 96;

function aspectOf(photo: Photo): number {
  return photo.image_width && photo.image_height
    ? photo.image_width / photo.image_height
    : 4 / 3;
}

/** Minimum grid columns enforced off desktop so a narrow viewport never
 * degrades to one photo per screen (comparable gallery apps default to 3-4). */
export const MOBILE_MIN_COLUMNS = 3;

/**
 * Smallest card the thumbnail slider may ask for on a touch device.
 *
 * The floor above is also a ceiling: on a 390px phone every card width the
 * shipped slider offers (120px and up) yields fewer columns than
 * MOBILE_MIN_COLUMNS, so the whole slider travel collapses onto 3 and the
 * control does nothing. 72px is the first width that clears the floor there —
 * floor((374 + 8) / (72 + 8)) = 4 — which is what gives the slider something to
 * change. Desktop keeps the server's own minimum.
 */
export const MOBILE_MIN_CARD_WIDTH_PX = 72;

/** Columns the CSS `repeat(auto-fill, minmax(cardMinW, 1fr))` grid produces,
 * floored to MOBILE_MIN_COLUMNS when isDesktop is false. */
export function gridColumnCount(width: number, cardMinW: number, gap: number, isDesktop = true): number {
  if (width <= 0) return isDesktop ? 1 : MOBILE_MIN_COLUMNS;
  const cols = Math.max(1, Math.floor((width + gap) / (cardMinW + gap)));
  return isDesktop ? cols : Math.max(MOBILE_MIN_COLUMNS, cols);
}

/**
 * Row-chunk the photos the way the CSS grid lays them out.
 *
 * With hideDetails (the default) cards are aspect-square, so heights are
 * exact. With details shown, the height is an estimate refined by the
 * tallest image in the row plus DETAILS_ESTIMATE_PX.
 */
export function buildGridRows(
  photos: Photo[],
  width: number,
  cardMinW: number,
  gap: number,
  hideDetails: boolean,
  isDesktop = true,
): GalleryRow[] {
  if (!photos.length || width <= 0) return [];
  const cols = gridColumnCount(width, cardMinW, gap, isDesktop);
  const cellW = (width - (cols - 1) * gap) / cols;

  const rows: GalleryRow[] = [];
  let offset = 0;
  for (let start = 0; start < photos.length; start += cols) {
    const rowPhotos = photos.slice(start, start + cols);
    let height: number;
    if (cols === 1) {
      height = Math.round(cellW / aspectOf(rowPhotos[0]))
        + (hideDetails ? 0 : DETAILS_ESTIMATE_PX);
    } else if (hideDetails) {
      height = Math.round(cellW);
    } else {
      const maxImgH = Math.max(...rowPhotos.map(p => cellW / aspectOf(p)));
      height = Math.round(maxImgH) + DETAILS_ESTIMATE_PX;
    }
    const widths = rowPhotos.map(() => Math.floor(cellW));
    rows.push({ photos: rowPhotos, widths, height, offset, startIndex: start });
    offset += height + gap;
  }
  return rows;
}

/** Justified mosaic rows preserving aspect ratios (same math the inline
 * gallery template used, plus offsets and start indexes). */
export function buildMosaicRows(
  photos: Photo[],
  width: number,
  targetHeight: number,
  gap: number,
): GalleryRow[] {
  if (!photos.length || width <= 0) return [];

  const rows: GalleryRow[] = [];
  let rowPhotos: Photo[] = [];
  let rowAspects: number[] = [];
  let rowStart = 0;
  let offset = 0;

  const pushRow = (widths: number[], height: number) => {
    rows.push({
      photos: [...rowPhotos], widths, height: Math.floor(height),
      offset, startIndex: rowStart,
    });
    offset += Math.floor(height) + gap;
    rowStart += rowPhotos.length;
    rowPhotos = [];
    rowAspects = [];
  };

  for (const photo of photos) {
    rowPhotos.push(photo);
    rowAspects.push(aspectOf(photo));

    const totalAspect = rowAspects.reduce((a, b) => a + b, 0);
    const availableWidth = width - (rowPhotos.length - 1) * gap;
    const rowHeight = availableWidth / totalAspect;

    if (rowHeight <= targetHeight) {
      const widths = rowAspects.map(a => Math.floor(a * rowHeight));
      // Distribute rounding remainder to the last photo
      const usedWidth = widths.reduce((a, b) => a + b, 0) + (widths.length - 1) * gap;
      widths[widths.length - 1] += width - usedWidth;
      pushRow(widths, rowHeight);
    }
  }

  // Last incomplete row: target height, left-aligned
  if (rowPhotos.length) {
    const widths = rowAspects.map(a => Math.floor(a * targetHeight));
    pushRow(widths, targetHeight);
  }

  return rows;
}

/** Total pixel height of all rows (offsets already include inter-row gaps). */
export function totalRowsHeight(rows: GalleryRow[]): number {
  if (!rows.length) return 0;
  const last = rows[rows.length - 1];
  return last.offset + last.height;
}

/**
 * Visible row range [first, last] for the given scroll position, found by
 * binary search on row offsets. Overscan extends the window in both
 * directions so fast scrolling doesn't flash blank rows.
 */
export function windowRange(
  rows: GalleryRow[],
  scrollTop: number,
  viewportH: number,
  overscan: number,
): { first: number; last: number } {
  if (!rows.length) return { first: 0, last: -1 };
  const top = Math.max(0, scrollTop - overscan);
  const bottom = scrollTop + viewportH + overscan;

  // First row whose bottom edge is below `top`
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].offset + rows[mid].height < top) lo = mid + 1;
    else hi = mid;
  }
  const first = lo;

  let last = first;
  while (last + 1 < rows.length && rows[last + 1].offset <= bottom) {
    last++;
  }
  return { first, last };
}
