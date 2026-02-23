---
name: signal-patterns
description: Signal-based state management patterns for zoneless Angular 20 components. Use when building components with signal(), computed(), effect(), fixing UI not updating issues, detecting array/object mutations, or handling parent-child communication with signals. Do NOT use for CSS/styling issues, backend Python code, or non-Angular work.
triggers:
  - "signal"
  - "computed"
  - "UI not updating"  # For code-level signal mutation issues; use chrome-devtools-debugging for browser-side inspection
  - "UI doesn't update"
  - "array mutation"
  - "object mutation"
  - "signal.set"
  - "signal.update"
  - "input signal"
  - "output signal"
  - "parent-child"
  - "zoneless"
  - "change detection"
  - "firstValueFrom"
  - "onCleanup"
negative_triggers:
  - "CSS"
  - "styling"
  - "layout"
  - "Tailwind"
  - "Python"
  - "backend"
  - "FastAPI"
  - "test"
  - "spec"
  - "Karma"
---

# Signal Patterns Skill

Expert guidance for building zoneless Angular 20 components with signal-based state management, immutable update patterns, and proper reactivity.

## Zoneless Architecture Overview

### How Signals Drive Rendering

This project uses **zoneless change detection** (no zone.js). All reactivity is driven by signals:

1. Signal values change via `signal.set()` or `signal.update()`
2. `computed()` values automatically recompute when dependencies change
3. Templates re-render when the signals they read are updated
4. `effect()` runs side effects when tracked signals change

There is no `NgZone`, no `ChangeDetectorRef`, no `markForCheck()`. Signals are the sole mechanism for triggering UI updates.

```typescript
@Component({
  selector: 'app-photo-list',
  template: `
    @for (photo of filteredPhotos(); track photo.path) {
      <app-photo-card [photo]="photo" />
    }
  `
})
export class PhotoListComponent {
  // Internal state
  private readonly searchTerm = signal('');
  readonly photos = signal<Photo[]>([]);

  // Derived state — auto-updates when photos or searchTerm change
  readonly filteredPhotos = computed(() => {
    const term = this.searchTerm().toLowerCase();
    return this.photos().filter(p =>
      p.filename.toLowerCase().includes(term)
    );
  });

  onSearch(term: string): void {
    this.searchTerm.set(term); // UI updates automatically
  }
}
```

## Signal-Based Patterns

### Pattern 1: Internal State with Signals

```typescript
@Component({
  selector: 'app-gallery-filters',
  template: `...`
})
export class GalleryFiltersComponent {
  private readonly searchTerm = signal('');
  private readonly selectedType = signal('');

  // Computed values automatically track signal dependencies
  protected readonly displayData = computed(() => {
    const type = this.selectedType();
    const term = this.searchTerm().toLowerCase();
    return this.allItems().filter(item =>
      (!type || item.type === type) &&
      item.name.toLowerCase().includes(term)
    );
  });
}
```

### Pattern 2: Input/Output Signals

```typescript
@Component({
  selector: 'app-photo-card',
  template: `...`
})
export class PhotoCardComponent {
  // Input signals (from parent)
  readonly photo = input.required<Photo>();
  readonly selected = input(false);

  // Output signals (to parent)
  readonly photoClicked = output<Photo>();

  // Computed from inputs
  protected readonly thumbnailUrl = computed(() =>
    `/thumbnail?path=${encodeURIComponent(this.photo().path)}`
  );

  onClick(): void {
    this.photoClicked.emit(this.photo());
  }
}
```

### Pattern 3: Effects for Side Effects

```typescript
@Component({
  selector: 'app-data-loader',
  template: `...`
})
export class DataLoaderComponent {
  private readonly api = inject(ApiService);

  readonly query = input<string>();
  protected readonly data = signal<Photo[]>([]);
  protected readonly loading = signal(false);

  constructor() {
    // Load data when query changes
    effect(() => {
      const q = this.query();
      if (!q) return;

      this.loading.set(true);
      firstValueFrom(this.api.get<Photo[]>('/photos', { q }))
        .then(result => this.data.set(result))
        .finally(() => this.loading.set(false));
    });
  }
}
```

### Pattern 4: Effects with Subscriptions (onCleanup)

When an effect subscribes to an observable, use `onCleanup` to prevent memory leaks:

```typescript
constructor() {
  effect((onCleanup) => {
    const id = this.personId();
    if (!id) return;

    const sub = this.api.get<Person>(`/persons/${id}`).subscribe(
      person => this.person.set(person)
    );
    onCleanup(() => sub.unsubscribe());
  });
}
```

**Prefer `firstValueFrom()` over subscriptions** when the observable completes after one emission (HTTP calls). Use subscriptions + `onCleanup` only for long-lived streams.

## Mutation Detection and Fixes

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

## Parent-Child Communication

### Safe Parent-Child Pattern

