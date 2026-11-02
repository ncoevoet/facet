import { ChangeDetectionStrategy, Component, ElementRef, Injector, afterNextRender, computed, inject, input, linkedSignal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { i18nKeys } from '../../core/i18n/keys';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

/** Files shown per page of the preview grid. */
const PAGE_SIZE = 24;

/** Read-only view of the server's resolved file list, including unindexed companions. */
@Component({
  selector: 'app-cull-file-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, MatIconModule, FilenamePipe, ThumbnailUrlPipe, TranslatePipe],
  template: `
    <section class="mt-4" [attr.aria-label]="I18N.cull.file_preview.title | translate">
      <h3 class="text-sm font-medium mb-2">{{ I18N.cull.file_preview.title | translate }}</h3>
      <p class="text-xs opacity-70 mb-3">{{ I18N.cull.file_preview.help | translate }}</p>
      @if (selected(); as file) {
        <button #previewBack mat-button type="button" (click)="closePreview()">
          <mat-icon aria-hidden="true">arrow_back</mat-icon>
          {{ I18N.cull.file_preview.back | translate }}
        </button>
        <figure class="mt-2">
          @if (largeFailed()) {
            <p class="p-6 text-center text-sm" role="status">{{ I18N.cull.file_preview.unavailable | translate }}</p>
          } @else {
            <img [src]="file.thumbnailPath | thumbnailUrl:1920" [alt]="file.path | filename"
                 class="w-full max-h-[45vh] object-contain" (error)="largeFailed.set(true)" />
          }
          <figcaption class="mt-2 text-xs break-all">{{ file.path }}</figcaption>
        </figure>
      }
        <ul class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          @for (file of pageFiles(); track file.path) {
            <li class="min-w-0">
              <button type="button" class="w-full rounded border border-[var(--mat-sys-outline-variant)] overflow-hidden text-left enabled:cursor-zoom-in enabled:hover:border-[var(--mat-sys-primary)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
                      [disabled]="file.sidecar || failed().has(file.path)"
                      [attr.aria-label]="I18N.cull.file_preview.enlarge | translate:{ name: (file.path | filename) }"
                      [attr.aria-pressed]="selected()?.path === file.path"
                      (click)="showPreview(file, $event)">
                @if (file.sidecar || failed().has(file.path)) {
                  <span class="aspect-[4/3] flex flex-col items-center justify-center gap-1 p-2 bg-[var(--mat-sys-surface-container)]">
                    <mat-icon aria-hidden="true">{{ file.sidecar ? 'description' : 'broken_image' }}</mat-icon>
                    <span class="text-xs text-center">{{ (file.sidecar ? I18N.cull.file_preview.sidecar : I18N.cull.file_preview.unavailable) | translate }}</span>
                  </span>
                } @else {
                  <img [src]="file.thumbnailPath | thumbnailUrl:320" [alt]="file.path | filename"
                       class="w-full aspect-[4/3] object-contain bg-[var(--mat-sys-surface-container)]"
                       loading="lazy" (error)="markFailed(file.path)" />
                }
                <span class="block text-xs p-2 break-all">{{ file.path | filename }}</span>
              </button>
              <p class="text-[10px] opacity-60 mt-1 truncate" [title]="file.path">{{ file.path }}</p>
            </li>
          }
        </ul>
      <nav class="flex items-center justify-between gap-2 mt-3" [attr.aria-label]="I18N.cull.file_preview.pages | translate">
        <button mat-button type="button" [disabled]="page() === 0" (click)="changePage(-1)">{{ I18N.cull.file_preview.previous | translate }}</button>
        <span class="text-xs text-center" aria-live="polite">{{ I18N.cull.file_preview.range | translate:{ start: start() + 1, end: end(), total: paths().length } }}</span>
        <button mat-button type="button" [disabled]="end() >= paths().length" (click)="changePage(1)">{{ I18N.cull.file_preview.next | translate }}</button>
      </nav>
    </section>
  `,
})
export class CullFilePreviewComponent {
  readonly paths = input.required<string[]>();
  readonly thumbnailPaths = input<Record<string, string>>({});
  protected readonly I18N = i18nKeys();
  private trigger: HTMLElement | null = null;
  private readonly injector = inject(Injector);
  private readonly previewBack = viewChild('previewBack', { read: ElementRef<HTMLButtonElement> });
  // A new file list (a new preview) resets the page, the enlarged file and the failed images.
  private readonly files = computed(() => [this.paths(), this.thumbnailPaths()] as const);
  protected readonly page = linkedSignal({ source: this.files, computation: () => 0 });
  protected readonly selected = linkedSignal<unknown, { path: string; thumbnailPath: string } | null>({
    source: this.files, computation: () => null });
  protected readonly failed = linkedSignal({ source: this.files, computation: () => new Set<string>() });
  protected readonly largeFailed = linkedSignal({ source: this.files, computation: () => false });
  protected readonly start = computed(() => this.page() * PAGE_SIZE);
  protected readonly end = computed(() => Math.min(this.start() + PAGE_SIZE, this.paths().length));
  protected readonly pageFiles = computed(() => this.paths().slice(this.start(), this.end())
    .map(path => ({ path, sidecar: path.toLowerCase().endsWith('.xmp'),
      thumbnailPath: Object.hasOwn(this.thumbnailPaths(), path) ? this.thumbnailPaths()[path] : path })));

  protected showPreview(file: { path: string; thumbnailPath: string }, event: Event): void {
    this.trigger = event.currentTarget as HTMLElement;
    this.largeFailed.set(false);
    this.selected.set(file);
    afterNextRender(() => {
      if (this.selected() === file) this.previewBack()?.nativeElement.focus();
    }, { injector: this.injector });
  }

  protected closePreview(): void {
    this.selected.set(null);
    this.trigger?.focus();
  }

  protected markFailed(path: string): void {
    this.failed.update(paths => new Set([...paths, path]));
  }

  protected changePage(delta: number): void {
    this.page.update(page => Math.max(0, Math.min(Math.ceil(this.paths().length / PAGE_SIZE) - 1, page + delta)));
    this.selected.set(null);
  }
}
