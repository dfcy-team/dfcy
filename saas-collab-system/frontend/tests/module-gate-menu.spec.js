import { describe, expect, it } from 'vitest';
import { canAccessPath, filterMenuItems } from '../src/router/menu';

const baseUser = {
  user_type: 'internal',
  permissions: ['development.requirement.view', 'integrations.view']
};

describe('module rollout menu and route gate', () => {
  it('hides disabled modules and rejects direct routes', () => {
    const user = { ...baseUser, module_statuses: { product_development: 'disabled', api_integrations: 'disabled' } };
    const labels = filterMenuItems(user).map((item) => item.label);
    expect(labels).not.toContain('产品开发');
    expect(labels).not.toContain('API数据接入');
    expect(canAccessPath(user, '/development/requirements')).toBe(false);
    expect(canAccessPath(user, '/integrations/readiness')).toBe(false);
  });

  it('keeps mock-only modules visible for local sandbox work', () => {
    const user = { ...baseUser, module_statuses: { product_development: 'mock_only' } };
    const labels = filterMenuItems(user).map((item) => item.label);
    expect(labels).toContain('产品开发');
    expect(canAccessPath(user, '/development/requirements')).toBe(true);
  });
});
