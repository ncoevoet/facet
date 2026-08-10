---
name: code-quality-analyzer
description: "Detect code smells, DRY violations, and refactoring opportunities across Angular codebase. Use when identifying duplicate code, reducing code duplication, extracting base classes, centralizing logic, detecting shotgun surgery patterns, or improving code maintainability. Do NOT use for linting/ESLint configuration, code formatting, performance profiling, or security vulnerability scanning. Also triggers on: extract base class, centralize logic, code quality, clean up messy code, or a long method."
---

# Code Quality Analyzer Skill

Expert guidance for identifying code smells, analyzing refactoring opportunities, and applying best practices to improve code maintainability and reduce duplication.

## Code Smell Detection

### 1. Duplicate Code
**Indicator**: Same pattern appears 3+ times across files
**Impact**: Maintenance burden increases, bugs must be fixed multiple places

```typescript
// BAD: Error handling duplicated in PhotoService, GalleryService, SettingsService
class PhotoService {
  getPhotos() {
    return this.http.get<Photo[]>(url).pipe(
      catchError(error => {
        console.error('API error:', error);
        this.snackBar.open('Failed to load', 'OK');
        return throwError(() => error);
      })
    );
  }
}

// SOLUTION: Extract to base class
class BaseApiService {
  protected handleApiError<T>(message: string): (error: any) => Observable<T> {
    return (error: any) => {
      console.error('API error:', error);
      this.snackBar.open(message, 'OK');
      return throwError(() => error);
    };
  }
}

class PhotoService extends BaseApiService {
  getPhotos() {
    return this.http.get<Photo[]>(url).pipe(catchError(this.handleApiError('Failed to load photos')));
  }
}
```

### 2. Shotgun Surgery
**Indicator**: Change in one location requires changes in many places
**Solution**: Centralize related logic

```typescript
// BAD: Score formatting logic spread across 5 components
gallery.ts:      score.toFixed(1) + '/10'
photo-card.ts:   score.toFixed(1) + '/10'
photo-detail.ts: score.toFixed(1) + '/10'

// SOLUTION: Centralize in a pipe or utility
@Pipe({ name: 'score', standalone: true })
class ScorePipe implements PipeTransform {
  transform(score: number): string {
    return score.toFixed(1) + '/10';
  }
}

// Use in all templates:
// {{ photo.aggregate | score }}
```

### 3. Long Methods
**Indicator**: Method/function > 50 lines
**Solution**: Extract sub-methods with clear names

```typescript
// BAD: One 80-line method doing everything
method() {
  // Validate input
  // Load data
  // Transform data
  // Save to cache
  // Update UI
}

// SOLUTION: Extract into focused methods
private validateInput(): boolean { /* 5 lines */ }
private loadData(): Observable<Data> { /* 10 lines */ }
private transformData(data: Data): TransformedData { /* 5 lines */ }
private saveToCache(data: TransformedData): void { /* 3 lines */ }
private updateUI(data: TransformedData): void { /* 5 lines */ }

public execute(): void {
  if (!this.validateInput()) return;
  this.loadData()
    .pipe(
      map(data => this.transformData(data)),
      tap(data => this.saveToCache(data)),
      tap(data => this.updateUI(data))
    ).subscribe();
}
```

### 4. Feature Envy
**Indicator**: Method uses more data from another class than its own
**Solution**: Move method to that class

```typescript
// BAD: Component envies Photo model
class GalleryComponent {
  private getPhotoSummary(photo: Photo) {
    return `${photo.filename} - ${photo.aggregate.toFixed(1)} (${photo.category})`;
  }
}

// SOLUTION: Move to the class that owns the data
class Photo {
  getSummary(): string {
    return `${this.filename} - ${this.aggregate.toFixed(1)} (${this.category})`;
  }
}
```

### 5. Data Clumps
**Indicator**: Same 3+ parameters passed together across methods
**Solution**: Create parameter object

```typescript
// BAD: Passing same filter parameters repeatedly
fetchPhotos(category: string, minScore: number, sortBy: string, page: number) { }
countPhotos(category: string, minScore: number, sortBy: string, page: number) { }
exportPhotos(category: string, minScore: number, sortBy: string, page: number) { }

// SOLUTION: Create data object
interface PhotoFilter {
  category: string;
  minScore: number;
  sortBy: string;
  page: number;
}

fetchPhotos(filter: PhotoFilter) { }
countPhotos(filter: PhotoFilter) { }
exportPhotos(filter: PhotoFilter) { }
```

