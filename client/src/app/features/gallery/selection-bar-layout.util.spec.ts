import { noticeLiftPx } from './selection-bar-layout.util';

describe('noticeLiftPx', () => {
  const base = { hostBottom: 800, barTop: 740, barBottom: 784, noticeTop: 700, noticeBottom: 784, barLeft: 16 };

  it('does not lift when a narrow card sits clear of the notices', () => {
    expect(noticeLiftPx({ ...base, barRight: 300, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
  });

  it('lifts by host bottom minus card top when a wide card reaches the notices', () => {
    expect(noticeLiftPx({ ...base, barRight: 1000, noticeLeft: 768, noticeRight: 1184 })).toBe(60);
  });

  it('treats touching edges as no overlap', () => {
    expect(noticeLiftPx({ ...base, barRight: 768, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
  });

  it('lifts on a full-width mobile card', () => {
    expect(noticeLiftPx({ hostBottom: 700, barTop: 640, barBottom: 692, noticeTop: 620, noticeBottom: 692, barLeft: 8, barRight: 392, noticeLeft: 8, noticeRight: 392 })).toBe(60);
  });

  it('never returns a negative lift', () => {
    expect(noticeLiftPx({ ...base, barTop: 900, barRight: 1000, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
  });

  it('does not lift bottom notices when the card has moved above them', () => {
    expect(noticeLiftPx({ ...base, barTop: 200, barBottom: 260, barRight: 1000, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
  });

  it('does not lift when the card is below or to the right of the notices', () => {
    expect(noticeLiftPx({ ...base, barTop: 784, barBottom: 800, barRight: 1000, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
    expect(noticeLiftPx({ ...base, barLeft: 1200, barRight: 1300, noticeLeft: 768, noticeRight: 1184 })).toBe(0);
  });

  it('is zero when the notice stack is absent', () => {
    expect(noticeLiftPx({ ...base, barRight: 1000, noticeLeft: null, noticeRight: null })).toBe(0);
    const measured = { ...base, barRight: 1000, noticeLeft: 768, noticeRight: 1184 };
    for (const key of ['noticeLeft', 'noticeRight', 'noticeTop', 'noticeBottom'] as const) {
      expect(noticeLiftPx({ ...measured, [key]: null })).toBe(0);
    }
  });
});
