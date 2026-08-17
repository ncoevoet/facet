# Mocking Patterns for Facet Angular Tests

## Contents

- [ApiService Mock](#apiservice-mock)
- [I18nService Mock](#i18nservice-mock)
- [AuthService Mock](#authservice-mock)
- [HttpClient Mock (for unit-testing services directly)](#httpclient-mock-for-unit-testing-services-directly)
- [Testing Pure Pipes](#testing-pure-pipes)
- [Test Helper Functions](#test-helper-functions)

## ApiService Mock

```typescript
const mockApiService = jasmine.createSpyObj('ApiService', [
  'get', 'post', 'getRaw', 'thumbnailUrl', 'faceThumbnailUrl',
  'personThumbnailUrl', 'imageUrl'
]);
mockApiService.get.and.returnValue(of({}));
mockApiService.post.and.returnValue(of({}));
mockApiService.thumbnailUrl.and.callFake(
  (path: string) => `/thumbnail?path=${encodeURIComponent(path)}`
);
mockApiService.faceThumbnailUrl.and.callFake(
  (id: number) => `/face_thumbnail/${id}`
);
```

## I18nService Mock

```typescript
const mockI18nService = {
  t: jasmine.createSpy('t').and.callFake(
    (key: string) => `translated:${key}`
  ),
  locale: jasmine.createSpy('locale').and.returnValue('en'),
  setLocale: jasmine.createSpy('setLocale').and.returnValue(Promise.resolve()),
  load: jasmine.createSpy('load').and.returnValue(Promise.resolve()),
  isLoaded: jasmine.createSpy('isLoaded').and.returnValue(true),
};
```

**Always test with `'translated:'` prefix**, not the key itself.

## AuthService Mock

```typescript
const mockAuthService = {
  isAuthenticated: jasmine.createSpy('isAuthenticated').and.returnValue(true),
  user: jasmine.createSpy('user').and.returnValue({ username: 'test' }),
  login: jasmine.createSpy('login').and.returnValue(Promise.resolve(true)),
  logout: jasmine.createSpy('logout'),
};
```

## HttpClient Mock (for unit-testing services directly)

```typescript
const mockHttpClient = jasmine.createSpyObj('HttpClient', ['get', 'post']);
mockHttpClient.get.and.returnValue(of(mockResponse));
```

## Testing Pure Pipes

```typescript
// TranslatePipe uses inject(I18nService) -- needs TestBed
describe('TranslatePipe', () => {
  let pipe: TranslatePipe;

  const mockI18nService = {
    t: jasmine.createSpy('t').and.callFake(
      (key: string) => `translated:${key}`
    ),
    locale: jasmine.createSpy('locale').and.returnValue('en'),
    isLoaded: jasmine.createSpy('isLoaded').and.returnValue(true),
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        TranslatePipe,
        { provide: I18nService, useValue: mockI18nService }
      ]
    });
    pipe = TestBed.inject(TranslatePipe);
  });

  it('should translate key', () => {
    expect(pipe.transform('gallery.title')).toBe('translated:gallery.title');
  });

  it('should pass variables to i18n service', () => {
    pipe.transform('photo.count', { count: 5 });
    expect(mockI18nService.t).toHaveBeenCalledWith('photo.count', { count: 5 });
  });
});
```

## Test Helper Functions

### Component Initialization Helper

```typescript
const initializeWithInput = (photo: Photo | undefined): void => {
  fixture.componentRef.setInput('photo', photo);
  fixture.detectChanges();
  TestBed.flushEffects();
};
```

### Mock Data Factory

```typescript
const createMockPhoto = (overrides?: Partial<Photo>): Photo => ({
  path: '/photos/test.jpg',
  filename: 'test.jpg',
  aggregate: 7.5,
  aesthetic: 8.0,
  face_quality: null,
  comp_score: 6.5,
  camera_model: 'Canon EOS R5',
  lens_model: null,
  tags: 'landscape,mountain',
  date_taken: '2025-01-15',
  image_width: 6000,
  image_height: 4000,
  face_count: 0,
  face_ratio: 0,
  is_burst_lead: null,
  burst_group_id: null,
  duplicate_group_id: null,
  ...overrides,
});
```

### Helper Naming Convention

- `initialize*` -- setup/lifecycle helpers
- `create*` -- mock data factories
- `set*` -- state modification helpers
- `expect*` -- assertion helpers

**When NOT to create helpers**: Used only 1-2 times, simpler than calling code, obscures test intent.
