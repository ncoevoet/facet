import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService } from './api.service';
import { Photo } from '../../shared/models/photo.model';

export interface Album {
  id: number;
  name: string;
  description: string;
  cover_photo_path: string | null;
  first_photo_path: string | null;
  is_smart: boolean;
  is_shared: boolean;
  smart_filter_json: string | null;
  scoring_context: string | null;
  photo_count: number;
  created_at: string;
  updated_at: string;
}

export interface AlbumScoringContextResult {
  updated: number;
  conflicts: number;
  manual_skipped: number;
  warning?: string;
}

export interface AlbumScoringContextClearResult {
  ok: boolean;
  cleared: number;
}

export interface AlbumSuggestedContext {
  suggested: string | null;
  moment: string | null;
  share: number;
  counts: Record<string, number>;
}

export interface AlbumPhotosResponse {
  photos: Photo[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
}

@Injectable({ providedIn: 'root' })
export class AlbumService {
  private api = inject(ApiService);

  list(params?: Record<string, string | number>): Observable<{ albums: Album[]; total: number; has_more: boolean }> {
    return this.api.get('/albums', params);
  }

  /** Manual (non-smart) albums only — the set used by the scope pickers. */
  listNonSmart(): Observable<Album[]> {
    return this.list().pipe(map(res => res.albums.filter(a => !a.is_smart)));
  }

  /** Resolve an album name from a string id (as carried in query params). */
  static nameById(albums: Album[], id: string | null): string | null {
    return id ? albums.find(a => a.id.toString() === id)?.name ?? null : null;
  }

  create(name: string, description = '', is_smart = false, smart_filter_json: string | null = null): Observable<Album> {
    return this.api.post('/albums', { name, description, is_smart, smart_filter_json });
  }

  get(id: number): Observable<Album> {
    return this.api.get(`/albums/${id}`);
  }

  update(id: number, updates: { name?: string; description?: string; cover_photo_path?: string; is_smart?: boolean; smart_filter_json?: string }): Observable<Album> {
    return this.api.put(`/albums/${id}`, updates);
  }

  delete(id: number): Observable<{ ok: boolean }> {
    return this.api.delete(`/albums/${id}`);
  }

  addPhotos(albumId: number, photoPaths: string[]): Observable<{ ok: boolean; photo_count: number }> {
    return this.api.post(`/albums/${albumId}/photos`, { photo_paths: photoPaths });
  }

  removePhotos(albumId: number, photoPaths: string[]): Observable<{ ok: boolean; photo_count: number }> {
    return this.api.delete(`/albums/${albumId}/photos`, { photo_paths: photoPaths });
  }

  getPhotos(albumId: number, params?: Record<string, string | number | boolean>): Observable<AlbumPhotosResponse> {
    return this.api.get(`/albums/${albumId}/photos`, params);
  }

  share(albumId: number): Observable<{ share_url: string; share_token: string }> {
    return this.api.post(`/albums/${albumId}/share`, {});
  }

  revokeShare(albumId: number): Observable<{ ok: boolean }> {
    return this.api.delete(`/albums/${albumId}/share`);
  }

  getShared(albumId: number, token: string): Observable<{ album: Album; photos: Photo[]; total: number }> {
    return this.api.get(`/shared/album/${albumId}`, { token });
  }

  /** Set the album's scoring context; materializes it onto member photos (last-write-wins). */
  setScoringContext(albumId: number, scoringContext: string): Observable<AlbumScoringContextResult> {
    return this.api.put(`/albums/${albumId}/scoring_context`, { scoring_context: scoringContext });
  }

  /** Clear the album's scoring context and undo it on exactly the members this album stamped. */
  clearScoringContext(albumId: number): Observable<AlbumScoringContextClearResult> {
    return this.api.delete(`/albums/${albumId}/scoring_context`);
  }

  /** Suggest a scoring context from the album's dominant narrative moment. Writes nothing. */
  getSuggestedContext(albumId: number): Observable<AlbumSuggestedContext> {
    return this.api.get(`/albums/${albumId}/suggested_context`);
  }

}
