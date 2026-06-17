import { of, Observable } from 'rxjs';
import { downloadAll } from './download';

describe('downloadAll', () => {
  let createObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let createElementSpy: ReturnType<typeof vi.spyOn>;
  let appendChildSpy: ReturnType<typeof vi.spyOn>;
  let removeChildSpy: ReturnType<typeof vi.spyOn>;
  let clickSpy: ReturnType<typeof vi.fn>;
  let anchors: HTMLAnchorElement[];

  beforeEach(() => {
    anchors = [];
    clickSpy = vi.fn();

    // jsdom may not implement URL.createObjectURL — define/spy it.
    createObjectURLSpy = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((obj: Blob | MediaSource) => `blob:mock/${(obj as Blob).size}`);
    revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);

    const realCreateElement = document.createElement.bind(document);
    createElementSpy = vi
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string) => {
        const el = realCreateElement(tag) as HTMLAnchorElement;
        if (tag === 'a') {
          el.click = clickSpy as unknown as () => void;
          anchors.push(el);
        }
        return el;
      });

    appendChildSpy = vi
      .spyOn(document.body, 'appendChild')
      .mockImplementation(((node: Node) => node) as typeof document.body.appendChild);
    removeChildSpy = vi
      .spyOn(document.body, 'removeChild')
      .mockImplementation(((node: Node) => node) as typeof document.body.removeChild);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function getRaw(): Observable<Blob> {
    return of(new Blob(['data'], { type: 'text/plain' }));
  }

  it('does nothing for an empty path list', async () => {
    const buildUrl = vi.fn((p: string) => `http://api/raw?path=${p}`);
    const rawFn = vi.fn(getRaw);
    await downloadAll([], buildUrl, rawFn);

    expect(buildUrl).not.toHaveBeenCalled();
    expect(rawFn).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });

  it('builds the URL, fetches the blob, and triggers a download for a single path', async () => {
    const buildUrl = vi.fn((p: string) => `http://api/raw?path=${p}`);
    const rawFn = vi.fn(getRaw);

    await downloadAll(['photos/IMG_1234.jpg'], buildUrl, rawFn);

    expect(buildUrl).toHaveBeenCalledWith('photos/IMG_1234.jpg');
    expect(rawFn).toHaveBeenCalledWith('http://api/raw?path=photos/IMG_1234.jpg');
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);

    expect(anchors).toHaveLength(1);
    const a = anchors[0];
    expect(a.href).toContain('blob:mock/');
    expect(a.download).toBe('IMG_1234.jpg');

    expect(appendChildSpy).toHaveBeenCalledWith(a);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeChildSpy).toHaveBeenCalledWith(a);
    expect(revokeObjectURLSpy).toHaveBeenCalledTimes(1);
  });

  it('derives the filename from the last path segment, supporting both / and \\ separators', async () => {
    const buildUrl = (p: string) => p;
    await downloadAll(['C:\\Users\\me\\pics\\shot.cr3'], buildUrl, getRaw);

    expect(anchors[0].download).toBe('shot.cr3');
  });

  it('uses an empty filename when the path has no segments', async () => {
    const buildUrl = (p: string) => p;
    await downloadAll([''], buildUrl, getRaw);

    expect(anchors[0].download).toBe('');
  });

  it('processes multiple paths sequentially, one download each', async () => {
    const buildUrl = (p: string) => `url:${p}`;
    const rawFn = vi.fn(getRaw);

    await downloadAll(['a/one.jpg', 'b/two.jpg', 'c/three.jpg'], buildUrl, rawFn);

    expect(rawFn).toHaveBeenCalledTimes(3);
    expect(clickSpy).toHaveBeenCalledTimes(3);
    expect(anchors.map((a) => a.download)).toEqual(['one.jpg', 'two.jpg', 'three.jpg']);
    expect(createObjectURLSpy).toHaveBeenCalledTimes(3);
    expect(revokeObjectURLSpy).toHaveBeenCalledTimes(3);
  });
});
