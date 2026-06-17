import { useDesktopSignal } from './media-query';

/** Build a controllable fake MediaQueryList that records its change handler. */
function makeFakeMql(initialMatches: boolean) {
  let changeHandler: ((e: MediaQueryListEvent) => void) | null = null;
  const addEventListener = vi.fn((type: string, cb: (e: MediaQueryListEvent) => void) => {
    if (type === 'change') changeHandler = cb;
  });
  const removeEventListener = vi.fn();
  const mql = {
    matches: initialMatches,
    media: '(min-width: 768px)',
    addEventListener,
    removeEventListener,
  } as unknown as MediaQueryList;
  return {
    mql,
    addEventListener,
    removeEventListener,
    // Simulate the browser firing a change event.
    fire: (matches: boolean) => changeHandler?.({ matches } as MediaQueryListEvent),
    hasHandler: () => changeHandler !== null,
  };
}

describe('useDesktopSignal', () => {
  let matchMediaSpy: ReturnType<typeof vi.spyOn>;

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts with isDesktop=false before setup is called', () => {
    const { isDesktop } = useDesktopSignal();
    expect(isDesktop()).toBe(false);
  });

  it('queries (min-width: 768px) and seeds the signal from matches on setup', () => {
    const fake = makeFakeMql(true);
    matchMediaSpy = vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);

    const { isDesktop, setup } = useDesktopSignal();
    setup();

    expect(matchMediaSpy).toHaveBeenCalledWith('(min-width: 768px)');
    expect(isDesktop()).toBe(true);
    expect(fake.hasHandler()).toBe(true);
  });

  it('seeds false when the media query does not match', () => {
    const fake = makeFakeMql(false);
    vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);

    const { isDesktop, setup } = useDesktopSignal();
    setup();

    expect(isDesktop()).toBe(false);
  });

  it('updates the signal when the media query change event fires', () => {
    const fake = makeFakeMql(false);
    vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);

    const { isDesktop, setup } = useDesktopSignal();
    setup();
    expect(isDesktop()).toBe(false);

    fake.fire(true);
    expect(isDesktop()).toBe(true);

    fake.fire(false);
    expect(isDesktop()).toBe(false);
  });

  it('invokes the onChange callback with the new match state', () => {
    const fake = makeFakeMql(false);
    vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);
    const onChange = vi.fn();

    const { setup } = useDesktopSignal({ onChange });
    setup();

    fake.fire(true);
    expect(onChange).toHaveBeenCalledWith(true);
    fake.fire(false);
    expect(onChange).toHaveBeenCalledWith(false);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it('does not require an onChange callback', () => {
    const fake = makeFakeMql(false);
    vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);

    const { setup } = useDesktopSignal();
    setup();
    expect(() => fake.fire(true)).not.toThrow();
  });

  it('removes the change listener on cleanup', () => {
    const fake = makeFakeMql(true);
    vi.spyOn(window, 'matchMedia').mockReturnValue(fake.mql);

    const { setup, cleanup } = useDesktopSignal();
    setup();
    cleanup();

    expect(fake.removeEventListener).toHaveBeenCalledTimes(1);
    expect(fake.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
    // The same handler that was registered should be removed.
    expect(fake.removeEventListener.mock.calls[0][1]).toBe(fake.addEventListener.mock.calls[0][1]);
  });

  it('is a no-op on cleanup when setup was never called', () => {
    const { cleanup } = useDesktopSignal();
    expect(() => cleanup()).not.toThrow();
  });
});
