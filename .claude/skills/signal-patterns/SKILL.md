---
name: signal-patterns
description: "Signal-based state management patterns for zoneless Angular 20 components. Use when building components with signal(), computed(), effect(), fixing UI not updating issues, detecting array/object mutations, or handling parent-child communication with signals. Do NOT use for CSS/styling issues, backend Python code, or non-Angular work. Also triggers on: UI doesn't update, array mutation, signal.set / signal.update, input/output signals, change detection, firstValueFrom, or onCleanup."
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

A signal only notifies when its **reference** changes, so `push`, `items[0].x = y` and
`obj.prop = z` all update the data and leave the UI stale. The fix is always to replace
rather than mutate: `update(items => [...items, x])`, `map` for an element change, a fresh
object literal for a property change.

The most common bug in this codebase is **array element property mutation** — the array
reference survives, so nothing renders.

→ Every red flag, with its correct replacement and a generic
`updateItemAtIndex` helper: [references/mutation-detection.md](references/mutation-detection.md)

## Parent-Child Communication

State flows down as `input()` signals and up as `output()` events; the child never mutates
what the parent owns.

→ The safe pattern in full: [references/parent-child.md](references/parent-child.md)

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
