import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import { toast } from '../lib/toast.jsx';

// Empty the toast store between tests: a toast left by one test must not
// satisfy a later test's wait for the same message (review W2b-U1).
// Registered FIRST on purpose: vitest runs afterEach hooks in reverse
// (`sequence.hooks: 'stack'`), so this runs after the unmount below and does
// not update a still-mounted ToastViewport outside act.
afterEach(() => toast.clear());
// Vitest runs without globals, so Testing Library's auto-cleanup hook is not
// registered — unmount rendered trees between tests explicitly.
afterEach(() => cleanup());

// jsdom has no layout: window.scrollTo only logs "Not implemented". The
// workspace scrolls to the top when an analysis starts (Analyze.jsx).
window.scrollTo = () => {};
