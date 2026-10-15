import type { ProfileDraft } from '../types';

export const emptyProfile = { name: '', email: '', phone: '', location: '', headline: '', summary: '', skills: '' };
const asString = (value: unknown) => typeof value === 'string' ? value : '';
export const profileToForm = (draft: ProfileDraft | undefined) => ({ ...emptyProfile, ...(draft || {}), skills: Array.isArray(draft?.skills) ? draft.skills.join(', ') : asString(draft?.skills) });
export const formToProfile = (form: typeof emptyProfile): ProfileDraft => ({ ...form, skills: form.skills.split(',').map((x) => x.trim()).filter(Boolean) });
