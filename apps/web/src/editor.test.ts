import { describe, expect, it } from 'vitest';
import { addEntry, addSection, blankContent, moveItem, removeEntry, removeSection, updateBullet } from './editor';

describe('resume editing operations', () => {
  it('adds and removes sections without changing their content', () => {
    const original = blankContent();
    const withCustom = addSection(original, 'Volunteer work');
    expect(withCustom.sections.at(-1)?.title).toBe('Volunteer work');
    expect(original.sections).toHaveLength(4);
    expect(removeSection(withCustom, withCustom.sections.at(-1)!.id).sections).toHaveLength(4);
  });

  it('adds entries and updates/removes individual bullets', () => {
    const section = addEntry({ id: 'experience', title: 'Experience', entries: [] });
    const entry = section.entries[0];
    const content = { ...blankContent(), sections: [section] };
    const edited = updateBullet(content, section.id, entry.id, 0, 'Improved onboarding conversion by 18%.');
    expect(edited.sections[0].entries[0].bullets).toEqual(['Improved onboarding conversion by 18%.']);
    expect(removeEntry(section, entry.id).entries).toHaveLength(0);
  });

  it('reorders items within bounds and preserves input arrays', () => {
    const input = ['Experience', 'Education', 'Projects'];
    expect(moveItem(input, 2, -1)).toEqual(['Experience', 'Projects', 'Education']);
    expect(moveItem(input, 0, -1)).toEqual(input);
    expect(input).toEqual(['Experience', 'Education', 'Projects']);
  });
});
