import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, OnInit, computed, effect, inject, signal, viewChild, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { NgTemplateOutlet } from '@angular/common';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom, Observable, Subject, takeUntil } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStack, PhotoStackService, StackMutation, StackRegroupPreview, StackRegroupMode } from '../../core/services/photo-stack.service';
import { i18nKeys } from '../../core/i18n/keys';
import { ImageUrlPipe, ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from './gallery.store';
import { StackActionsService } from './stack-actions.service';
import { BY_PATHS_MAX } from './gallery-filters.util';
import { isPageShortcutBlocked, isTypingContext } from '../../shared/utils/keyboard';
import { reconcileRegroupDraft, regroupSourceEffects } from './stack-regroup-state';
import { STACK_EDITOR_HOST } from './stack-editor-host';
import { SyncedZoomComponent, FIT_ZOOM } from './synced-zoom.component';
import { PageContextService } from '../../core/agent/page-context.service';
import { StackReviewActionsService } from './stack-review-actions.service';
import { STACK_MAX_MEMBERS, STACK_MIN_MEMBERS } from './stack-limits';

const MUTATION_FAILURE: Record<number, 'conflict' | 'unavailable'> = { 409: 'conflict', 404: 'unavailable', 403: 'unavailable' };

/** Compare stored camera walltimes without guessing a timezone. EXIF and ISO
 *  separators must not make December sort before January in the same year. */
function captureDateKey(date: string | null | undefined): string {
  return date ? date.replace(/^(\d{4}):(\d{2}):(\d{2})/, '$1-$2-$3').replace('T', ' ') : '\uffff';
}

@Component({
  selector: 'app-stack-editor',
  standalone: true,
  imports: [NgTemplateOutlet, MatDialogModule, SyncedZoomComponent, ImageUrlPipe, MatButtonModule, MatIconModule, MatTooltipModule, ThumbnailUrlPipe, FilenamePipe, PluralKeyPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col h-full min-h-0 min-w-0' },
  template: `
    @if (page) {
      <h1 class="shrink-0 text-lg font-medium px-3 py-2">{{ I18N.stacks.create | translate }}</h1>
    } @else {
      <h2 mat-dialog-title class="shrink-0">{{ (stack() ? I18N.stacks.title : I18N.stacks.create) | translate }}</h2>
    }
    <div class="flex flex-col min-h-0 flex-1 px-3 sm:px-6 overflow-x-hidden" [class.overflow-y-auto]="!page">
      <div class="shrink-0" [class.max-h-40]="page" [class.overflow-y-auto]="page">
      <p class="text-sm opacity-80 mb-3">{{ (editable() ? I18N.stacks.hint : I18N.stacks.read_only) | translate }}</p>
      @if (regrouping() && preview()?.source_stacks?.length) {
        <fieldset class="border-0 p-0 mb-3" [disabled]="saving() || saved() || !editable()">
          <legend class="text-sm font-medium mb-1">{{ I18N.stacks.regroup_policy | translate }}</legend>
          <div class="flex flex-wrap gap-2">
            <button mat-stroked-button data-stack-mode="combine" class="aria-pressed:!bg-[var(--mat-sys-secondary-container)] aria-pressed:!text-[var(--mat-sys-on-secondary-container)]" [attr.aria-pressed]="mode() === 'combine'" (click)="changeMode('combine')">
              <mat-icon aria-hidden="true" [class.invisible]="mode() !== 'combine'">check</mat-icon>{{ I18N.stacks.regroup_combine | translate }}
            </button>
            <button mat-stroked-button data-stack-mode="selected" class="aria-pressed:!bg-[var(--mat-sys-secondary-container)] aria-pressed:!text-[var(--mat-sys-on-secondary-container)]" [attr.aria-pressed]="mode() === 'selected'" (click)="changeMode('selected')">
              <mat-icon aria-hidden="true" [class.invisible]="mode() !== 'selected'">check</mat-icon>{{ I18N.stacks.regroup_selected | translate }}
            </button>
          </div>
          <p class="text-sm mt-2 opacity-80">{{ (mode() === 'combine' ? I18N.stacks.regroup_combine_hint : I18N.stacks.regroup_selected_hint) | translate }}</p>
        </fieldset>
      }
      @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error(); as failure) {
        <div role="alert" class="my-3">
          <p>{{ I18N.stacks[failure] | translate }}</p>
          <button mat-button data-stack-retry (click)="retry()" [disabled]="saving() || loading()">{{ (failure === 'error' ? I18N.stacks.regroup_retry : I18N.stacks.reload) | translate }}</button>
        </div>
      }
      </div>
      @if (ready()) {
        <div class="shrink-0" [class.max-h-24]="page" [class.overflow-y-auto]="page">
        <div class="flex flex-wrap justify-between items-center gap-2 text-sm mb-2" aria-live="polite">
          <p data-stack-member-count>{{ paths().length | pluralKey:I18N.stacks.member_count:I18N.stacks.member_count_plural | translate:{ count: paths().length } }}</p>
          @if (regrouping()) { <p>{{ I18N.stacks.regroup_counts | translate:{ selected: explicitPaths().length, effective: paths().length } }}</p> }
        </div>
        @if (rejectedCount()) { <p role="status" data-stack-excluded class="text-sm mb-1">{{ I18N.stacks.reject_count | translate:{ count: rejectedCount() } }}</p> }
        @if (extraCount()) { <p class="text-sm mb-2" role="status">{{ extraCount() | pluralKey:I18N.stacks.regroup_extra:I18N.stacks.regroup_extra_plural | translate:{ count: extraCount() } }}</p> }
        @if (sourceEffects().length) {
          <section class="rounded-lg border border-current/20 p-3 text-sm mb-3 shrink-0" [attr.aria-label]="I18N.stacks.regroup_sources | translate">
            <p data-stack-source-summary aria-live="polite">{{ I18N.stacks.regroup_summary | translate:sourceSummary() }}</p>
            <details class="mt-1">
              <summary class="cursor-pointer font-medium">{{ I18N.stacks.regroup_sources | translate }}</summary>
              <div class="max-h-36 overflow-y-auto mt-2">
                @for (source of sourceEffects(); track source.id) {
                  <p data-stack-source class="mb-1"><span class="font-medium">{{ source.cover | filename }}</span>: {{ I18N.stacks.regroup_moved | translate:{ moved: source.moved, total: source.total } }} · {{ I18N.stacks[source.outcome] | translate:{ count: source.remaining } }}</p>
                }
              </div>
            </details>
          </section>
        }
        </div>
        @if (focused(); as path) {
          <div class="relative bg-black/90 rounded-xl flex items-center justify-center overflow-hidden" [class]="page ? 'flex-1 min-h-0' : 'shrink-0 h-[28dvh] min-h-32 sm:h-[36dvh]'">
            @if (page) {
              <app-synced-zoom #zoomPane class="block w-full h-full min-h-0" [src]="path | thumbnailUrl:1920" [placeholderSrc]="path | thumbnailUrl:640"
                [fullResSrc]="path | imageUrl" [frameKey]="path" [alt]="path | filename" [zoom]="zoom()" (zoomChange)="zoom.set($event)" />
            } @else {
            <img data-stack-preview [src]="path | thumbnailUrl:1920" [alt]="path | filename" decoding="async" class="w-full h-full object-contain" />
            }
            @if (page) {
              <button mat-icon-button data-stack-zoom class="!absolute top-2 right-2 !bg-black/75 !text-white" (click)="toggleZoom()" [disabled]="saving() || loading()" [attr.aria-pressed]="zoom().scale > 1" [attr.aria-label]="I18N.culling.shortcuts.zoom | translate" [matTooltip]="I18N.culling.shortcuts.zoom | translate"><mat-icon aria-hidden="true">{{ zoom().scale > 1 ? 'zoom_out' : 'zoom_in' }}</mat-icon></button>
            }
            @if (path === cover()) { <span class="absolute top-2 left-2 rounded-full bg-black/75 text-white px-3 py-1 text-xs flex items-center gap-1"><mat-icon aria-hidden="true">star</mat-icon>{{ I18N.stacks.cover | translate }}</span> }
          </div>
          <div class="shrink-0 flex items-center justify-between gap-2 my-1 min-w-0">
            <span class="text-sm truncate" [title]="path">{{ path | filename }}</span>
            @if (editable() && !saved()) {
              <button mat-icon-button data-stack-reject (click)="rejectFocused()" [disabled]="saving() || loading()" [attr.aria-label]="I18N.stacks.reject_focused | translate" [matTooltip]="I18N.stacks.reject_focused | translate" aria-keyshortcuts="R"><mat-icon aria-hidden="true">block</mat-icon></button>
            }
            @if (page && editable() && !saved()) {
              <div class="flex shrink-0">
                <ng-container [ngTemplateOutlet]="coverButton" [ngTemplateOutletContext]="{ $implicit: path }" />
                <ng-container [ngTemplateOutlet]="memberActions" [ngTemplateOutletContext]="{ $implicit: path, index: focusedIndex(), first: focusedIndex() === 0, last: focusedIndex() === paths().length - 1, compact: false }" />
              </div>
            }
            @if (!page) { <button mat-icon-button (click)="openMember(path)" [disabled]="saving()" [attr.aria-label]="I18N.stacks.open_member | translate:{ path }" [matTooltip]="I18N.stacks.open_member | translate:{ path: (path | filename) }"><mat-icon aria-hidden="true">open_in_new</mat-icon></button> }
          </div>
        }
        @if (paths().length < 2) { <p role="status" class="my-3">{{ (regrouping() ? I18N.stacks.regroup_minimum : I18N.stacks.dissolve_hint) | translate }}</p> }
        <ol class="gap-2 pb-2" [class]="page ? 'flex shrink-0 overflow-x-auto' : 'grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] sm:grid-cols-[repeat(auto-fill,minmax(144px,1fr))]'">
          @for (path of paths(); track path; let index = $index; let first = $first; let last = $last) {
            <li data-stack-tile class="min-w-0 rounded-lg border border-current/20 overflow-hidden" [class.w-28]="page" [class.shrink-0]="page" [class.border-[var(--mat-sys-primary)]]="path === focused()">
              <button #thumbnail [attr.data-stack-focus]="path" class="relative block w-full cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-[-3px]" (click)="focusMember(path)" [disabled]="saving()"
                [attr.aria-pressed]="path === focused()" [attr.aria-label]="(path === cover() ? I18N.stacks.regroup_focus_cover : I18N.stacks.regroup_focus) | translate:{ path: (path | filename) }">
                <img [src]="path | thumbnailUrl:640" [alt]="path | filename" loading="lazy" decoding="async" class="w-full h-[84px] sm:h-[108px] object-contain bg-black/70" />
                @if (path === cover()) { <span class="absolute top-1 left-1 rounded bg-black/80 text-white px-1 text-xs">{{ I18N.stacks.cover | translate }}</span> }
              </button>
              <span data-stack-filename class="block text-xs truncate px-2 pt-2" tabindex="0" [matTooltip]="path" [title]="path" [attr.aria-label]="path">{{ path | filename }}</span>
              @if (editable() && !page) {
                <ng-container [ngTemplateOutlet]="coverButton" [ngTemplateOutletContext]="{ $implicit: path }" />
                <div class="flex justify-center">
                  <ng-container [ngTemplateOutlet]="memberActions" [ngTemplateOutletContext]="{ $implicit: path, index, first, last, compact: true }" />
                </div>
              }
            </li>
          }
        </ol>
        @if (editable() && additions().length) {
          <button mat-button data-stack-add (click)="addSelected()" [disabled]="saving() || loading() || paths().length + additions().length > STACK_MAX_MEMBERS">{{ additions().length | pluralKey:I18N.stacks.add_selected:I18N.stacks.add_selected_plural | translate:{ count: additions().length } }}</button>
        }
      }
    </div>
    <footer class="flex flex-wrap items-center justify-end shrink-0 px-3 py-2 sm:px-6 border-t border-current/10 gap-1">
      <button #closeButton [attr.data-stack-back]="page ? '' : null" mat-button (click)="close()" [disabled]="saving()">{{ (page ? I18N.stacks.back_gallery : I18N.dialog.close) | translate }}</button>
      @if (saved() && page) {
        <span role="status" data-stack-saved class="text-sm">{{ I18N.stacks.saved | translate }}</span>
        <button mat-flat-button data-stack-continue (click)="continueEditing()" [disabled]="loading() || saving()">{{ I18N.stacks.continue_editing | translate }}</button>
      }
      @if (ready() && !saved()) {
        @if (skippable()) { <button mat-button (click)="skipSuggestion()" [disabled]="saving()">{{ I18N.stacks.suggestion_skip_group | translate }}</button> }
        @if (stack()) { <button mat-button (click)="selectMembers()" [disabled]="saving()">{{ I18N.stacks.select_all | translate:{ count: memberCount() } }}</button> }
        @if (editable()) {
          @if (stack() && !regrouping()) { <button mat-button (click)="unstack()" [disabled]="saving()">{{ I18N.stacks.unstack | translate }}</button> }
          <button mat-flat-button data-stack-save (click)="save()" [disabled]="saving() || loading() || !dirty() || !valid()">{{ (stack() ? I18N.ui.buttons.save : I18N.stacks.create) | translate }}</button>
        }
      }
    </footer>
    <ng-template #coverButton let-path>
      @if (page) {
        <button mat-icon-button [attr.data-stack-cover]="path" (click)="setCover(path)" [disabled]="!canEditDraft()" [attr.aria-pressed]="path === cover()" [attr.aria-label]="I18N.stacks.cover_for | translate:{ path }" [matTooltip]="I18N.stacks.cover_for | translate:{ path: (path | filename) }"><mat-icon aria-hidden="true">{{ path === cover() ? 'star' : 'star_outline' }}</mat-icon></button>
      } @else {
        <button mat-button class="!w-full" [attr.data-stack-cover]="path" (click)="setCover(path)" [disabled]="!canEditDraft()" [attr.aria-pressed]="path === cover()" [attr.aria-label]="I18N.stacks.cover_for | translate:{ path }" [matTooltip]="I18N.stacks.cover_for | translate:{ path: (path | filename) }">
          <mat-icon aria-hidden="true">{{ path === cover() ? 'star' : 'star_outline' }}</mat-icon>{{ I18N.stacks.cover | translate }}
        </button>
      }
    </ng-template>
    <ng-template #memberActions let-path let-index="index" let-first="first" let-last="last" let-compact="compact">
      <button mat-icon-button [class]="compact ? '!w-9 !h-10 !p-2' : ''" (click)="move(index, -1)" [disabled]="!canEditDraft() || first" [attr.aria-label]="I18N.stacks.move_up | translate:{ path }" [matTooltip]="I18N.stacks.move_up | translate:{ path: (path | filename) }"><mat-icon aria-hidden="true">arrow_back</mat-icon></button>
      <button mat-icon-button [class]="compact ? '!w-9 !h-10 !p-2' : ''" (click)="move(index, 1)" [disabled]="!canEditDraft() || last" [attr.aria-label]="I18N.stacks.move_down | translate:{ path }" [matTooltip]="I18N.stacks.move_down | translate:{ path: (path | filename) }"><mat-icon aria-hidden="true">arrow_forward</mat-icon></button>
      <button mat-icon-button [class]="compact ? '!w-9 !h-10 !p-2' : ''" [attr.data-stack-remove]="path" (click)="remove(path)" [disabled]="!canEditDraft()" [attr.aria-label]="I18N.stacks.remove | translate:{ path }" [matTooltip]="I18N.stacks.remove | translate:{ path: (path | filename) }"><mat-icon aria-hidden="true">remove_circle_outline</mat-icon></button>
    </ng-template>
  `,
})
export class StackEditorComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly STACK_MAX_MEMBERS = STACK_MAX_MEMBERS;
  readonly host = inject(STACK_EDITOR_HOST);
  readonly data = this.host.data;
  readonly page = this.host.presentation === 'page';
  readonly saved = signal(false);
  readonly zoom = signal({ ...FIT_ZOOM });
  private readonly zoomPane = viewChild<SyncedZoomComponent>('zoomPane');
  private readonly pageContext = inject(PageContextService);
  readonly focusedIndex = computed(() => this.paths().indexOf(this.focused()));
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private readonly actions = inject(StackActionsService);
  private readonly reviewActions = inject(StackReviewActionsService);
  private readonly rejectExclusions = new Map<string, object>();
  readonly rejectedCount = signal(0);
  private readonly sharedRestores = new Map<string, () => void>();
  private coverVersion = 0;
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly session = this.stacks.context();
  private readonly initialEdition = this.auth.isEdition();
  private readonly cancelLoad = new Subject<void>();
  private retryAction: 'load' | 'save' | 'unstack' | 'add' | { open: string } | { reject: string } = 'load';
  private readonly closeButton = viewChild<ElementRef<HTMLButtonElement>>('closeButton');
  private readonly thumbnails = viewChildren<ElementRef<HTMLButtonElement>>('thumbnail');
  private closing = false;
  private loadSequence = 0;
  readonly stack = signal<PhotoStack | null>(null);
  readonly paths = signal<string[]>([]);
  readonly cover = signal('');
  readonly focused = signal('');
  readonly regrouping = signal(!this.data.stackId && !this.data.skippable);
  readonly mode = signal<StackRegroupMode>('combine');
  readonly explicitPaths = signal([...new Set(this.data.paths ?? [])]);
  readonly preview = signal<StackRegroupPreview | null>(null);
  readonly previewCurrent = signal(false);
  private readonly excluded = new Set<string>();
  readonly sourceEffects = computed(() => regroupSourceEffects(this.regrouping() ? this.preview() : null, this.paths()));
  readonly sourceSummary = computed(() => {
    const effects = this.sourceEffects();
    return { combined: effects.filter(source => source.remaining === 0).length,
      retained: effects.filter(source => source.remaining >= 2).length,
      unstacked: effects.filter(source => source.remaining === 1).length };
  });
  readonly extraCount = computed(() => this.regrouping() ? this.paths().filter(path => !this.explicitPaths().includes(path)).length : 0);
  readonly ready = signal(false);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<'error' | 'conflict' | 'unavailable' | 'regroup_limit' | null>(null);
  readonly editable = computed(() => this.auth.isEdition() && (!this.data.stackId || this.stack()?.editable === true));
  /** The signal-backed part of the draft-edit guard, shared with the template's [disabled] bindings. */
  readonly canEditDraft = computed(() => this.editable() && !this.saved() && !this.saving() && !this.loading());
  readonly memberCount = computed(() => this.stack()?.members.length ?? this.paths().length);
  readonly additions = computed(() => (this.data.selectedPaths ?? []).filter(path => !this.paths().includes(path)));
  readonly skippable = computed(() => this.data.skippable === true && this.editable() && !this.stack()
    && this.paths().length < STACK_MIN_MEMBERS);
  readonly valid = computed(() => this.paths().length <= STACK_MAX_MEMBERS
    && (this.regrouping() ? this.previewCurrent() && this.paths().length >= STACK_MIN_MEMBERS
      : this.stack() !== null || this.paths().length >= STACK_MIN_MEMBERS));
  readonly dirty = computed(() => {
    const previous = this.stack();
    return this.regrouping() || !previous || previous.cover_path !== this.cover() || JSON.stringify(previous.members.map(m => m.path)) !== JSON.stringify(this.paths());
  });

  constructor() {
    effect(() => { this.focused(); this.zoom.set({ ...FIT_ZOOM }); });
    effect(() => { this.data.reviewDraft?.excluded(); this.ready(); this.syncReviewDraft(); });
    this.host.keydown$.pipe(takeUntilDestroyed()).subscribe(event => this.onKeydown(event));
    this.host.closing$.pipe(takeUntilDestroyed()).subscribe(() => this.clearPrivateState());
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (!this.page && event instanceof NavigationStart) this.invalidate();
    });
    effect(() => {
      this.auth.identity();
      if (!this.session() || this.auth.isEdition() !== this.initialEdition || this.data.reviewDraft && !this.data.reviewDraft.current()) this.invalidate();
    });
  }

  toggleZoom(): void { if (this.current() && this.ready() && !this.saving() && !this.loading()) this.zoomPane()?.toggleZoom(); }
  async continueEditing(): Promise<void> {
    if (!this.current() || this.saving() || this.loading()) return;
    this.saved.set(false); this.previewCurrent.set(false);
    await this.load();
  }
  ngOnInit(): void { void this.load(); }
  private canMutateDraft(): boolean { return this.current() && this.canEditDraft(); }
  private current(): boolean { return !this.destroyRef.destroyed && !this.closing && this.session() && this.auth.isEdition() === this.initialEdition && (!this.data.reviewDraft || this.data.reviewDraft.current()); }
  private clearPrivateState(): void {
    this.closing = true; this.loadSequence++; this.cancelLoad.next();
    this.paths.set([]); this.stack.set(null); this.explicitPaths.set([]); this.preview.set(null);
    this.previewCurrent.set(false); this.excluded.clear(); this.sharedRestores.clear(); this.rejectExclusions.clear(); this.rejectedCount.set(0); this.focused.set(''); this.cover.set('');
    this.ready.set(false); this.saved.set(false); this.error.set(null); this.loading.set(false); this.saving.set(false);
    this.zoom.set({ ...FIT_ZOOM });
  }
  private invalidate(): void { this.clearPrivateState(); this.host.invalidate(); }
  close(): void { if (!this.saving()) this.host.finish('close'); }
  skipSuggestion(): void { if (this.skippable() && !this.saving()) this.host.finish('skip'); }

  async load(): Promise<void> {
    if (this.regrouping()) { await this.loadPreview(); return; }
    if (!this.current() || this.saving()) return;
    const sequence = ++this.loadSequence;
    this.loading.set(true); this.ready.set(false); this.error.set(null); this.retryAction = 'load';
    try {
      if (this.data.stackId) {
        const stack = await firstValueFrom(this.stacks.get(this.data.stackId).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
        if (!this.current() || sequence !== this.loadSequence) return;
        if (!stack) { this.error.set('unavailable'); return; }
        this.stack.set(stack); this.paths.set(stack.members.map(member => member.path)); this.cover.set(stack.cover_path);
      } else {
        const paths = [...new Set(this.data.paths ?? [])];
        if (paths.length < STACK_MIN_MEMBERS || paths.length > STACK_MAX_MEMBERS) { this.error.set('unavailable'); return; }
        const photos: Photo[] = [];
        for (let offset = 0; offset < paths.length; offset += BY_PATHS_MAX) {
          const res = await firstValueFrom(this.api.post<{ photos: Photo[]; missing: string[] }>('/photos/by_paths',
            { paths: paths.slice(offset, offset + BY_PATHS_MAX) }).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
          if (!this.current() || sequence !== this.loadSequence) return;
          photos.push(...res.photos);
        }
        if (photos.length !== paths.length) { this.error.set('unavailable'); return; }
        const byPath = new Map(photos.map(photo => [photo.path, photo]));
        this.paths.set(paths.sort((a, b) => captureDateKey(byPath.get(a)?.date_taken).localeCompare(captureDateKey(byPath.get(b)?.date_taken)) || a.localeCompare(b)));
        this.cover.set(this.data.activePath && paths.includes(this.data.activePath) ? this.data.activePath : (this.data.paths?.[0] ?? paths[0]));
      }
      this.focused.set(this.paths().includes(this.data.activePath ?? '') ? this.data.activePath! : this.cover());
      this.ready.set(true); this.syncReviewDraft();
    } catch { if (this.current() && sequence === this.loadSequence) this.error.set('error'); }
    finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }

  async loadPreview(): Promise<void> {
    if (!this.current() || this.saving()) return;
    if (this.explicitPaths().length < STACK_MIN_MEMBERS || this.explicitPaths().length > STACK_MAX_MEMBERS) {
      this.error.set('unavailable'); return;
    }
    const sequence = ++this.loadSequence;
    this.cancelLoad.next();
    this.loading.set(true); this.previewCurrent.set(false); this.error.set(null); this.retryAction = 'load';
    const previous = this.paths().length ? { paths: this.paths(), cover: this.cover() } : null;
    if (this.page) this.ready.set(false);
    try {
      const preview = await firstValueFrom(this.stacks.previewRegroup(this.explicitPaths(), this.mode())
        .pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || sequence !== this.loadSequence) return;
      const draft = reconcileRegroupDraft(preview, previous, this.excluded);
      this.preview.set(preview); this.paths.set(draft.paths); this.cover.set(draft.cover);
      if (!draft.paths.includes(this.focused())) this.focused.set(!previous && draft.paths.includes(this.data.activePath ?? '') ? this.data.activePath! : draft.cover);
      this.previewCurrent.set(true); this.ready.set(true);
    } catch (failure) {
      if (this.current() && sequence === this.loadSequence) this.showFailure(failure);
    } finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }
  // Deliberately not canMutateDraft(): a mode switch must stay possible while a preview is loading.
  changeMode(mode: StackRegroupMode): void {
    if (!this.current() || !this.editable() || this.saved() || this.saving() || mode === this.mode()) return;
    this.mode.set(mode); void this.loadPreview();
  }
  retry(): void {
    if (typeof this.retryAction === 'object') {
      if ('reject' in this.retryAction) void this.rejectFocused(this.retryAction.reject);
      else void this.openMember(this.retryAction.open);
    }
    else if (this.retryAction === 'add') void this.addSelected();
    else if (this.retryAction === 'unstack' && this.error() === 'error') void this.unstack();
    else if (this.retryAction === 'save' && this.error() === 'error') void this.save();
    else void this.load();
  }
  focusMember(path: string): void {
    if (this.current() && !this.saving() && this.paths().includes(path)) this.focused.set(path);
  }
  private onKeydown(event: KeyboardEvent): void {
    if (!this.current() || this.saving() || event.defaultPrevented || isTypingContext(event) || this.page && isPageShortcutBlocked(event)
      || event.repeat || this.page && this.pageContext.overlays().length > 0
      || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey
      || !['ArrowLeft', 'ArrowRight', 'r', 'R'].includes(event.key)
      || (event.target instanceof HTMLElement ? event.target : null)?.closest('[role="slider"], [role="radiogroup"], input, select')) return;
    if (event.key.toLowerCase() === 'r') {
      event.preventDefault(); event.stopPropagation(); void this.rejectFocused(); return;
    }
    const index = this.paths().indexOf(this.focused());
    const next = this.paths()[index + (event.key === 'ArrowRight' ? 1 : -1)];
    event.preventDefault(); event.stopPropagation();
    if (next) {
      this.focusMember(next);
      const button = this.thumbnails()[this.paths().indexOf(next)]?.nativeElement;
      button?.focus({ preventScroll: true }); button?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    }
  }
  private showFailure(failure: unknown): void {
    const status = (failure as { status?: number }).status;
    this.error.set(status === 422 ? 'regroup_limit' : MUTATION_FAILURE[status ?? 0] ?? 'error');
    if (this.regrouping() && status !== undefined && [403, 404, 409, 422].includes(status)) this.previewCurrent.set(false);
  }

  setCover(path: string): void { if (this.canMutateDraft() && this.paths().includes(path)) { this.coverVersion++; this.cover.set(path); } }
  move(index: number, delta: number): void {
    if (!this.canMutateDraft()) return;
    const paths = [...this.paths()]; const target = index + delta;
    if (index < 0 || index >= paths.length || target < 0 || target >= paths.length) return;
    [paths[index], paths[target]] = [paths[target], paths[index]]; this.paths.set(paths);
  }
  remove(path: string): void {
    if (!this.canMutateDraft()) return;
    const index = this.paths().indexOf(path);
    if (index < 0) return;
    const next = this.paths()[index + 1] ?? this.paths()[index - 1] ?? '';
    const buttons = this.thumbnails();
    const removedHasFocus = buttons[index]?.nativeElement.closest('li')?.contains(document.activeElement);
    const nextButton = buttons[index + 1]?.nativeElement ?? buttons[index - 1]?.nativeElement;
    if (this.regrouping()) this.excluded.add(path);
    this.paths.update(paths => paths.filter(member => member !== path));
    if (this.focused() === path || removedHasFocus) this.focused.set(next);
    if (removedHasFocus) (nextButton ?? this.closeButton()?.nativeElement)?.focus();
    if (this.cover() === path) this.cover.set(this.paths()[0] ?? '');
  }
  private syncReviewDraft(): void {
    const incoming = this.data.reviewDraft?.excluded();
    if (!incoming || !this.current() || !this.ready() || this.saved()) return;
    for (const path of incoming) {
      if (!this.sharedRestores.has(path) && this.paths().includes(path)) this.sharedRestores.set(path, this.excludeRejectedMember(path));
    }
    for (const [path, restore] of this.sharedRestores) {
      if (!incoming.has(path)) { restore(); this.sharedRestores.delete(path); }
    }
  }

  private excludeRejectedMember(path: string): () => void {
    const before = [...this.paths()]; const oldCover = this.cover();
    const index = before.indexOf(path); const token = {};
    this.rejectExclusions.set(path, token); this.rejectedCount.set(this.rejectExclusions.size);
    this.excluded.add(path);
    this.paths.set(before.filter(member => member !== path));
    if (this.focused() === path) this.focused.set(before[index + 1] ?? before[index - 1] ?? '');
    if (oldCover === path) this.cover.set(this.paths()[0] ?? '');
    const fallback = this.cover(); const coverVersion = this.coverVersion;
    return () => {
      if (!this.current() || this.saved() || this.rejectExclusions.get(path) !== token) return;
      this.rejectExclusions.delete(path); this.rejectedCount.set(this.rejectExclusions.size);
      this.excluded.delete(path);
      if (this.regrouping() && !this.preview()?.paths.includes(path)) return;
      if (this.paths().includes(path)) return;
      const paths = [...this.paths()];
      const previous = before.slice(0, index).reverse().find(member => paths.includes(member));
      const following = before.slice(index + 1).find(member => paths.includes(member));
      paths.splice(previous ? paths.indexOf(previous) + 1 : following ? paths.indexOf(following) : paths.length, 0, path);
      this.paths.set(paths);
      if (oldCover === path && this.cover() === fallback && this.coverVersion === coverVersion) this.cover.set(path);
      if (!this.focused()) this.focused.set(path);
    };
  }

  async rejectFocused(path = this.focused()): Promise<void> {
    if (!this.current() || !this.editable() || !this.ready() || this.saved() || this.saving() || this.loading()
      || !this.paths().includes(path)) return;
    const shared = this.data.reviewDraft;
    const live = () => this.current() && this.editable() && !this.saved() && (!shared || shared.current());
    if (!live() || shared && !shared.lock()) return;
    this.saving.set(true); this.host.setBusy(true); this.error.set(null); this.retryAction = { reject: path };
    try {
      await this.reviewActions.reject(path, {
        session: this.session, live,
        beginUndo: () => {
          if (shared?.current() && !shared.lock()) return false;
          if (!live()) return true;
          if (this.saving() || this.loading()) { shared?.unlock(); return false; }
          this.saving.set(true); this.host.setBusy(true); return true;
        },
        endUndo: () => { shared?.unlock(); if (live()) { this.saving.set(false); this.host.setBusy(false); } },
        exclude: () => {
          if (!shared) return this.excludeRejectedMember(path);
          const restore = shared.exclude(path); this.syncReviewDraft();
          return () => { restore(); this.syncReviewDraft(); };
        },
      });
    } catch { if (live()) this.error.set('error'); }
    finally { shared?.unlock(); if (live()) { this.saving.set(false); this.host.setBusy(false); } }
  }
  async addSelected(): Promise<void> {
    if (!this.canMutateDraft()
      || this.paths().length + this.additions().length > STACK_MAX_MEMBERS) return;
    const additions = this.additions();
    const paths = [...this.paths(), ...additions];
    // Expanded companions are draft members, never implicit explicit selections.
    const selectedPaths = this.regrouping() ? [...new Set([...this.explicitPaths(), ...additions])] : paths;
    const mode = this.regrouping() ? this.mode() : 'combine';
    const sequence = ++this.loadSequence;
    this.loading.set(true); this.error.set(null); this.retryAction = 'add';
    try {
      const preview = await firstValueFrom(this.stacks.previewRegroup(selectedPaths, mode)
        .pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || sequence !== this.loadSequence) return;
      if (preview.source_stacks.some(source => source.id !== this.stack()?.id) || this.regrouping()) {
        // Only an explicit addition crossing a source boundary changes strict edit semantics.
        const sourcePaths = this.stack()?.members.map(member => member.path) ?? [];
        sourcePaths.filter(path => !paths.includes(path)).forEach(path => this.excluded.add(path));
        additions.forEach(path => this.excluded.delete(path));
        this.explicitPaths.set(selectedPaths); this.mode.set(mode); this.regrouping.set(true);
        const draft = reconcileRegroupDraft(preview, { paths, cover: this.cover() }, this.excluded);
        this.preview.set(preview); this.paths.set(draft.paths); this.cover.set(draft.cover); this.previewCurrent.set(true);
      } else this.paths.set(paths);
      for (const path of additions) { this.rejectExclusions.delete(path); this.excluded.delete(path); }
      this.rejectedCount.set(this.rejectExclusions.size);
    } catch (failure) { if (this.current() && sequence === this.loadSequence) this.showFailure(failure); }
    finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }
  selectMembers(): void {
    if (!this.current() || !this.ready() || this.saving()) return;
    // Select stored, permitted membership, never unsaved draft additions/removals.
    this.store.restoreSelection(this.stack()?.members.map(member => member.path) ?? this.paths()); this.host.finish('close');
  }
  async openMember(path: string): Promise<void> {
    if (!this.current() || this.saving() || this.loading() || !this.paths().includes(path)) return;
    const allowed = () => {
      const pinned = this.store.pinnedPaths();
      return pinned === null || pinned.includes(path);
    };
    if (!allowed()) return;
    this.saving.set(true); this.error.set(null); this.retryAction = { open: path };
    try {
      const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || !allowed()) return;
      this.host.finish('close');
      await this.stacks.navigateMember(path, photo, allowed, this.router.url.startsWith('/photo?'));
    } catch { if (this.current()) this.error.set('error'); }
    finally { if (this.current()) this.saving.set(false); }
  }
  async save(): Promise<void> {
    if (!this.current() || !this.ready() || !this.editable() || !this.valid() || !this.dirty() || this.saved() || this.saving() || this.loading()) return;
    const preview = this.preview();
    if (this.regrouping()) {
      if (preview && this.previewCurrent()) {
        const chosen = new Set(this.paths());
        const contributes = preview.source_stacks.some(source => source.members.some(member => chosen.has(member.path)));
        await this.mutate(this.stacks.regroup(preview, this.paths(), this.cover()), contributes ? 'update' : 'create');
      }
      return;
    }
    const stack = this.stack();
    await this.mutate(stack ? this.stacks.update(stack, this.paths(), this.paths().length ? this.cover() : null) : this.stacks.create(this.paths(), this.cover()), stack ? 'update' : 'create');
  }
  async unstack(): Promise<void> {
    const stack = this.stack();
    if (!this.current() || this.regrouping() || !stack || !this.editable() || this.saved() || this.saving() || this.loading()) return;
    await this.mutate(this.stacks.unstack(stack), 'unstack');
  }
  private async mutate(request: Observable<StackMutation>, action: 'create' | 'update' | 'unstack'): Promise<void> {
    const shared = this.data.reviewDraft;
    if (shared && !shared.lock()) return;
    this.saving.set(true); this.error.set(null); this.host.setBusy(true);
    const paths = [...new Set([...(this.stack()?.members.map(member => member.path) ?? []), ...this.paths()])];
    try {
      const applied = await this.actions.commit(request, {
        paths, action, labelKey: this.I18N.stacks.saved, session: this.session, live: () => this.current(),
        onUndone: this.host.onUndone,
      });
      if (applied && this.current()) { this.saved.set(true); this.previewCurrent.set(false); this.host.finish('saved'); }
    } catch (failure) {
      if (this.current()) {
        this.retryAction = action === 'unstack' ? 'unstack' : 'save'; this.showFailure(failure);
      }
    } finally {
      shared?.unlock();
      if (this.current()) { this.saving.set(false); this.host.setBusy(false); }
    }
  }
}
