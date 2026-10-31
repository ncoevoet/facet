import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { extractErrorDetail } from '../../core/utils/http-error.util';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';

type CullAction = 'copy_keeps' | 'trash_rejects' | 'move_rejects';

interface CullRequest {
  /** Named photos. Omitted, not empty, when `filters` names the set instead —
   *  the server takes exactly one of the two. */
  paths?: string[];
  /** The whole current gallery view, from which the server derives the rows.
   *  Bounded at 10,000 server-side (412) — the same ceiling a path list carries;
   *  what it avoids is putting the paths on the wire, not the cap. */
  filters?: Record<string, string> | null;
  /** Photos unticked out of a filter-scoped selection. */
  exclude?: string[];
  action: CullAction;
  target_dir: string | null;
  include_companions: boolean;
  include_sequence_siblings: boolean;
  dry_run: boolean;
  preview_digest?: string;
}

interface CullResponse {
  preview_digest?: string;
  would_copy?: string[];
  would_move?: string[];
  would_trash?: string[];
  skipped?: string[];
  excluded_by_state?: number;
  matched?: number;
  sequence_siblings?: number;
  copied?: number;
  moved?: number;
  trashed?: number;
  errors?: number | string[];
}

/**
 * Edition-only "Cull to folder…" dialog. Defaults to the additive copy action
 * and always previews (dry-run) before any destructive apply. Move/trash need a
 * second, explicit click after the preview.
 */
