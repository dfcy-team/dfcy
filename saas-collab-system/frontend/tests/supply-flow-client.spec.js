import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { canAccessPath } from '../src/router/menu';
import { idempotencyKey } from '../src/api/supplyFlow';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('SC-FLOW client contract', () => {
  it('registers internal routes with exact view permissions and denies supplier users', () => {
    const internal = { user_type: 'internal', permissions: ['supply.consolidation.view'] };
    expect(canAccessPath(internal, '/supply-chain/consolidations')).toBe(true);
    expect(canAccessPath(internal, '/supply-chain/shipments')).toBe(false);
    expect(canAccessPath({ ...internal, permissions: ['supply.shipment.view'] }, '/supply-chain/shipments')).toBe(true);
    expect(canAccessPath({ user_type: 'external', permissions: ['supply.consolidation.view'] }, '/supply-chain/consolidations')).toBe(false);
  });

  it('uses API2 paths, exact action permissions and stable idempotency keys', () => {
    const api = read('src/api/supplyFlow.js');
    const page = read('src/views/supply-chain/SupplyFlowConsole.vue');
    expect(api).toContain('/api/internal/supply-chain/consolidations/sites/');
    expect(api).toContain('/api/internal/supply-chain/consolidations/consolidations/');
    expect(api).toContain('/api/internal/supply-chain/shipments/');
    expect(api).toContain("'Idempotency-Key'");
    expect(page).toContain('expected_version');
    for (const permission of ['supply.consolidation.allocate', 'supply.consolidation.release', 'supply.shipment.allocate', 'supply.shipment.dispatch']) {
      expect(page).toContain(permission);
    }
    for (const status of ['draft', 'loading', 'customs_declared', 'dispatched', 'port_arrived', 'warehouse_arrived', 'warehouse_cleared', 'cancelled']) expect(page).toContain(status);
    expect(page).toContain('集货箱分配 ID');
    expect(page).toContain("item.state === 'transferred'");
    expect(idempotencyKey('dispatch', 12, { expected_version: 4 })).toBe(idempotencyKey('dispatch', 12, { expected_version: 4 }));
    expect(idempotencyKey('dispatch', 12, { expected_version: 4 })).not.toBe(idempotencyKey('dispatch', 12, { expected_version: 5 }));
  });

  it('keeps local-only boundaries explicit and does not expose production endpoints', () => {
    const page = read('src/views/supply-chain/SupplyFlowConsole.vue');
    expect(page).toContain('不发送真实通知');
    expect(page).toContain('download-ticket');
    expect(page).not.toMatch(/supabase|service.?role|api\.weixin|jscode2session/i);
  });
});
