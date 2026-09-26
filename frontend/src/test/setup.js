import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// Vitest runs without globals, so Testing Library's auto-cleanup hook is not
// registered — unmount rendered trees between tests explicitly.
afterEach(() => cleanup());
