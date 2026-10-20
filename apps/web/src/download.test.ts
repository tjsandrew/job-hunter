import { afterEach, expect, test, vi } from 'vitest';
import { downloadFile } from './download';

afterEach(() => vi.restoreAllMocks());

test('signed downloads navigate directly without fetching or attaching credentials', () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch');
  let navigated = '';
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { navigated = this.href; });
  downloadFile({url: 'https://documents.example.test/resume?signature=test'}, 'resume.pdf');
  expect(navigated).toBe('https://documents.example.test/resume?signature=test');
  expect(fetchSpy).not.toHaveBeenCalled();
});

test('rejects executable download URLs', () => {
  expect(() => downloadFile({url: 'javascript:alert(1)'}, 'resume.pdf')).toThrow('Invalid download');
});
