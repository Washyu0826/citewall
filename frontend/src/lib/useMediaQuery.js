import { useEffect, useState } from 'react';

/**
 * `true` while the CSS media query matches. Used where a layout must render
 * ONE variant (not two with `hidden` classes) — duplicated DOM would duplicate
 * ids, labels and test ids.
 */
export function useMediaQuery(query) {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return undefined;
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}
