import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import {
  buildFolderBreadcrumbs,
  folderDisplayName,
  type FolderItem,
  type FoldersResponse,
} from '../folders/folders.util';

export interface FolderPickerData {
  path_prefix?: string;
}

@Component({
  selector: 'app-folder-picker-dialog',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title>{{ 'gallery.choose_folder' | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-2 min-w-[320px]">
      <nav class="flex items-center gap-1 text-sm flex-wrap">
        <button mat-button class="!min-w-0 !px-2" (click)="navigateTo('')">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">home</mat-icon>
          {{ 'folders.root' | translate }}
        </button>
        @for (crumb of breadcrumbs(); track crumb.path) {
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          @if (!$last) {
            <button mat-button class="!min-w-0 !px-2" (click)="navigateTo(crumb.path)">{{ crumb.name }}</button>
          } @else {
            <span class="px-2 font-medium">{{ crumb.name }}</span>
          }
        }
      </nav>

      <div class="flex items-center gap-2 rounded-lg bg-[var(--mat-sys-surface-container-high)] px-3 py-2">
        <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60">filter_alt</mat-icon>
        <span class="text-xs opacity-70">{{ 'gallery.use_this_folder' | translate }}</span>
        <span class="text-sm font-medium truncate">
          @if (prefix()) {
            {{ currentName() }}
          } @else {
            {{ 'gallery.all_folders' | translate }}
          }
        </span>
      </div>

      @if (children().length > 1) {
        <mat-form-field subscriptSizing="dynamic" class="w-full">
          <mat-icon matPrefix class="mr-1 opacity-60">search</mat-icon>
          <input matInput
                 [placeholder]="'folders.find_folder' | translate"
                 [attr.aria-label]="'folders.find_folder' | translate"
                 [value]="query()"
                 (input)="query.set($any($event.target).value)" />
        </mat-form-field>
      }

      @if (loading()) {
        <div class="flex justify-center py-8">
          <mat-spinner diameter="32" />
        </div>
      } @else if (loadError()) {
        <div class="flex flex-col items-center gap-2 px-1 py-6">
          <p class="text-xs opacity-70 text-center">{{ 'folders.load_error.message' | translate }}</p>
          <button mat-stroked-button (click)="retry()">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">refresh</mat-icon>
            {{ 'gallery.load_error.retry' | translate }}
          </button>
        </div>
      } @else if (!filteredChildren().length) {
        <p class="text-xs opacity-50 px-1 py-6 text-center">{{ 'folders.empty' | translate }}</p>
      } @else {
        <div class="flex flex-col gap-1 max-h-[360px] overflow-y-auto">
          @for (folder of filteredChildren(); track folder.path) {
            <button
              class="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-[var(--mat-sys-surface-container-high)] transition-colors text-left w-full cursor-pointer"
              (click)="navigateTo(folder.path)"
            >
              <mat-icon class="!text-base !w-5 !h-5 !leading-5 opacity-60 shrink-0">folder</mat-icon>
              <span class="text-sm truncate flex-1">{{ folder.name }}</span>
              <span class="text-xs opacity-60 shrink-0">{{ folder.photo_count | number }}</span>
              <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40 shrink-0">chevron_right</mat-icon>
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'ui.buttons.cancel' | translate }}</button>
      <button mat-flat-button (click)="dialogRef.close(prefix())">{{ 'ui.buttons.apply' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class FolderPickerDialogComponent {
  private readonly api = inject(ApiService);
  readonly dialogRef = inject(MatDialogRef<FolderPickerDialogComponent>);
  private readonly data: FolderPickerData = inject(MAT_DIALOG_DATA, { optional: true }) ?? {};

  readonly prefix = signal(this.data.path_prefix ?? '');
  readonly children = signal<FolderItem[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal(false);
  readonly query = signal('');

  protected readonly breadcrumbs = computed(() => buildFolderBreadcrumbs(this.prefix()));
  protected readonly currentName = computed(() => folderDisplayName(this.prefix()));
  readonly filteredChildren = computed(() => {
    const query = this.query().toLowerCase().trim();
    const all = this.children();
    return query ? all.filter(f => f.name.toLowerCase().includes(query)) : all;
  });

  private readonly levelCache = new Map<string, FolderItem[]>();
  private loadSeq = 0;

  constructor() {
    void this.navigateTo(this.prefix());
  }

  async navigateTo(prefix: string): Promise<void> {
    const seq = ++this.loadSeq;
    this.prefix.set(prefix);
    this.query.set('');
    this.loadError.set(false);

    const cached = this.levelCache.get(prefix);
    if (cached) {
      this.children.set(cached);
      this.loading.set(false);
      return;
    }

    this.loading.set(true);
    try {
      const res = await firstValueFrom(this.api.get<FoldersResponse>('/folders', { prefix }));
      if (seq !== this.loadSeq) return;
      this.levelCache.set(prefix, res.folders);
      this.children.set(res.folders);
    } catch {
      // The endpoint reports its own failures as an empty list, so only transport errors land here.
      if (seq !== this.loadSeq) return;
      this.children.set([]);
      this.loadError.set(true);
    } finally {
      if (seq === this.loadSeq) this.loading.set(false);
    }
  }

  retry(): void {
    void this.navigateTo(this.prefix());
  }
}
