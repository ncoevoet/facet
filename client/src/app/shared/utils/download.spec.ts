import { of, throwError } from 'rxjs';
import { downloadFile } from './download';

describe('downloadFile', () => {
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

  const blob = () => of(new Blob(['data'], { type: 'text/plain' }));

  it('fetches the blob and saves it under the given filename', async () => {
    await downloadFile(blob(), 'IMG_1234.jpg');

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

  it('rejects and saves nothing when the fetch fails', async () => {
    await expect(downloadFile(throwError(() => new Error('gone')), 'x.jpg')).rejects.toThrow('gone');

    expect(clickSpy).not.toHaveBeenCalled();
  });
});
