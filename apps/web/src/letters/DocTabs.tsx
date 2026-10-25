import type { DocumentTab } from '../routes';
import './letters.css';

/** The switch under the "My resumes" heading: resumes and cover letters are two views of the same page. */
export function DocTabs({ section, onSection, resumeCount, letterCount }: { section: DocumentTab; onSection: (section: DocumentTab) => void; resumeCount: number; letterCount: number | null }) {
  const tab = (value: DocumentTab, label: string, count: number | null) => <button type="button" role="tab" id={`doc-tab-${value}`} aria-selected={section === value} className={`doc-tab ${section === value ? 'active' : ''}`} onClick={() => onSection(value)}>{label}{count !== null && <span className="doc-count">{count}</span>}</button>;
  return <div role="tablist" aria-label="Documents" className="doc-tabs">{tab('resumes', 'Resumes', resumeCount)}{tab('letters', 'Cover letters', letterCount)}</div>;
}
