import { ThumbnailUrlPipe, ImageUrlPipe, FaceThumbnailUrlPipe, PersonThumbnailUrlPipe } from './thumbnail-url.pipe';

describe('ThumbnailUrlPipe', () => {
  let pipe: ThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new ThumbnailUrlPipe();
  });

  it('returns URL with path param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
    expect(url.startsWith('/thumbnail?')).toBe(true);
  });

  it('includes size param when provided', () => {
    const url = pipe.transform('/photos/test.jpg', 640);
    expect(url).toContain('size=640');
  });

  it('omits size param when not provided', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).not.toContain('size=');
  });

  it('handles paths with special characters', () => {
    const url = pipe.transform('/photos/my photo.jpg');
    expect(url).toContain('path=');
    expect(url).not.toContain(' ');
  });
});

describe('ImageUrlPipe', () => {
  let pipe: ImageUrlPipe;

  beforeEach(() => {
    pipe = new ImageUrlPipe();
  });

  it('returns full-size image URL with path param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url.startsWith('/image?')).toBe(true);
    expect(url).toContain('path=%2Fphotos%2Ftest.jpg');
  });

  it('does not include a size param', () => {
    const url = pipe.transform('/photos/test.jpg');
    expect(url).not.toContain('size=');
  });
});

describe('FaceThumbnailUrlPipe', () => {
  let pipe: FaceThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new FaceThumbnailUrlPipe();
  });

  it('returns face thumbnail URL with face id', () => {
    expect(pipe.transform(42)).toBe('/face_thumbnail/42');
  });

  it('handles id 0', () => {
    expect(pipe.transform(0)).toBe('/face_thumbnail/0');
  });
});

describe('PersonThumbnailUrlPipe', () => {
  let pipe: PersonThumbnailUrlPipe;

  beforeEach(() => {
    pipe = new PersonThumbnailUrlPipe();
  });

  it('returns person thumbnail URL with person id', () => {
    expect(pipe.transform(7)).toBe('/person_thumbnail/7');
  });

  it('handles large ids', () => {
    expect(pipe.transform(9999)).toBe('/person_thumbnail/9999');
  });
});
