import type { ResumeLayout, ResumeSection } from '../../types';

const bulletNames = { '•': 'dot', '–': 'dash', '▪': 'square' } as const;

/** Class names for the style keys a resume sets. A resume without the new keys gets none, so it looks as it always did. */
export function styleClasses(layout: ResumeLayout): string[] {
  const classes: string[] = [];
  if (layout.heading_style) classes.push(`heading-${layout.heading_style}`);
  if (layout.accent_color) classes.push(`accent-${layout.accent_color}`);
  if (layout.bullet_char && bulletNames[layout.bullet_char]) classes.push(`bullet-${bulletNames[layout.bullet_char]}`);
  if (layout.header_align) classes.push(`header-${layout.header_align}`);
  if (layout.section_spacing) classes.push(`spacing-${layout.section_spacing}`);
  if (layout.contact_separator === 'newline') classes.push('contact-lines');
  return classes;
}

export function joinContact(parts: string[], separator: ResumeLayout['contact_separator']): string {
  if (separator === 'newline') return parts.join('\n');
  return parts.join(separator === '|' ? '  |  ' : '  ·  ');
}

export function isSkillsSection(section: ResumeSection): boolean {
  return section.kind === 'skills' || (!section.kind && /^skills?\b/i.test(section.title.trim()));
}

export type SkillGroup = { label: string; items: string[] };
const splitList = (text: string) => text.split(/[,;]/).map((part) => part.trim()).filter(Boolean);

/** Reads a skills section as labelled lists. An entry is a group: heading = label, bullets = skills (comma lists allowed). */
export function skillGroups(section: ResumeSection): SkillGroup[] {
  return section.entries.map((entry) => {
    const fromBullets = entry.bullets.flatMap(splitList);
    const items = fromBullets.length ? fromBullets : splitList(entry.subheading || '');
    const heading = (entry.heading || '').trim();
    // A bare heading is a single skill, not a label.
    if (!items.length) return { label: '', items: heading ? [heading] : [] };
    return { label: heading, items };
  }).filter((group) => group.items.length);
}
