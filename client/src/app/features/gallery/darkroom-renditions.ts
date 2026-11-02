import { DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { ThumbnailUrlPipe, ImageUrlPipe, STORED_THUMBNAIL_EDGE, RENDERED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { SyncedZoomComponent, LoadedSources, SHARP_PRELOAD_DEBOUNCE_MS, DisplayedRendition } from './synced-zoom.component';
import { RunGeneration, updateMapSignal } from './culling.store';
import { CullingGroup, FrameSize, cullPreviewUrl, computePeakingOverlay, computePooledPeakingOverlays, loadFrameImage, PEAKING_FIT_EDGE } from './burst-culling.pipes';

const DARKROOM_THUMB_SIZE = RENDERED_THUMBNAIL_EDGE;
const STORED_EDGE = STORED_THUMBNAIL_EDGE;
/** Reuse the empty map so clearing an empty overlay does not notify consumers. */
const NO_PEAKING_OVERLAYS = new Map<string, string>();
/** Keep recently viewed overlays bounded during long culling sessions. */
const PEAKING_CACHE_MAX = 8;

/** Frame membership and view lifetime remain owned by the culling workspace. */
export interface DarkroomRenditionContext {
  group(): CullingGroup | null;
  focusedIndex(): number;
  compareMode(): 'single' | '2up' | '4up';
  visiblePaths(): string[];
  highResolution(): boolean;
  peakingActive(): boolean;
  gridActive(): boolean;
  current(): boolean;
  epoch(): number;
  captureSession(): () => boolean;
}

/**
 * Per-workspace image attempts, prefetchers and derived image resources.
 * Construct in the workspace injection context, then connect after its fields
 * initialize. No effect or eager context read runs during construction.
 */
export class DarkroomRenditions {
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly currentPath = computed(() => this.context.group()?.photos[this.context.focusedIndex()]?.path);

  constructor(private readonly context: DarkroomRenditionContext) {}

  /** Selected style for this darkroom session ('' = flat Original). Not persisted. */
  readonly activeStyle = signal('');
  /** True while a developed preview renders (spinner overlay over the flat frame). */
  readonly previewLoading = signal(false);
  readonly developedFailure = signal<{ path: string; style: string } | null>(null);
  private readonly developedAttempt = signal<{ path: string; style: string; attempt: number } | null>(null);
  private readonly developedSession = crypto.randomUUID();
  readonly developedPreviewUrl = computed(() => {
    const path = this.currentPath(), style = this.activeStyle();
    if (!path || !style) return '';
    const src = cullPreviewUrl(path, style);
    const retry = this.developedAttempt();
    if (retry?.path !== path || retry.style !== style) return src;
    const url = new URL(src, document.baseURI);
    url.searchParams.set('facet_retry', `${this.developedSession}-${retry.attempt}`);
    url.searchParams.set('ngsw-bypass', '1');
    return url.href;
  });
  /** In-flight developed-preview image, so its handlers can be detached when a newer frame supersedes it. */
  private previewImg: HTMLImageElement | null = null;

  /** Frame path → generated edge-map PNG, for the frames currently on screen. */
  readonly peakingOverlays = signal<Map<string, string>>(NO_PEAKING_OVERLAYS);
  /** Frame path → natural pixel size, so the grid lands on the letterboxed
   *  image box rather than on the pane's own (usually wider) rectangle. */
  readonly frameSizes = signal<Map<string, FrameSize>>(new Map());
  /** Guards against a superseded pass publishing over a newer one. */
  private readonly peakingRun = new RunGeneration();

  /** Renders already fetched into the browser cache (the panes' own preloaders
   *  and the neighbour prefetch fill it), so a revisited frame skips the
   *  panes' debounce. */
  readonly loadedRenders = new LoadedSources();
  /** The path whose render the single pane has finished loading. Peaking and
   *  the neighbour prefetch wait for it, so the current frame is first in the
   *  server's render queue. */
  private readonly sharpPath = signal<string | null>(null);
  /** Failed attempts belong to individual visible panes; a new attempt clears its fallback. */
  readonly failedRenderPaths = signal<ReadonlySet<string>>(new Set());
  readonly pendingRenderPaths = signal<ReadonlySet<string>>(new Set());
  readonly RENDITION_PENDING: DisplayedRendition = { kind: 'thumbnail', phase: 'loading' };
  readonly displayedRenditions = signal<ReadonlyMap<string, DisplayedRendition>>(new Map());

  onDisplayedRendition(state: DisplayedRendition, path: string, style: string): void {
    if (this.destroyRef.destroyed || !this.context.current()
      || !this.context.visiblePaths().includes(path) || style !== (this.context.compareMode() === 'single' ? this.activeStyle() : '')) return;
    this.displayedRenditions.update(current => new Map([...current].filter(([key]) => this.context.visiblePaths().includes(key))).set(path, state));
  }

  retryDarkroomPane(pane: SyncedZoomComponent): void {
    const path = this.currentPath();
    if (!path || !this.context.visiblePaths().includes(pane.frameKey() ?? '') || !this.context.current()) return;
    const failed = this.developedFailure();
    if (this.context.compareMode() === 'single' && (failed?.path === path || this.activeStyle())) {
      const style = failed?.path === path ? failed.style : this.activeStyle();
      this.developedFailure.set(null);
      this.developedAttempt.update(previous => ({ path, style, attempt: (previous?.attempt ?? 0) + 1 }));
      this.activeStyle.set(style);
    } else pane.retry();
  }

  /** Neighbour preloaders in flight, kept so they are not collected mid-fetch
   *  and can be aborted when the frame changes. */
  private neighbourThumbs = new Map<string, HTMLImageElement>();
  private neighbourRenders = new Map<string, HTMLImageElement>();

  onSharpLoaded(src: string, path = this.currentPath()): void {
    this.onSharpState(src, path, 'loaded');
  }

  onSharpPending(src: string, path = this.currentPath()): void {
    this.onSharpState(src, path, 'pending');
  }

  onSharpFailed(src: string, path = this.currentPath()): void {
    this.onSharpState(src, path, 'failed');
  }

  /** Ignore obsolete panes and style previews; only the focused single pane
   *  controls neighbour prefetch, while every pane owns its fallback source. */
  private onSharpState(src: string, path: string | undefined, state: 'loaded' | 'pending' | 'failed'): void {
    if (!path || !this.context.visiblePaths().includes(path)) return;
    const actual = new URL(src, document.baseURI);
    const expected = new URL(this.frameThumbUrl(path, DARKROOM_THUMB_SIZE), document.baseURI);
    // Retry URLs carry a pane-owned nonce; all frame/revision/render parameters
    // still have to match before the old sharp/peaking pipeline can settle.
    for (const url of [actual, expected]) { url.searchParams.delete('facet_retry'); url.searchParams.delete('ngsw-bypass'); }
    if (actual.href !== expected.href) return;
    const visible = this.context.visiblePaths();
    this.pendingRenderPaths.update(paths => {
      const next = new Set([...paths].filter(path => visible.includes(path)));
      if (state === 'pending') next.add(path); else next.delete(path);
      return next;
    });
    this.failedRenderPaths.update(paths => {
      const next = new Set([...paths].filter(path => visible.includes(path)));
      if (state === 'failed') next.add(path);
      else next.delete(path);
      return next.size === paths.size && [...next].every(path => paths.has(path)) ? paths : next;
    });
    if (this.context.compareMode() === 'single') this.sharpPath.set(state === 'loaded' ? path : null);
  }

  /** Paths of the previous and next frame in single view; none in compare mode,
   *  with a darktable style active (that pane waits for its own render), or on a
   *  metered connection. */
  private readonly neighbourPaths = computed<string[]>(() => {
    const group = this.context.group();
    if (!group || this.context.compareMode() !== 'single' || this.activeStyle()) return [];
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (connection?.saveData) return [];
    const idx = this.context.focusedIndex();
    return [group.photos[idx - 1]?.path, group.photos[idx + 1]?.path].filter((p): p is string => !!p);
  }, { equal: (a, b) => a.length === b.length && a.every((p, i) => p === b[i]) });

  /** Each frame's preview revision, so the URLs built here match the ones the template binds. */
  private readonly frameRevisions = computed(() =>
    new Map((this.context.group()?.photos ?? []).map(photo => [photo.path, photo.preview_revision] as const)));

  private frameThumbUrl(path: string, size: number): string {
    return this.thumbnailUrl.transform(path, size, this.frameRevisions().get(path));
  }

  /** Fetch `urls` into the browser cache, diffing the previous batch in `sink`
   *  by URL: a fetch still wanted, or listed in `keep` (the frame being stepped
   *  onto, whose own pane is about to ask for the same URL), carries on
   *  untouched, so the browser never cancels and restarts it. The rest is
   *  aborted (handlers cleared before `src`, so a late load is inert). */
  private prefetch(
    urls: string[],
    sink: Map<string, HTMLImageElement>,
    onLoaded?: (url: string) => void,
    keep: readonly string[] = [],
  ): Map<string, HTMLImageElement> {
    const retained = new Set<string>([...urls, ...keep]);
    const next = new Map<string, HTMLImageElement>();
    for (const [url, img] of sink) {
      if (retained.has(url)) next.set(url, img);
      else this.abortImage(img);
    }
    for (const url of urls) {
      if (next.has(url)) continue;
      const img = new Image();
      img.onload = () => onLoaded?.(url);
      img.onerror = () => {};
      img.src = url;
      next.set(url, img);
    }
    return next;
  }

  private abortPrefetch(sink: Map<string, HTMLImageElement>): void {
    for (const img of sink.values()) this.abortImage(img);
    sink.clear();
  }

  private abortImage(img: HTMLImageElement): void {
    img.onload = null;
    img.onerror = null;
    img.src = '';
  }

  /** Frame path → the edge map already built for it and the source it came from. */
  private readonly peakingCache = new Map<string, { src: string; url: string }>();
  private readonly thumbnailUrl = new ThumbnailUrlPipe();
  private readonly fullResUrl = new ImageUrlPipe();

  /** The source peaking measures: the 1920 render at fit (the pane shows it once
   *  loaded) or the full-resolution image past the fit scale (SyncedZoomComponent's
   *  rule). */
  private frameSource(path: string, hiRes: boolean): string {
    return hiRes
      ? this.fullResUrl.transform(path, true, this.frameRevisions().get(path))
      : this.frameThumbUrl(path, this.failedRenderPaths().has(path) ? STORED_EDGE : DARKROOM_THUMB_SIZE);
  }

  /** Drop the overlays and everything that could still republish them: a pass
   *  awaiting its raster work would otherwise land after the toggle went off and
   *  paint the frames again. */
  private clearPeaking(): void {
    this.peakingRun.cancel();
    this.peakingCache.clear();
    if (this.peakingOverlays().size > 0) this.peakingOverlays.set(NO_PEAKING_OVERLAYS);
  }

  /**
   * Rebuild the peaking overlays for the displayed frames, publishing each as it
   * lands so a 4-up compare shows the first pane's edges without waiting on the
   * other three. A frame already convolved from the same source is reused, and a
   * newer pass invalidates this one rather than racing it.
   *
   * Panes shown together go through the pooled pass instead: side by side, the
   * question is which frame carries more red, and that only means something when
   * one threshold painted them both.
   */
  private async refreshPeaking(paths: string[], hiRes: boolean): Promise<void> {
    const run = this.peakingRun.next();
    if (paths.length > 1) return this.refreshPooledPeaking(paths, hiRes, run);
    const overlays = new Map<string, string>();
    for (const path of paths) {
      const src = this.frameSource(path, hiRes);
      const cached = this.peakingCache.get(path);
      let url = cached?.src === src ? cached.url : null;
      if (!url) {
        url = await this.renderPeaking(src, hiRes ? undefined : PEAKING_FIT_EDGE);
        if (!this.peakingRun.isCurrent(run)) return;
        if (url) {
          this.peakingCache.set(path, { src, url });
          this.trimPeakingCache();
        }
      }
      if (!url) continue;
      overlays.set(path, url);
      this.peakingOverlays.set(new Map(overlays));
    }
  }

  /**
   * One pooled pass over every visible pane, published together.
   *
   * Cached under the whole set's sources rather than each frame's own, because a
   * pooled overlay is only valid for the set it was pooled over: the same frame
   * paired with a different one is a different answer.
   */
  private async refreshPooledPeaking(paths: string[], hiRes: boolean, run: number): Promise<void> {
    const srcs = paths.map(path => this.frameSource(path, hiRes));
    const poolKey = srcs.join('|');
    const cached = paths.map(path => this.peakingCache.get(path));
    if (cached.every(entry => entry?.src === poolKey)) {
      this.peakingOverlays.set(new Map(paths.map((path, i) => [path, cached[i]!.url])));
      return;
    }
    const urls = await this.renderPooledPeaking(srcs, hiRes ? undefined : PEAKING_FIT_EDGE);
    if (!this.peakingRun.isCurrent(run)) return;
    const overlays = new Map<string, string>();
    paths.forEach((path, i) => {
      const url = urls.get(srcs[i]);
      if (!url) return;
      this.peakingCache.set(path, { src: poolKey, url });
      overlays.set(path, url);
    });
    this.trimPeakingCache();
    this.peakingOverlays.set(overlays);
  }

  /** Drop the oldest edge maps once the cache is over its bound (insertion
   *  order, which for a walk through a group is also least-recently-shown). */
  private trimPeakingCache(): void {
    while (this.peakingCache.size > PEAKING_CACHE_MAX) {
      const oldest = this.peakingCache.keys().next().value;
      if (oldest === undefined) return;
      this.peakingCache.delete(oldest);
    }
  }

  /** Seam over the raster pipeline, so it can be stubbed where no canvas exists. */
  private renderPeaking(src: string, maxEdge?: number): Promise<string | null> {
    return computePeakingOverlay(src, maxEdge).catch(() => null);
  }

  /** The same seam for the pooled pass. */
  private renderPooledPeaking(srcs: string[], maxEdge?: number): Promise<Map<string, string>> {
    return computePooledPeakingOverlays(srcs, maxEdge).catch(() => new Map<string, string>());
  }

  /** Measure a frame once, for the composition grid's viewBox. */
  private async ensureFrameSize(path: string): Promise<void> {
    const current = this.context.captureSession();
    if (this.frameSizes().has(path)) return;
    const size = await this.measureFrame(this.frameSource(path, false));
    if (size && current()) updateMapSignal(this.frameSizes, path, size);
  }

  /** Seam over the image load, for the same reason as renderPeaking. */
  private measureFrame(src: string): Promise<FrameSize | null> {
    return loadFrameImage(src)
      .then(img => ({ w: img.naturalWidth || img.width, h: img.naturalHeight || img.height }))
      .catch(() => null);
  }

  /** Preload the developed JPEG for a frame; swap it in on load, revert on error. */
  private preloadDevelopedPreview(path: string, style: string): void {
    this.previewLoading.set(true);
    const url = this.developedPreviewUrl();
    const epoch = this.context.epoch();
    if (this.previewImg) {
      this.previewImg.onload = null;
      this.previewImg.onerror = null;
    }
    const img = new Image();
    this.previewImg = img;
    const isStale = () =>
      !this.context.current() || this.destroyRef.destroyed || epoch !== this.context.epoch() || this.context.compareMode() !== 'single'
      || path !== this.context.group()?.photos[this.context.focusedIndex()]?.path
      || style !== this.activeStyle() || url !== this.developedPreviewUrl();
    img.onload = () => {
      if (isStale()) return;
      this.previewLoading.set(false);
      this.developedFailure.set(null);
    };
    img.onerror = () => {
      if (isStale()) return;
      this.previewLoading.set(false);
      this.developedFailure.set({ path, style });
      this.activeStyle.set('');
      this.snackBar.open(this.i18n.t(I18N.culling.cull_style.error), '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    };
    img.src = url;
  }

  /** Pick a darktable style for the darkroom preview ('' = flat Original). */
  selectCullStyle(style: string): void {
    this.developedFailure.set(null);
    this.activeStyle.set(style);
  }

  /** Register at the workspace's original image-effect initialization point. */
  connect(): void {
    // Render the developed preview whenever the focused single-view frame or the
    // selected style changes; the spinner shows over the flat frame until it loads.
    effect(onCleanup => {
      const style = this.activeStyle();
      const group = this.context.group();
      const idx = this.context.focusedIndex();
      const single = this.context.compareMode() === 'single';
      const photo = group?.photos[idx];
      if (!style || !photo || !single) {
        this.previewLoading.set(false);
        return;
      }
      this.preloadDevelopedPreview(photo.path, style);
      onCleanup(() => {
        if (this.previewImg) {
          this.previewImg.onload = null; this.previewImg.onerror = null; this.previewImg.src = ''; this.previewImg = null;
        }
      });
    });
    // Prefetch the neighbours' stored thumbnails at once (cheap), and their
    // renders only after the current frame's own render has loaded.
    effect(() => {
      const paths = this.neighbourPaths();
      const current = this.currentPath();
      untracked(() => {
        const keep = current ? [this.frameThumbUrl(current, STORED_EDGE)] : [];
        this.neighbourThumbs = this.prefetch(paths.map(p => this.frameThumbUrl(p, STORED_EDGE)), this.neighbourThumbs, undefined, keep);
      });
    });
    effect(() => {
      const paths = this.neighbourPaths();
      const current = this.currentPath();
      const sharp = this.sharpPath() === current;
      untracked(() => {
        const urls = sharp ? paths.map(p => this.frameThumbUrl(p, DARKROOM_THUMB_SIZE)) : [];
        // Keep already-started current/neighbor renders while revalidating a
        // revisit; only a fresh success may start additional neighbor work.
        const keep = [current, ...paths].filter((path): path is string => !!path)
          .map(path => this.frameThumbUrl(path, DARKROOM_THUMB_SIZE));
        this.neighbourRenders = this.prefetch(urls, this.neighbourRenders, url => this.loadedRenders.add(url), keep);
      });
    });
    // Rebuild the peaking edge map when the toggle, the displayed frames or the
    // pane's source resolution change. Panning never lands here: the transform
    // moves the existing overlay, and the hi-res flag is a computed boolean, so
    // a pan at a fixed scale notifies nothing.
    effect(() => {
      const active = this.context.peakingActive();
      const paths = this.context.visiblePaths();
      const hiRes = this.context.highResolution();
      // In plain single view wait for the render attempt. On failure, measure
      // the stored thumbnail that the pane continues displaying. Compare mode and
      // a darktable style keep their own timing.
      // Read outside untracked so a compare pane's failure or recovery rebuilds the pool.
      const failed = this.failedRenderPaths();
      const awaitingSharp = this.context.compareMode() === 'single' && !this.activeStyle()
        && this.sharpPath() !== paths[0] && !failed.has(paths[0]);
      untracked(() => {
        if (active && paths.length > 0 && awaitingSharp) {
          // Hide, but keep the edge maps of frames already seen: stepping back to
          // one is then served from the cache instead of re-convolved.
          this.peakingRun.cancel();
          if (this.peakingOverlays().size > 0) this.peakingOverlays.set(NO_PEAKING_OVERLAYS);
          return;
        }
        if (!active || paths.length === 0) {
          this.clearPeaking();
          return;
        }
        void this.refreshPeaking(paths, hiRes);
      });
    });
    // Measure the frames the composition grid is about to cover, so its viewBox
    // letterboxes onto the image exactly like the pane's object-contain does.
    // Debounced like the panes' own render requests: measuring fetches the same
    // 1920 render, which a held arrow key must not queue per frame.
    effect(onCleanup => {
      if (!this.context.gridActive()) return;
      const paths = this.context.visiblePaths();
      const timer = setTimeout(() => {
        for (const path of paths) void this.ensureFrameSize(path);
      }, SHARP_PRELOAD_DEBOUNCE_MS);
      onCleanup(() => clearTimeout(timer));
    });
  }

  resetEvidence(): void {
    this.displayedRenditions.set(new Map());
    this.developedFailure.set(null);
  }

  resetPaneReadiness(recreated: boolean): void {
    if (recreated) this.failedRenderPaths.set(new Set());
    this.sharpPath.set(null);
  }

  resetStackView(): void {
    this.frameSizes.set(new Map());
    this.failedRenderPaths.set(new Set());
    this.sharpPath.set(null);
    this.clearPeaking();
    this.dispose();
  }

  /** The workspace invalidates its page epoch before calling this on destroy. */
  dispose(): void {
    this.abortPrefetch(this.neighbourThumbs);
    this.abortPrefetch(this.neighbourRenders);
  }
}
