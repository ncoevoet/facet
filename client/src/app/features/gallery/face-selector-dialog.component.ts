import { Component, inject, signal, OnInit } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

interface PhotoFace {
  id: number;
  face_index: number;
  person_id: number | null;
  person_name: string | null;
}

@Component({
  selector: 'app-face-selector-dialog',
  imports: [
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    FaceThumbnailUrlPipe,
    TranslatePipe,
  ],
  template: `
    <h2 mat-dialog-title class="truncate" [matTooltip]="'manage_persons.select_face' | translate">{{ 'manage_persons.select_face' | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px] min-h-[120px]">
      @if (loading()) {
        <div class="flex items-center justify-center gap-3 py-8">
          <mat-spinner diameter="24"></mat-spinner>
        </div>
      } @else {
        <div class="flex flex-wrap gap-2 justify-center">
          @for (face of unassignedFaces(); track face.id) {
            <button
              class="relative rounded-full overflow-hidden border-2 border-transparent hover:border-[var(--mat-sys-primary)] transition-colors"
              (click)="dialogRef.close(face)">
              <img [src]="face.id | faceThumbnailUrl"
                   alt=""
                   class="w-28 h-28 object-cover" />
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="dialogRef.close(null)">{{ 'dialog.cancel' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class FaceSelectorDialogComponent implements OnInit {
  private api = inject(ApiService);
  readonly data: { photoPath: string } = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<FaceSelectorDialogComponent>);

  readonly loading = signal(true);
  readonly unassignedFaces = signal<PhotoFace[]>([]);

  async ngOnInit(): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ faces: PhotoFace[] }>('/photo/faces', { path: this.data.photoPath }),
      );
      this.unassignedFaces.set((res.faces ?? []).filter(f => !f.person_id));
    } catch { /* ignore */ }
    this.loading.set(false);
  }
}