## DRY Violation Detection

### Pattern Recognition
Search for:
1. **Line-for-line identical blocks** (5+ lines appearing 3+ times)
2. **Conceptually identical patterns** (different variable names but same logic)
3. **Copy-pasted methods** with minor modifications
4. **Repeated validation/transformation** logic

### Quick Detection Commands
```bash
# Find potential duplicates
grep -r "catchError" --include="*.service.ts" client/src/app/ | wc -l

# Look for repeated patterns
grep -r "pipe(" client/src/app/ --include="*.service.ts" | \
  grep -c "tap\|map\|catchError"

# Find repeated signal patterns
grep -r "signal<" --include="*.ts" client/src/app/ | wc -l
```

## Refactoring Decision Tree

### Is the code duplicated?
- **YES -> 5+ line blocks in 3+ places?**
  - Base class (behavior inheritance)
  - Utility function (stateless logic)
  - Injectable service (stateful behavior)

### Is it a cross-cutting concern?
- **YES** (error handling, logging, caching):
  - Base service class or HTTP interceptor
  - Angular pipe for display formatting

### Does one class know too much about another?
- **YES**: Move responsibility to appropriate class

### Are parameters always passed together?
- **YES**: Create parameter object or data class

## Refactoring Patterns

### Pattern 1: Base Class Extraction
Use when: Multiple classes share behavior, have same parent interface

```typescript
// Extract common error handling
class BaseApiService {
  protected http = inject(HttpClient);
  protected snackBar = inject(MatSnackBar);

  protected handleError<T>(message: string): (error: any) => Observable<T> {
    return (error) => {
      console.error(`API error:`, error);
      this.snackBar.open(message, 'OK', { duration: 3000 });
      return throwError(() => error);
    };
  }
}
```

### Pattern 2: Utility Function Extraction
Use when: Stateless transformation logic, calculation, formatting

```typescript
// Extract score formatting utility
export function formatScore(score: number, maxScore = 10): string {
  return `${score.toFixed(1)}/${maxScore}`;
}

export function formatPercentage(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

// Use in any component
displayScore = computed(() => formatScore(this.$photo().aggregate));
```

### Pattern 3: Injectable Service Extraction
Use when: Stateful logic, caching, complex operations, needs dependencies

```typescript
// Extract caching service
@Injectable({ providedIn: 'root' })
class PhotoCacheService {
  private cache = new Map<string, Photo[]>();

  get(key: string, factory: () => Observable<Photo[]>): Observable<Photo[]> {
    if (this.cache.has(key)) {
      return of(this.cache.get(key)!);
    }
    return factory().pipe(
      tap(data => this.cache.set(key, data))
    );
  }

  invalidate(key?: string): void {
    key ? this.cache.delete(key) : this.cache.clear();
  }
}
```

## Refactoring Verification

After refactoring, verify:
- No increase in file count (or justified increase)
- `npx ng build` compiles cleanly from `client/`
- No change in public API (backward compatible)
- Code is simpler, not more complex
- Duplicated code removed (not just moved)

## When NOT to Refactor

- Code is about to be deleted anyway
- Refactoring would break public API
- Code is isolated/rarely changed
- Not truly duplicated (coincidental similarity)

## Examples

**User says**: "Find duplicated error handling across services"
1. Search: `grep -r "catchError" --include="*.service.ts" client/src/app/` -- find 8 occurrences
2. Analyze: 6 of 8 use identical error notification pattern
3. Report: "6 services duplicate error handling -> extract to `BaseApiService.handleError()`"
4. Propose: Base class with shared `catchError` operator
5. Verify: All child classes extend base, build succeeds

**User says**: "This code feels messy, help me clean it up"
1. Read the file -- identify code smells (long methods, data clumps, feature envy)
2. Categorize: 2 long methods (>50 lines), 1 data clump (filter params)
3. Propose refactoring with decision tree: stateless -> utility, stateful -> service
4. Apply changes, verify no public API breakage

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Refactoring breaks child classes | Base class method signature changed | Check ALL child classes before modifying base |
| "False positive" duplication | Coincidentally similar but semantically different code | Only refactor truly duplicated logic, not coincidental similarity |
| Over-abstraction | Extracting a helper used only once | Only extract when pattern appears 3+ times |
| Refactoring breaks tests | Mocks tied to old implementation | Update test mocks to match new structure |
