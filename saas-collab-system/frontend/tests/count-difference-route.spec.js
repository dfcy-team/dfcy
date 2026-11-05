import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import applicationRouter from '../src/router';
import { canAccessPath, findRouteCapability } from '../src/router/menu';

describe('清点差额旧入口兼容', () => {
  it('原生入口沿用发货单查看权限并拒绝外部账号', () => {
    const path = '/supply-chain/count-differences';
    expect(findRouteCapability(path)).toMatchObject({ permissions: ['supply.v2.view'], userTypes: ['internal'] });
    expect(canAccessPath({ user_type: 'internal', permissions: ['supply.v2.view'] }, path)).toBe(true);
    expect(canAccessPath({ user_type: 'internal', permissions: [] }, path)).toBe(false);
    expect(canAccessPath({ user_type: 'external', permissions: ['supply.v2.view'] }, path)).toBe(false);
  });
  it('旧静态入口进入同一个受保护的原生页面并保留查询参数', async () => {
    const children = applicationRouter.options.routes.flatMap(route => route.children || []);
    const legacy = children.find(route => route.path === 'count-difference-choices');
    const native = children.find(route => route.path === 'supply-chain/count-differences');
    expect(legacy).toBeTruthy();
    expect(native.component).toBeTypeOf('function');
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { ...legacy, path: `/${legacy.path}` },
      { ...native, path: `/${native.path}`, component: { template: '<div />' } },
    ] });
    await router.push('/count-difference-choices/?source=historical');
    expect(router.currentRoute.value.path).toBe('/supply-chain/count-differences');
    expect(router.currentRoute.value.query).toEqual({ source: 'historical' });
  });
});
