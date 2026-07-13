import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Phase 3 API and safety boundaries', () => {
  it('keeps finance analytics inside the finance partition', () => {
    const source = read('src/api/financeAnalytics.js');
    expect(source).toContain('/api/finance/analytics/');
    expect(source).not.toMatch(/\/api\/(internal|external|rpa)\//);
  });

  it('keeps report exports inside the report partition', () => {
    const source = read('src/api/reportExports.js');
    expect(source).toContain('/api/report/');
    expect(source).not.toMatch(/\/api\/(internal|external|finance|rpa)\//);
  });

  it('uses the frozen Phase 3 resource names', () => {
    expect(read('src/api/alerts.js')).toContain('/api/internal/alerts/business/');
    expect(read('src/api/replenishment.js')).toContain('/api/internal/alerts/inventory/');
    expect(read('src/api/replenishment.js')).toContain('/api/internal/replenishment/recommendations/');
    expect(read('src/api/lifecycle.js')).toContain('/api/internal/lifecycle/decisions/');
    expect(read('src/api/configCenter.js')).toContain('/api/internal/config/definitions/');
    expect(read('src/api/configCenter.js')).toContain('/api/internal/config/values/');
  });

  it('parses the frozen collection response before falling back to mock items', () => {
    expect(read('src/components/Phase3AnalyticsPage.vue')).toContain('Array.isArray(data.results)');
    expect(read('src/components/Phase3DecisionPage.vue')).toContain('Array.isArray(data.results)');
  });

  it('does not add high-risk execution endpoints', () => {
    const files = [
      'src/api/analytics.js', 'src/api/replenishment.js', 'src/api/lifecycle.js',
      'src/api/alerts.js', 'src/api/configCenter.js', 'src/api/financeAnalytics.js',
      'src/api/reportExports.js'
    ].map(read).join('\n');
    expect(files).not.toMatch(/\/admin\/|\/api\/rpa\/|payments|transfers|withdrawals|purchase-orders/);
  });

  it('exposes loading and accessible status on shared pages', () => {
    expect(read('src/components/Phase3AnalyticsPage.vue')).toContain('aria-busy');
    expect(read('src/components/Phase3DecisionPage.vue')).toContain('aria-busy');
  });
});
