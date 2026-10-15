import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import type { Resume } from '../types';
import { ResumePreview } from './ResumePreview';
import { resume } from './build/testData';

afterEach(() => cleanup());
const show = (doc: Resume) => render(<ResumePreview resume={doc} />);
const paper = (container: HTMLElement) => container.querySelector('article')!;

describe('ResumePreview', () => {
  it('renders a document without the new keys exactly as before', () => {
    const { container } = show(resume());
    expect(container.innerHTML).toBe('<article class="resume-paper classic font-auto paper-A4" style="font-size: 11px; padding: 45px; line-height: 1.25;"><header class="paper-header"><h1>Alice Tan</h1><div>alice@example.com  ·  +65 5555 0100  ·  Singapore</div></header><p class="paper-summary">Backend engineer.</p><section class="paper-section"><h2>Experience</h2><div class="paper-entry"><div class="paper-entry-head"><strong>Backend Engineer</strong><span>Jul 2023 – Present</span></div><div class="paper-subheading">Harbour Metrics</div><ul><li>Built FastAPI services.</li><li>Cut p95 query time.</li></ul></div></section><section class="paper-section"><h2>Skills</h2><div class="paper-entry"><div class="paper-entry-head"><strong>Languages</strong><span></span></div><div class="paper-subheading"></div><ul><li>Python, SQL</li></ul></div><div class="paper-entry"><div class="paper-entry-head"><strong>Tools</strong><span></span></div><div class="paper-subheading"></div><ul><li>Docker</li><li>Git</li></ul></div></section><section class="paper-section"><h2>Fun facts</h2><div class="paper-entry"><div class="paper-entry-head"><strong>Chess</strong><span></span></div><div class="paper-subheading"></div></div></section></article>');
  });

  it('leaves out hidden sections', () => {
    const doc = resume(); doc.content.sections[2].hidden = true;
    show(doc);
    expect(screen.queryByRole('heading', { name: 'Fun facts' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Experience' })).toBeInTheDocument();
  });

  it('applies heading, bullet, spacing, accent and header classes for the keys a resume sets', () => {
    const { container } = show(resume({ layout: { font_size: 11, margin: 18, heading_style: 'small-caps', bullet_char: '–', section_spacing: 'airy', accent_color: 'navy', header_align: 'left' } }));
    const classes = paper(container).className.split(' ');
    expect(classes).toEqual(expect.arrayContaining(['heading-small-caps', 'bullet-dash', 'spacing-airy', 'accent-navy', 'header-left']));
    show(resume({ layout: { font_size: 11, margin: 18, heading_style: 'bold', bullet_char: '▪', section_spacing: 'compact', accent_color: 'maroon', header_align: 'center' } }));
    const second = paper(document.body.lastElementChild as HTMLElement).className;
    expect(second).toMatch(/heading-bold.*accent-maroon|accent-maroon.*heading-bold/);
    expect(second).toContain('bullet-square'); expect(second).toContain('spacing-compact'); expect(second).toContain('header-center');
  });

  it('joins the contact line with the chosen separator', () => {
    const { container, rerender } = show(resume({ layout: { font_size: 11, margin: 18, contact_separator: '|' } }));
    expect(container.querySelector('.paper-header div')!.textContent).toBe('alice@example.com  |  +65 5555 0100  |  Singapore');
    rerender(<ResumePreview resume={resume({ layout: { font_size: 11, margin: 18, contact_separator: 'newline' } })} />);
    expect(container.querySelector('.paper-header div')!.textContent).toBe('alice@example.com\n+65 5555 0100\nSingapore');
    expect(paper(container).className).toContain('contact-lines');
  });

  it('renders date ranges in the chosen format and keeps typed dates as typed', () => {
    const doc = resume({ layout: { font_size: 11, margin: 18, date_format: 'July 2023', present_label: 'Current' } });
    doc.content.sections[0].entries[0].date_range = { start: '2023-07', end: null, current: true };
    doc.content.sections[0].entries.push({ id: 'e9', heading: 'Intern', subheading: '', dates: 'Summer 2021', bullets: [] });
    doc.content.sections[0].entries[1].date_range = undefined;
    show(doc);
    expect(screen.getByText('July 2023 – Current')).toBeInTheDocument();
    expect(screen.getByText('Summer 2021')).toBeInTheDocument();
    expect(screen.queryByText('Jul 2023 – Present')).not.toBeInTheDocument();
  });

  it('falls back to typed dates when a range renders to nothing, and uses defaults when keys are absent', () => {
    const doc = resume();
    doc.content.sections[0].entries[0].date_range = { start: '2023-07', end: '2024-02', current: false };
    show(doc);
    expect(screen.getByText('Jul 2023 – Feb 2024')).toBeInTheDocument();
    cleanup();
    doc.content.sections[0].entries[0].date_range = { start: null, end: null, current: false };
    show(doc);
    expect(screen.getByText('Jul 2023 – Present')).toBeInTheDocument();
  });

  describe('skills layout', () => {
    const skillsDoc = (skills_layout: 'inline' | 'grouped' | 'columns') => resume({ layout: { font_size: 11, margin: 18, skills_layout } });
    it('groups skills under their labels', () => {
      const { container } = show(skillsDoc('grouped'));
      const lines = [...container.querySelectorAll('.paper-skills.grouped p')].map((line) => line.textContent);
      expect(lines).toEqual(['Languages: Python, SQL', 'Tools: Docker, Git']);
    });
    it('runs skills together on one line', () => {
      const { container } = show(skillsDoc('inline'));
      expect(container.querySelector('.paper-skills.inline')!.textContent).toBe('Python, SQL, Docker, Git');
    });
    it('lists skills in columns', () => {
      const { container } = show(skillsDoc('columns'));
      expect(within(container.querySelector('.paper-skills.columns') as HTMLElement).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Python', 'SQL', 'Docker', 'Git']);
    });
    it('treats a section marked as skills the same even with another title', () => {
      const doc = skillsDoc('inline'); doc.content.sections[1].title = 'Toolbox'; doc.content.sections[1].kind = 'skills';
      const { container } = show(doc);
      expect(container.querySelector('.paper-skills.inline')).not.toBeNull();
    });
  });
});
