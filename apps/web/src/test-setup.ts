import '@testing-library/jest-dom/vitest';
import { beforeEach } from 'vitest';
import { clearLists } from './listCache';

// What the app remembers in browser memory between screens (listCache.ts) must not leak from one test into the next.
beforeEach(() => clearLists());
