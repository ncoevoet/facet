import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import type { components } from '../../../core/api/schema';

/** ``POST /api/person/{id}/face_boxes`` response: normalised ``[x1, y1, x2, y2]`` boxes per path. */
type PersonFaceBoxesResponse = components['schemas']['PersonFaceBoxesResponse'];

/** The server's cap on paths per request. */
export const FACE_BOXES_MAX_PATHS = 200;

interface Pending {
  personId: number;
  paths: Map<string, (boxes: number[][]) => void>;
}

/**
 * One person's face boxes for many gallery tiles, fetched in batches: every tile
 * asking in the same microtask shares one ``face_boxes`` POST (split above the
 * server's 200-path cap), and answers are cached per person and path until the
 * gallery moves to another person. A face change drops the cached answer for its
 * photo (``invalidate``); a change that can touch many photos, such as a merge or
 * a find-more add, drops them all (``clear``).
 */
@Injectable({ providedIn: 'root' })
export class PersonFaceBoxesService {
  private readonly api = inject(ApiService);
  private readonly cache = new Map<string, Promise<number[][]>>();
  private cachedPersonId: number | null = null;
  private pending: Pending | null = null;

  /** The normalised boxes of ``personId``'s faces in ``path``; empty when it has none or the request fails. */
  boxes(personId: number, path: string): Promise<number[][]> {
    if (personId !== this.cachedPersonId) {
      this.cache.clear();
      this.cachedPersonId = personId;
    }
    const key = `${personId}|${path}`;
    const cached = this.cache.get(key);
    if (cached) return cached;
    const promise = new Promise<number[][]>((resolve) => this.enqueue(personId, path, resolve));
    this.cache.set(key, promise);
    return promise;
  }

  /** Forget the cached boxes for ``path``, so the next tile asking re-fetches. */
  invalidate(path: string): void {
    // The cache only ever holds one person's answers (it is cleared on a person change).
    if (this.cachedPersonId !== null) this.cache.delete(`${this.cachedPersonId}|${path}`);
  }

  /** Forget every cached box. */
  clear(): void {
    this.cache.clear();
  }

  private enqueue(personId: number, path: string, resolve: (boxes: number[][]) => void): void {
    if (this.pending && this.pending.personId !== personId) this.flush();
    if (!this.pending) {
      const batch: Pending = { personId, paths: new Map() };
      this.pending = batch;
      queueMicrotask(() => {
        if (this.pending === batch) this.flush();
      });
    }
    this.pending.paths.set(path, resolve);
  }

  private flush(): void {
    const batch = this.pending;
    this.pending = null;
    if (!batch) return;
    const entries = [...batch.paths.entries()];
    for (let i = 0; i < entries.length; i += FACE_BOXES_MAX_PATHS) {
      void this.send(batch.personId, entries.slice(i, i + FACE_BOXES_MAX_PATHS));
    }
  }

  private async send(personId: number, entries: [string, (boxes: number[][]) => void][]): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.post<PersonFaceBoxesResponse>(
        `/person/${personId}/face_boxes`, { paths: entries.map(([path]) => path) }));
      for (const [path, resolve] of entries) resolve(res.boxes?.[path] ?? []);
    } catch {
      // Not cached, so a later render asks again.
      for (const [path, resolve] of entries) {
        this.cache.delete(`${personId}|${path}`);
        resolve([]);
      }
    }
  }
}
