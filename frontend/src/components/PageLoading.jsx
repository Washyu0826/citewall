import { useTranslation } from 'react-i18next';

import { Skeleton, SkeletonText } from './Skeleton.jsx';
import { Page } from './ui/page.jsx';

/**
 * Placeholder while a lazily loaded page downloads (research 09 FE-L4). Keeps
 * the page frame so the shell does not jump, and tells screen readers what is
 * happening.
 */
export function PageLoading() {
  const { t } = useTranslation();
  return (
    <Page>
      <div role="status" aria-live="polite">
        <span className="sr-only">{t('page.loading')}</span>
        <Skeleton className="mb-8 h-9 w-64" />
        <SkeletonText lines={4} className="max-w-3xl" />
      </div>
    </Page>
  );
}

export default PageLoading;
