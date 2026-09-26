import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { QueryClientProvider } from '@tanstack/react-query';

import App from './App.jsx';
import CrashFallback from './components/CrashFallback.jsx';
import { ThemeProvider } from './lib/theme.jsx';
import { queryClient } from './lib/queryClient.js';
import i18n from './lib/i18n.js';
import { ToastViewport } from './lib/toast.jsx';
import { initSentry, SentryErrorBoundary } from './lib/sentry.jsx';
import './index.css';

// Day 5: init Sentry before render so React errors are captured by the boundary.
initSentry();


createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <SentryErrorBoundary fallback={<CrashFallback />}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <BrowserRouter>
              <App />
              <ToastViewport />
            </BrowserRouter>
          </ThemeProvider>
        </QueryClientProvider>
      </I18nextProvider>
    </SentryErrorBoundary>
  </React.StrictMode>
);
