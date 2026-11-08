import type { DocumentTab } from '../routes';
import './letters.css';

/** The switch under the "My documents" heading: one tab per kind of document, each with its count when known. */
export function DocTabs({ section, onSection, resumeCount, letterCount, uploadCount = null }: { section: DocumentTab; onSection: (section: DocumentTab) => void; resumeCount: number; letterCount: number | null; uploadCount?: number | null }) {
  const tab = (value: DocumentTab, label: string, count: number | null) => <button type="button" role="tab" id={`doc-tab-${value}`} aria-selected={section === value} className={`doc-tab ${section === value ? 'active' : ''}`} onClick={() => onSection(value)}>{label}{count !== null && <span className="doc-count">{count}</span>}</button>;
  return <div role="tablist" aria-label="Documents" className="doc-tabs">{tab('resumes', 'Resumes', resumeCount)}{tab('letters', 'Cover letters', letterCount)}{tab('uploads', 'Uploaded files', uploadCount)}</div>;
}
