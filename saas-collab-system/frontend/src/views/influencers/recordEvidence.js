import { sampledInfluencerCount } from './outreachTaskState';

const text = (value) => String(value ?? '').trim();
const historicalSources = new Set(['feishu_full_20260908', 'legacy_shop_analytics_bd']);

export function hasPlatformIdentity(row) {
  return Boolean(text(row?.nickname_id ?? row?.handle) || text(row?.profile?.external_influencer_id));
}

export function archiveStateLabel(row) {
  if (row?.is_blacklisted) return '已拉黑';
  if (row?.status !== 'active') return '停用';
  return hasPlatformIdentity(row) ? '正常' : '启用 · 身份待补全';
}

export function recordSourceLabel(row) {
  return ({ feishu_full_20260908: '飞书历史导入', legacy_shop_analytics_bd: '历史店铺分析导入', manual: '手工登记' })[row?.source] || '未明确标注的来源';
}

export function taskProgressNotice(row) {
  if (!row || !['pending', 'in_progress'].includes(row.status)) return '';
  const count = sampledInfluencerCount(row);
  const reached = Number(row.target_count) > 0 && count >= Number(row.target_count);
  if (!count) return '';
  const prefix = historicalSources.has(row.source)
    ? '历史导入任务保留来源登记的状态，送样进度独立统计。'
    : '任务已有送样记录，任务状态与送样进度分别显示。';
  if (reached) return `${prefix}已达到送样目标，请核对任务状态。`;
  return row.status === 'pending' ? `${prefix}当前仍为待开始，请核对。` : '';
}

export function matchedVideoCount(row) {
  if (row?.video_match_count !== null && row?.video_match_count !== undefined && row?.video_match_count !== '') {
    const count = Number(row.video_match_count);
    if (Number.isFinite(count) && count >= 0) return count;
  }
  return Array.isArray(row?.video_matches) ? row.video_matches.length : null;
}

export function publishedEvidenceNotice(row) {
  if (row?.status !== 'published' || matchedVideoCount(row) !== 0) return '';
  return `记录来源：${recordSourceLabel(row)}。当前登记为已发布，但尚无关联的已发布视频；请核对发布依据，不能以此判定未发布。`;
}
