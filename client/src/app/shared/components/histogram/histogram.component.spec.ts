import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { HISTOGRAM_MODE_KEYS } from '../../../core/services/histogram-preferences.service';
import { I18nService } from '../../../core/services/i18n.service';
import { HistogramComponent } from './histogram.component';

/** A 2x1 frame: one pure-red pixel, one pure-blue one. */
const SAMPLED_PIXELS = new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255]);

describe('HistogramComponent', () => {
  let fixture: ComponentFixture<HistogramComponent>;
  let mockApi: { get: Mock };
  let getContext: Mock;
  let loadedImages: { src: string; onload: (() => void) | null }[];

  // Echoes the key with its params substituted, so a test can see the values
  // the component passed rather than only the key it chose.
  const mockI18n = {
    t: vi.fn((key: string, vars?: Record<string, string | number>) =>
      Object.entries(vars ?? {}).reduce(
        (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)), key)),
    currentLang: vi.fn(() => 'en'),
    locale: vi.fn(() => 'en'),
    translations: vi.fn(() => ({})),
  };

  function svg(): SVGElement | null {
    return fixture.nativeElement.querySelector('svg');
  }

  function polylines(): SVGPolylineElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('polyline'));
  }

  function markers(side: 'left' | 'right'): Element[] {
    const holder = fixture.nativeElement.querySelector(`div.absolute.${side}-0`);
    return holder ? Array.from(holder.querySelectorAll('span')) : [];
  }

  function modeButtons(): HTMLButtonElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('button'));
  }

  function render(inputs: {
    path?: string; src?: string; monochrome?: boolean; height?: number;
    showModeToggle?: boolean; defaultMode?: string; indicatorPercent?: number;
    surface?: string;
  }): void {
    for (const [key, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(key, value);
    }
    fixture.detectChanges();
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of({ bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null })) };
    loadedImages = [];
    getContext = vi.fn(() => ({
      drawImage: vi.fn(),
      getImageData: vi.fn(() => ({ data: SAMPLED_PIXELS })),
    }));

    HTMLCanvasElement.prototype.getContext = getContext as unknown as
      typeof HTMLCanvasElement.prototype.getContext;
    // jsdom never fetches an <img>, so onload would never fire: record every
    // instance and let each test decide when it "loads".
    vi.stubGlobal('Image', class {
      decoding = '';
      naturalWidth = 2;
      naturalHeight = 1;
      onload: (() => void) | null = null;
      private url = '';
      get src(): string { return this.url; }
      set src(value: string) {
        this.url = value;
        loadedImages.push(this as unknown as { src: string; onload: (() => void) | null });
      }
    });

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    fixture = TestBed.createComponent(HistogramComponent);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.detail);
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.tooltip);
  });

  it('draws the stored bins without sampling the thumbnail', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: [0.25, 0, 0, 0], g: [0, 1, 0, 0], b: [0, 0, 0.5, 0],
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg' });

    expect(mockApi.get).toHaveBeenCalledWith('/photo/histogram', { path: '/a.jpg', bins: 64 });
    expect(loadedImages).toHaveLength(0);
    expect(polylines()).toHaveLength(3);
    expect(polylines()[0].getAttribute('points'))
      .toBe('0.0,30.0 42.7,40.0 85.3,40.0 128.0,40.0');
  });

  it('draws the filled luminance curve in luminance mode', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: [0.25, 0, 0, 0], g: [0, 1, 0, 0], b: [0, 0, 0.5, 0],
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg', defaultMode: 'luma' });

    expect(polylines()).toHaveLength(0);
    expect(fixture.nativeElement.querySelector('polygon').getAttribute('points'))
      .toBe('0,40 0.0,0.0 42.7,20.0 85.3,40.0 128.0,40.0 128,40');
  });

  it('shows luma immediately for a legacy row, without eagerly sampling', () => {
    render({ path: '/a.jpg', src: '/thumb/a.jpg', defaultMode: 'luma' });

    expect(svg()).not.toBeNull();
    expect(polylines()).toHaveLength(0);
    // luma mode never needs channel data -- no eager canvas sample.
    expect(loadedImages).toHaveLength(0);
  });

  it('lazily samples the thumbnail for RGB once a legacy (luma-only) stored measurement resolves in RGB mode', () => {
    // A 200 with a real luma array and null r/g/b: distinct from both a 404
    // (which falls straight to sample()) and a full per-channel row.
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null,
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg', defaultMode: 'rgb' });
    fixture.detectChanges();

    expect(loadedImages).toHaveLength(1);
    loadedImages[0].onload!();
    fixture.detectChanges();

    expect(getContext).toHaveBeenCalled();
    expect(polylines()).toHaveLength(3);
  });

  it('lazily samples once the user switches to a channel mode after a legacy load', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null,
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg', showModeToggle: true, defaultMode: 'luma' });
    expect(loadedImages).toHaveLength(0);

    modeButtons()[1].click(); // 'rgb'
    fixture.detectChanges();

    expect(loadedImages).toHaveLength(1);
    loadedImages[0].onload!();
    fixture.detectChanges();

    expect(polylines()).toHaveLength(3);
  });

  it('keeps clipping markers governed exclusively by the stored measurement, never fabricated from the sample', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null, clipped: null,
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg', defaultMode: 'rgb', indicatorPercent: 0 });
    fixture.detectChanges();
    loadedImages[0].onload!();
    fixture.detectChanges();

    // The canvas sample has real pixel data (a pure-red and a pure-blue
    // pixel) that would clip at threshold 0 if markers were computed from
    // it -- they must stay absent because the stored measurement is null.
    expect(markers('left')).toHaveLength(0);
    expect(markers('right')).toHaveLength(0);
  });

  it('draws luminance only for a monochrome photo even with RGB bins', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0, 0, 0], r: [1, 0, 0, 0], g: [1, 0, 0, 0], b: [1, 0, 0, 0],
    }));

    render({ path: '/a.jpg', src: '/thumb/a.jpg', monochrome: true });

    expect(svg()).not.toBeNull();
    expect(polylines()).toHaveLength(0);
  });

  it('falls back to sampling the thumbnail when the photo has no stored histogram', () => {
    mockApi.get.mockReturnValue(throwError(() => new Error('404')));

    render({ path: '/a.jpg', src: '/thumb/a.jpg' });
    expect(svg()).toBeNull();

    expect(loadedImages).toHaveLength(1);
    expect(loadedImages[0].src).toBe('/thumb/a.jpg');
    loadedImages[0].onload!();
    fixture.detectChanges();

    expect(getContext).toHaveBeenCalled();
    expect(polylines()).toHaveLength(3);
  });

  it('samples the thumbnail when no path is provided at all', () => {
    render({ src: '/thumb/a.jpg' });

    expect(mockApi.get).not.toHaveBeenCalled();
    expect(loadedImages).toHaveLength(1);
    loadedImages[0].onload!();
    fixture.detectChanges();
    expect(svg()).not.toBeNull();
  });

  it('renders nothing when neither a path nor a thumbnail is given', () => {
    render({});

    expect(mockApi.get).not.toHaveBeenCalled();
    expect(loadedImages).toHaveLength(0);
    expect(svg()).toBeNull();
  });

  it('ignores a stale sampled frame after the photo changed', () => {
    render({ src: '/thumb/a.jpg' });
    const stale = loadedImages[0];

    render({ src: '/thumb/b.jpg' });
    stale.onload!();
    fixture.detectChanges();

    expect(svg()).toBeNull();
  });

  // --- clipping markers ---------------------------------------------------

  const CLIPPED = {
    bins: 4,
    luma: [0, 1, 0.5, 0], r: [0, 1, 0, 0], g: [0, 1, 0, 0], b: [0, 1, 0, 0],
    clipped: {
      shadow: { luma: 0, r: 9.58, g: 2.94, b: 1.63 },
      highlight: { luma: 0, r: 0.0035, g: 0, b: 0 },
    },
  };

  it('marks only the channels above the indicator threshold', () => {
    mockApi.get.mockReturnValue(of(CLIPPED));

    render({ path: '/a.jpg', indicatorPercent: 2 });

    // Shadows: R 9.58% and G 2.94% clear 2%, B 1.63% does not.
    expect(markers('left')).toHaveLength(2);
    // Highlights: R is 0.0035%, far below the threshold.
    expect(markers('right')).toHaveLength(0);
  });

  it('a lower threshold catches the single-channel clip luminance cannot see', () => {
    mockApi.get.mockReturnValue(of(CLIPPED));

    render({ path: '/a.jpg', indicatorPercent: 0.001 });

    const right = markers('right');
    expect(right).toHaveLength(1);
    expect(right[0].className).toContain('bg-red-500');
  });

  it('names the offending channels and their percentages in the tooltip', () => {
    mockApi.get.mockReturnValue(of(CLIPPED));

    render({ path: '/a.jpg', indicatorPercent: 2 });

    const label = fixture.nativeElement
      .querySelector('div.absolute.left-0')!.getAttribute('aria-label');
    expect(label).toBe('histogram.clipping.shadow');
    expect(mockI18n.t).toHaveBeenCalledWith(
      'histogram.clipping.shadow', { channels: 'R 9.6% · G 2.9%' });
  });

  it('shows no markers at all for a photo that was never measured', () => {
    // A legacy row answers with clipped: null. Unknown is NOT clean, so the
    // widget must stay silent rather than draw an all-clear.
    mockApi.get.mockReturnValue(of({ ...CLIPPED, clipped: null }));

    render({ path: '/a.jpg', indicatorPercent: 0 });

    expect(markers('left')).toHaveLength(0);
    expect(markers('right')).toHaveLength(0);
  });

  it('shows one neutral marker for a monochrome photo, not three colour ones', () => {
    mockApi.get.mockReturnValue(of({
      ...CLIPPED,
      clipped: {
        shadow: { luma: 8, r: 8, g: 8, b: 8 },
        highlight: { luma: 0, r: 0, g: 0, b: 0 },
      },
    }));

    render({ path: '/a.jpg', monochrome: true, indicatorPercent: 1 });

    const left = markers('left');
    expect(left).toHaveLength(1);
    expect(left[0].className).toContain('bg-neutral-300');
  });

  it('keeps the markers in luminance mode', () => {
    mockApi.get.mockReturnValue(of(CLIPPED));

    render({ path: '/a.jpg', defaultMode: 'luma', indicatorPercent: 2 });

    expect(fixture.nativeElement.querySelector('polygon')).not.toBeNull();
    expect(markers('left')).toHaveLength(2);
  });

  // --- height + mode toggle ------------------------------------------------

  it('draws at the requested height, in both the box and the geometry', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: null, g: null, b: null,
    }));

    render({ path: '/a.jpg', height: 112 });

    expect(svg()!.getAttribute('viewBox')).toBe('0 0 128 112');
    expect((svg() as SVGElement & { style: CSSStyleDeclaration }).style.height).toBe('112px');
    // The curve is re-laid-out for the taller box, not stretched from a 40px one.
    expect(fixture.nativeElement.querySelector('polygon').getAttribute('points'))
      .toContain('112');
  });

  it('hides the mode toggle unless it is asked for', () => {
    render({ path: '/a.jpg' });
    expect(modeButtons()).toHaveLength(0);
  });

  it('hides the mode toggle for a monochrome photo', () => {
    render({ path: '/a.jpg', showModeToggle: true, monochrome: true });
    expect(modeButtons()).toHaveLength(0);
  });

  it('switches to luminance and remembers the choice', () => {
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: [0.25, 0, 0, 0], g: [0, 1, 0, 0], b: [0, 0, 0.5, 0],
    }));

    render({ path: '/a.jpg', showModeToggle: true });
    expect(polylines()).toHaveLength(3);

    modeButtons()[0].click();
    fixture.detectChanges();

    expect(polylines()).toHaveLength(0);
    expect(fixture.nativeElement.querySelector('polygon')).not.toBeNull();
    expect(localStorage.getItem(HISTOGRAM_MODE_KEYS.detail)).toBe('luma');
  });

  // --- single-channel modes -------------------------------------------------

  const RGB_BINS = {
    bins: 4, luma: [1, 0.5, 0, 0], r: [0.25, 0, 0, 0], g: [0, 1, 0, 0], b: [0, 0, 0.5, 0],
  };

  it.each([
    ['r', 'fill-red-500'],
    ['g', 'fill-green-500'],
    ['b', 'fill-blue-500'],
  ] as const)('fills a %s-only polygon coloured %s, not a bare stroke', (mode, fillClass) => {
    mockApi.get.mockReturnValue(of(RGB_BINS));

    render({ path: '/a.jpg', defaultMode: mode });

    expect(polylines()).toHaveLength(0);
    const polygon = fixture.nativeElement.querySelector('polygon');
    expect(polygon).not.toBeNull();
    expect(polygon.getAttribute('points')).not.toBe('');
    expect(polygon.getAttribute('class')).toContain(fillClass);
  });

  it('keeps markers for every channel in a single-channel mode, not just the active one', () => {
    mockApi.get.mockReturnValue(of(CLIPPED));

    render({ path: '/a.jpg', defaultMode: 'g', indicatorPercent: 2 });

    // Same R 9.58% / G 2.94% clear-2% shadow markers as RGB/luma mode -- a
    // blown channel is lost data whichever curve happens to be on screen.
    expect(markers('left')).toHaveLength(2);
  });

  it('offers all five channel-mode buttons when the toggle is shown', () => {
    render({ path: '/a.jpg', showModeToggle: true });
    expect(modeButtons()).toHaveLength(5);
    expect(modeButtons().map(b => b.textContent?.trim()))
      .toEqual(['histogram.mode.luminance', 'histogram.mode.rgb',
        'histogram.mode.red', 'histogram.mode.green', 'histogram.mode.blue']);
  });

  it('detail and tooltip surfaces persist their channel mode independently', () => {
    mockApi.get.mockReturnValue(of(RGB_BINS));
    render({ path: '/a.jpg', showModeToggle: true, surface: 'detail' });
    modeButtons()[2].click(); // 'r' on the detail surface
    fixture.detectChanges();
    expect(localStorage.getItem(HISTOGRAM_MODE_KEYS.detail)).toBe('r');
    expect(localStorage.getItem(HISTOGRAM_MODE_KEYS.tooltip)).toBeNull();

    // A second instance on the tooltip surface, sharing the same injector
    // (and therefore the same HistogramPreferencesService singleton), must
    // resolve its OWN default rather than the detail surface's stored 'r'.
    const tooltipFixture = TestBed.createComponent(HistogramComponent);
    mockApi.get.mockReturnValue(of(RGB_BINS));
    for (const [key, value] of Object.entries(
      { path: '/a.jpg', showModeToggle: true, surface: 'tooltip', defaultMode: 'rgb' })) {
      tooltipFixture.componentRef.setInput(key, value);
    }
    tooltipFixture.detectChanges();

    expect(Array.from(tooltipFixture.nativeElement.querySelectorAll('polyline'))).toHaveLength(3);
  });

  it('prefers a stored choice over the configured default', () => {
    localStorage.setItem(HISTOGRAM_MODE_KEYS.detail, 'luma');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: mockApi }] });
    fixture = TestBed.createComponent(HistogramComponent);
    mockApi.get.mockReturnValue(of({
      bins: 4, luma: [1, 0.5, 0, 0], r: [0.25, 0, 0, 0], g: [0, 1, 0, 0], b: [0, 0, 0.5, 0],
    }));

    render({ path: '/a.jpg', defaultMode: 'rgb' });

    expect(polylines()).toHaveLength(0);
  });
});
