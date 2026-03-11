import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private baseUrl = '/api';

  get<T>(path: string, params?: Record<string, string | number | boolean>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== '' && value !== undefined && value !== null) {
          httpParams = httpParams.set(key, String(value));
        }
      }
    }
    return this.http.get<T>(`${this.baseUrl}${path}`, { params: httpParams });
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

  /** Get raw response (e.g., for binary thumbnails) */
  getRaw(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }

  /** Build thumbnail URL */
  thumbnailUrl(path: string, size?: number): string {
    const params = new URLSearchParams({ path });
    if (size) params.set('size', String(size));
    return `/thumbnail?${params}`;
  }

  /** Build face thumbnail URL */
  faceThumbnailUrl(faceId: number): string {
    return `/face_thumbnail/${faceId}`;
  }

  /** Build person thumbnail URL */
  personThumbnailUrl(personId: number): string {
    return `/person_thumbnail/${personId}`;
  }

  /** Build full image URL */
  imageUrl(path: string): string {
    return `/image?path=${encodeURIComponent(path)}`;
  }
}
