import type { Resume, ResumeEntry, ResumeSection } from '../types';
import { formatDateRange } from './build/dates';
import { isSkillsSection, joinContact, skillGroups, styleClasses } from './build/previewStyle';
import './build/build.css';

function Skills({ section, layout }: { section: ResumeSection; layout: NonNullable<Resume['layout']['skills_layout']> }) {
  const groups = skillGroups(section);
  if (!groups.length) return null;
  if (layout === 'inline') return <p className="paper-skills inline">{groups.flatMap((group) => group.items).join(', ')}</p>;
  if (layout === 'columns') return <ul className="paper-skills columns">{groups.flatMap((group) => group.items).map((item, index) => <li key={index}>{item}</li>)}</ul>;
  return <div className="paper-skills grouped">{groups.map((group, index) => <p key={index}>{group.label && <strong>{group.label}: </strong>}{group.items.join(', ')}</p>)}</div>;
}

export function ResumePreview({ resume }: { resume: Resume }) {
  const { content, layout } = resume;
  const dateText = (entry: ResumeEntry) => (entry.date_range && formatDateRange(entry.date_range, layout.date_format, layout.present_label)) || entry.dates;
  const classes = styleClasses(layout).join(' ');
  return <article className={`resume-paper ${resume.template} font-${layout.font_family || 'auto'} paper-${layout.page_size || 'A4'}${classes ? ` ${classes}` : ''}`} style={{ fontSize: `${layout.font_size}px`, padding: `${layout.margin * 2.5}px`, lineHeight: layout.line_spacing || 1.25 }}><header className="paper-header"><h1>{content.name || 'Your Name'}</h1><div>{joinContact([content.email, content.phone, content.location].filter(Boolean), layout.contact_separator) || 'Email · Phone · Location'}</div></header>{content.summary && <p className="paper-summary">{content.summary}</p>}{content.sections.filter((section) => !section.hidden).map((section) => <section className="paper-section" key={section.id}><h2>{section.title || 'Section'}</h2>{layout.skills_layout && isSkillsSection(section) ? <Skills section={section} layout={layout.skills_layout} /> : section.entries.map((entry) => <div className="paper-entry" key={entry.id}><div className="paper-entry-head"><strong>{entry.heading || 'Role, degree, or project'}</strong><span>{dateText(entry)}</span></div><div className="paper-subheading">{entry.subheading}</div>{entry.bullets.some(Boolean) && <ul>{entry.bullets.filter(Boolean).map((bullet, i) => <li key={i}>{bullet}</li>)}</ul>}</div>)}</section>)}</article>;
}