```typescript
// Parent
@Component({
  selector: 'app-parent',
  template: `
    <app-child
      [photos]="photos()"
      (photoUpdated)="onPhotoUpdated($event)"
    />
  `
})
export class ParentComponent {
  protected readonly photos = signal<Photo[]>([]);

  onPhotoUpdated(photo: Photo): void {
    this.photos.update(photos =>
      photos.map(p => p.path === photo.path ? photo : p)
    );
  }
}

// Child
@Component({
  selector: 'app-child',
  template: `
    @for (photo of photos(); track photo.path) {
      <button (click)="selectPhoto(photo)">{{ photo.filename }}</button>
    }
  `
})
export class ChildComponent {
  readonly photos = input<Photo[]>([]);
  readonly photoUpdated = output<Photo>();

  selectPhoto(photo: Photo): void {
    // Emit new object — never mutate the input
    this.photoUpdated.emit({ ...photo, selected: true });
  }
}
```

## Detecting Signal Issues

### Symptom: UI Doesn't Update After Change

1. Verify the template reads a signal (e.g., `photos()` not `photos`)
2. Look for array/object mutations not creating new references
3. Verify all state changes use `signal.set()` or `signal.update()`
4. Check that computed signals depend on the correct source signals

### Debugging Steps

```typescript
// Add temporary logging via effect
effect(() => {
  console.log('Photos updated:', this.photos().length);
});

// Check if a method runs but UI doesn't update
method() {
  this.doWork();
  // If UI doesn't update: likely mutation issue
  // Temporary force-update for debugging:
  this.items.set([...this.items()]);
}
```

## Using firstValueFrom with Signals

This project uses `firstValueFrom()` to convert HTTP observables to promises inside effects and methods:

```typescript
@Injectable({ providedIn: 'root' })
export class GalleryStore {
  private readonly api = inject(ApiService);
  readonly photos = signal<Photo[]>([]);
  readonly loading = signal(false);

  async loadPhotos(params: Record<string, string>): Promise<void> {
    this.loading.set(true);
    try {
      const response = await firstValueFrom(
        this.api.get<PhotosResponse>('/photos', params)
      );
      this.photos.set(response.photos);
    } finally {
      this.loading.set(false);
    }
  }
}
```

## Verification Checklist

For signal-based components, verify:

- All reactive data uses `signal()`, `computed()`, or `input()`
- No array element property mutations (use `.map()`)
- No object property mutations (use spread `{ ...obj }`)
- All internal state changes use `signal.set()` or `signal.update()`
- Effects properly track their signal dependencies
- No `ChangeDetectorRef` usage (not needed in zoneless)
- No `NgZone` usage (not present in zoneless)
- Templates call signals as functions: `photos()` not `photos`
- `firstValueFrom()` used for HTTP calls in async methods
- `onCleanup` used in effects with subscriptions

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| UI doesn't update after `items[i].prop = value` | Array element mutation — signal sees same reference | Use `signal.update(items => items.map(...))` to create new array |
| UI doesn't update after `obj.prop = value` | Object property mutation — signal sees same reference | Use `signal.set({ ...obj, prop: value })` to create new object |
| Child component doesn't update | Parent passes same array reference to input | Parent must create new array reference: `[...items]` |
| `forEach` mutation not detected | `items.forEach(i => i.checked = true)` mutates in place | Use `.map()` to create new array with updated elements |
| Computed doesn't recompute | Dependency not read inside `computed()` | Ensure all signal dependencies are called inside the computed callback |
| Effect runs too often | Effect tracks signals it shouldn't | Extract signal reads outside the effect or use `untracked()` |
| Effect creates infinite loop | Effect writes to a signal it also reads | Use `untracked()` for the write, or restructure to use `computed()` |

## Examples

**User says**: "My list UI doesn't update after I push an item"
1. Identify the signal holding the array: `photos = signal<Photo[]>([])`
2. Find the mutation: `this.photos().push(newPhoto)` -- mutates in place, signal sees same reference
3. Fix: `this.photos.update(photos => [...photos, newPhoto])`
4. Verify: template re-renders after the update

**User says**: "Computed signal doesn't recompute"
1. Check the computed callback: is it reading the right signal dependencies?
2. Verify signals are called as functions inside `computed()`: `this.photos()` not `this.photos`
3. Check if dependency is being read conditionally (early return before reading it)
4. Fix: ensure all dependencies are read unconditionally at the top of the callback

**User says**: "How do I communicate from child to parent?"
1. Child: declare `output<Photo>()` and call `.emit()` with new object (never mutate input)
2. Parent: bind `(photoUpdated)="onPhotoUpdated($event)"` in template
3. Parent handler: use `signal.update()` with `.map()` to replace the updated item immutably

## See Also

- **effect-safety-validator** — Detect infinite loops, NG0101, unsafe effect patterns (Angular 20 breaking changes)
- **test-creation** — Testing signal inputs/outputs, computed signals, and effects with Karma/Jasmine
