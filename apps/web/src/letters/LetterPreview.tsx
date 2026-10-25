import { useLayoutEffect, useRef, useState } from 'react';
import type { CoverLetter } from '../types';
import { paperDimensions } from '../studio/ResumePreview';
import './letters.css';

const PX_PER_MM = 96 / 25.4;

/** The letter on a sheet of the chosen paper, scaled down to fit the pane. Says so when the text runs past one page. */
export function LetterPreview({ letter }: { letter: CoverLetter }) {
  const { content, layout, template } = letter;
  const dimensions = paperDimensions(layout.page_size);
  const width = dimensions.width * PX_PER_MM, height = dimensions.height * PX_PER_MM;
  const margin = (layout.margin ?? 22) * PX_PER_MM;
  const box = useRef<HTMLDivElement>(null);
  const paper = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.7);
  const [overflow, setOverflow] = useState(false);
  const signature = [content.email, content.phone, content.location].filter(Boolean).join('  ·  ');
  useLayoutEffect(() => {
    const measure = () => {
      if (box.current && box.current.clientWidth > 0) setScale(Math.min(1, box.current.clientWidth / width));
      if (paper.current) setOverflow(paper.current.scrollHeight > height + 1);
    };
    measure();
    if (typeof ResizeObserver === 'undefined' || !box.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(box.current);
    return () => observer.disconnect();
  }, [JSON.stringify(content), JSON.stringify(layout), template, width, height]);
  return <div className="letter-preview" ref={box}>
    <div className="letter-frame" style={{ width: width * scale, height: height * scale }}>
      <div ref={paper} className={`letter-paper font-${layout.font_family || 'auto'} ${template}`} aria-label="Letter preview" role="img"
        style={{ width, height, padding: margin, fontSize: ((layout.font_size ?? 11) * 96) / 72, lineHeight: layout.line_spacing ?? 1.3, transform: `scale(${scale})` }}>
        <header><h1>{content.name || 'Your Name'}</h1>{signature && <p>{signature}</p>}</header>
        {content.date && <p>{content.date}</p>}
        {content.recipient && <p className="letter-lines">{content.recipient}</p>}
        {content.greeting && <p>{content.greeting}</p>}
        {content.paragraphs.filter((paragraph) => paragraph.trim()).map((paragraph, index) => <p key={index} className="letter-lines">{paragraph}</p>)}
        {content.closing && <p>{content.closing}</p>}
        <p>{content.signature || content.name}</p>
      </div>
    </div>
    {overflow && <p className="letter-overflow" role="status">This letter is longer than one page. Shorten it, or reduce the size or margin.</p>}
  </div>;
}
