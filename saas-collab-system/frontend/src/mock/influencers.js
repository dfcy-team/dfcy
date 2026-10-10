import { successResponse } from './index';

const demoInfluencer = (params = {}) => ({
  id: 1, code: 'creator-demo', name: '示例达人', platform: 'TikTok',
  ...([true, 'true', 1, '1'].includes(params.include_nickname_id)
    ? { nickname_id: 'creator-demo', account_nickname: '示例账号昵称' } : {}),
  registered_platforms: ['tiktok'],
  category: '生活方式', follower_count: 128000, contact_name: '商务A', contact_phone_masked: '***8800',
  contact_email_masked: 'b***@example.com', cooperation_status: 'prospect', status: 'active'
});

export const influencerMocks = {
  list: (params = {}) => successResponse({ status: 'mock', count: 1, next: null, previous: null, results: [demoInfluencer(params)] }),
  detail: (id, params = {}) => successResponse({ ...demoInfluencer(params), id, contacts: [], blacklist_history: [], api_status: 'mock' })
};
