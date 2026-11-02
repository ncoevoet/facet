import { DestroyRef, Injector, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { AlbumService, Album } from '../../core/services/album.service';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { SequenceOverrideService, SequenceKind } from '../../core/services/sequence-override.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { Photo } from '../../shared/models/photo.model';
import { SEQUENCE_KINDS_KEPT_WHOLE } from '../../shared/pipes/sequence-kind.pipe';
import { basename, copyLines } from '../../shared/utils/clipboard';
import { downloadAll } from '../../shared/utils/download';
import { isBracketLadderRejection } from '../../shared/utils/sequence-ladder';
import { CreateAlbumDialogComponent } from '../albums/create-album-dialog.component';
import { ExportEditorDialogComponent } from './export-editor-dialog.component';
import { GalleryStore, BatchResult } from './gallery.store';
import { observeManualTags } from './manual-tag-observation.util';
import type { ManualTagsDialogData, ManualTagsDialogResult } from './manual-tags-dialog.component';

/** The view owns parking, focus restoration and its album menu. */
export interface GallerySelectionHost {
  isActive(): boolean;
  clearSelection(): void;
  albumAdded(album: Album): void;
}

/**
 * Captures selection targets and coordinates their commands, confirmations and Undo.
 * Constructed once in the gallery's injection context: guards and effects retain
 * the gallery lifetime, including its parked visits. It is never a root singleton.
 */
export class GallerySelectionActions {
  private readonly I18N = i18nKeys();
  private readonly store = inject(GalleryStore);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly albumService = inject(AlbumService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly journal = inject(UserActivityJournal);
  private readonly photoActions = inject(PhotoActionsService);
  private readonly undoService = inject(UndoService);
  private readonly sequenceOverrides = inject(SequenceOverrideService);
  private readonly staleness = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly selectedPaths = this.store.selectedPaths;
  private readonly excludedPaths = this.store.excludedPaths;
  private readonly viewScoped = this.store.viewScopeSelected;
  private readonly selectionCount = this.store.selectionCount;
  readonly downloading = signal(false);

  constructor(private readonly host: GallerySelectionHost) {}

  private async resolveSelectionPaths(
    confirmMessageKey: string | null = I18N.gallery.selection.view_scope_confirm_message,
  ): Promise<string[] | null> {
    const target = this.captureSelectionContext();
    const guard = this.staleness.create(this.destroyRef, { track: 'status', requireEdition: false, valid: target.current });
    try {
      if (!guard.current()) return null;
      if (!target.viewScoped) return target.paths;
      if (confirmMessageKey !== null && await this.confirmWholeView(confirmMessageKey) === null) {
        return null;
      }
      if (!guard.current()) return null;
      const paths = await this.store.pathsInView();
      return guard.current() ? paths : null;
    } finally { guard.dispose(); }
  }

  async copyPaths(explicitPaths?: string[]): Promise<void> {
    // Copying changes nothing, so it says so rather than borrowing the
    // mutation wording every other whole-view action confirms with.
    const paths = explicitPaths
      ?? await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_copy_message);
    if (!paths?.length) return;
    await copyLines(paths.map(basename));
    this.snackBar.open(this.i18n.t(I18N.gallery.selection.copied), '', { duration: 2000 });
  }

  /** Above this size, undo (chunked per-photo inverse calls) is not offered. */
  private static readonly UNDO_MAX_PHOTOS = 500;

  /** Above this many photos a download is confirmed first: it is one blob fetch
   *  plus one synthetic anchor click per photo, and a whole-view selection (or
   *  a "Keep top N%" one) turns that into thousands. */
  private static readonly DOWNLOAD_CONFIRM_PHOTOS = 50;

  /** The server caps a sequence correction at 500 frames, and a set is a
   *  handful of frames one camera shot together — so it is never "the view". */
  private static readonly MARK_SEQUENCE_MAX_PHOTOS = 500;

  /**
   * Ask before a mutation runs over the whole filtered view.
   *
   * The count comes from the server rather than from `total()`, which is only
   * ever whichever page response landed last. Returns the number shown to the
   * user, or null if they declined (or it could not be fetched) — the caller
   * checks the server's own count against it afterwards.
   *
   * `messageKey` names what the action will actually do to those photos; the
   * default states a mutation, which is what every batch write is.
   */
  private async confirmWholeView(
    messageKey: string = I18N.gallery.selection.view_scope_confirm_message,
  ): Promise<number | null> {
    const target = this.captureSelectionContext();
    const guard = this.staleness.create(this.destroyRef, { track: 'status', requireEdition: false, valid: target.current });
    try {
      if (!guard.current()) return null;
      const total = await this.store.countInView();
      if (total === null || !guard.current()) return null;
      const count = Math.max(0, total - target.excluded.size);
      if (count === 0) {
        this.snackBar.open(this.i18n.t(I18N.gallery.selection.view_scope_empty), '', { duration: 3000 });
        return null;
      }
      const ref = this.dialog.open(ConfirmDialogComponent, {
        data: {
          title: this.i18n.t(I18N.gallery.selection.view_scope_confirm_title),
          message: this.i18n.t(messageKey, { count }),
        },
      });
      const confirmed = await firstValueFrom(ref.afterClosed());
      return confirmed && guard.current() ? count : null;
    } finally { guard.dispose(); }
  }

  /** Captures command membership independently of hover and later selection changes. */
  private captureSelectionContext() {
    const paths = new Set(this.selectedPaths());
    const excluded = new Set(this.excludedPaths());
    const viewScoped = this.viewScoped();
    const query = viewScoped ? JSON.stringify(this.store.filterPayload()) : null;
    const current = () => this.host.isActive() && !this.router.currentNavigation?.() && this.viewScoped() === viewScoped && (viewScoped
      ? JSON.stringify(this.store.filterPayload()) === query && this.excludedPaths().size === excluded.size && [...excluded].every(path => this.excludedPaths().has(path))
      : this.selectedPaths().size === paths.size && [...paths].every(path => this.selectedPaths().has(path)));
    return { paths: [...paths], excluded, viewScoped, current };
  }

  private async executeBatchAction(
    action: (paths: string[]) => Promise<BatchResult | null>,
    i18nKey: string,
    extraParams?: Record<string, string | number>,
  ): Promise<void> {
    const target = this.captureSelectionContext();
    const guard = this.staleness.create(this.destroyRef, { track: 'status' });
    try {
      if (!guard.current()) return;
      let announced: number | null = null;
      if (target.viewScoped) {
        announced = await this.confirmWholeView();
        if (announced === null) return;
      }
      if (!guard.current() || !target.current()) return;
      const result = await action(target.paths);
      if (result === null || !guard.current()) return; // store owns confirmed-write repair
      if (target.current()) this.host.clearSelection();
      const params = { count: result.count, ...extraParams };
      this.offerMutationUndo(result, i18nKey, params);
      // The view can move between the count and the write (another session, a
      // scan). Say so rather than absorbing it: the user approved a number.
      if (announced !== null && announced !== result.count) {
        this.snackBar.open(
          this.i18n.t(I18N.gallery.selection.view_scope_mismatch, { count: result.count, announced }),
          '', { duration: 5000 },
        );
      }
    } finally { guard.dispose(); }
  }

  private offerMutationUndo(
    result: BatchResult,
    i18nKey: string,
    params: Record<string, string | number>,
    restoreSelection = true,
  ): void {
    // Undo replays inverse calls from a snapshot, and the snapshot can only
    // cover LOADED photos -- so offering it for an action that reached further
    // would promise to restore 64 of 5,000. Gate on coverage, not just size.
    const covered = result.snapshot.size === result.targeted;
    if (covered && result.snapshot.size > 0 && result.snapshot.size <= GallerySelectionActions.UNDO_MAX_PHOTOS) {
      this.undoService.register({
        labelKey: i18nKey,
        labelParams: params,
        undo: async () => {
          await this.store.restoreSnapshot(result.snapshot);
          // The snapshot's keys, not `paths`: they are the same set whenever
          // undo is offered at all (that is what `covered` asserts), and they
          // are the only ones a view-scoped action ever named.
          if (restoreSelection) this.store.restoreSelection(result.snapshot.keys());
        },
      });
    } else {
      this.snackBar.open(this.i18n.t(i18nKey, params), '', { duration: 2000 });
    }
  }

  async reviewSingle(path: string, decision: 'kept' | 'undecided'): Promise<BatchResult | null> {
    const result = await this.store.batchReview([path], decision, false);
    if (result) this.offerMutationUndo(result, this.I18N.review.updated, { count: result.count }, false);
    return result;
  }

  async batchReview(decision: 'kept' | 'undecided'): Promise<void> {
    await this.executeBatchAction(p => this.store.batchReview(p, decision), this.I18N.review.updated);
  }

  async batchFavorite(): Promise<void> {
    await this.executeBatchAction(p => this.store.batchFavorite(p), 'gallery.selection.batch_favorited');
  }

  async batchReject(): Promise<void> {
    await this.executeBatchAction(p => this.store.batchReject(p), 'gallery.selection.batch_rejected');
  }

  async batchRate(rating: number): Promise<void> {
    if (!Number.isInteger(rating) || rating < 0 || rating > 5) return;
    const target = this.captureSelectionContext();
    const token = this.auth.token;
    let closePreview = () => {};
    const guard = this.staleness.create(this.destroyRef, { track: 'status', onNavigate: () => closePreview() });
    try {
      if (!guard.current()) return;
      const paths = await this.resolveSelectionPaths(null);
      if (!paths?.length || !guard.current() || !target.current() || this.auth.token !== token) return;
      const selected = new Set(paths);
      const observed = new Map<number, number>();
      let loaded = 0;
      for (const photo of this.store.photos()) {
        if (!selected.has(photo.path)) continue;
        if (!Object.hasOwn(photo, 'star_rating') || photo.star_rating === undefined) continue;
        const value = photo.star_rating ?? 0;
        if (!Number.isInteger(value) || value < 0 || value > 5) continue;
        loaded++;
        observed.set(value, (observed.get(value) ?? 0) + 1);
      }
      const { BatchRatingDialogComponent } = await import('./batch-rating-dialog.component');
      if (!guard.current() || !target.current() || this.auth.token !== token) return;
      const ref = this.dialog.open(BatchRatingDialogComponent, { width: '95vw', maxWidth: '540px', data: {
        paths, rating, loaded, wholeView: target.viewScoped, observed: [...observed].map(([rating, count]) => ({ rating, count })),
      } });
      closePreview = () => ref.close();
      const watch = effect(() => {
        if (!guard.current() || this.auth.token !== token) ref.close();
      }, { injector: this.injector });
      let chosen: number | undefined;
      try { chosen = await firstValueFrom(ref.afterClosed()); }
      finally { watch.destroy(); }
      if (chosen === undefined || !Number.isInteger(chosen) || chosen < 0 || chosen > 5 || !guard.current() || this.auth.token !== token) return;
      const result = await this.store.batchRatingPaths(paths, chosen);
      if (!result || !guard.current()) return;
      if (target.current()) this.host.clearSelection();
      const params = { count: result.count, rating: chosen };
      if (loaded === paths.length && result.snapshot.size === result.targeted && result.targeted > 0 && result.targeted <= GallerySelectionActions.UNDO_MAX_PHOTOS) {
        this.undoService.register({ labelKey: 'gallery.selection.batch_rated', labelParams: params, undo: async () => {
          if (await this.store.restoreRatingSnapshot(result.snapshot, chosen)) this.store.restoreSelection(result.snapshot.keys());
        } });
      } else this.snackBar.open(this.i18n.t(I18N.gallery.selection.batch_rated, params), '', { duration: 3000 });
    } finally { guard.dispose(); }
  }

  /**
   * Declare the selected frames one panorama the detector missed.
   *
   * Not routed through `executeBatchAction`: that undoes by restoring a photo's
   * favorite/reject/rating snapshot, and nothing here touches those — the
   * inverse of a correction is dropping it, which is its own endpoint. Two
   * frames is the floor because one frame is not a set.
   */
  async markAsPanorama(kind: SequenceKind): Promise<void> {
    // Unlike the flag mutations, this one keeps its path list: the server caps
    // the correction at MARK_SEQUENCE_MAX_PHOTOS frames and there is no
    // filter-scoped form, because declaring a whole view to be one panorama is
    // not a thing anyone means.
    if (this.viewScoped()) {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.mark_needs_paths), '', { duration: 4000 });
      return;
    }
    const paths = [...this.selectedPaths()];
    if (paths.length < 2) {
      this.snackBar.open(this.i18n.t(I18N.gallery.selection.mark_needs_two), '', { duration: 3000 });
      return;
    }
    if (paths.length > GallerySelectionActions.MARK_SEQUENCE_MAX_PHOTOS) {
      this.snackBar.open(
        this.i18n.t(I18N.gallery.selection.mark_too_many,
                    { count: paths.length, max: GallerySelectionActions.MARK_SEQUENCE_MAX_PHOTOS }),
        '', { duration: 4000 },
      );
      return;
    }
    try {
      await this.sequenceOverrides.setAsync(paths, kind);
    } catch (error) {
      const notALadder = isBracketLadderRejection(kind, error);
      this.snackBar.open(
        this.i18n.t(notALadder ? I18N.culling.bracket.not_a_ladder : I18N.errors.action_failed),
        '', { duration: 3000 },
      );
      return;
    }
    this.store.patchSequenceOverride(paths, kind);
    this.host.clearSelection();
    this.undoService.register({
      labelKey: kind === 'bracket' ? I18N.gallery.selection.marked_bracket : I18N.gallery.selection.marked_panorama,
      labelParams: { count: paths.length },
      undo: async () => {
        await this.sequenceOverrides.clearAsync(paths);
        this.store.patchSequenceOverride(paths, null);
        this.store.restoreSelection(paths);
      },
    });
  }

  async downloadSelected(type = 'original', profile?: string, explicitPaths?: string[]): Promise<void> {
    // Confirms below in its own words, against the count it actually resolved.
    const paths = explicitPaths ?? await this.resolveSelectionPaths(null);
    if (!paths?.length) return;
    // One blob fetch and one synthetic anchor click per photo, serially: past a
    // few dozen that is a browser-melting amount of work to start by accident,
    // and both "Keep top N%" and a whole-view selection reach thousands.
    if (paths.length > GallerySelectionActions.DOWNLOAD_CONFIRM_PHOTOS && !await this.confirmDownload(paths.length)) {
      return;
    }
    this.downloading.set(true);
    try {
      await downloadAll(
        paths,
        path => this.api.downloadUrl(path, type, profile),
        url => this.api.getRaw(url),
      );
    } finally {
      this.downloading.set(false);
    }
  }

  private async confirmDownload(count: number): Promise<boolean> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.gallery.selection.download_confirm_title, { count }),
        message: this.i18n.t(I18N.gallery.selection.download_confirm_message, { count }),
      },
    });
    return !!await firstValueFrom(ref.afterClosed());
  }

  async addToAlbum(albumId: number, explicitPaths?: string[]): Promise<void> {
    // No filter-scoped form server-side, so a whole-view selection resolves to
    // paths here rather than adding nothing at all. Filing photos into an album
    // writes album_photos rows and leaves the photos themselves untouched, so
    // it must not confirm in the wording of a mutation.
    const paths = explicitPaths
      ?? await this.resolveSelectionPaths(I18N.gallery.selection.view_scope_album_message);
    if (!paths?.length) return;
    await firstValueFrom(this.albumService.addPhotos(albumId, paths));
    this.journal.record('album', paths, { album_id: albumId, action: 'add' });
    this.snackBar.open(this.i18n.t(I18N.albums.photos_added), '', { duration: 2000 });
    // Explicit paths come from the context menu on one photo: the user's
    // selection is theirs to keep.
    if (explicitPaths === undefined) this.host.clearSelection();
  }

  async createAlbumAndAdd(explicitPaths?: string[]): Promise<void> {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    const album = await firstValueFrom(ref.afterClosed());
    if (!album) return;
    this.host.albumAdded(album);
    await this.addToAlbum(album.id, explicitPaths);
  }

  openExportDialog(explicitPaths?: string[]): void {
    // Explicit paths name what to export, so the album route below -- which
    // exports the whole album whatever is selected -- must not claim them.
    if (explicitPaths !== undefined) {
      this.dialog.open(ExportEditorDialogComponent, { width: '420px', data: { paths: [...explicitPaths] } });
      return;
    }
    const albumId = this.route.snapshot.paramMap.get('albumId');
    if (albumId) {
      this.dialog.open(ExportEditorDialogComponent, { width: '420px', data: { albumId: +albumId } });
      return;
    }
    // Under view scope the dialog gets the filter, not a path list. The 10,000
    // ceiling (and its 412) applies either way: what this avoids is putting the
    // paths on the wire, not the cap.
    this.dialog.open(ExportEditorDialogComponent, {
      width: '420px',
      data: this.viewScoped()
        ? { filters: this.store.filterPayload(), exclude: [...this.excludedPaths()], count: this.selectionCount() }
        : { paths: [...this.selectedPaths()] },
    });
  }

  async openCaptureDateDialog(): Promise<void> {
    if (!this.auth.isEdition()) return;
    const viewScoped = this.viewScoped();
    const selected = this.selectedPaths();
    const first = viewScoped ? undefined : this.store.photos().find(photo => selected.has(photo.path) && photo.date_taken);
    const data = {
      paths: [...selected],
      filters: viewScoped ? structuredClone(this.store.filterPayload()) : null,
      exclude: viewScoped ? [...this.excludedPaths()] : [],
      count: this.selectionCount(),
      reference: first?.date_taken ? { path: first.path, date: first.date_taken } : null,
    };
    if (!viewScoped && !data.paths.length) return;
    const liveness = this.staleness.create(this.destroyRef, { track: 'status' });
    try {
      const { CaptureDateDialogComponent } = await import('../photo-detail/capture-date-dialog.component');
      if (!liveness.current()) return;
      this.dialog.open(CaptureDateDialogComponent, { width: '95vw', maxWidth: '760px', data });
    } finally { liveness.dispose(); }
  }

  async openBatchGpsDialog(): Promise<void> {
    if (!this.auth.isEdition() || !this.selectionCount()) return;
    const selectionIdentity = () => JSON.stringify({
      view: this.viewScoped(), paths: [...this.selectedPaths()].sort(),
      exclude: [...this.excludedPaths()].sort(), filters: this.store.filterPayload(),
    });
    const originalSelection = selectionIdentity();
    const batch = this.viewScoped()
      ? { filters: structuredClone(this.store.filterPayload()), exclude: [...this.excludedPaths()] }
      : { photo_paths: [...this.selectedPaths()] };
    const { current, dispose } = this.staleness.create(this.destroyRef);
    const onBatchApplied = () => {
      if (current() && selectionIdentity() === originalSelection) this.store.clearSelection();
    };
    try {
      const { GpsEditDialogComponent } = await import('../photo-detail/gps-edit-dialog.component');
      if (!current()) return;
      this.dialog.open(GpsEditDialogComponent, {
        width: '95vw', maxWidth: '640px',
        data: { path: '', filename: this.i18n.t(I18N.photo_detail.gps.batch_title), lat: null, lng: null, batch, onBatchApplied },
      });
    } finally { dispose(); }
  }

  /** Bulk add/remove of one manual tag. The dialog owns the request; the list is
   *  refetched afterwards because a photo opened in the detail view carries the
   *  grid row's `manual_tags`, which a bulk write has just made stale. */
  async openManualTagsDialog(): Promise<void> {
    if (!this.auth.isEdition() || !this.selectionCount()) return;
    const owner = this.auth.identity();
    const viewScoped = this.viewScoped();
    const target = this.captureSelectionContext();
    const token = this.auth.token;
    const liveness = this.staleness.create(this.destroyRef, { track: 'status' });
    try {
      const paths = await this.resolveSelectionPaths(null);
      if (!paths?.length || !liveness.current() || !target.current() || this.auth.token !== token) return;
      const selected = new Set(paths);
      const repaired = new WeakSet<ManualTagsDialogResult>();
      const repair = async (result: ManualTagsDialogResult): Promise<void> => {
        if (this.auth.identity() !== owner || repaired.has(result) || !result.confirmedCount && !result.uncertain) return;
        repaired.add(result);
        // Tag/text membership may gain offscreen rows. The store retains parked
        // repair debt and respects the currently authorized view without selection reset.
        const filters = this.store.filters();
        const membershipMayChange = this.store.pinnedPaths() === null
          && (viewScoped || !!filters.tag || !!filters.search || !!this.store.currentAlbum()?.is_smart);
        await this.store.refreshPaths(membershipMayChange ? null : paths);
      };
      const data: ManualTagsDialogData = {
        paths,
        fromWholeView: viewScoped,
        count: paths.length,
        observation: observeManualTags(this.store.photos().filter(photo => selected.has(photo.path))),
        onSettled: result => { void repair(result); },
      };
      const { ManualTagsDialogComponent } = await import('./manual-tags-dialog.component');
      if (!liveness.current() || !target.current() || this.auth.token !== token) return;
      const ref = this.dialog.open<InstanceType<typeof ManualTagsDialogComponent>, ManualTagsDialogData, ManualTagsDialogResult>(ManualTagsDialogComponent, {
        width: '95vw', maxWidth: '600px', closeOnNavigation: false, data,
      });
      const written = await firstValueFrom(ref.afterClosed());
      // An accepted operation can finish after navigation parked this gallery.
      // Queue its repair debt for the same principal; never restore old selection.
      if (!written || this.auth.identity() !== owner || !written.confirmedCount && !written.uncertain) return;
      this.journal.record('tags', paths, { ...written, count: written.confirmedCount });
      await repair(written);
    } finally { liveness.dispose(); }
  }

  async openCullDialog(explicitPaths?: string[]): Promise<void> {
    const explicit = explicitPaths !== undefined;
    const viewScoped = !explicit && this.viewScoped();
    const paths = explicit ? [...explicitPaths] : [...this.selectedPaths()];
    if (!viewScoped && !paths.length) return;
    const filterScope = JSON.stringify(this.store.filterPayload());
    const { current, dispose } = this.staleness.create(this.destroyRef, {
      track: 'status', valid: () => JSON.stringify(this.store.filterPayload()) === filterScope,
    });
    try {
      // Taken before the dialog: the reload after a cull may drop these rows.
      const culled = explicit ? this.store.photos().filter(p => paths.includes(p.path)) : [];
      const { CullDialogComponent } = await import('./cull-dialog.component');
      if (!current()) return;
      const ref = this.dialog.open(CullDialogComponent, {
        closeOnNavigation: false,
        width: '48rem',
        maxWidth: '95vw',
        data: {
          paths,
          // Same trade as the export: the filter travels instead of the paths,
          // and the server's 10,000 ceiling (412) applies to it just the same.
          filters: viewScoped ? this.store.filterPayload() : null,
          exclude: viewScoped ? [...this.excludedPaths()] : [],
          count: explicit ? paths.length : this.selectionCount(),
          trashAvailable: this.store.config()?.cull?.trash_available ?? false,
          allowTrash: this.store.config()?.cull?.allow_trash ?? false,
        },
      });
      const applied = await firstValueFrom(ref.afterClosed());
      if (applied && current()) {
        // Reload first: clearing the selection hands focus back to the marked
        // card, and the rows the cull has just moved away are still standing in
        // the list until this returns.
        if (!explicit) {
          await this.store.reloadPhotos();
          if (current()) this.host.clearSelection();
          return;
        }
        // loadPhotos() drops a whole-view selection (a view selection names the
        // view, and the reload is what the store reads as "the view changed"),
        // so what the user built is captured first and put back after it.
        const wasViewScoped = this.viewScoped();
        const kept = wasViewScoped ? new Set(this.excludedPaths()) : new Set(this.selectedPaths());
        await this.store.reloadPhotos();
        if (current()) this.restoreSelectionWithout(wasViewScoped, kept, culled);
      }
    } finally { dispose(); }
  }

  /** After a cull of explicit paths only those photos leave the selection; the
   *  rest of what the user built stays, in the scope it was built in. Under
   *  view scope "leaves" means joining the exclusion list. */
  private restoreSelectionWithout(wasViewScoped: boolean, kept: Set<string>, culled: Photo[]): void {
    const gone = new Set(culled.map(p => p.path));
    if (!wasViewScoped) {
      this.store.restoreSelection([...kept].filter(path => !gone.has(path)));
      return;
    }
    this.store.selectWholeView();
    for (const path of new Set([...kept, ...gone])) this.store.toggleSelection({ path } as Photo);
  }

  /**
   * Bulk "Delete…": paths only, never `filters`/`exclude` (decision 8 / B5) --
   * a filter-driven request is the one shape that can trash an unbounded set,
   * so under view scope this is disabled rather than switched to a
   * filter-based request; the guard below is a belt-and-braces check against
   * the button state, not the primary gate.
   *
   * Drops rows via `GalleryStore.removePhotos` (decision 6 bullet 4), never
   * `loadPhotos()` -- the existing cull reload is correct for cull, whose
   * rows survive a move/trash, but delete's rows are already gone from
   * `photos` server-side by the time this response returns.
   */
  async removeSelectedFromCatalog(): Promise<void> {
    if (this.viewScoped()) return;
    await this.photoActions.removeFromCatalog([...this.selectedPaths()]);
  }

  async deleteSelected(explicitPaths?: string[]): Promise<void> {
    const explicit = explicitPaths !== undefined;
    // Explicit paths name their own targets, so view scope -- which `paths`
    // cannot express -- is not in play.
    if (!explicit && this.viewScoped()) return;
    const paths = explicit ? [...explicitPaths] : [...this.selectedPaths()];
    if (!paths.length) return;
    const selectedSet = new Set(paths);
    const loaded = this.store.photos().filter(p => selectedSet.has(p.path));
    // One explicit path is the context menu's single-photo delete: it gets the
    // single-photo wording, and the lead check photo-detail makes.
    const lone = explicit && paths.length === 1;
    if (lone && !loaded.length) return;
    const hasSiblings = loaded.some(p =>
      !!p.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(p.sequence_kind));
    const { PhotoDeleteDialogComponent } = await import('../../shared/components/photo-delete-dialog/photo-delete-dialog.component');
    const ref = this.dialog.open(PhotoDeleteDialogComponent, {
      ...(lone ? { width: '95vw', maxWidth: '28rem' } : { width: '32rem' }),
      data: {
        surface: lone ? 'photo_detail' : 'bulk',
        paths,
        count: paths.length,
        hasCompanion: true,
        hasSiblings,
        // No per-path lead signal client-side for a bulk selection -- the
        // response's own `refused_bracket_lead` is what the partial-result
        // toast below reports instead.
        hasBracketLead: lone && loaded[0].sequence_kind === 'bracket' && loaded[0].sequence_ev_offset === 0,
      },
    });
    const result = await firstValueFrom(ref.afterClosed());
    if (!result) return;
    const res = await this.photoActions.deletePhotos(paths, result);
    if (!res) return;
    // `removed_missing` rows are as gone as trashed ones -- the grid must not
    // keep a tile for a row the server just reconciled away.
    const removed = [...res.deleted, ...res.removed_missing];
    this.store.removePhotos(removed);
    // `removePhotos` already prunes the deleted paths out of the selection.
    if (!explicit) this.host.clearSelection();
    // Every failure bucket counts as "failed" here, not just
    // `refused_bracket_lead` -- an unwritable trash dir (errors), a path the
    // rescan already dropped (not_found/not_visible) or whose file was
    // already gone (skipped) are just as much a reason the user's count came
    // up short, and a response where every path landed in one of those must
    // read as a failure rather than the "0 deleted, 0 refused" neutral result
    // the old two-field toast rendered.
    const failed = res.refused_bracket_lead.length + res.not_found.length + res.not_visible.length
      + res.skipped.length + Object.keys(res.errors).length;
    if (removed.length === 0 && failed > 0) {
      this.snackBar.open(this.i18n.t(I18N.cull.delete_failed), '', { duration: 4000 });
    } else {
      this.snackBar.open(
        this.i18n.t(I18N.cull.delete_partial_result, { deleted: removed.length, failed }),
        '', { duration: 4000 },
      );
    }
  }
}
