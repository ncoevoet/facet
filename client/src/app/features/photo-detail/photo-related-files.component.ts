import { LogicalAssetApplied } from '../../shared/models/logical-asset-change';
import { PhotoLogicalAssetComponent } from './photo-logical-asset.component';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal } from '@angular/core';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationStart, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { MatIconModule } from '@angular/material/icon';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
import type { RelatedFilesResponse } from '../../core/api/types';
import type { Photo } from '../../shared/models/photo.model';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';

@Component({
  selector: 'app-photo-related-files',
  imports: [MatIconModule, TranslatePipe, ContextHelpComponent, PhotoLogicalAssetComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <details [open]="expanded()" data-related-files tabindex="-1" (keydown.escape)="expanded() && close($event, trigger)">
      <summary #trigger (click)="toggle($event)" class="flex min-h-11 cursor-pointer items-center gap-2 text-xs font-medium focus-visible:outline-2">
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">file_copy</mat-icon>{{ I18N.related_files.title | translate }}
      </summary>
      @if (expanded()) {
        <div class="space-y-2 pb-2 text-xs">
          @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
          @else if (failed()) {
            <p role="alert">{{ I18N.related_files.failed | translate }}</p>
            <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
          } @else if (data(); as result) {
            <ul class="m-0 list-none space-y-2 p-0" [attr.aria-label]="I18N.related_files.title | translate">
              @for (file of rows(); track file.name) {
                <li class="flex min-w-0 items-start gap-2">
                  <mat-icon aria-hidden="true" class="!h-4 !w-4 shrink-0 !text-base">{{ file.icon }}</mat-icon>
                  <div class="min-w-0 flex-1">
                    <bdi class="block break-words font-medium">{{ file.name }}</bdi>
                    <span class="text-[var(--mat-sys-on-surface-variant)]">{{ file.kindLabel | translate }} · {{ file.stateLabel | translate }}</span>
                    @if (file.indexed && file.kind !== 'photo') { <span class="ml-1">· {{ I18N.related_files.indexed | translate }}</span> }
                    @if (file.raw_download) { <span class="block">{{ I18N.related_files.raw_download | translate }}</span> }
                  </div>
                </li>
              }
            </ul>
            @if (result.inventory_state === 'unavailable') {
              <p class="m-0">{{ I18N.related_files.unchecked | translate }}</p>
              <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
            }
            @if (result.multiple_raw_candidates) { <p class="m-0">{{ I18N.related_files.multiple_raw | translate }}</p> }
            @if (result.basename_sidecar_unverified) { <p class="m-0">{{ I18N.related_files.basename_unverified | translate }}</p> }
            <app-photo-logical-asset [photo]="photo()" (applied)="logicalApplied.emit($event)" />
            <app-context-help [label]="I18N.related_files.help_title" [keys]="helpKeys()" />
          }
        </div>
      }
    </details>
  `,
})
export class PhotoRelatedFilesComponent {
  readonly photo = input.required<Photo>();
  readonly logicalApplied = output<LogicalAssetApplied>();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly I18N = I18N;
  protected readonly expanded = signal(false);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly data = signal<RelatedFilesResponse | null>(null);
  protected readonly helpKeys = computed(() => this.data()?.indexed_images_only
    ? [I18N.related_files.help, I18N.related_files.multi_user_scope] : [I18N.related_files.help]);
  private request?: Subscription;
  private revision = 0;
  private navigating = false;
  protected readonly rows = computed(() => (this.data()?.files ?? []).map(file => ({
    ...file,
    icon: file.kind.startsWith('xmp') ? 'description' : file.kind === 'raw' ? 'raw_on' : 'image',
    kindLabel: ({ photo: I18N.related_files.photo, raw: I18N.related_files.raw, jpeg: I18N.related_files.jpeg,
      xmp_full: I18N.related_files.xmp_full, xmp_basename: I18N.related_files.xmp_basename,
      xmp_fallback: I18N.related_files.xmp_fallback })[file.kind],
    stateLabel: ({ available: I18N.related_files.available, missing: I18N.related_files.missing,
      unavailable: I18N.related_files.unavailable, link: I18N.related_files.link })[file.state],
  })));

  constructor() {
    effect(() => { this.photo(); this.auth.status(); this.reset(); });
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(event => {
      if (event instanceof NavigationStart) { this.navigating = true; this.reset(); }
      if (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) this.navigating = false;
    });
    this.destroyRef.onDestroy(() => this.reset());
  }

  protected toggle(event: Event): void {
    event.preventDefault();
    if (this.expanded()) this.reset();
    else if (!this.navigating && this.auth.status()) { this.expanded.set(true); this.load(); }
  }

  protected close(event: Event, trigger: HTMLElement): void {
    event.preventDefault(); event.stopPropagation(); this.reset(); trigger.focus();
  }

  protected load(): void {
    if (!this.expanded() || this.navigating || !this.auth.status()) return;
    this.request?.unsubscribe();
    const revision = ++this.revision;
    const photo = this.photo();
    const owner = this.auth.status();
    const token = this.auth.token;
    const current = () => !this.destroyRef.destroyed && revision === this.revision && this.expanded()
      && !this.navigating && this.photo() === photo && this.auth.status() === owner && this.auth.token === token;
    this.data.set(null); this.failed.set(false); this.loading.set(true);
    this.request = this.api.get<RelatedFilesResponse>('/photo/related_files', { path: photo.path }).subscribe({
      next: data => {
        if (current()) { this.data.set(data); this.loading.set(false); }
        else if (revision === this.revision) this.reset();
      },
      error: () => {
        if (current()) { this.failed.set(true); this.loading.set(false); }
        else if (revision === this.revision) this.reset();
      },
    });
  }

  private reset(): void {
    this.revision++; this.request?.unsubscribe(); this.request = undefined;
    this.expanded.set(false); this.loading.set(false); this.failed.set(false); this.data.set(null);
  }
}
