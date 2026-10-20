import { useLayoutEffect, useRef, useState } from 'react';
import type { Resume, ResumeEntry, ResumeSection } from '../types';
import { formatDateRange } from './build/dates';
import { isSkillsSection, joinContact, skillGroups, styleClasses } from './build/previewStyle';
import './build/build.css';
import './previewPages.css';

export type PreviewPages = { count: number; entries: Record<string, number>; bullets: Record<string, number> };
const PX_PER_MM = 96 / 25.4;
export function paperDimensions(type?: string) {
  return type === 'letter' ? {width: 215.9, height: 279.4} : {width: 210, height: 297};
}

function Skills({ section, layout }: { section: ResumeSection; layout: NonNullable<Resume['layout']['skills_layout']> }) {
  const groups = skillGroups(section);
  if (!groups.length) return null;
  if (layout === 'inline') return <p className="paper-skills inline">{groups.flatMap((group) => group.items).join(', ')}</p>;
  if (layout === 'columns') return <ul className="paper-skills columns">{groups.flatMap((group) => group.items).map((item, index) => <li key={index}>{item}</li>)}</ul>;
  return <div className="paper-skills grouped">{groups.map((group, index) => <p key={index}>{group.label && <strong>{group.label}: </strong>}{group.items.join(', ')}</p>)}</div>;
}

export function ResumePreview({ resume, onPages }: { resume: Resume; onPages?: (pages: PreviewPages) => void }) {
  const { content, layout } = resume;
  const dimensions = paperDimensions(layout.page_size);
  const width = dimensions.width * PX_PER_MM, height = dimensions.height * PX_PER_MM;
  const margin = layout.margin * PX_PER_MM;
  const innerWidth = width - margin * 2, innerHeight = height - margin * 2;
  const gap = 32, stride = innerWidth + gap;
  const container = useRef<HTMLDivElement>(null);
  const flow = useRef<HTMLDivElement>(null);
  const report = useRef(onPages); report.current = onPages;
  const [scale, setScale] = useState(560 / width);
  const [pages, setPages] = useState(1);
  useLayoutEffect(() => {
    let alive = true;
    const measure = () => {
      if (!alive || !container.current || !flow.current) return;
      const available = container.current.clientWidth;
      if (available > 0) setScale(Math.min(1, available / width));
      const element = flow.current;
      const count = Math.max(1, Math.ceil((element.scrollWidth + gap - 1) / stride));
      setPages(count);
      const origin = element.getBoundingClientRect();
      const renderedScale = element.closest('article')!.getBoundingClientRect().width / width || 1;
      const entries: Record<string, number> = {}, bullets: Record<string, number> = {};
      element.querySelectorAll<HTMLElement>('[data-preview-entry], [data-preview-bullet]').forEach(node => {
        const rect = node.getClientRects()[0];
        if (!rect) return;
        const page = Math.max(1, Math.min(count, 1 + Math.floor((rect.left - origin.left + 1) / (stride * renderedScale))));
        if (node.dataset.previewEntry) entries[node.dataset.previewEntry] = page;
        if (node.dataset.previewBullet) bullets[node.dataset.previewBullet] = page;
      });
      report.current?.({count, entries, bullets});
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure);
    if (container.current) observer?.observe(container.current);
    if (flow.current) observer?.observe(flow.current);
    void document.fonts?.ready.then(measure);
    window.addEventListener('resize', measure);
    return () => { alive = false; observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, [content, layout, width, innerWidth, innerHeight, stride]);
  const dateText = (entry: ResumeEntry) => (entry.date_range && formatDateRange(entry.date_range, layout.date_format, layout.present_label)) || entry.dates;
  const classes = styleClasses(layout).join(' ');
  return <div className="resume-pages" ref={container}>
    {Array.from({length: pages}, (_, page) => <div className="resume-page" key={page}>
      <div className="resume-page-label">{layout.page_size === 'letter' ? 'US Letter' : 'A4'} · Page {page + 1} of {pages}</div>
      <div className="resume-page-frame" style={{width: width * scale, height: height * scale}}>
        <article aria-label={`${layout.page_size === 'letter' ? 'US Letter' : 'A4'} page ${page + 1}`} className={`resume-paper ${resume.template} font-${layout.font_family || 'auto'} paper-${layout.page_size || 'A4'}${classes ? ` ${classes}` : ''}`} style={{width, height, minHeight: height, maxWidth: 'none', fontSize: `${layout.font_size}pt`, padding: `${layout.margin}mm`, lineHeight: layout.line_spacing || 1.25, transform: `scale(${scale})`, transformOrigin: 'top left'}}>
          <div className="paper-page-window" style={{width: innerWidth, height: innerHeight}}>
            <div ref={page === 0 ? flow : undefined} className="paper-flow" aria-hidden={page > 0 ? true : undefined} style={{width: innerWidth, height: innerHeight, columnWidth: innerWidth, columnGap: gap, columnFill: 'auto', transform: `translateX(${-page * stride}px)`}}>
<header className="paper-header"><h1>{content.name || 'Your Name'}</h1><div>{joinContact([content.email, content.phone, content.location].filter(Boolean), layout.contact_separator) || 'Email · Phone · Location'}</div></header>{content.summary && <p className="paper-summary">{content.summary}</p>}{content.sections.filter((section) => !section.hidden).map((section) => <section className="paper-section" key={section.id}><h2>{section.title || 'Section'}</h2>{layout.skills_layout && isSkillsSection(section) ? <Skills section={section} layout={layout.skills_layout} /> : section.entries.map((entry) => <div className="paper-entry" key={entry.id} data-preview-entry={entry.id}><div className="paper-entry-head"><strong>{entry.heading || 'Role, degree, or project'}</strong><span>{dateText(entry)}</span></div><div className="paper-subheading">{entry.subheading}</div>{entry.bullets.some(Boolean) && <ul>{entry.bullets.map((bullet, i) => bullet && <li key={i} data-preview-bullet={`${entry.id}:${i}`}>{bullet}</li>)}</ul>}</div>)}</section>)}
            </div>
          </div>
        </article>
      </div>
    </div>)}
  </div>;
}
