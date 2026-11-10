import { AuthService } from '../../../core/services/auth.service';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import type { components } from '../../../core/api/schema';

/** ``POST /api/person/{id}/face_boxes`` response: normalised ``[x1, y1, x2, y2]`` boxes per path. */
type PersonFaceBoxesResponse = components['schemas']['PersonFaceBoxesResponse'];

/** The server's cap on paths per request. */
export const FACE_BOXES_MAX_PATHS = 200;
export const FACE_BOXES_MAX_CACHE_ENTRIES = 4000;

interface Pending {
  personId: number;
  owner: string;
  paths: Map<string, (boxes: number[][]) => void>;
}

/**
 * Selected people's face boxes for many gallery tiles, fetched per person: every tile
 * asking in the same microtask shares one ``face_boxes`` POST (split above the
 * server's 200-path cap). A bounded cache keeps answers per account, person and path. A face change drops the cached answer for its
 * photo (``invalidate``); a change that can touch many photos, such as a merge or
 * a find-more add, drops them all (``clear``).
 */
@Injectable({ providedIn: 'root' })
export class PersonFaceBoxesService {
  private readonly api = inject(ApiService);
  private readonly cache = new Map<string, Promise<number[][]>>();
  private readonly auth = inject(AuthService);
  private owner: string | null = null;
  private generation = 0;
  private readonly pending = new Map<number, Pending>();
  private readonly inFlight = new Set<string>();
  readonly revision = signal(0);

  /** The normalised boxes of ``personId``'s faces in ``path``; empty when it has none or the request fails. */
  boxes(personId: number, path: string): Promise<number[][]> {
    const owner = this.auth.identity();
    if (owner !== this.owner) {
      const previous = this.owner;
      this.owner = owner;
      if (previous !== null) this.clear();
    }
    const key = `${personId}|${path}`;
    const cached = this.cache.get(key);
    if (cached) { this.cache.delete(key); this.cache.set(key, cached); return cached; }
    this.inFlight.add(key);
    const promise = new Promise<number[][]>((resolve) => this.enqueue(personId, path, resolve));
    this.cache.set(key, promise);

    return promise;
  }

  /** Forget the cached boxes for ``path``, so the next tile asking re-fetches. */
  invalidate(path: string): void {
    for (const key of this.cache.keys()) if (key.slice(key.indexOf('|') + 1) === path) { this.cache.delete(key); this.inFlight.delete(key); }
    for (const batch of this.pending.values()) {
      batch.paths.get(path)?.([]);
      batch.paths.delete(path);
    }
    this.revision.update(value => value + 1);
  }

  /** Forget every cached box. */
  clear(): void {
    this.generation++;
    this.cache.clear();
    this.inFlight.clear();
    for (const batch of this.pending.values()) for (const resolve of batch.paths.values()) resolve([]);
    this.pending.clear();
    this.revision.update(value => value + 1);
  }

  private enqueue(personId: number, path: string, resolve: (boxes: number[][]) => void): void {
    let batch = this.pending.get(personId);
    if (!batch) {
      batch = { personId, owner: this.auth.identity(), paths: new Map() };
      this.pending.set(personId, batch);
      const captured = batch;
      queueMicrotask(() => this.flush(captured));
    }
    batch.paths.set(path, resolve);
  }

  private flush(batch: Pending): void {
    if (this.pending.get(batch.personId) !== batch) return;
    if (batch.owner !== this.auth.identity()) {
      this.clear();
      this.owner = this.auth.identity();
      return;
    }
    this.pending.delete(batch.personId);
    const entries = [...batch.paths.entries()];
    for (let i = 0; i < entries.length; i += FACE_BOXES_MAX_PATHS) {
      void this.send(batch.personId, batch.owner, entries.slice(i, i + FACE_BOXES_MAX_PATHS));
    }
  }

  private async send(personId: number, owner: string, entries: [string, (boxes: number[][]) => void][]): Promise<void> {
    const generation = this.generation;
    const observed = new Map(entries.map(([path]) => [path, this.cache.get(`${personId}|${path}`)]));
    try {
      const res = await firstValueFrom(this.api.post<PersonFaceBoxesResponse>(
        `/person/${personId}/face_boxes`, { paths: entries.map(([path]) => path) }));
      for (const [path, resolve] of entries) resolve(generation === this.generation && owner === this.auth.identity()
        && this.cache.get(`${personId}|${path}`) === observed.get(path) ? res.boxes?.[path] ?? [] : []);
    } catch {
      // Not cached, so a later render asks again.
      for (const [path, resolve] of entries) {
        if (generation === this.generation && this.cache.get(`${personId}|${path}`) === observed.get(path)) this.cache.delete(`${personId}|${path}`);
        resolve([]);
      }
    } finally {
      for (const [path] of entries) {
        const key = `${personId}|${path}`;
        if (!this.cache.has(key) || this.cache.get(key) === observed.get(path)) this.inFlight.delete(key);
      }
      // Pending promises must never be evicted: callers share their resolver.
      for (const key of this.cache.keys()) {
        if (this.cache.size <= FACE_BOXES_MAX_CACHE_ENTRIES) break;
        if (!this.inFlight.has(key)) this.cache.delete(key);
      }
    }
  }
}
