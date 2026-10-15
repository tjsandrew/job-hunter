import { Field } from '../ui';
import type { ResumeContent } from '../types';

export function ContactEditor({ content, onContent }: { content: ResumeContent; onContent: (v: ResumeContent) => void }) {
  const keys: (keyof ResumeContent)[] = ['name', 'email', 'phone', 'location']; const labels: Record<string, string> = { name: 'Full name', email: 'Email', phone: 'Phone', location: 'Location' };
  return <div className="contact-editor"><h3>Contact details</h3><div className="form-grid two-col">{keys.map((key) => <Field key={key} label={labels[key]} value={content[key] as string} onChange={(value) => onContent({ ...content, [key]: value })} placeholder={labels[key]} />)}</div></div>;
}
