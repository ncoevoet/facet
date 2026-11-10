import type { WritableSignal } from '@angular/core';

/** Replace one key immutably so consumers observe the new map. */
export function updateMapSignal<K, V>(signal: WritableSignal<Map<K, V>>, key: K, value: V): void {
  signal.update(current => new Map(current).set(key, value));
}

/** Keep the existing map when the requested key is already absent. */
export function deleteMapKey<K, V>(signal: WritableSignal<Map<K, V>>, key: K): void {
  signal.update(current => {
    if (!current.has(key)) return current;
    const next = new Map(current); next.delete(key); return next;
  });
}
