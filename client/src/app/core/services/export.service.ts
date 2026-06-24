import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface SidecarExportResult {
  ok: boolean;
  written: number;
  skipped: number;
  errors: number;
  sidecars: string[];
}

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

  /** Write a single XMP sidecar next to one photo. */
  exportXmp(path: string, overwrite = false): Observable<{ ok: boolean; sidecar: string; overwrote: boolean }> {
    return this.api.post('/photo/export_xmp', { path, overwrite });
  }

  /** Embed metadata into the original photo file (and write the sidecar). */
  embedMetadata(path: string): Observable<{ ok: boolean; embedded: string | null; sidecar: string }> {
    return this.api.post('/photo/embed_metadata', { path });
  }

  /** Write XMP sidecars for many photos by explicit paths. */
  exportSidecars(paths: string[], overwrite = false): Observable<SidecarExportResult> {
    return this.api.post('/export/sidecars', { paths, overwrite });
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
