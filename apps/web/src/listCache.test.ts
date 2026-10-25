import { beforeEach, describe, expect, it } from 'vitest';
import { clearLists, dropList, listKey, readList, SETTINGS_KEY, writeList } from './listCache';

describe('list cache', () => {
  beforeEach(() => clearLists());

  it('returns nothing for a list it has not seen', () => {
    expect(readList(listKey('alice', 'for-you', '', 0))).toBeUndefined();
  });

  it('keeps a list apart by user, tab, search and refresh count', () => {
    writeList(listKey('alice', 'for-you', '', 0), 'A');
    expect(readList(listKey('alice', 'for-you', '', 0))?.value).toBe('A');
    expect(readList(listKey('casey', 'for-you', '', 0))).toBeUndefined();
    expect(readList(listKey('alice', 'all', '', 0))).toBeUndefined();
    expect(readList(listKey('alice', 'for-you', 'data', 0))).toBeUndefined();
    expect(readList(listKey('alice', 'for-you', '', 1))).toBeUndefined();   // a save, pass or profile change bumps this
  });

  it('calls a young list fresh, an older one stale but usable, and drops one that is too old', () => {
    const key = listKey('alice', 'all');
    writeList(key, 'A', 1_000);
    expect(readList(key, 1_000 + 59_000)?.fresh).toBe(true);
    expect(readList(key, 1_000 + 61_000)).toMatchObject({ value: 'A', fresh: false });
    expect(readList(key, 1_000 + 11 * 60_000)).toBeUndefined();
    expect(readList(key, 1_000)).toBeUndefined();   // the too-old read removed it
  });

  it('drops one list without touching the others', () => {
    writeList(SETTINGS_KEY, { revision: 1 });
    writeList(listKey('alice', 'all'), 'A');
    dropList(SETTINGS_KEY);
    expect(readList(SETTINGS_KEY)).toBeUndefined();
    expect(readList(listKey('alice', 'all'))?.value).toBe('A');
  });

  it('forgets the oldest lists beyond its limit and can be cleared', () => {
    for (let i = 0; i < 45; i += 1) writeList(listKey('alice', 'all', `q${i}`), i);
    expect(readList(listKey('alice', 'all', 'q0'))).toBeUndefined();
    expect(readList(listKey('alice', 'all', 'q44'))?.value).toBe(44);
    clearLists();
    expect(readList(listKey('alice', 'all', 'q44'))).toBeUndefined();
  });
});
