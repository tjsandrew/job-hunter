import type { CoverLetter, LetterContent, LetterNote, ResumeLayout, Template } from '../types';
import { Field, Icon } from '../ui';
import { LetterPreview } from './LetterPreview';
import './letters.css';

export type LetterEditorProps = {
  letter: CoverLetter; notes: LetterNote[]; jobTitle?: string; saveLabel: string; busy: boolean;
  attachLabel: string | null; attachedRevision: number | null;
  onTitle: (title: string) => void; onContent: (content: LetterContent) => void; onLayout: (layout: ResumeLayout) => void; onTemplate: (template: Template) => void;
  onReview: () => void; onDownload: () => void; onAttach: () => void; onBack: () => void; onDelete: () => void; onAnother?: () => void;
};

const FONT_SIZES = [9, 10, 11, 12, 13, 14];
const MARGINS = [15, 18, 20, 22, 25, 28, 30];

export function LetterEditor(props: LetterEditorProps) {
  const { letter, notes, jobTitle, saveLabel, busy, attachLabel, attachedRevision } = props;
  const { content, layout } = letter;
  const saved = saveLabel === 'Saved';
  const reviewed = letter.reviewed_revision === letter.revision;
  const setContent = (changes: Partial<LetterContent>) => props.onContent({ ...content, ...changes });
  const setParagraph = (index: number, text: string) => setContent({ paragraphs: content.paragraphs.map((item, at) => (at === index ? text : item)) });
  const move = (index: number, by: number) => {
    const next = [...content.paragraphs]; const target = index + by;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setContent({ paragraphs: next });
  };
  return <div className="editor-page letter-editor" data-busy={busy ? 'true' : 'false'} aria-busy={busy}>
    <div className="editor-head">
      <button className="back-link" onClick={props.onBack}><Icon name="back" /> Cover letters</button>
      <div className="editor-title"><input aria-label="Letter title" disabled={busy} value={letter.title} onChange={(event) => props.onTitle(event.target.value)} /><span className={`save-state ${saved ? 'saved' : ''}`}><i />{saveLabel}</span></div>
      <div className="editor-actions">
        {props.onAnother && <button className="button secondary" onClick={props.onAnother} disabled={busy}>Write another version</button>}
        <button className="icon-button danger" title="Delete letter" aria-label="Delete letter" onClick={props.onDelete} disabled={busy || !saved}><Icon name="trash" /></button>
      </div>
    </div>
    {jobTitle && <p className="letter-for">Written for <strong>{jobTitle}</strong></p>}
    {/* The same toolbar as the resume editor: the style buttons on the left, the layout settings as a pop-over on the right. */}
    <div className="editor-toolbar"><div className="template-select"><span>STYLE</span>
      <button className={letter.template === 'classic' && layout.font_family !== 'latex' ? 'selected' : ''} disabled={busy} onClick={() => { props.onTemplate('classic'); props.onLayout({ ...layout, font_family: 'auto' }); }}>Classic serif</button>
      <button className={layout.font_family === 'latex' ? 'selected' : ''} disabled={busy} onClick={() => { props.onTemplate('classic'); props.onLayout({ ...layout, font_family: 'latex' }); }}>LaTeX classic</button>
      <button className={letter.template === 'modern' ? 'selected' : ''} disabled={busy} onClick={() => { props.onTemplate('modern'); props.onLayout({ ...layout, font_family: 'auto' }); }}>Modern sans</button></div>
      <div className="layout-controls"><details className="resume-layout-settings"><summary>Layout settings</summary><div className="resume-layout-fields">
        <label>Size <select aria-label="Font size" value={layout.font_size} disabled={busy} onChange={(event) => props.onLayout({ ...layout, font_size: Number(event.target.value) })}>{FONT_SIZES.map((size) => <option key={size}>{size}</option>)}</select></label>
        <label>Margin <select aria-label="Page margin" value={layout.margin} disabled={busy} onChange={(event) => props.onLayout({ ...layout, margin: Number(event.target.value) })}>{MARGINS.map((size) => <option key={size} value={size}>{size} mm</option>)}</select></label>
        <label>Typeface <select aria-label="Letter typeface" value={layout.font_family || 'auto'} disabled={busy} onChange={(event) => props.onLayout({ ...layout, font_family: event.target.value as NonNullable<ResumeLayout['font_family']> })}>{[['auto', 'Template default'], ['serif', 'Serif'], ['latex', 'Latin Modern (LaTeX)'], ['sans', 'Sans serif'], ['mono', 'Monospace']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>Line spacing <select aria-label="Line spacing" value={layout.line_spacing || 1.3} disabled={busy} onChange={(event) => props.onLayout({ ...layout, line_spacing: Number(event.target.value) })}>{[1, 1.15, 1.3, 1.4, 1.6, 1.8].map((value) => <option key={value} value={value}>{value.toFixed(2).replace(/0$/, '')}</option>)}</select></label>
        <label>Paper <select aria-label="Page size" value={layout.page_size || 'A4'} disabled={busy} onChange={(event) => props.onLayout({ ...layout, page_size: event.target.value as 'A4' | 'letter' })}><option value="A4">A4</option><option value="letter">US Letter</option></select></label>
      </div></details></div></div>
    <div className="editor-main letter-main" inert={busy}>
      <div className="editor-pane letter-pane">
        {notes.length > 0 && <section className="letter-notes" aria-label="Check these before you send">
          {/* Open when something needs a look; folded when everything was confirmed, so the fields stay in view. */}
          <details open={notes.some((note) => note.kind === 'warn')}>
            <summary>Check these before you send <span>{notes.filter((note) => note.kind === 'ok').length} confirmed{notes.some((note) => note.kind === 'warn') ? `, ${notes.filter((note) => note.kind === 'warn').length} to check` : ''}</span></summary>
            <ul>{notes.map((note, index) => <li key={index} className={note.kind}>{note.kind !== 'info' && <Icon name={note.kind === 'ok' ? 'check' : 'alert'} />}<span>{note.text}</span></li>)}</ul>
          </details>
        </section>}
        <div className="editor-scroll">
          <Field label="Addressed to" value={content.recipient} onChange={(value) => setContent({ recipient: value })} multiline />
          <div className="letter-two"><Field label="Date" value={content.date} onChange={(value) => setContent({ date: value })} /><Field label="Greeting" value={content.greeting} onChange={(value) => setContent({ greeting: value })} /></div>
          {content.paragraphs.map((paragraph, index) => <div className="letter-paragraph" key={index}>
            <Field label={`Paragraph ${index + 1}`} value={paragraph} onChange={(value) => setParagraph(index, value)} multiline />
            <div className="letter-paragraph-tools">
              <button type="button" className="icon-button" aria-label={`Move paragraph ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}><Icon name="up" /></button>
              <button type="button" className="icon-button" aria-label={`Move paragraph ${index + 1} down`} disabled={index === content.paragraphs.length - 1} onClick={() => move(index, 1)}><Icon name="down" /></button>
              <button type="button" className="icon-button danger" aria-label={`Remove paragraph ${index + 1}`} disabled={content.paragraphs.length <= 1} onClick={() => setContent({ paragraphs: content.paragraphs.filter((_, at) => at !== index) })}><Icon name="trash" /></button>
            </div>
          </div>)}
          <button type="button" className="button text-button" disabled={content.paragraphs.length >= 12} onClick={() => setContent({ paragraphs: [...content.paragraphs, ''] })}><Icon name="plus" /> Add paragraph</button>
          <div className="letter-two"><Field label="Closing" value={content.closing} onChange={(value) => setContent({ closing: value })} /><Field label="Signed" value={content.signature} onChange={(value) => setContent({ signature: value })} /></div>
          <details className="letter-details"><summary>Your details</summary>
            <div className="letter-two"><Field label="Name" value={content.name} onChange={(value) => setContent({ name: value })} /><Field label="Email" value={content.email} onChange={(value) => setContent({ email: value })} /></div>
            <div className="letter-two"><Field label="Phone" value={content.phone} onChange={(value) => setContent({ phone: value })} /><Field label="Location" value={content.location} onChange={(value) => setContent({ location: value })} /></div>
          </details>
        </div>
      </div>
      <div className="preview-pane letter-preview-pane"><div className="preview-head"><div><strong>Live preview</strong><span>The PDF follows this layout</span></div></div><div className="paper-stage"><LetterPreview letter={letter} /></div></div>
    </div>
    <div className="editor-footer">
      <span><span className="footer-dot" />{saved ? 'All changes saved' : saveLabel}</span>
      <button className="button text-button" title="Confirm that you have read this saved revision" onClick={props.onReview} disabled={busy || !saved || reviewed}>{reviewed ? <><Icon name="check" /> Reviewed</> : 'Mark as reviewed'}</button>
      <button className="button secondary small-button" disabled={busy || !reviewed || !saved} onClick={props.onDownload}><Icon name="download" /> Download PDF</button>
      {attachLabel && <button className="button primary small-button" disabled={busy || !reviewed || !saved || attachedRevision === letter.revision} onClick={props.onAttach}>{attachedRevision === letter.revision ? 'Attached to application' : attachLabel}</button>}
    </div>
  </div>;
}
