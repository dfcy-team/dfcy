import { requestApi } from './request';
const base = '/api/internal/issue-tracking/';
export async function tracking(path, method = 'get', data, params) {
  const result = await requestApi({ url: base + path, method, data, params });
  if (!result.success) throw new Error(result.message || '事项跟踪请求失败');
  return result.data;
}
export const rows = value => Array.isArray(value) ? value : value?.results || [];
export const states = { pending: '待办理', processing: '办理中', confirming: '待确认', closed: '已关闭' };
export const actions = { feedback: '办理反馈', submit: '提交完成', return: '退回办理', close: '确认关闭', reopen: '重开', reassign: '改派', reschedule: '改期', transfer: '部门移交', remind: '催办' };
