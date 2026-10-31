import { stackDialogConfig } from '../gallery/stack-dialog.config';
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, effect, inject, input, output, signal, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationStart, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog } from '@angular/material/dialog';
import { AuthService } from '../../core/services/auth.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { PhotoStack, PhotoStackService } from '../../core/services/photo-stack.service';
import { i18nKeys } from '../../core/i18n/keys';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { GalleryStore } from '../gallery/gallery.store';

/** Read-only navigation: membership comes exclusively from the authorized endpoint. */
@Component({
  selector: 'app-stack-navigator',
  imports: [MatButtonModule, MatIconModule, ThumbnailUrlPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block shrink-0 min-w-0', '[style.min-height.px]': 'reservedHeight()' },
  template: `
    @if (error()) {
      <div class="flex items-center gap-2 px-3 py-1" role="alert">
        <span>{{ I18N.stacks.error | translate }}</span>
        <button mat-button (click)="retry()">{{ I18N.stacks.reload | translate }}</button>
      </div>
    }
    @if (visibleStack(); as group) {
      <nav data-stack-navigator [attr.aria-label]="I18N.stacks.title | translate" class="border-b border-[var(--mat-sys-outline-variant)] px-2 py-1 min-w-0">
        <div class="flex items-center gap-1 flex-wrap">
          <span class="text-sm font-medium">{{ I18N.stacks.title | translate }}</span>
          <button mat-icon-button data-stack-prev (click)="step(-1)" [disabled]="position() <= 0"
            [attr.aria-label]="I18N.stacks.previous | translate"><mat-icon>chevron_left</mat-icon></button>
          <span data-stack-position role="status" class="text-sm">{{ I18N.stacks.browse_position | translate:{ position: position() + 1, count: members().length } }}</span>
          <button mat-icon-button data-stack-next (click)="step(1)" [disabled]="position() >= members().length - 1"
            [attr.aria-label]="I18N.stacks.next | translate"><mat-icon>chevron_right</mat-icon></button>
          @if (auth.isEdition() && group.editable) {
            <button mat-button data-stack-manage (click)="manage()">{{ I18N.stacks.manage | translate }}</button>
          }
        </div>
        <div class="flex gap-2 overflow-x-auto py-1">
          @for (member of members(); track member.path) {
            <button #thumbnail data-stack-thumbnail class="shrink-0 rounded overflow-hidden cursor-pointer focus-visible:outline-2 border-2 border-transparent"
              [class.border-[var(--mat-sys-primary)]]="member.path === path()"
              [attr.aria-current]="member.path === path() ? 'true' : null"
              [attr.aria-label]="I18N.stacks.open_member | translate:{ path: member.path }"
              (click)="openMember(member.path)">
              <img [src]="member.path | thumbnailUrl:96:member.preview_revision" alt="" loading="lazy" decoding="async" class="w-14 h-12 object-cover" />
            </button>
          }
        </div>
      </nav>
    }
  `,
})
export class StackNavigatorComponent {
  readonly path = input.required<string>();
  readonly allowedPaths = input<string[] | null>(null);
  /** Whether the open photo is known to belong to a stack: only then does a pending lookup own the arrows. */
  readonly stacked = input(false);
  readonly memberOpened = output<string>();
  protected readonly I18N = i18nKeys();
  protected readonly auth = inject(AuthService);
  private readonly stacks = inject(PhotoStackService);
  private readonly assistantChanges = inject(AssistantChangesService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly store = inject(GalleryStore);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly owner = this.auth.identity();
  private readonly generation = signal(0);
  private readonly thumbnails = viewChildren<ElementRef<HTMLButtonElement>>('thumbnail');
  private navigating = false;
  private reservedTarget: string | null = null;
  private reservedRevision = 0;
  protected readonly reservedHeight = signal<number | null>(null);
  readonly stack = signal<PhotoStack | null>(null);
  readonly error = signal(false);
  private readonly loading = signal(true);
  readonly members = computed(() => {
    const allowed = this.allowedPaths();
    return (this.stack()?.members ?? []).filter(member => allowed === null || allowed.includes(member.path));
  });
  readonly position = computed(() => this.members().findIndex(member => member.path === this.path()));

  readonly visibleStack = computed(() => this.position() >= 0 ? this.stack() : null);

  constructor() {
    // History can restore membership without navigating or using the stack service.
    // Invalidate immediately so an older reply or key press cannot use the old members.
    this.store.organizationRestored$.pipe(takeUntilDestroyed()).subscribe(() => this.invalidate());
    this.assistantChanges.batch$.pipe(takeUntilDestroyed()).subscribe(batch => {
      // A pending response has not disclosed membership yet. Any nonempty
      // batch may change that unknown set, so do not let its old reply land.
      if (batch.paths === null || (this.loading() && batch.paths.length > 0)
        || batch.paths.some(path => path === this.path()
          || this.stack()?.members.some(member => member.path === path))) this.invalidate();
    });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        const target = this.photoPath(event.url);
        // Keep only layout, never old membership, while an authorized member
        // gets its own fresh lookup. Measure before clearing the rendered strip.
        if (this.owner === this.auth.identity() && this.visibleStack()
          && this.members().some(member => member.path === target)) {
          this.reservedTarget = target;
          this.reservedRevision = this.stacks.revision();
          this.reservedHeight.set(this.host.nativeElement.getBoundingClientRect().height || null);
        } else this.clearReservation();
        this.navigating = true;
      } else if (event instanceof NavigationEnd || event instanceof NavigationCancel || event instanceof NavigationError) {
        this.navigating = false;
        if (!(event instanceof NavigationEnd) || this.photoPath(event.urlAfterRedirects) !== this.reservedTarget) this.clearReservation();
      } else return;
      this.stack.set(null);
      this.generation.update(value => value + 1);
    });
    effect(onCleanup => {
      const path = this.path();
      const generation = this.generation();
      const revision = this.stacks.revision();
      const identity = this.auth.identity();
      if (identity !== this.owner || revision !== this.reservedRevision
        || (!this.navigating && path !== this.reservedTarget)) this.clearReservation();
      this.stack.set(null); this.error.set(false); this.loading.set(true);
      if (this.navigating || identity !== this.owner) return;
      const context = this.stacks.context();
      const current = () => context() && !this.navigating && this.path() === path && this.generation() === generation && this.stacks.revision() === revision;
      const request = this.stacks.byPhoto(path).subscribe({
        next: group => {
          if (!current()) return;
          this.clearReservation();
          this.loading.set(false);
          if (group?.members.some(member => member.path === path)) this.stack.set(group);
        },
        error: () => { if (current()) { this.clearReservation(); this.error.set(true); this.loading.set(false); } },
      });
      onCleanup(() => request.unsubscribe());
    });
    effect(() => {
      const allowed = this.allowedPaths();
      if (this.reservedTarget !== null && allowed !== null && !allowed.includes(this.reservedTarget)) this.clearReservation();
    });
    effect(() => {
      const active = this.thumbnails()[this.position()]?.nativeElement;
      active?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    });
  }

  private invalidate(): void {
    this.clearReservation();
    this.stack.set(null);
    this.loading.set(true);
    this.generation.update(value => value + 1);
  }

  private photoPath(url: string): string | null {
    const tree = this.router.parseUrl(url);
    const outlets = tree.root.children;
    const segments = outlets['primary']?.segments;
    return Object.keys(outlets).length === 1 && segments?.length === 1 && segments[0].path === 'photo'
      && tree.queryParamMap.getAll('path').length === 1 ? tree.queryParamMap.get('path') : null;
  }

  private clearReservation(): void {
    this.reservedTarget = null;
    this.reservedHeight.set(null);
  }

  retry(): void { this.clearReservation(); this.generation.update(value => value + 1); }

  openMember(path: string): void {
    if (this.navigating || this.owner !== this.auth.identity() || !this.members().some(member => member.path === path)) return;
    this.memberOpened.emit(path);
  }

  /** True also at a boundary: arrows never escape an active stack, nor a pending lookup of a stacked photo. A failed lookup or an unstacked photo leaves them to the gallery. */
  step(delta: number): boolean {
    if (this.navigating || this.owner !== this.auth.identity()) return true;
    if (this.loading()) return this.stacked();
    if (this.error() || !this.stack() || this.position() < 0) return false;
    const next = this.members()[this.position() + delta];
    if (next) this.openMember(next.path);
    return true;
  }

  async manage(): Promise<void> {
    const group = this.stack();
    if (!group?.editable || !this.auth.isEdition()) return;
    const context = this.stacks.context();
    const { StackDialogComponent } = await import('../gallery/stack-dialog.component');
    if (this.destroyRef.destroyed || !context() || !this.auth.isEdition() || this.stack() !== group) return;
    const ref = this.dialog.open(StackDialogComponent, stackDialogConfig({ stackId: group.id, selectedPaths: this.store.viewScopeSelected() ? [] : [...this.store.selectedPaths()] }));
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      if (context()) this.retry();
    });
  }
}
