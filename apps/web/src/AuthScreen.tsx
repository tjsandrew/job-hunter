import type { ReactNode } from 'react';
import { BrandLogo, Icon } from './ui';

const highlights = [
  { icon: 'search', title: 'Discover', text: 'Roles ranked against your own experience.' },
  { icon: 'check', title: 'Check your fit', text: 'See which requirements you meet, with evidence.' },
  { icon: 'studio', title: 'Apply with confidence', text: 'Tailor a resume and track every application.' },
];

/** Shared full-page frame for the signed-out screens, in the same colours and type as the workspace. */
export function AuthScreen({ title, text, children }: { title: string; text?: string; children: ReactNode }) {
  return <div className="auth-screen">
    <aside className="auth-hero">
      <div className="auth-hero-brand"><BrandLogo size={46} /><div><strong>job hunter</strong><span>CAREER WORKSPACE</span></div></div>
      <div className="auth-hero-body">
        <h2>Find the role.<br />Fit the role.<br />Land the role.</h2>
        <ul>{highlights.map((item) => <li key={item.title}><span className="auth-hero-icon"><Icon name={item.icon} /></span><div><strong>{item.title}</strong><p>{item.text}</p></div></li>)}</ul>
      </div>
    </aside>
    <main className="auth-panel">
      <section className="auth-card">
        <div className="auth-card-logo"><BrandLogo size={56} /></div>
        <h1>{title}</h1>
        {text && <p className="auth-lead">{text}</p>}
        {children}
      </section>
    </main>
  </div>;
}
