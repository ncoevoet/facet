# Parent-Child Communication with Signals

Passing state down and events up without reintroducing the mutation bugs
`references/mutation-detection.md` covers. Referenced from `SKILL.md`.

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
