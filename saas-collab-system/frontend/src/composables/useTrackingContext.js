import { onBeforeUnmount, watch } from 'vue';
export function useTrackingContext(source) {
  const publish = value => window.dispatchEvent(new CustomEvent('issue-tracking-context', { detail: value }));
  watch(source, value => publish(value || null), { immediate: true, deep: true });
  onBeforeUnmount(() => publish(null));
}
