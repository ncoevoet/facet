import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, input, output, signal, viewChild } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { Photo } from '../../shared/models/photo.model';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

/** Reads the originating collection; never changes its query, selection or sort. */
@Component({
  selector: 'app-photo-collection-sidebar',
  imports: [MatIconModule, ThumbnailUrlPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'relative hidden xl:flex shrink-0 min-h-0 border-r border-[var(--mat-sys-outline-variant)]', '[style.width.px]': 'collapsed() ? 40 : width()' },
  template: `
    <aside class="flex min-h-0 min-w-0 flex-1 flex-col" [attr.aria-label]="I18N.photo_detail.collection.title | translate">
      <div class="flex min-h-10 shrink-0 items-center gap-1 px-1">
        <button type="button" class="flex h-8 w-8 shrink-0 items-center justify-center rounded hover:bg-[var(--mat-sys-surface-container)]"
          [attr.aria-label]="(collapsed() ? I18N.photo_detail.collection.show : I18N.photo_detail.collection.hide) | translate"
          [attr.aria-expanded]="!collapsed()" (click)="toggle()">
          <mat-icon>{{ collapsed() ? 'chevron_right' : 'chevron_left' }}</mat-icon>
        </button>
        @if (!collapsed()) {
          <span class="min-w-0 truncate text-xs font-medium" [title]="title() || (I18N.photo_detail.collection.title | translate)">{{ title() || (I18N.photo_detail.collection.title | translate) }}</span>
        }
      </div>
      @if (!collapsed()) {
        <p class="m-0 px-2 pb-2 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.photo_detail.collection.loaded | translate:{ loaded: photos().length, total: total() } }}</p>
        <div #scroller class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2" tabindex="0" [attr.aria-label]="I18N.photo_detail.collection.title | translate">
          <div class="grid gap-2" [style.grid-template-columns]="columns()">
            @for (photo of photos(); track photo.path) {
              <button type="button" [attr.data-collection-current]="photo.path === currentPath() ? '' : null"
                [attr.aria-current]="photo.path === currentPath() ? 'true' : null" [attr.aria-label]="photo.filename"
                [title]="photo.filename" (click)="choose.emit(photo.path)"
                class="min-w-0 overflow-hidden rounded border-2 border-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--mat-sys-primary)]"
                [class.!border-[var(--mat-sys-primary)]]="photo.path === currentPath()">
                <img [src]="photo.path | thumbnailUrl:240:photo.preview_revision" alt="" loading="lazy" class="aspect-square w-full object-cover" />
                <span class="block truncate px-1 py-1 text-xs">{{ photo.filename }}</span>
              </button>
            }
          </div>
          @if (hasMore()) {
            <button type="button" class="mt-2 min-h-10 w-full rounded border border-[var(--mat-sys-outline-variant)] px-2 text-xs"
              [disabled]="loading()" (click)="more.emit()">{{ (loading() ? I18N.ui.labels.loading : I18N.photo_detail.collection.more) | translate }}</button>
          }
        </div>
        <div role="separator" tabindex="0" aria-orientation="vertical" [attr.aria-label]="I18N.photo_detail.collection.resize | translate"
          aria-valuemin="144" aria-valuemax="384" [attr.aria-valuenow]="width()"
          class="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none focus-visible:bg-[var(--mat-sys-primary)]"
          (pointerdown)="start($event)" (pointermove)="move($event)" (pointerup)="finish($event)"
          (pointercancel)="finish($event, true)" (lostpointercapture)="finish($event, true)" (keydown)="resizeKey($event)"></div>
      }
    </aside>
  `,
})
export class PhotoCollectionSidebarComponent {
  protected readonly I18N = I18N;
  readonly photos = input<readonly Photo[]>([]);
  readonly currentPath = input('');
  readonly title = input('');
  readonly total = input(0);
  readonly hasMore = input(false);
  readonly loading = input(false);
  readonly choose = output<string>();
  readonly more = output<void>();
  protected readonly width = signal(192);
  protected readonly collapsed = signal(false);
  protected readonly columns = computed(() => `repeat(${this.width() >= 280 ? 2 : 1}, minmax(0, 1fr))`);
  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private drag: { id: number; x: number; width: number; target: HTMLElement } | null = null;
  private frame: number | null = null;
  private resizeFrame: number | null = null;
  private pendingWidth: number | null = null;

  constructor() {
    // Reflow and hidden-to-visible transitions must keep the same photo in view too.
    effect(cleanup => {
      this.currentPath(); this.width();
      const viewport = this.scroller()?.nativeElement;
      this.revealCurrent();
      if (viewport && typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(() => this.revealCurrent());
        observer.observe(viewport);
        cleanup(() => observer.disconnect());
      }
    });
    inject(DestroyRef).onDestroy(() => {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      if (this.drag) this.finishPointer(true);
    });
  }

  private revealCurrent(): void {
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      const viewport = this.scroller()?.nativeElement;
      const active = viewport?.querySelector<HTMLElement>('[data-collection-current]');
      if (!viewport || !active) return;
      const area = viewport.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      if (item.top < area.top) viewport.scrollTop -= area.top - item.top;
      else if (item.bottom > area.bottom) viewport.scrollTop += item.bottom - area.bottom;
    });
  }

  protected toggle(): void { this.collapsed.update(value => !value); }
  private setWidth(width: number): void { this.width.set(Math.max(144, Math.min(384, width))); }
  protected start(event: PointerEvent): void {
    if (this.drag || event.button !== 0 || !event.isPrimary) return;
    event.preventDefault(); event.stopPropagation();
    const target = event.currentTarget as HTMLElement;
    target.focus();
    this.drag = { id: event.pointerId, x: event.clientX, width: this.width(), target };
    try { target.setPointerCapture(event.pointerId); } catch { /* Synthetic pointer. */ }
  }
  protected move(event: PointerEvent): void {
    if (this.drag?.id !== event.pointerId) return;
    event.preventDefault(); event.stopPropagation();
    this.pendingWidth = this.drag.width + event.clientX - this.drag.x;
    if (this.resizeFrame === null) this.resizeFrame = requestAnimationFrame(() => {
      this.resizeFrame = null;
      if (this.pendingWidth !== null) this.setWidth(this.pendingWidth);
      this.pendingWidth = null;
    });
  }
  protected finish(event: PointerEvent, cancel = false): void {
    if (this.drag?.id === event.pointerId) this.finishPointer(cancel);
  }
  private finishPointer(cancel: boolean): void {
    const drag = this.drag;
    this.drag = null;
    if (!drag) return;
    if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
    this.resizeFrame = null;
    if (!cancel && this.pendingWidth !== null) this.setWidth(this.pendingWidth);
    this.pendingWidth = null;
    if (cancel) this.width.set(drag.width);
    try { drag.target.releasePointerCapture(drag.id); } catch { /* Already released. */ }
  }
  protected resizeKey(event: KeyboardEvent): void {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key)) return;
    if (event.key === 'Escape' && !this.drag) return;
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Escape') { this.finishPointer(true); return; }
    this.finishPointer(true);
    this.setWidth(event.key === 'Home' ? 144 : event.key === 'End' ? 384 : this.width() + (event.key === 'ArrowRight' ? 16 : -16));
  }
}
