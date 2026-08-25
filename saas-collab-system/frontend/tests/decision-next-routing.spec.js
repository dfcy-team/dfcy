import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { hasRouteCapability, menuItems } from '../src/router/menu';

const paths = [
  '/decision/inventory/alerts',
  '/decision/inventory/replenishment',
  '/decision/lifecycle/reviews',
  '/decision/lifecycle/history',
  '/decision/lifecycle/clearance-requests',
  '/decision/alerts/business'
];

describe('embedded decision application routing', () => {
  it('keeps every decision submenu in the host workspace', () => {
    const decision = menuItems.find((item) => item.label === '经营决策');
    expect(decision.children.map((item) => item.path)).toEqual(paths);
    expect(decision.children.every((item) => item.external !== true)).toBe(true);

    const workspace = readFileSync(
      resolve(process.cwd(), '../decision-frontend/src/components/decision-workspace.tsx'),
      'utf8'
    );
    for (const path of paths) {
      expect(router.resolve(path).matched.length, path).toBeGreaterThan(0);
      expect(hasRouteCapability(path), path).toBe(true);
      expect(workspace).toContain(`path: "${path.replace('/decision', '')}"`);
    }
  });

  it('renders Next.js as right-side content without a second shell', () => {
    const embedded = readFileSync(resolve(process.cwd(), 'src/views/decision/DecisionEmbeddedPage.vue'), 'utf8');
    const workspace = readFileSync(
      resolve(process.cwd(), '../decision-frontend/src/components/decision-workspace.tsx'),
      'utf8'
    );
    expect(embedded).toContain('/decision-app');
    expect(embedded).toContain('?embed=1');
    expect(workspace).toContain('!embedded ? <aside className="sidebar">');
    expect(workspace).toContain('!embedded ? <header className="topbar">');
  });
});
