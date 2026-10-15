import { api } from '../../api';
import type { Resume, ResumeContent, ResumeLayout, ResumeSection, SectionKind, Template, UserSettings } from '../../types';

type Defaults = UserSettings['resume_defaults'];

export const defaultPointsPerItem = 4;
export const buildOptionsFrom = (defaults: Defaults | undefined) => ({
  pointsPerItem: Math.max(1, Math.round(Number(defaults?.build?.points_per_item)) || defaultPointsPerItem),
  includeSummary: defaults?.build?.include_profile_summary !== false,
  template: (defaults?.template === 'modern' ? 'modern' : 'classic') as Template,
  sectionOrder: (defaults?.sections || []).map((section) => section.kind),
});

/** Old resumes have no `kind`; infer it from the title as the editor does. */
export function sectionKind(section: ResumeSection): SectionKind {
  if (section.kind) return section.kind;
  const title = section.title.trim().toLowerCase();
  if (/^(professional |work )?(experience|history|employment)|^work\b/.test(title)) return 'experience';
  if (/^education|^academic/.test(title)) return 'education';
  if (/^projects?\b/.test(title)) return 'projects';
  if (/^(technical )?skills?\b/.test(title)) return 'skills';
  return 'custom';
}

/** What "Save as my default" stores: template, layout, and section order with titles and hidden flags. */
export function resumeToDefaults(resume: Resume, existing: Defaults | undefined): Defaults {
  return {
    ...existing,
    template: resume.template,
    layout: { ...resume.layout } as Record<string, string | number>,
    sections: resume.content.sections.map((section) => ({ kind: sectionKind(section), title: section.title, ...(section.hidden ? { hidden: true } : {}) })),
  };
}

export async function saveAsDefault(resume: Resume): Promise<UserSettings> {
  const current = await api.getSettings();
  return api.putSettings({ resume_defaults: resumeToDefaults(resume, current.resume_defaults), expected_revision: current.revision });
}

/** Applies saved defaults to a resume: template, layout keys, then section order, titles and hidden flags. Content is otherwise untouched. */
export function applyDefaults(resume: Pick<Resume, 'template' | 'layout' | 'content'>, defaults: Defaults | undefined): { template: Template; layout: ResumeLayout; content: ResumeContent } {
  const template = defaults?.template || resume.template;
  const layout = { ...resume.layout, ...(defaults?.layout || {}) } as ResumeLayout;
  const rules = defaults?.sections || [];
  if (!rules.length) return { template, layout, content: resume.content };
  const remaining = [...resume.content.sections];
  const ordered: ResumeSection[] = [];
  for (const rule of rules) {
    const index = remaining.findIndex((section) => sectionKind(section) === rule.kind && (rule.kind !== 'custom' || !rule.title || section.title === rule.title));
    if (index < 0) continue;
    const [section] = remaining.splice(index, 1);
    const next: ResumeSection = { ...section, kind: sectionKind(section) };
    if (rule.title) next.title = rule.title;
    if (rule.hidden) next.hidden = true; else delete next.hidden;
    ordered.push(next);
  }
  return { template, layout, content: { ...resume.content, sections: [...ordered, ...remaining] } };
}
