import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import type { components } from '../api/schema';

export type SidecarJobStatus = components['schemas']['SidecarJobStatus'];
export type ExportPreview = components['schemas']['ExportPreviewResponse'];
export type ExportPreviewRequest = components['schemas']['ExportPreviewRequest'];
export type SidecarJobScope =
  | { paths: string[]; filters?: never; exclude?: string[] }
  | { filters: Record<string, string>; paths?: never; exclude?: string[] };

export interface AlbumExportResult {
  ok: boolean;
  mode: 'sidecars' | 'copy' | 'symlink';
  target_dir?: string;
  written?: number;
  copied?: number;
  skipped: number;
  errors: number;
}

export type AlbumExportMode = 'sidecars' | 'copy' | 'symlink';

@Injectable({ providedIn: 'root' })
export class ExportService {
  private api = inject(ApiService);

  previewExport(request: ExportPreviewRequest): Observable<ExportPreview> {
    return this.api.post('/export/preview', request);
  }

  previewRetry(id: string): Observable<ExportPreview> {
    return this.api.post(`/export/sidecar_jobs/${encodeURIComponent(id)}/preview`);
  }

  applyExport(preview: ExportPreview): Observable<SidecarJobStatus> {
    return this.api.post('/export/apply', {
      ...preview.request, preview_token: preview.preview_token, selected_paths: preview.selected_paths,
    });
  }

  /** Write a single XMP sidecar next to one photo. */
  exportXmp(path: string, overwrite = false): Observable<{ ok: boolean; sidecar: string; overwrote: boolean }> {
    return this.api.post('/photo/export_xmp', { path, overwrite });
  }

  /** Embed metadata into the original photo file (and write the sidecar). */
  embedMetadata(path: string): Observable<{ ok: boolean; embedded: string | null; sidecar: string }> {
    return this.api.post('/photo/embed_metadata', { path });
  }

  /** Start a bounded background export; the receipt never includes photo paths. */
  startSidecarJob(scope: SidecarJobScope, overwrite = false): Observable<SidecarJobStatus> {
    return this.api.post('/export/sidecar_jobs', { ...scope, overwrite });
  }

  recentSidecarJobs(): Observable<SidecarJobStatus[]> {
    return this.api.get('/export/sidecar_jobs');
  }

  sidecarJob(id: string): Observable<SidecarJobStatus> {
    return this.api.get(`/export/sidecar_jobs/${encodeURIComponent(id)}`);
  }

  /** Stop between completed file writes; already-written metadata is retained. */
  cancelSidecarJob(id: string): Observable<SidecarJobStatus> {
    return this.api.post(`/export/sidecar_jobs/${encodeURIComponent(id)}/cancel`);
  }

  /** Explicit new job for failed/skipped/unprocessed files using current metadata. */
  retrySidecarJob(id: string): Observable<SidecarJobStatus> {
    return this.api.post(`/export/sidecar_jobs/${encodeURIComponent(id)}/retry`);
  }

  /** "Basket" export: an album's selects as sidecars, or copied/symlinked out. */
  exportAlbum(albumId: number, mode: AlbumExportMode, targetDir = '', overwrite = false): Observable<AlbumExportResult> {
    return this.api.post(`/albums/${albumId}/export`, {
      mode,
      target_dir: targetDir,
      overwrite,
    });
  }
}
