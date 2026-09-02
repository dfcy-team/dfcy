import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { hasRouteCapability, menuItems } from '../src/router/menu';

const routes = [
  ['/decision/inventory/alerts', 'InventoryAlertList'],
  ['/decision/inventory/replenishment', 'ReplenishmentSuggestionList'],
  ['/decision/lifecycle/reviews', 'LifecycleReviewList'],
  ['/decision/lifecycle/history', 'LifecycleReviewHistory'],
  ['/decision/lifecycle/clearance-requests', 'ClearanceRequestList'],
  ['/decision/alerts/business', 'BusinessAlertList']
];

describe('Vue decision routing', () => {
  it('keeps every decision submenu inside the host Vue workspace', () => {
    const decision = menuItems.find((item) => item.label === '经营决策');
    expect(decision.children.map((item) => item.path)).toEqual(routes.map(([path]) => path));
    expect(decision.children.every((item) => item.external !== true)).toBe(true);

    for (const [path] of routes) {
      expect(router.resolve(path).matched.length, path).toBeGreaterThan(0);
      expect(hasRouteCapability(path), path).toBe(true);
    }
  });

  it('maps decision paths directly to the existing Vue pages', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/router/index.js'), 'utf8');
    for (const [path, component] of routes) {
      expect(source).toContain(`{ path: '${path.slice(1)}', component: ${component} }`);
    }
    expect(source).not.toContain('DecisionEmbeddedPage');
    expect(source).not.toContain('/decision-app');
  });
});
