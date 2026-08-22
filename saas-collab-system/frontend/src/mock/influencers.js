import { successResponse } from './index';

export const influencerMocks = {
  list: () => successResponse({ status: 'mock', count: 1, next: null, previous: null, results: [{
    id: 1, code: 'creator-demo', name: '示例达人', platform: 'TikTok', handle_masked: '@c***mo',
    category: '生活方式', follower_count: 128000, contact_name: '商务A', contact_phone_masked: '***8800',
    contact_email_masked: 'b***@example.com', cooperation_status: 'prospect', status: 'active'
  }] })
};
