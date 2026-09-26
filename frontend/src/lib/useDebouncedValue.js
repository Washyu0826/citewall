import { useEffect, useState } from 'react';

/**
 * Return `value` only after it has stopped changing for `delayMs`.
 * Used so typing a case ID doesn't fire one /v1/quota request per keystroke.
 */
export function useDebouncedValue(value, delayMs = 400) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
