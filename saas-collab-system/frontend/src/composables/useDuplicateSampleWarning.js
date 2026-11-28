import { computed, onScopeDispose, ref, unref, watch } from 'vue';
import { fetchDuplicateSampleRecords } from '../api/influencers';
import { useAuthStore } from '../stores/auth';
import { cockpitActorKey } from '../utils/cockpitDraft';

const labels = { pending: '待处理', shipped: '已发货', delivered: '已签收', overdue: '已逾期', blacklisted: '已拉黑' };
const read = value => typeof value === 'function' ? value() : unref(value);

// Optional create-dialog guidance, never an additional creation gate.
export function useDuplicateSampleWarning(active, influencerId) {
  const auth = useAuthStore();
  const records = ref([]);
  let generation = 0, controller;
  const actorKey = () => cockpitActorKey(auth.currentUser);
  const id = () => String(read(influencerId) ?? '');
  const visible = () => Boolean(read(active));
  const reset = () => { generation++; controller?.abort(); controller = undefined; records.value = []; };
  watch([visible, id, actorKey, () => auth.currentUser, () => auth.authorizationStale], async () => {
    reset();
    const token = generation, actor = actorKey(), user = auth.currentUser, selected = id();
    if (!visible() || !actor || auth.authorizationStale || !/^[1-9][0-9]*$/.test(selected)) return;
    controller = new AbortController();
    try {
      const response = await fetchDuplicateSampleRecords(selected, { signal: controller.signal });
      if (token !== generation || !visible() || selected !== id() || actor !== actorKey()
          || auth.currentUser !== user || auth.authorizationStale) return;
      const items = response?.success && Array.isArray(response.data?.records) ? response.data.records : [];
      records.value = items.filter(row => row && typeof row.fulfillment_no === 'string' && labels[row.status])
        .slice(0, 3).map(row => ({ fulfillment_no: row.fulfillment_no, status: row.status }));
    } catch {
      // A denied, stale, cancelled or unavailable warning must not block create.
      if (token === generation) records.value = [];
    }
  }, { immediate: true });
  onScopeDispose(reset);
  const warning = computed(() => records.value.length
    ? `该达人已有${records.value.map(row => `${row.fulfillment_no}（${labels[row.status]}）`).join('、')}送样记录，请确认是否重复送样；仍可继续创建。` : '');
  return { records, warning };
}
