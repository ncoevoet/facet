import type { components } from '../../core/api/schema';
import { i18nKeys } from '../../core/i18n/keys';
import { HistoryDiffPipe, HistoryValue } from './organization-history-diff.pipe';

type Entry = components['schemas']['OrganizationEntry'];
type Snapshot = Entry['changes'][number]['before'];

const I18N = i18nKeys();
const H = I18N.organization_history;
const pipe = new HistoryDiffPipe();
const text = (value: string): HistoryValue => ({ key: '', text: value });
const key = (value: string): HistoryValue => ({ key: value, text: '' });
function entry(kind: Entry['kind'], changes: [Snapshot, Snapshot][]): Entry {
  return { id: 1, kind, created_at: '2026-11-10T10:00:00', part: 1, parts: 1, reverted: false, superseded: false,
    changes: changes.map(([before, after], index) => ({ path: `/p/${index}.jpg`, before, after, revision: 1 })) };
}

describe('HistoryDiffPipe', () => {
  it('summarises a single favorite change with its before and after values', () => {
    const diff = pipe.transform(entry('review', [[[0, 1, 0, 0], [0, 0, 0, 0]]]));
    const favorite = { label: H.favorite, before: key(H.yes), after: key(H.no) };
    expect(diff.summary).toEqual([favorite]);
    expect(diff.photos).toEqual([{ path: '/p/0.jpg', changes: [favorite] }]);
  });

  it('folds rejected and kept into one decision, a rejected photo counting as rejected even when kept', () => {
    const diff = pipe.transform(entry('logical_review', [[[null, 0, 1, 1], [null, 0, 0, 1]]]));
    expect(diff.summary).toEqual([{ label: H.decision, before: key(H.rejected), after: key(H.kept) }]);
    const undecided = pipe.transform(entry('review', [[[0, 0, 0, 1], [0, 0, 0, 0]]]));
    expect(undecided.summary).toEqual([{ label: H.decision, before: key(H.kept), after: key(I18N.culling.lightbox.undecided) }]);
  });

  it('reports values that differ across photos as several values', () => {
    const stars = pipe.transform(entry('review', [[[3, 0, 0, 0], [5, 0, 0, 0]], [[4, 0, 0, 0], [5, 0, 0, 0]]]));
    expect(stars.summary).toEqual([{ label: H.stars, before: null, after: text('5') }]);
    const shifted = pipe.transform(entry('date', [
      [['2024:01:01 10:00:00', 1], ['2024:01:01 11:00:00', 1]],
      [['2024:01:02 10:00:00', 1], ['2024:01:02 11:00:00', 1]],
    ]));
    expect(shifted.summary).toEqual([{ label: H.capture_date, before: null, after: null }]);
  });

  it('summarises a secondary field only when no primary field changed, and lists both per photo', () => {
    const flagOnly = pipe.transform(entry('date', [[['2024:01:01 00:00:00', 1], ['2024:01:01 00:00:00', 0]]]));
    expect(flagOnly.summary).toEqual([{ label: H.manual_date, before: key(H.yes), after: key(H.no) }]);
    const both = pipe.transform(entry('date', [[[null, 0], ['2024:01:01 00:01:00', 1]]]));
    const date = { label: H.capture_date, before: key(H.unknown), after: text('01/01/2024 00:01') };
    expect(both.summary).toEqual([date]);
    expect(both.photos[0].changes).toEqual([date, { label: H.manual_date, before: key(H.no), after: key(H.yes) }]);
  });

  it('does not report a first review row as a change of an unrated, unfavorited photo', () => {
    const diff = pipe.transform(entry('review', [[[null, null, null, null], [0, 0, 1, 0]]]));
    expect(diff.summary).toEqual([{ label: H.decision, before: key(I18N.culling.lightbox.undecided), after: key(H.rejected) }]);
    expect(diff.photos[0].changes).toHaveLength(1);
  });

  it('shows a location as one rounded coordinate pair', () => {
    const diff = pipe.transform(entry('gps', [[[null, null, 0], [50.8503396, 4.35171, 1]]]));
    expect(diff.summary).toEqual([{ label: H.gps, before: key(H.unknown), after: text('50.85034, 4.35171') }]);
  });

  it('names a stack cover by its file name and keeps a photo whose values did not change', () => {
    const diff = pipe.transform(entry('stack', [[[1, '/a/cover.jpg', 0], [1, '/a/cover.jpg', 0]], [[null, null, null], [2, '/b/new.jpg', 1]]]));
    expect(diff.photos[0]).toEqual({ path: '/p/0.jpg', changes: [] });
    expect(diff.photos[1].changes).toEqual([
      { label: I18N.stacks.stack_id, before: key(H.unknown), after: text('2') },
      { label: I18N.stacks.cover, before: key(H.unknown), after: text('new.jpg') },
      { label: I18N.stacks.position, before: key(H.unknown), after: text('1') },
    ]);
    expect(diff.summary).toEqual([{ label: I18N.stacks.stack_id, before: key(H.unknown), after: text('2') }]);
  });
});
