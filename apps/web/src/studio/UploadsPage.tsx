import { DocTabs } from '../letters/DocTabs';
import type { DocumentTab } from '../routes';
import { UploadedResumes } from './UploadedResumes';

/** The "Uploaded files" tab of My documents: the original PDF and Word files, beside resumes and cover letters. */
export function UploadsPage({ onSection, resumeCount }: { onSection: (section: DocumentTab) => void; resumeCount: number }) {
  return <div className="page-wrap">
    <div className="page-heading"><div><div className="eyebrow">YOUR DOCUMENTS</div><h1>My documents</h1><p>Your resumes, cover letters and the original files you uploaded, in one place.</p></div></div>
    <DocTabs section="uploads" onSection={onSection} resumeCount={resumeCount} letterCount={null} />
    <UploadedResumes />
  </div>;
}
