import { onBeforeUnmount, ref } from 'vue';

// Keep table and pager behavior in sync with the responsive layout.
export function useCompactViewport(breakpoint = 760) {
  const media = typeof window.matchMedia === 'function'
    ? window.matchMedia(`(max-width: ${breakpoint}px)`)
    : null;
  const compact = ref(media?.matches ?? false);
  const update = (event) => { compact.value = event.matches; };
  media?.addEventListener('change', update);
  onBeforeUnmount(() => media?.removeEventListener('change', update));
  return compact;
}
