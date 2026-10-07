import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const sourcePath = (relativePath) => fileURLToPath(new URL(relativePath, import.meta.url));
const syncJobs = readFileSync(sourcePath('../src/views/integrations/SyncJobList.vue'), 'utf8');
const historyBatches = readFileSync(sourcePath('../src/components/HistorySyncBatches.vue'), 'utf8');
const capabilityMatrix = readFileSync(sourcePath('../src/views/integrations/IntegrationCapabilityMatrix.vue'), 'utf8');

describe('credential refresh and capability status copy', () => {
  it('separates scheduler heartbeat, refresh execution, and current authorization expiry', () => {
    expect(syncJobs).toContain('续期调度心跳');
    expect(syncJobs).toContain('续期队列');
    expect(syncJobs).toContain('授权状态与有效期');
    expect(syncJobs).toContain('续期执行');
    expect(syncJobs).toContain('credential_refresh?.expires_at');
    expect(syncJobs).toContain('refresh.state]');
    expect(syncJobs).toContain('scheduler.value = data.credential_scheduler || {}');
    expect(syncJobs).toContain('当前授权未到期');
  });

  it('distinguishes historical errors from current authorization and waiting segments', () => {
    expect(historyBatches).toContain('当前授权：');
    expect(historyBatches).toContain('历史运行错误：');
    expect(historyBatches).toContain('等待授权续期：');
    expect(historyBatches).toContain('recovery_hint');
    expect(historyBatches).toContain('重试可恢复失败分段');
    expect(historyBatches).toContain('无效或正在运行的分段会保留并跳过');
  });

  it('labels capabilities without a dedicated check and offers no substitute check', () => {
    expect(capabilityMatrix).toContain('本能力未接入独立检查');
    expect(capabilityMatrix).toContain('读取开关仅表示配置');
    expect(capabilityMatrix).not.toContain("checkResources.PRICE");
    expect(capabilityMatrix).not.toContain("checkResources.FULFILLMENT");
    expect(capabilityMatrix).not.toContain("checkResources.PAYMENT");
  });
});
