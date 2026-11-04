import { randomUuid } from '../../shared/utils/random-uuid';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal, computed, DestroyRef, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { PersonOption } from '../gallery/gallery.store';
import { PersonSelectorDialogComponent } from '../gallery/person-selector-dialog.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import type { components } from '../../core/api/schema';
import { i18nKeys } from '../../core/i18n/keys';
import { AuthService } from '../../core/services/auth.service';
import { PersonAssignmentHistoryService } from '../../core/services/person-assignment-history.service';

export type FaceBox = [number, number, number, number];
export type ManualFaceRegion = components['schemas']['ManualFaceRegion'];
export type ManualFaceFrame = components['schemas']['ManualFaceFrame'];
export interface ManualFaceDialogData {
  path: string;
  filename: string;
  onCommitted: () => Promise<void>;
  /** Called after an object was marked or removed, so the photo page can redraw them. */
  onObjectsChanged?: () => void;
}
export type PhotoObject = components['schemas']['PhotoObject'];
export function dragBox(start: [number, number], end: [number, number]): FaceBox {
  const clamp = (value: number) => Math.max(0, Math.min(1, value));
  return [
    clamp(Math.min(start[0], end[0])),
    clamp(Math.min(start[1], end[1])),
    clamp(Math.max(start[0], end[0])),
    clamp(Math.max(start[1], end[1])),
  ];
}
@Component({
  selector: 'app-manual-face-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ I18N.manual_faces.title | translate }} — {{ data.filename }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-4">
      <div class="flex gap-2" role="group" [attr.aria-label]="I18N.manual_faces.mark_kind | translate">
        <button mat-stroked-button [attr.aria-pressed]="kind() === 'face'" [class.!bg-[var(--mat-sys-secondary-container)]]="kind() === 'face'"
          (click)="kind.set('face')" [disabled]="saving()">{{ I18N.manual_faces.kind_face | translate }}</button>
        <button mat-stroked-button [attr.aria-pressed]="kind() === 'object'" [class.!bg-[var(--mat-sys-secondary-container)]]="kind() === 'object'"
          (click)="kind.set('object')" [disabled]="saving()">{{ I18N.manual_faces.kind_object | translate }}</button>
      </div>
      <p>{{ (kind() === 'face' ? I18N.manual_faces.instructions : I18N.manual_faces.object_instructions) | translate }}</p>
      @if (loading()) {
        <p role="status">{{ I18N.ui.labels.loading | translate }}</p>
      }

      @if (frameUnavailable()) {
        <p role="status">{{ I18N.manual_faces.unavailable | translate }}</p>
      }

      @if (overlappingPersonBox()) {
        <p role="status">{{ I18N.manual_faces.same_person_overlap | translate }}</p>
      }
      @if (error()) {
        <p role="alert">{{ error() | translate }}</p>
      }

      <button mat-button (click)="reloadFrame()" [disabled]="saving() || loading()">
        {{ I18N.manual_faces.reload | translate }}
      </button>
      @if (frame()) {
        <div class="flex justify-center bg-black">
          <div
            class="relative inline-flex max-w-full touch-none select-none"
            (pointerdown)="startDraw($event)"
            (pointermove)="moveDraw($event)"
            (pointerup)="endDraw($event)"
            (pointercancel)="cancelDraw()"
          >
            <img
              [src]="imageUrl()"
              [alt]="I18N.manual_faces.preview | translate"
              draggable="false"
              class="block max-w-full max-h-[45vh] w-auto h-auto"
            />
            <div
              class="absolute pointer-events-none border-2 border-yellow-400 bg-yellow-400/15"
              [style.left.%]="bbox()[0] * 100"
              [style.top.%]="bbox()[1] * 100"
              [style.width.%]="(bbox()[2] - bbox()[0]) * 100"
              [style.height.%]="(bbox()[3] - bbox()[1]) * 100"
            ></div>
          </div>
        </div>
        <fieldset [disabled]="saving() || loading()" class="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <legend>{{ I18N.manual_faces.coordinates | translate }}</legend>
          @for (label of coordinateLabels; track $index; let index = $index) {
            <label class="flex flex-col gap-1"
              >{{ label | translate }}
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                [ngModel]="percentages()[index]"
                (ngModelChange)="setCoordinate(index, $event)"
                class="border rounded p-2 w-full bg-transparent"
              />
            </label>
          }
        </fieldset>
        @if (kind() === 'face') {
          <button mat-button (click)="choosePerson()" [disabled]="saving()">
            {{ personLabel() || (I18N.manual_faces.choose_person | translate) }}
          </button>
          @if (needsRemark()) {
            <p role="status">{{ I18N.manual_faces.remark | translate }}</p>
          }
        } @else {
          <label class="flex flex-col gap-1">{{ I18N.manual_faces.object_label | translate }}
            <input type="text" maxlength="64" [ngModel]="objectLabel()" (ngModelChange)="objectLabel.set($event)"
              [placeholder]="I18N.manual_faces.object_placeholder | translate"
              class="border rounded p-2 w-full bg-transparent" [disabled]="saving()" />
          </label>
        }

        <div class="flex flex-wrap gap-2">
          @if (kind() === 'face') {
            <button mat-flat-button (click)="save()" [disabled]="!valid() || saving()">
              {{ I18N.ui.buttons.save | translate }}
            </button>
          } @else {
            <button mat-flat-button (click)="saveObject()" [disabled]="!objectValid() || saving()">
              {{ I18N.ui.buttons.save | translate }}
            </button>
          }
          <button mat-button (click)="newRegion()" [disabled]="saving()">
            {{ I18N.manual_faces.add | translate }}
          </button>
        </div>
      }

      <h3>{{ I18N.manual_faces.saved | translate }}</h3>
      @if (listFailed()) {
        <p role="alert">{{ I18N.errors.action_failed | translate }}</p>
      }
      @for (region of regions(); track region.id) {
        <div class="flex items-center flex-wrap gap-2 border-t pt-2">
          <span class="flex-1">{{
            region.person_name || (I18N.manual_faces.unnamed | translate)
          }}</span>
          @if (region.source_changed) {
            <span>{{ I18N.manual_faces.needs_review | translate }}</span>
          }

          <button mat-button (click)="edit(region)" [disabled]="!frame() || saving()">
            {{ I18N.manual_faces.edit | translate }}
          </button>
          <button mat-button (click)="remove(region)" [disabled]="saving() || loading()">
            {{ I18N.manual_faces.remove | translate }}
          </button>
        </div>
      } @empty {
        @if (listLoaded() && !listFailed()) {
          <p>{{ I18N.manual_faces.empty | translate }}</p>
        }
      }

      <h3>{{ I18N.manual_faces.objects | translate }}</h3>
      @for (o of objects(); track o.id) {
        <div class="flex items-center flex-wrap gap-2 border-t pt-2">
          <span class="flex-1">{{ o.label }}</span>
          <button mat-button (click)="removeObject(o)" [disabled]="saving()">
            {{ I18N.manual_faces.remove | translate }}
          </button>
        </div>
      } @empty {
        <p>{{ I18N.manual_faces.objects_empty | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end"
      ><button mat-button mat-dialog-close>
        {{ I18N.manual_faces.close | translate }}
      </button></mat-dialog-actions
    >
  `,
})
export class ManualFaceDialogComponent implements OnInit {
  readonly data: ManualFaceDialogData = inject(MAT_DIALOG_DATA);
  readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly owner = this.auth.identity();
  private readonly assignmentHistory = inject(PersonAssignmentHistoryService);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);
  readonly frame = signal<ManualFaceFrame | null>(null);
  /** What the drawn box marks: a face (with a person) or an object (with a label). */
  readonly kind = signal<'face' | 'object'>('face');
  readonly objectLabel = signal('');
  readonly objects = signal<PhotoObject[]>([]);
  readonly bbox = signal<FaceBox>([0, 0, 0, 0]);
  readonly person = signal<{
    person_id?: number;
    new_person_name?: string;
  } | null>(null);
  readonly personLabel = signal('');
  readonly regions = signal<ManualFaceRegion[]>([]);
  readonly loading = signal(false);
  readonly listFailed = signal(false);
  readonly listLoaded = signal(false);
  private readonly emptyCoordinates = signal<ReadonlySet<number>>(new Set());
  readonly percentages = computed(() =>
    this.bbox().map((value, index) =>
      this.emptyCoordinates().has(index) ? null : Math.round(value * 1e6) / 1e4,
    ),
  );
  private readonly reviewRegionIds = new Set<number>();
  readonly frameUnavailable = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');
  readonly editingId = signal<number | null>(null);
  readonly needsRemark = signal(false);
  readonly imageUrl = computed(() =>
    this.frame() ? 'data:image/jpeg;base64,' + this.frame()!.image_base64 : '',
  );
  readonly coordinateLabels = [
    this.I18N.manual_faces.left,
    this.I18N.manual_faces.top,
    this.I18N.manual_faces.right,
    this.I18N.manual_faces.bottom,
  ];
  readonly overlappingPersonBox = computed(() => {
    const personId = this.person()?.person_id;
    if (personId == null) return false;
    const [left, top, right, bottom] = this.bbox();
    if (right <= left || bottom <= top) return false;
    return this.regions().some(region => {
      if (region.id === this.editingId() || region.person_id !== personId || region.source_changed) return false;
      const [x1, y1, x2, y2] = region.bbox;
      return Math.min(right, x2) > Math.max(left, x1) && Math.min(bottom, y2) > Math.max(top, y1);
    });
  });

  readonly valid = computed(() => {
    const f = this.frame(),
      b = this.bbox(),
      p = this.person();
    const validPerson =
      p?.person_id !== undefined ||
      (!!p?.new_person_name?.trim() && p.new_person_name.trim().length <= 120);
    return (
      !!f &&
      validPerson &&
      !this.loading() &&
      this.emptyCoordinates().size === 0 &&
      !this.needsRemark() &&
      b.every(Number.isFinite) &&
      b[0] >= 0 &&
      b[1] >= 0 &&
      b[2] <= 1 &&
      b[3] <= 1 &&
      (b[2] - b[0]) * f.width >= 4 - 1e-9 &&
      (b[3] - b[1]) * f.height >= 4 - 1e-9
    );
  });
  readonly objectValid = computed(() => {
    const b = this.bbox();
    return (
      !!this.frame() &&
      !this.loading() &&
      !!this.objectLabel().trim() &&
      this.emptyCoordinates().size === 0 &&
      b.every(Number.isFinite) &&
      b[2] - b[0] >= 0.005 &&
      b[3] - b[1] >= 0.005
    );
  });
  private drag: {
    pointerId: number;
    start: [number, number];
  } | null = null;
  private attempt: {
    signature: string;
    clientId: string;
  } | null = null;
  ngOnInit(): void {
    void this.load();
  }

  async reloadFrame(): Promise<void> {
    if (this.saving() || this.loading()) return;
    this.loading.set(true);
    await Promise.all([this.fetchFrame(), this.fetchRegions()]);
    if (!this.destroyRef.destroyed) {
      // Both reads must settle before marking cached rows: the list can arrive last.
      this.regions().forEach((region) => this.reviewRegionIds.add(region.id));
      if (this.bbox().some((value) => value !== 0)) this.needsRemark.set(true);
      this.loading.set(false);
    }
  }

  private async fetchFrame(): Promise<void> {
    try {
      const result = await firstValueFrom(
        this.api.get<ManualFaceFrame>('/photo/manual-face-frame', { path: this.data.path }),
      );
      if (!this.destroyRef.destroyed) {
        this.frame.set(result);
        this.frameUnavailable.set(false);
        this.error.set('');
      }
    } catch {
      if (!this.destroyRef.destroyed) {
        this.frame.set(null);
        this.frameUnavailable.set(true);
      }
    }
  }

  async load(): Promise<void> {
    this.loading.set(true);
    await Promise.all([this.fetchRegions(), this.fetchFrame(), this.fetchObjects()]);
    if (!this.destroyRef.destroyed) this.loading.set(false);
  }

  private async fetchObjects(): Promise<void> {
    try {
      const result = await firstValueFrom(
        this.api.get<components['schemas']['PhotoObjectsResponse']>('/photo/objects', { path: this.data.path }),
      );
      if (!this.destroyRef.destroyed) this.objects.set(result.objects);
    } catch {
      // The face editor works without the object list; it stays empty.
    }
  }

  async saveObject(): Promise<void> {
    if (!this.objectValid() || this.saving() || this.auth.identity() !== this.owner) return;
    this.saving.set(true);
    this.error.set('');
    try {
      const created = await firstValueFrom(this.api.post<PhotoObject>('/photo/objects', {
        path: this.data.path, label: this.objectLabel().trim(), box: [...this.bbox()],
      }));
      if (!this.destroyRef.destroyed) {
        this.objects.update((list) => [...list, created]);
        this.objectLabel.set('');
        this.bbox.set([0, 0, 0, 0]);
      }
      this.data.onObjectsChanged?.();
    } catch {
      if (!this.destroyRef.destroyed) this.error.set(this.I18N.manual_faces.save_failed);
    } finally {
      if (!this.destroyRef.destroyed) this.saving.set(false);
    }
  }

  private isCurrentEditor(): boolean {
    return !this.destroyRef.destroyed && this.auth.identity() === this.owner;
  }

  async removeObject(object: PhotoObject): Promise<void> {
    if (this.saving() || !this.isCurrentEditor()) return;
    this.saving.set(true);
    this.error.set('');
    try {
      await firstValueFrom(this.api.delete('/photo/objects/' + object.id));
      if (this.auth.identity() !== this.owner) return;
      if (!this.destroyRef.destroyed) this.objects.update((list) => list.filter((o) => o.id !== object.id));
      this.data.onObjectsChanged?.();
    } catch {
      if (this.isCurrentEditor()) this.error.set(this.I18N.errors.action_failed);
    } finally {
      if (this.isCurrentEditor()) this.saving.set(false);
    }
  }

  private async fetchRegions(): Promise<void> {
    try {
      const result = await firstValueFrom(
        this.api.get<components['schemas']['ManualFacesResponse']>('/photo/manual-faces', {
          path: this.data.path,
        }),
      );
      if (!this.destroyRef.destroyed) {
        this.regions.set(result.regions);
        this.listLoaded.set(true);
        this.listFailed.set(false);
      }
    } catch {
      if (!this.destroyRef.destroyed) {
        this.listLoaded.set(false);
        this.listFailed.set(true);
      }
    }
  }

  setCoordinate(index: number, percentage: number | null): void {
    if (this.saving()) return;
    const empty = new Set(this.emptyCoordinates());
    if (percentage === null || !Number.isFinite(percentage)) {
      empty.add(index);
      this.emptyCoordinates.set(empty);
      return;
    }
    empty.delete(index);
    this.emptyCoordinates.set(empty);
    const next: FaceBox = [...this.bbox()];
    next[index] = Math.max(0, Math.min(100, Number(percentage))) / 100;
    this.bbox.set(next);
    this.needsRemark.set(false);
  }

  private point(event: PointerEvent): [number, number] {
    const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
    return [
      (event.clientX - bounds.left) / bounds.width,
      (event.clientY - bounds.top) / bounds.height,
    ];
  }

  startDraw(event: PointerEvent): void {
    if (this.saving() || this.loading() || event.button !== 0) return;
    event.preventDefault();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    this.drag = { pointerId: event.pointerId, start: this.point(event) };
    this.moveDraw(event);
  }

  moveDraw(event: PointerEvent): void {
    if (!this.drag || this.drag.pointerId !== event.pointerId) return;
    this.bbox.set(dragBox(this.drag.start, this.point(event)));
    this.emptyCoordinates.set(new Set());
    this.needsRemark.set(false);
  }

  endDraw(event: PointerEvent): void {
    this.moveDraw(event);
    this.drag = null;
  }

  cancelDraw(): void {
    this.drag = null;
  }

  async choosePerson(): Promise<void> {
    const result = (await firstValueFrom(
      this.dialog
        .open(PersonSelectorDialogComponent, {
          width: '420px',
        })
        .afterClosed(),
    )) as
      | {
          kind: 'select';
          person: PersonOption;
        }
      | {
          kind: 'create';
          name: string;
        }
      | null;
    if (!result || this.destroyRef.destroyed || this.auth.identity() !== this.owner) return;
    this.person.set(
      result.kind === 'select' ? { person_id: result.person.id } : { new_person_name: result.name },
    );
    this.personLabel.set(result.kind === 'select' ? (result.person.name ?? '') : result.name);
  }

  newRegion(): void {
    this.emptyCoordinates.set(new Set());
    this.editingId.set(null);
    this.bbox.set([0, 0, 0, 0]);
    this.person.set(null);
    this.personLabel.set('');
    this.needsRemark.set(false);
    this.error.set('');
    this.attempt = null;
  }

  edit(region: ManualFaceRegion): void {
    this.emptyCoordinates.set(new Set());
    this.editingId.set(region.id);
    this.bbox.set([...region.bbox]);
    this.person.set(region.person_id === null ? null : { person_id: region.person_id });
    this.personLabel.set(region.person_name ?? '');
    this.needsRemark.set(region.source_changed || this.reviewRegionIds.has(region.id));
    this.error.set('');
    this.attempt = null;
  }

  async save(): Promise<void> {
    if (!this.valid() || this.saving() || this.auth.identity() !== this.owner) return;
    const owner = this.auth.identity();
    const id = this.editingId();
    const body: components['schemas']['ManualFaceWrite'] = {
      path: this.data.path,
      frame_token: this.frame()!.frame_token,
      bbox: [...this.bbox()] as FaceBox,
      ...this.person()!,
    };
    // A refreshed token still represents the same create intent after a lost response.
    const signature = JSON.stringify({ path: body.path, bbox: body.bbox, ...this.person()! });
    if (!this.attempt || this.attempt.signature !== signature)
      this.attempt = { signature, clientId: randomUuid() };
    const request =
      id === null
        ? this.api.post<ManualFaceRegion>('/photo/manual-faces', {
            ...body,
            client_id: this.attempt.clientId,
          })
        : this.api.put<ManualFaceRegion>('/photo/manual-faces/' + id, body);
    this.saving.set(true);
    this.error.set('');
    try {
      const actual = await firstValueFrom(request);
      if (actual.person_id != null) this.assignmentHistory.record(actual.person_id, owner);
      if (this.auth.identity() !== owner) return;
      if (!this.destroyRef.destroyed) {
        this.reviewRegionIds.delete(actual.id);
        this.regions.update((list) => [...list.filter((row) => row.id !== actual.id), actual]);
        this.newRegion();
      }

      await this.refreshMembership();
    } catch (error) {
      if (!this.destroyRef.destroyed) {
        const detectedOverlap =
          error instanceof HttpErrorResponse &&
          error.status === 409 &&
          error.error?.detail?.code === 'detected_face_overlap';
        this.error.set(
          detectedOverlap
            ? this.I18N.manual_faces.detected_overlap
            : this.I18N.manual_faces.save_failed,
        );
      }
    } finally {
      if (!this.destroyRef.destroyed) this.saving.set(false);
    }
  }
  private async refreshMembership(): Promise<void> {
    try {
      await this.data.onCommitted();
    } catch {
      if (!this.destroyRef.destroyed) this.error.set(this.I18N.manual_faces.refresh_failed);
    }
  }
  async remove(region: ManualFaceRegion): Promise<void> {
    if (this.saving() || this.loading() || !this.isCurrentEditor()) return;
    this.saving.set(true);
    this.error.set('');
    try {
      await firstValueFrom(
        this.api.delete(
          '/photo/manual-faces/' + region.id + '?path=' + encodeURIComponent(this.data.path),
        ),
      );
      if (this.auth.identity() !== this.owner) return;
      if (!this.destroyRef.destroyed) {
        this.regions.update((list) => list.filter((row) => row.id !== region.id));
        if (this.editingId() === region.id) this.newRegion();
      }

      await this.refreshMembership();
    } catch {
      if (this.isCurrentEditor()) this.error.set(this.I18N.errors.action_failed);
    } finally {
      if (this.isCurrentEditor()) this.saving.set(false);
    }
  }
}
