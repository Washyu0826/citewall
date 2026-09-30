// Loading skeletons. Plain divs with Tailwind animate-pulse (removed under
// prefers-reduced-motion by the global rule in index.css).

const LINE_WIDTHS = ['w-full', 'w-5/6', 'w-4/6', 'w-11/12', 'w-3/4'];

export function Skeleton({ className = '' }) {
  return <div className={`animate-pulse rounded bg-surface-sunken ${className}`} aria-hidden="true" />;
}

export function SkeletonText({ lines = 3, className = '' }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={`h-3 ${LINE_WIDTHS[i % LINE_WIDTHS.length]}`} />
      ))}
    </div>
  );
}

export function SkeletonBar({ className = '' }) {
  return <Skeleton className={`h-1.5 w-full ${className}`} />;
}

export function SkeletonCard({ className = '' }) {
  return (
    <div className={`space-y-3 rounded-brand border border-line bg-surface-raised p-4 ${className}`}>
      <Skeleton className="h-4 w-1/3" />
      <SkeletonText lines={3} />
      <SkeletonBar />
    </div>
  );
}

export default Skeleton;
