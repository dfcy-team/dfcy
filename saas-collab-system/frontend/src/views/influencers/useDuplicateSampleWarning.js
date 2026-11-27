import { ref, watch } from 'vue';
import { fetchDuplicateSampleRecords } from '../../api/influencers';

const labels = { pending: '待处理', shipped: '已发货', delivered: '已送达', overdue: '已逾期', blacklisted: '已拉黑' };

export function useDuplicateSampleWarning(getInfluencer) {
  const warning = ref('');
  watch(getInfluencer, async (influencer, _, onCleanup) => {
    warning.value = '';
    if (!influencer) return;
    let active = true;
    onCleanup(() => { active = false; });
    try {
      const response = await fetchDuplicateSampleRecords(influencer);
      if (!active || !response.success) return;
      const matches = (response.data?.records || []).filter(record => labels[record.status]);
      if (matches.length) {
        warning.value = `该达人已有送样：${matches.map(record => `${record.fulfillment_no}（${labels[record.status]}）`).join('、')}。请确认是否重复送样。`;
      }
    } catch {
      // The optional warning must not block creation.
    }
  }, { immediate: true });
  return warning;
}
