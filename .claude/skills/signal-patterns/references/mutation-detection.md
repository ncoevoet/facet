# Mutation Detection and Fixes

Every way a signal silently fails to update the UI because the reference did not change,
with the correct replacement for each. Referenced from `SKILL.md`.

## Contents

- [RED FLAG: Array Mutation](#red-flag-array-mutation)
- [RED FLAG: Object Property Mutation](#red-flag-object-property-mutation)
- [RED FLAG: Array Element Property Mutation](#red-flag-array-element-property-mutation)
- [The Safe Pattern for Array Updates](#the-safe-pattern-for-array-updates)

### RED FLAG: Array Mutation

```typescript
// WRONG: Array mutated in-place, signal sees same reference = no UI update
const items = this.items();
items.push(newItem);           // Reference unchanged
items[0].score = 9.5;         // Element mutation not detected

// CORRECT: Replace array to trigger signal update
this.items.update(items => [...items, newItem]);
this.items.update(items => items.map((item, i) =>
  i === 0 ? { ...item, score: 9.5 } : item
));
```

### RED FLAG: Object Property Mutation

```typescript
// WRONG: Property mutation not detected
const photo = this.selectedPhoto();
photo.tags = 'landscape,mountain';  // Same reference

// CORRECT: Create new object
this.selectedPhoto.set({ ...this.selectedPhoto(), tags: 'landscape,mountain' });

// CORRECT: Use computed for derived values
protected readonly photoDisplay = computed(() => {
  const photo = this.selectedPhoto();
  return { ...photo, displayName: photo.filename.replace(/\.[^.]+$/, '') };
});
```

### RED FLAG: Array Element Property Mutation

This is the most common issue:

```typescript
// WRONG: Most common bug — element property changes, array ref stays same
method() {
  const photos = this.photos();
  photos[0].selected = true;  // UI doesn't update!
}

// SOLUTION 1: Replace whole array with map
this.photos.update(photos =>
  photos.map((photo, i) =>
    i === 0 ? { ...photo, selected: true } : photo
  )
);

// SOLUTION 2: Splice with spread
this.photos.update(photos => [
  ...photos.slice(0, index),
  { ...photos[index], selected: true },
  ...photos.slice(index + 1)
]);
```

### The Safe Pattern for Array Updates

```typescript
// Generic helper for updating an item at a specific index
private updateItemAtIndex<T extends object>(
  items: T[],
  index: number,
  updates: Partial<T>
): T[] {
  return items.map((item, i) =>
    i === index ? { ...item, ...updates } : item
  );
}

// Usage
togglePhotoSelected(index: number): void {
  this.photos.update(photos =>
    this.updateItemAtIndex(photos, index, {
      selected: !photos[index].selected
    })
  );
}

// Update by identity (e.g., by path)
updatePhoto(updated: Photo): void {
  this.photos.update(photos =>
    photos.map(p => p.path === updated.path ? updated : p)
  );
}
```
