import type { PhotoFaceRow } from '../photo-detail/photo-face-layer.component';

export type NormalizedBox = [number, number, number, number];

export function normalizedInspectionBox(value: unknown): NormalizedBox | null {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1)) return null;
  const [x1, y1, x2, y2] = value;
  return x2 > x1 && y2 > y1 ? [x1, y1, x2, y2] : null;
}

export interface SharedInspectionPerson {
  id: number;
  name: string;
  boxes: Map<string, NormalizedBox>;
}

/** Saved assignments are correspondence hints, not a new identity confidence claim.
 * Multiple occurrences, missing geometry or inconsistent names require manual framing. */
export function sharedInspectionPeople(paths: readonly string[], faces: ReadonlyMap<string, readonly PhotoFaceRow[]>): SharedInspectionPerson[] {
  if (paths.length < 2) return [];
  const first = faces.get(paths[0]) ?? [];
  const ids = new Set(first.map(face => face.person_id).filter((id): id is number => id != null && Number.isInteger(id) && id >= 0));
  const shared: SharedInspectionPerson[] = [];
  for (const id of ids) {
    const boxes = new Map<string, NormalizedBox>();
    let name: string | null = null;
    for (const path of paths) {
      const matches = (faces.get(path) ?? []).filter(face => face.person_id === id);
      const face = matches.length === 1 ? matches[0] : null;
      const box = normalizedInspectionBox(face?.box);
      const label = face?.person_name?.trim();
      if (!box || !label || name !== null && name !== label) break;
      name = label;
      boxes.set(path, box);
    }
    if (name && boxes.size === paths.length) shared.push({ id, name, boxes });
  }
  return shared;
}
