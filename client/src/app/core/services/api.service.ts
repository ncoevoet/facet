import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import type { McpTokenCreate, McpTokenCreated, McpTokenList, McpTokenRevoked } from '../api/types';
import { thumbnailUrl, imageUrl, faceThumbnailUrl, personThumbnailUrl } from '../../shared/pipes/thumbnail-url.pipe';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private baseUrl = '/api';

  get<T>(path: string, params?: Record<string, string | number | boolean>, context?: HttpContext): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        // Empty type is an explicit All photos choice, distinct from the
        // server default used when the key is absent.
        if ((value !== '' || key === 'type') && value !== undefined && value !== null) {
          httpParams = httpParams.set(key, String(value));
        }
      }
    }
    return this.http.get<T>(`${this.baseUrl}${path}`, { params: httpParams, context });
  }

  post<T>(path: string, body?: unknown): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${path}`, body);
  }

  put<T>(path: string, body?: unknown): Observable<T> {
    return this.http.put<T>(`${this.baseUrl}${path}`, body);
  }

  delete<T>(path: string, body?: unknown): Observable<T> {
    return body
      ? this.http.request<T>('DELETE', `${this.baseUrl}${path}`, { body })
      : this.http.delete<T>(`${this.baseUrl}${path}`);
  }

  /** The caller's agent access tokens (metadata only, never the secret). */
  listMcpTokens(): Observable<McpTokenList> {
    return this.get<McpTokenList>('/mcp/tokens');
  }

  /** Mint an agent access token; the response carries the plaintext exactly once. */
  createMcpToken(body: McpTokenCreate): Observable<McpTokenCreated> {
    return this.post<McpTokenCreated>('/mcp/tokens', body);
  }

  revokeMcpToken(id: number): Observable<McpTokenRevoked> {
    return this.delete<McpTokenRevoked>(`/mcp/tokens/${id}`);
  }

  /** Get raw response (e.g., for binary thumbnails) */
  getRaw(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }

  /** Build thumbnail URL */
  thumbnailUrl(path: string, size?: number, revision?: string | null): string {
    return thumbnailUrl(path, size, revision);
  }

  /** Build face thumbnail URL */
  faceThumbnailUrl(faceId: number): string {
    return faceThumbnailUrl(faceId);
  }

  /** Build person thumbnail URL */
  personThumbnailUrl(personId: number): string {
    return personThumbnailUrl(personId);
  }

  /** Build full image URL */
  imageUrl(path: string, revision?: string | null): string {
    return imageUrl(path, false, revision);
  }

  /** Build a download URL with an optional rendition profile. */
  downloadUrl(path: string, type = 'original', profile = ''): string {
    const params = new URLSearchParams({ path, type });
    if (profile) params.set('profile', profile);
    return `/api/download?${params}`;
  }
}
