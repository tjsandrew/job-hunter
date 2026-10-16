import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChoiceChips, TagInput } from './ui';

afterEach(cleanup);

function Roles({ initial = [] as string[] }) {
  const [values, setValues] = useState<string[]>(initial);
  return <><TagInput label="Roles" values={values} onChange={setValues} placeholder="add a role" /><output aria-label="current">{JSON.stringify(values)}</output></>;
}
const current = () => JSON.parse(screen.getByLabelText('current').textContent || '[]') as string[];

describe('TagInput', () => {
  it('adds values one at a time with Enter and shows each as a removable chip', async () => {
    const user = userEvent.setup();
    render(<Roles />);
    const box = screen.getByLabelText('Add Roles');
    await user.type(box, 'Backend Engineer{Enter}');
    await user.type(box, 'Data Analyst{Enter}');
    expect(current()).toEqual(['Backend Engineer', 'Data Analyst']);
    expect(screen.getByRole('button', { name: 'Remove Backend Engineer' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove Backend Engineer' }));
    expect(current()).toEqual(['Data Analyst']);
  });

  it('treats a comma as "add this one", ignores blanks and case-insensitive duplicates', async () => {
    const user = userEvent.setup();
    render(<Roles initial={['Data Analyst']} />);
    const box = screen.getByLabelText('Add Roles');
    await user.type(box, 'data analyst,');
    await user.type(box, '   {Enter}');
    await user.type(box, 'Platform Engineer,');
    expect(current()).toEqual(['Data Analyst', 'Platform Engineer']);
  });

  it('keeps a half-typed value when the box loses focus, and Backspace removes the last chip', async () => {
    const user = userEvent.setup();
    render(<><Roles /><button>elsewhere</button></>);
    const box = screen.getByLabelText('Add Roles');
    await user.type(box, 'Support Engineer');
    await user.click(screen.getByRole('button', { name: 'elsewhere' }));
    expect(current()).toEqual(['Support Engineer']);
    await user.click(box);
    await user.keyboard('{Backspace}');
    expect(current()).toEqual([]);
  });
});

describe('ChoiceChips', () => {
  it('toggles fixed options on and off', async () => {
    const user = userEvent.setup();
    function Modes() {
      const [values, setValues] = useState<string[]>(['hybrid']);
      return <><ChoiceChips label="Work modes" options={[{ value: 'remote', label: 'Remote' }, { value: 'hybrid', label: 'Hybrid' }]} values={values} onChange={setValues} /><output aria-label="modes">{values.join(',')}</output></>;
    }
    render(<Modes />);
    expect(screen.getByRole('button', { name: 'Hybrid' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Remote' }));
    expect(screen.getByLabelText('modes').textContent).toBe('hybrid,remote');
    await user.click(screen.getByRole('button', { name: 'Hybrid' }));
    expect(screen.getByLabelText('modes').textContent).toBe('remote');
  });
});
