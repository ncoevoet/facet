import { Pipe, PipeTransform } from '@angular/core';
import type { components } from '../../core/api/schema';
import { i18nKeys } from '../../core/i18n/keys';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { basename } from '../../shared/utils/clipboard';

type Entry = components['schemas']['OrganizationEntry'];
type Snapshot = Entry['changes'][number]['before'];

/** A shown value: an i18n key to translate, or literal text when `key` is empty. */
export interface HistoryValue { key: string; text: string }
/** One field that changed. A null side holds several values across the entry's photos. */
export interface HistoryFieldChange { label: string; before: HistoryValue | null; after: HistoryValue | null }
export interface HistoryPhotoDiff { path: string; changes: HistoryFieldChange[] }
export interface HistoryDiff { summary: HistoryFieldChange[]; photos: HistoryPhotoDiff[] }

/** `exact` shows a change that the rounded `read` would hide. */
interface FieldSpec { label: string; primary: boolean; read: Reader; exact?: Reader }
type Reader = (snapshot: Snapshot) => HistoryValue;

const I18N = i18nKeys();
const H = I18N.organization_history;
const captureDate = new CaptureDatePipe();
const text = (value: string): HistoryValue => ({ key: '', text: value });
const key = (value: string): HistoryValue => ({ key: value, text: '' });
const NOT_SET = key(H.unknown);
const missing = (value: Snapshot[number] | undefined): value is null | undefined => value === null || value === undefined;
const plain = (index: number) => (snapshot: Snapshot): HistoryValue => missing(snapshot[index]) ? NOT_SET : text(String(snapshot[index]));
/** An absent flag reads as No: a photo without a review row is not a favorite. */
const flag = (index: number) => (snapshot: Snapshot): HistoryValue => key(snapshot[index] ? H.yes : H.no);
/** 0 and absent stars both mean unrated, which the gallery shows the same way. */
const rating = (snapshot: Snapshot): HistoryValue => snapshot[0] ? text(String(snapshot[0])) : NOT_SET;
const coordinate = (value: Snapshot[number]): string => String(Number(Number(value).toFixed(5)));
const location = (round: boolean): Reader => s => missing(s[0]) || missing(s[1]) ? NOT_SET
  : text(round ? `${coordinate(s[0])}, ${coordinate(s[1])}` : `${Number(s[0])}, ${Number(s[1])}`);
/** The capture-date pipe stops at minutes; a shift of seconds needs them shown. */
const captured = (seconds: boolean): Reader => s => {
  if (missing(s[0])) return NOT_SET;
  const value = String(s[0]);
  const shown = captureDate.transform(value);
  const second = /[ T]\d{2}:\d{2}:(\d{2})/.exec(value)?.[1];
  return text(seconds && second && shown !== value ? `${shown}:${second}` : shown);
};

/** Review snapshots are [stars, favorite, rejected, kept]; a rejected photo is rejected even when also kept. */
function decision(snapshot: Snapshot): HistoryValue {
  if (snapshot[2]) return key(H.rejected);
  return key(snapshot[3] ? H.kept : I18N.culling.lightbox.undecided);
}

const REVIEW: FieldSpec[] = [
  { label: H.stars, primary: true, read: rating },
  { label: H.favorite, primary: true, read: flag(1) },
  { label: H.decision, primary: true, read: decision },
];

/** Snapshot layouts mirror `db/organization_history.py` FIELDS and the stack snapshot. */
const FIELDS: Record<Entry['kind'], FieldSpec[]> = {
  review: REVIEW,
  logical_review: REVIEW,
  gps: [
    { label: H.gps, primary: true, read: location(true), exact: location(false) },
    { label: H.manual_gps, primary: false, read: flag(2) },
  ],
  date: [
    { label: H.capture_date, primary: true, read: captured(false), exact: captured(true) },
    { label: H.manual_date, primary: false, read: flag(1) },
  ],
  stack: [
    { label: I18N.stacks.stack_id, primary: true, read: plain(0) },
    { label: I18N.stacks.cover, primary: false, read: s => missing(s[1]) ? NOT_SET : text(basename(String(s[1]))) },
    { label: I18N.stacks.position, primary: false, read: plain(2) },
  ],
};

const same = (a: HistoryValue, b: HistoryValue): boolean => a.key === b.key && a.text === b.text;
function uniform(values: (HistoryValue | null)[]): HistoryValue | null {
  const [first] = values;
  return first && values.every(value => value && same(value, first)) ? first : null;
}

/** What an organization history entry changed: per photo, only the fields whose value
 * differs, photos with a change first; as a summary, the changed main fields (or, when
 * none changed, the rest). */
@Pipe({ name: 'historyDiff', standalone: true, pure: true })
export class HistoryDiffPipe implements PipeTransform {
  transform(entry: Entry): HistoryDiff {
    const specs = FIELDS[entry.kind];
    const photos = entry.changes.map(change => ({
      path: change.path,
      changes: specs.flatMap(spec => {
        const differs = (read: Reader): HistoryFieldChange | null => {
          const before = read(change.before);
          const after = read(change.after);
          return same(before, after) ? null : { label: spec.label, before, after };
        };
        const found = differs(spec.read) ?? (spec.exact ? differs(spec.exact) : null);
        return found ? [found] : [];
      }),
    })).sort((a, b) => Number(!a.changes.length) - Number(!b.changes.length));
    const changed = (primary: boolean): HistoryFieldChange[] => specs.filter(spec => spec.primary === primary).flatMap(spec => {
      const rows = photos.flatMap(photo => photo.changes.filter(change => change.label === spec.label));
      if (!rows.length) return [];
      return [{ label: spec.label, before: uniform(rows.map(row => row.before)), after: uniform(rows.map(row => row.after)) }];
    });
    const primary = changed(true);
    return { summary: primary.length ? primary : changed(false), photos };
  }
}
