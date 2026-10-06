import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import { toast } from '../lib/toast.jsx';

// Vitest runs without globals, so Testing Library's auto-cleanup hook is not
// registered — unmount rendered trees between tests explicitly.
afterEach(() => cleanup());
// …and empty the toast store: a toast left by one test must not satisfy
// the next test's wait for the same message (review W2b-U1).
afterEach(() => toast.clear());

// jsdom has no layout: window.scrollTo only logs "Not implemented". The
// workspace scrolls to the top when an analysis starts (Analyze.jsx).
window.scrollTo = () => {};
