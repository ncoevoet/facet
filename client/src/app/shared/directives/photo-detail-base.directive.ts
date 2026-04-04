import { Directive, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../models/photo.model';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';

/**
 * Abstract base for photo detail components.
 * Holds shared signals, computed properties, and effects
 * used by both the full PhotoDetailComponent and SharedPhotoDetailComponent.
 */
@Directive()
export abstract class PhotoDetailBase {
  protected readonly api = inject(ApiService);
  protected readonly i18n = inject(I18nService);

  /** Each subclass defines how the photo is loaded and stored. */
  abstract readonly photo: ReturnType<typeof signal<Photo | null>>;

  protected readonly fullImageLoaded = signal(false);
  protected readonly translatingCaption = signal(false);
  protected readonly translatedCaption = signal<string | null>(null);

  protected readonly displayCaption = computed(() =>
    this.translatedCaption() ?? this.photo()?.caption ?? null,
  );

  protected readonly fullImageUrl = computed(() => {
    const p = this.photo();
    return p ? this.api.imageUrl(p.path) : '';
  });

  protected readonly hasExif = computed(() => {
    const p = this.photo();
    if (!p) return false;
    return !!(p.camera_model || p.lens_model || p.focal_length || p.f_stop || p.shutter_speed || p.iso);
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
    this.translatingCaption.set(true);
    firstValueFrom(this.api.get<{ caption: string; lang?: string }>('/caption', { path: p.path, lang: locale }))
      .then(res => {
        if (res.lang) {
          this.translatedCaption.set(res.caption);
        } else {
          this.translatedCaption.set(null);
        }
      })
      .catch(() => this.translatedCaption.set(null))
      .finally(() => this.translatingCaption.set(false));
  });

  protected onFullImageLoad(): void {
    this.fullImageLoaded.set(true);
  }
}
