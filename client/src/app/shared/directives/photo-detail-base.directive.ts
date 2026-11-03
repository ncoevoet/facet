import { randomUuid } from '../utils/random-uuid';
import { Directive, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Photo, hasExifFields } from '../models/photo.model';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { thumbnailUrl } from '../pipes/thumbnail-url.pipe';
import { SharedAlbumMediaScope, sharedAlbumMediaUrl } from '../utils/shared-album-media';
import type { DisplayedRendition } from '../../features/gallery/synced-zoom.component';

/**
 * Abstract base for photo detail components.
 * Holds shared signals, computed properties, and effects
 * used by both the full PhotoDetailComponent and SharedPhotoDetailComponent.
 */
@Directive()
export abstract class PhotoDetailBase {
  protected readonly api = inject(ApiService);
  protected readonly i18n = inject(I18nService);
  private readonly editionAuth = inject(AuthService);
  private readonly imageOwner = this.editionAuth.identity();

  /** Each subclass defines how the photo is loaded and stored. */
  abstract readonly photo: ReturnType<typeof signal<Photo | null>>;
  protected readonly sharedAlbumMedia = signal<SharedAlbumMediaScope | null>(null);

  private readonly loadedImageUrl = signal<string | null>(null);
  protected readonly fullImageLoaded = computed(() => !!this.fullImageUrl() && this.loadedImageUrl() === this.fullImageUrl());
  protected readonly sourceRendition = signal<DisplayedRendition>({ kind: 'source', phase: 'loading' });
  protected readonly thumbnailRendition = signal<DisplayedRendition>({ kind: 'thumbnail', phase: 'loading' });
  protected readonly displayedRendition = computed(() => this.fullImageLoaded() ? this.sourceRendition() : this.thumbnailRendition());
  private readonly imageAttempt = signal(0);
  private readonly imageSession = randomUuid();
  protected readonly translatingCaption = signal(false);
  protected readonly translatedCaption = signal<string | null>(null);

  protected readonly displayCaption = computed(() =>
    this.translatedCaption() ?? this.photo()?.caption ?? null,
  );

  protected readonly fullImageUrl = computed(() => {
    const p = this.photo();
    if (!p) return '';
    const scope = this.sharedAlbumMedia();
    const src = scope ? sharedAlbumMediaUrl(scope, 'image', p.path, undefined, p.preview_revision)
      : this.api.imageUrl(p.path, p.preview_revision);
    if (!this.imageAttempt()) return src;
    const url = new URL(src, document.baseURI);
    url.searchParams.set('facet_retry', `${this.imageSession}-${this.imageAttempt()}`);
    url.searchParams.set('ngsw-bypass', '1');
    return url.href;
  });

  private readonly imageResetEffect = effect(() => {
    this.fullImageUrl();
    this.loadedImageUrl.set(null);
    this.sourceRendition.set({ kind: 'source', phase: 'loading' });
  });
  protected readonly thumbnailImageUrl = computed(() => {
    const p = this.photo();
    return p ? thumbnailUrl(p.path, 640, p.preview_revision, this.sharedAlbumMedia()) : '';
  });
  private readonly thumbnailResetEffect = effect(() => {
    this.thumbnailImageUrl();
    this.thumbnailRendition.set({ kind: 'thumbnail', phase: 'loading' });
  });

  protected readonly hasExif = computed(() => {
    const p = this.photo();
    if (!p) return false;
    return hasExifFields(p);
  });

  protected readonly captionTranslationEffect = effect(() => {
    const p = this.photo();
    const locale = this.i18n.locale();
    if (!p?.caption || locale === 'en') {
      this.translatedCaption.set(null);
      return;
    }
    if (p.caption_translated) {
      this.translatedCaption.set(p.caption_translated);
      return;
    }
    if (this.sharedAlbumMedia()) {
      this.translatedCaption.set(null);
      this.translatingCaption.set(false);
      return;
    }
    this.translatingCaption.set(true);
    const requestPath = p.path;
    const isStale = () => this.photo()?.path !== requestPath || this.i18n.locale() !== locale;
    // GET only reads a stored translation; producing one runs a model, so an edition user POSTs for it.
    firstValueFrom(this.api.get<{ caption: string; lang?: string }>('/caption', { path: p.path, lang: locale }))
      .then(res => res.lang || !this.editionAuth.isEdition()
        ? res
        : firstValueFrom(this.api.post<{ caption: string; lang?: string }>('/caption', { path: requestPath, lang: locale })))
      .then(res => {
        if (isStale()) return;
        if (res.lang) {
          this.translatedCaption.set(res.caption);
        } else {
          this.translatedCaption.set(null);
        }
      })
      .catch(() => {
        if (!isStale()) this.translatedCaption.set(null);
      })
      .finally(() => {
        if (!isStale()) this.translatingCaption.set(false);
      });
  });

  protected onFullImageLoad(event: Event): void {
    const img = this.currentImage(event, this.fullImageUrl());
    if (!img || !img.complete || !img.naturalWidth || !img.naturalHeight) return;
    this.sourceRendition.set({ kind: 'source', phase: 'ready', width: img.naturalWidth, height: img.naturalHeight });
    this.loadedImageUrl.set(this.fullImageUrl());
  }

  protected onFullImageError(event: Event): void {
    if (!this.currentImage(event, this.fullImageUrl())) return;
    this.loadedImageUrl.set(null);
    this.sourceRendition.set({ kind: 'source', phase: 'failed' });
  }

  protected onThumbnailState(event: Event, failed = false): void {
    const p = this.photo();
    if (!p) return;
    const img = this.currentImage(event, this.thumbnailImageUrl());
    if (!img || !failed && (!img.complete || !img.naturalWidth || !img.naturalHeight)) return;
    this.thumbnailRendition.set(failed ? { kind: 'thumbnail', phase: 'failed' } : { kind: 'thumbnail', phase: 'ready', width: img.naturalWidth, height: img.naturalHeight });
  }

  private currentImage(event: Event, expected: string): HTMLImageElement | null {
    const img = event.target;
    return this.imageOwner === this.editionAuth.identity() && expected && img instanceof HTMLImageElement && (img.currentSrc || img.src) === new URL(expected, document.baseURI).href ? img : null;
  }

  protected retryFullImage(): void {
    if (this.imageOwner === this.editionAuth.identity()) this.imageAttempt.update(value => value + 1);
  }
}
