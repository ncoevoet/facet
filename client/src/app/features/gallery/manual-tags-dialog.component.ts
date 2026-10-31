import { Component, computed, DestroyRef, effect, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import type { ManualTagObservation } from './manual-tag-observation.util';
import { i18nKeys } from '../../core/i18n/keys';
import { chunkPhotoPaths } from './gallery.store';

export interface ManualTagsDialogScope {
  paths: string[];
  fromWholeView?: boolean;
  count: number;
  observation?: ManualTagObservation | null;
}
export interface ManualTagsDialogData extends ManualTagsDialogScope {
  /** Settlement outlives the dialog's close animation and its caller's route. */
  onSettled: (result: ManualTagsDialogResult) => void;
}

type ManualTagAction = 'add' | 'delete' | 'replace' | 'clear';
interface ManualTagPlan {
  action: ManualTagAction;
  tag: string;
  values: string[];
  bodies: Record<string, unknown>[];
}
export interface ManualTagsDialogResult {
  confirmedCount: number;
  tag: string;
  action: ManualTagAction;
  incomplete: boolean;
  uncertain: boolean;
}

@Component({
  selector: 'app-manual-tags-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title class="flex items-center gap-2 !text-lg"><mat-icon aria-hidden="true">sell</mat-icon>{{ I18N.manual_tags.title | translate }}</h2>
    <mat-dialog-content class="!text-sm !leading-6">
      <div class="border-b border-[var(--mat-sys-outline-variant)] pb-3 mb-3">
      <p data-tag-target class="text-sm font-medium">{{ I18N.manual_tags.batch.target | translate:{ count: data.count } }}</p>
      <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.manual_tags.batch.ownership | translate }}</p>
      @if (data.fromWholeView) {
        <p data-tag-view-scope class="text-sm">{{ I18N.manual_tags.batch.captured_view_scope | translate }}</p>
      } @else {
        <p class="text-xs">{{ I18N.manual_tags.batch.explicit_scope | translate }}</p>
      }
        <div class="flex flex-wrap gap-1 mb-3">
          @for (name of targetNames; track $index) { <span class="max-w-full truncate rounded bg-[var(--mat-sys-surface-container)] px-2 py-1 text-xs" [title]="name">{{ name }}</span> }
          @if (data.paths.length > targetNames.length) { <span class="text-xs py-1">{{ I18N.manual_tags.batch.more | translate:{ count: data.paths.length - targetNames.length } }}</span> }
        </div>
      </div>
      @if (data.observation; as observed) {
        <details class="mb-3">
          <summary class="cursor-pointer text-sm py-2">{{ I18N.manual_tags.batch.observed | translate:{ loaded: observed.photos, count: data.count } }}</summary>
          <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ (observed.photos === data.count ? I18N.manual_tags.batch.complete : I18N.manual_tags.batch.sample) | translate }}</p>
          <div class="flex flex-wrap gap-1">
            @for (item of observed.tags; track item.tag) {
              <span class="rounded bg-[var(--mat-sys-surface-container)] px-2 py-1 text-xs">{{ item.tag }} · {{ item.count }}/{{ observed.photos }}</span>
            }
          </div>
          @if (observed.overflow) { <p class="text-xs">{{ I18N.manual_tags.batch.more | translate:{ count: observed.overflow } }}</p> }
        </details>
      }
      @if (plan(); as preview) {
        <section data-tag-preview class="bg-[var(--mat-sys-surface-container-low)] rounded p-3 my-3">
          <h3 class="m-0 text-base font-medium">{{ I18N.manual_tags.batch.preview | translate }}</h3>
          <p class="mb-0 break-words">{{ (preview.action === 'add' ? I18N.manual_tags.batch.add_preview : preview.action === 'delete' ? I18N.manual_tags.batch.remove_preview : preview.action === 'replace' ? I18N.manual_tags.batch.replace_preview : I18N.manual_tags.batch.clear_preview) | translate:{ tag: preview.tag, count: data.count } }}</p>
          @if (preview.action === 'replace') {
            <ul class="my-2 flex list-none flex-wrap gap-1 p-0" data-replacement-values>
              @for (value of preview.values; track value) { <li class="max-w-full break-words rounded bg-[var(--mat-sys-surface-container-high)] px-2 py-1 text-sm">{{ value }}</li> }
            </ul>
          }
          @if (preview.action === 'replace' || preview.action === 'clear') {
            <p class="mb-0 text-sm">{{ I18N.manual_tags.batch.replace_boundary | translate }}</p>
          }
        </section>
        @if (saving() || confirmed()) {
          <p class="text-sm" role="status">{{ I18N.manual_tags.batch.progress | translate:{ done: completedBatches(), total: preview.bodies.length, count: confirmed() } }}</p>
        }
      } @else {
        <mat-form-field class="w-full" subscriptSizing="dynamic">
          <mat-label>{{ I18N.manual_tags.batch.tag_list | translate }}</mat-label>
          <textarea matInput rows="3" maxlength="3300" [value]="tag()" (input)="onInput($event)"></textarea>
          <mat-hint>{{ I18N.manual_tags.batch.tag_list_hint | translate }}</mat-hint>
        </mat-form-field>
        <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--mat-sys-outline-variant)] pt-3">
          <button mat-button (click)="preview('add')" [disabled]="values().length !== 1">{{ I18N.manual_tags.add_action | translate }}</button>
          <button mat-button (click)="preview('delete')" [disabled]="values().length !== 1">{{ I18N.manual_tags.remove_action | translate }}</button>
          <button mat-flat-button data-replace-tags (click)="preview('replace')" [disabled]="!values().length || values().length > 50">{{ I18N.manual_tags.batch.replace | translate }}</button>
          <button mat-button data-clear-tags (click)="preview('clear')">{{ I18N.manual_tags.batch.clear | translate }}</button>
        </div>
      }
      @if (failed()) {
        <p class="text-sm text-[var(--mat-sys-error)] mt-3" role="alert">{{ I18N.manual_tags.error | translate }}</p>
        @if (uncertain()) { <p class="text-xs">{{ (plan()?.action === 'replace' || plan()?.action === 'clear' ? I18N.manual_tags.batch.recheck : I18N.manual_tags.batch.uncertain) | translate }}</p> }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [disabled]="saving()" (click)="cancel()">{{ (failed() ? I18N.dialog.close : I18N.ui.buttons.cancel) | translate }}</button>
      @if (plan()) {
        @if (!failed() && !confirmed()) { <button mat-button [disabled]="saving()" (click)="edit()">{{ I18N.manual_tags.batch.edit | translate }}</button> }
        <button mat-flat-button data-apply-tags [disabled]="saving() || uncertain() && (plan()?.action === 'replace' || plan()?.action === 'clear')" (click)="apply()">{{ (saving() ? I18N.manual_tags.batch.saving : failed() ? I18N.manual_tags.batch.retry : I18N.ui.buttons.apply) | translate }}</button>
      }
    </mat-dialog-actions>
  `,
})
export class ManualTagsDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly owner = this.auth.identity();
  private readonly status = this.auth.status();
  private readonly token = this.auth.token;
  private readonly dialogRef = inject(MatDialogRef<ManualTagsDialogComponent>);
  private readonly input = inject<ManualTagsDialogData>(MAT_DIALOG_DATA);
  readonly data: ManualTagsDialogScope = structuredClone({
    paths: this.input.paths, fromWholeView: this.input.fromWholeView,
    count: this.input.count, observation: this.input.observation,
  });
  protected readonly targetNames = this.data.paths.slice(0, 3).map(path => path.split(/[\\/]/).pop() ?? path);
  readonly tag = signal('');
  protected readonly values = computed(() => [...new Set(this.tag().split(/\r?\n/).map(value => value.trim()).filter(Boolean))]);
  readonly saving = signal(false);
  readonly failed = signal(false);
  readonly uncertain = signal(false);
  readonly confirmed = signal(0);
  readonly completedBatches = signal(0);
  readonly plan = signal<ManualTagPlan | null>(null);
  private closing = false;
  private revoked = false;
  private lastSettlement: ManualTagsDialogResult | undefined;
  private readonly ownsDialog = computed(() => this.auth.identity() === this.owner && this.auth.isEdition()
    && this.auth.status() === this.status);

  constructor() {
    this.dialogRef.beforeClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.closing = true;
      this.revoked = true;
    });
    effect(() => {
      const sameOwner = this.auth.identity() === this.owner;
      const authorized = this.ownsDialog();
      const saving = this.saving();
      if (!authorized) this.revoked = true;
      if (!this.closing && (!sameOwner || this.revoked && !saving)) {
        this.dialogRef.close(sameOwner ? this.lastSettlement : undefined);
      }
    });
  }

  protected onInput(event: Event): void { this.tag.set((event.target as HTMLInputElement).value); }

  preview(action: ManualTagAction): void {
    const values = action === 'clear' ? [] : this.values();
    if (this.plan() || this.saving() || !this.live()
      || action !== 'clear' && (!values.length || values.length > 50)
      || (action === 'add' || action === 'delete') && values.length !== 1) return;
    const tag = values.join(' · ');
    const bodies = chunkPhotoPaths(this.data.paths).map(chunk => ({ photo_paths: chunk }));
    if (!bodies.length) return;
    this.plan.set({ action, tag, values: [...values], bodies: structuredClone(bodies) });
  }

  edit(): void {
    if (!this.saving() && !this.failed() && !this.confirmed()) this.plan.set(null);
  }

  cancel(): void {
    if (this.saving()) return;
    this.dialogRef.close(this.lastSettlement);
  }

  private live(): boolean { return !this.closing && !this.revoked && !this.destroyRef.destroyed && this.ownsDialog() && this.auth.token === this.token; }
  private receipt(incomplete: boolean): ManualTagsDialogResult | undefined {
    const plan = this.plan();
    return plan ? { confirmedCount: this.confirmed(), tag: plan.tag, action: plan.action, incomplete, uncertain: this.uncertain() } : undefined;
  }

  async apply(): Promise<void> {
    const plan = this.plan();
    if (!plan || this.saving() || !this.live() || this.uncertain() && (plan.action === 'replace' || plan.action === 'clear')) return;
    this.saving.set(true);
    this.failed.set(false);
    let complete = false;
    let attempted = false;
    const previousDisableClose = this.dialogRef.disableClose;
    this.dialogRef.disableClose = true;
    try {
      for (let index = this.completedBatches(); index < plan.bodies.length; index++) {
        if (!this.live()) return;
        attempted = true;
        const response = await firstValueFrom(this.api.post<{ count: number }>('/photos/batch_manual_tags', {
          ...plan.bodies[index], action: plan.action,
          ...(plan.action === 'replace' ? { tags: plan.values } : plan.action === 'clear' ? {} : { tag: plan.tag }),
        }));
        this.confirmed.update(count => count + response.count);
        this.completedBatches.set(index + 1);
      }
      complete = true;
    } catch (error) {
      this.failed.set(true);
      if (!(error instanceof HttpErrorResponse && error.status >= 400 && error.status < 500)) this.uncertain.set(true);
    } finally {
      const settlement = this.receipt(!complete);
      this.lastSettlement = settlement;
      this.saving.set(false);
      this.dialogRef.disableClose = this.confirmed() > 0 || this.uncertain() || previousDisableClose;
      // A request already sent can commit after close/rights loss. Its same-owner
      // repair is independent of whether this component still has a view.
      if (attempted && settlement && (settlement.confirmedCount || settlement.uncertain)) this.input.onSettled(settlement);
      if (complete && this.live()) this.dialogRef.close(settlement);
    }
  }
}
