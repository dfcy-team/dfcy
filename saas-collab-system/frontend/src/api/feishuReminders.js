import { requestApi } from './request';

const base = '/api/internal/integrations/feishu/business-reminders';
export const reminderOptions = (search = '') => requestApi({ method: 'get', url: `${base}/options/`, params: { search } });
export const previewReminder = data => requestApi({ method: 'post', url: `${base}/preview/`, data });
export const sendReminder = data => requestApi({ method: 'post', url: `${base}/send/`, data });
export const reminderHistory = () => requestApi({ method: 'get', url: `${base}/` });
export const reminderStatus = id => requestApi({ method: 'get', url: `${base}/${id}/` });
export const retryReminder = (id, operation_id) => requestApi({ method: 'post', url: `${base}/${id}/`, data: { operation_id } });
