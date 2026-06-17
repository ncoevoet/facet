import { of, Observable } from 'rxjs';
import { downloadAll } from './download';

describe('downloadAll', () => {
  let revokeObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let appendChildSpy: ReturnType<typeof vi.spyOn>;
  let removeChildSpy: ReturnType<typeof vi.spyOn>;
  let clickSpy: ReturnType<typeof vi.fn>;
  let anchors: HTMLAnchorElement[];

  beforeEach(() => {
    anchors = [];
    clickSpy = vi.fn();

    // jsdom may not implement URL.createObjectURL — define/spy it. We never assert
    // on its call count (a shared global other specs also touch), only on the blob
    // URL it returns, so the spy itself doesn't need to be captured.
    vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((obj: Blob | MediaSource) => `blob:mock/${(obj as Blob).size}`);
    revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);

    const realCreateElement = document.createElement.bind(document);
    vi
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

    // Assert on the operation's own anchor, not the global URL.* call counts:
    // createObjectURL/revokeObjectURL are shared globals other specs also touch,
    // so exact-count assertions flake under vitest's parallel file execution.
    expect(anchors).toHaveLength(1);
    const a = anchors[0];
    expect(a.href).toContain('blob:mock/'); // proves createObjectURL ran for this download
    expect(a.download).toBe('IMG_1234.jpg');

    expect(appendChildSpy).toHaveBeenCalledWith(a);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeChildSpy).toHaveBeenCalledWith(a);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith(a.href); // blob URL freed (no leak)
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
    // One blob URL created (href set) and freed per download — scoped to this
    // operation's anchors so it can't flake on sibling specs' global URL.* calls.
    for (const a of anchors) {
      expect(a.href).toContain('blob:mock/');
      expect(revokeObjectURLSpy).toHaveBeenCalledWith(a.href);
    }
  });
});
