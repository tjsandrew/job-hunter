import type { ProfileBank, ProfileItem, Resume } from '../../types';

const base = { archived_at: null, origin: 'manual' as const, import_id: null, parent_id: null, revision: 1 };
const point = (id: string, text: string, tags: string[], skills: string[] = [], alternatives: { id: string; text: string }[] = []) => ({ id, text, tags, skills, alternatives });

export const items: ProfileItem[] = [
  { ...base, id: 'exp-1', kind: 'experience', position: 0, tags: [], data: { title: 'Backend Engineer', organisation: 'Harbour Metrics', start: '2023-07', end: null, current: true, bullets: [
    point('b1', 'Built FastAPI services on PostgreSQL.', ['backend'], ['FastAPI', 'PostgreSQL']),
    point('b2', 'Made analytics dashboards 4x faster.', ['data']),
    point('b3', 'Cut p95 query time by 40%.', ['backend'], ['PostgreSQL'], [{ id: 'v1', text: 'Reduced p95 query latency by 40% across reporting.' }]),
    point('b4', 'Added REST endpoints with integration tests.', ['backend']),
    point('b5', 'Mentored two interns.', ['leadership']),
  ] } },
  { ...base, id: 'exp-2', kind: 'experience', position: 1, tags: [], data: { title: 'Data Analyst', organisation: 'Straits Commerce', start: '2022-07', end: '2023-06', bullets: [point('d1', 'Automated weekly reports.', ['data'])] } },
  { ...base, id: 'edu-1', kind: 'education', position: 2, tags: [], data: { qualification: 'BSc Computer Science', institution: 'NUS', start: '2018', end: '2022', bullets: [] } },
  { ...base, id: 'proj-1', kind: 'project', position: 3, tags: [], data: { name: 'Booking app', start: '2021', end: '2021', bullets: [point('p1', 'Built a React booking app.', ['frontend'])] } },
  { ...base, id: 'skill-py', kind: 'skill', position: 4, tags: [], data: { name: 'Python', category: 'language', bullets: [] } },
  { ...base, id: 'skill-sql', kind: 'skill', position: 5, tags: [], data: { name: 'SQL', category: 'language', bullets: [] } },
];
export const emptyGroups = { experience: [], education: [], project: [], skill: [], certification: [], award: [], volunteering: [], custom: [] };
export const bank = (): ProfileBank => ({ basics: { name: 'Alice Tan' }, items: structuredClone(items), grouped: structuredClone(emptyGroups), bank_revision: 4, confirmed_revision: null, profile_epoch: 0 });

export const resume = (patch: Partial<Resume> = {}): Resume => ({ id: 'r1', title: 'Backend Engineer – Stripe', kind: 'resume', revision: 2, template: 'classic', reviewed_revision: null, job_id: null,
  layout: { font_size: 11, margin: 18 },
  content: { name: 'Alice Tan', email: 'alice@example.com', phone: '+65 5555 0100', location: 'Singapore', summary: 'Backend engineer.', sections: [
    { id: 's1', title: 'Experience', entries: [{ id: 'e1', heading: 'Backend Engineer', subheading: 'Harbour Metrics', dates: 'Jul 2023 – Present', bullets: ['Built FastAPI services.', 'Cut p95 query time.'] }] },
    { id: 's2', title: 'Skills', entries: [{ id: 'e2', heading: 'Languages', subheading: '', dates: '', bullets: ['Python, SQL'] }, { id: 'e3', heading: 'Tools', subheading: '', dates: '', bullets: ['Docker', 'Git'] }] },
    { id: 's3', title: 'Fun facts', entries: [{ id: 'e4', heading: 'Chess', subheading: '', dates: '', bullets: [] }] },
  ] }, ...patch });

/** Items for the certifications / awards / volunteering sections, and a project that belongs to the Backend Engineer job. */
export const extraItems: ProfileItem[] = [
  { ...base, id: 'cert-1', kind: 'certification', position: 6, tags: ['backend'], data: { name: 'AWS Developer Associate', issuer: 'Amazon', start: '2024-03', bullets: [] } },
  { ...base, id: 'award-1', kind: 'award', position: 7, tags: ['backend'], data: { title: 'Hackathon winner', awarder: 'City Council', start: '2021', bullets: [] } },
  { ...base, id: 'vol-1', kind: 'volunteering', position: 8, tags: [], data: { title: 'Mentor', organisation: 'Code Club', start: '2020', end: '2021', bullets: [point('v-b1', 'Taught Python to teenagers.', ['education'])] } },
  { ...base, id: 'proj-job', kind: 'project', position: 9, parent_id: 'exp-1', tags: [], data: { name: 'Billing rewrite', start: '2023', end: '2023', bullets: [point('pj1', 'Rewrote the billing service.', ['backend'])] } },
];
export const bankWithExtras = (): ProfileBank => { const data = bank(); data.items.push(...structuredClone(extraItems)); return data; };