@Component({
  selector: 'app-cull-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatCheckboxModule,
            MatProgressSpinnerModule, TranslatePipe],
  // Same title-row phantom flex item as the other dialogs: neutralise the
  // Material title's content:"" ::before so the row gap lands correctly.
  styles: `
    h2[mat-dialog-title]::before {
      content: none;
    }
  `,

  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-6 !pt-5 !pb-4 before:content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">delete_sweep</mat-icon>
      </span>
      {{ (data.allRejects ? I18N.cull.trash_all_rejects : data.action ? 'cull.' + data.action : I18N.cull.title) | translate }}
    </h2>
    <mat-dialog-content class="!pt-2 min-w-[22rem] max-w-[32rem]">
      @if (data.allRejects) {
        <p class="text-sm mb-3">{{ I18N.cull.all_rejects_scope | translate }}</p>
      }
      @if (count) {
        <p class="text-sm opacity-70 mb-3">{{ count }} {{ I18N.cull.selected | translate }}</p>
      }

      <div class="flex flex-col gap-1 mb-3">
        @for (a of actions; track a) {
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cullAction" [value]="a"
                   [checked]="action() === a" (change)="setAction(a)" />
            <span class="text-sm">{{ 'cull.' + a | translate }}</span>
          </label>
        }
      </div>

      @if (!data.trashAvailable) {
        <p class="text-xs opacity-60 mb-3">
          {{ (data.allowTrash ? I18N.cull.trash_missing_pkg : I18N.cull.trash_disabled) | translate }}
        </p>
      }

      @if (needsTarget()) {
        <label for="cullTargetDir" class="block text-xs opacity-60 mb-1">{{ I18N.cull.target_dir | translate }}</label>
        <input id="cullTargetDir" type="text" [value]="targetDir()" (input)="onTargetInput($event)"
               class="w-full text-sm font-mono rounded border border-[var(--mat-sys-outline-variant)] bg-transparent px-2 py-1.5 mb-3"
               placeholder="/path/to/folder" />
      }

      <mat-checkbox [checked]="includeCompanions()" (change)="includeCompanions.set($event.checked); preview.set(null)"
                    class="text-sm block">
        {{ I18N.cull.include_companions | translate }}
      </mat-checkbox>
      <mat-checkbox [checked]="includeSequenceSiblings()"
                    (change)="includeSequenceSiblings.set($event.checked); preview.set(null)"
                    class="text-sm block">
        {{ I18N.cull.include_sequence_siblings | translate }}
      </mat-checkbox>

      @if (preview(); as p) {
        <div class="mt-3 p-2 rounded bg-[var(--mat-sys-surface-container)] text-sm">
          @if (p.matched === 0) {
            <p>{{ I18N.cull.nothing_matched | translate }}</p>
          } @else {
            <p>{{ p.affected.length }} {{ I18N.cull.would_affect | translate }}</p>
          }
          @if (p.siblings) {
            <p class="opacity-60">{{ p.siblings }} {{ I18N.cull.sequence_siblings | translate }}</p>
          }
          @if (p.excluded) {
            <p class="opacity-60">{{ p.excluded }} {{ I18N.cull.excluded_by_state | translate }}</p>
          }
          @if (p.skipped.length) {
            <p class="opacity-60">{{ p.skipped.length }} {{ I18N.cull.skipped | translate }}</p>
          }
        </div>
      }

      @if (partialFailure()) {
        <p class="mt-3 text-sm text-[var(--mat-sys-error)]" role="alert">{{ I18N.cull.partial_error | translate }}</p>
      }
      @if (errorDetail(); as detail) {
        <p class="mt-3 text-sm text-[var(--mat-sys-error)]">{{ I18N.cull.error | translate }}</p>
        <p class="mt-1 text-xs text-[var(--mat-sys-error)] opacity-80">{{ I18N.errors.server_detail | translate }} {{ detail }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close [disabled]="applying()">{{ I18N.cull.cancel | translate }}</button>
      <button mat-stroked-button [disabled]="busy() || (needsTarget() && !targetDir())"
              (click)="runPreview()">
        @if (busy() && !applying()) { <mat-spinner diameter="16" class="!inline-block !align-middle !mr-1" [attr.aria-label]="I18N.ui.labels.loading | translate" /> }
        {{ I18N.cull.preview | translate }}
      </button>
      <button mat-flat-button color="primary" [attr.aria-busy]="applying()"
              [disabled]="busy() || !preview() || (data.action && !preview()?.digest) || (needsTarget() && !targetDir())"
              (click)="apply()">
        @if (applying()) { <mat-spinner diameter="16" class="!inline-block !align-middle !mr-1" [attr.aria-label]="I18N.ui.labels.loading | translate" /> }
        {{ I18N.cull.apply | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class CullDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly owner = this.auth.identity();
  private readonly originUrl = this.router.url;
  private closed = false;
  private readonly navigatedDuringApply = signal(false);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialogRef = inject(MatDialogRef<CullDialogComponent>);
  protected readonly data = inject<{
    paths: string[];
    /** Set when the selection is the whole filtered view rather than a path list. */
    filters?: Record<string, string> | null;
    exclude?: string[];
    /** How many photos the selection stands for — larger than `paths.length`
     *  under a filter-scoped selection, where no list is sent at all. */
    count?: number;
    trashAvailable?: boolean;
    allowTrash?: boolean;
    /** Offer only this action and preview it as soon as the dialog opens. */
    action?: CullAction;
    allRejects?: boolean;
  }>(MAT_DIALOG_DATA);

  protected readonly actions: CullAction[] = this.data.action ? [this.data.action]
    : this.data.trashAvailable
      ? ['copy_keeps', 'move_rejects', 'trash_rejects']
      : ['copy_keeps', 'move_rejects'];
  protected readonly action = signal<CullAction>(this.data.action ?? 'copy_keeps');
  protected readonly targetDir = signal('');
  protected readonly includeCompanions = signal(false);
  protected readonly includeSequenceSiblings = signal(false);
  protected readonly preview = signal<{
    affected: string[]; skipped: string[]; excluded: number; matched: number; siblings: number; digest?: string;
  } | null>(null);
  protected readonly busy = signal(false);
  protected readonly applying = signal(false);
  protected readonly errorDetail = signal<string | null>(null);
  protected readonly partialFailure = signal(false);

  protected readonly needsTarget = computed(() => this.action() !== 'trash_rejects');
  protected readonly count = this.data.count ?? this.data.paths.length;

  constructor() {
    effect(() => {
      if (!this.current()) this.dialogRef.close();
    });
    this.dialogRef.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closed = true; });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        // The request can already have moved files. Keep its result visible;
        // account/access changes still close the dialog through current().
        if (this.applying()) this.navigatedDuringApply.set(true);
        else this.dialogRef.close();
      }
    });
    if (this.data.action) void this.runPreview();
  }

  protected setAction(a: CullAction): void {
    this.action.set(a);
    this.preview.set(null);
    this.errorDetail.set(null);
  }

  protected onTargetInput(event: Event): void {
    this.targetDir.set((event.target as HTMLInputElement).value);
    this.preview.set(null);
    this.errorDetail.set(null);
  }

  private body(dryRun: boolean): CullRequest {
    const filters = this.data.filters ?? null;
    return {
      // Exactly one target form reaches the server: a filter-scoped selection
      // sends no path list; the same 10,000-photo server cap still applies.
      paths: filters ? undefined : this.data.paths,
      filters: filters ?? undefined,
      exclude: filters ? (this.data.exclude ?? []) : undefined,
      action: this.action(),
      target_dir: this.needsTarget() ? this.targetDir() : null,
      include_companions: this.includeCompanions(),
      include_sequence_siblings: this.includeSequenceSiblings(),
      dry_run: dryRun,
      preview_digest: dryRun ? undefined : this.preview()?.digest,
    };
  }

  private matchesCurrentForm(requested: CullRequest): boolean {
    const current = this.body(true);
    return requested.action === current.action
      && requested.target_dir === current.target_dir
      && requested.include_companions === current.include_companions
      && requested.include_sequence_siblings === current.include_sequence_siblings;
  }

  private current(): boolean {
    return !this.closed && !this.destroyRef.destroyed && this.owner === this.auth.identity()
      && this.auth.isEdition() && (this.navigatedDuringApply() || this.originUrl === this.router.url);
  }

  async runPreview(): Promise<void> {
    if (!this.current() || this.busy()) return;
    this.preview.set(null);
    this.partialFailure.set(false);
    this.busy.set(true);
    this.errorDetail.set(null);
    const requested = this.body(true);
    try {
      const res = await firstValueFrom(this.api.post<CullResponse>('/cull/apply', requested));
      if (!this.current() || !this.matchesCurrentForm(requested)) {
        return;
      }
      const affected = res.would_copy ?? res.would_move ?? res.would_trash ?? [];
      this.preview.set({
        digest: res.preview_digest, affected, skipped: res.skipped ?? [], excluded: res.excluded_by_state ?? 0,
        matched: res.matched ?? affected.length, siblings: res.sequence_siblings ?? 0,
      });
    } catch (error) {
      if (!this.current() || !this.matchesCurrentForm(requested)) return;
      this.preview.set(null);
      this.errorDetail.set(this.data.allRejects && error instanceof HttpErrorResponse && error.status === 412
        ? this.i18n.t(I18N.cull.all_rejects_limit)
        : extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.cull.error), '', { duration: 3000 });
    } finally {
      this.busy.set(false);
    }
  }

  async apply(): Promise<void> {
    if (!this.current() || this.busy() || !this.preview() || (this.data.action && !this.preview()?.digest)) return;
    this.partialFailure.set(false);
    this.busy.set(true);
    this.applying.set(true);
    const disableClose = this.dialogRef.disableClose;
    this.dialogRef.disableClose = true;
    this.errorDetail.set(null);
    try {
      const result = await firstValueFrom(this.api.post<CullResponse>('/cull/apply', this.body(false)));
      if (!this.current()) return;
      if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
        this.preview.set(null);
        this.partialFailure.set(true);
        this.snackBar.open(this.i18n.t(I18N.cull.partial_error), '', { duration: 4000 });
        return;
      }
      this.snackBar.open(this.i18n.t(I18N.cull.done), '', { duration: 2500 });
      this.dialogRef.close(true);
    } catch (error) {
      if (!this.current()) return;
      this.preview.set(null);
      this.errorDetail.set(extractErrorDetail(error) ?? null);
      this.snackBar.open(this.i18n.t(I18N.cull.error), '', { duration: 3000 });
    } finally {
      this.applying.set(false);
      this.dialogRef.disableClose = disableClose;
      this.busy.set(false);
    }
  }
}
