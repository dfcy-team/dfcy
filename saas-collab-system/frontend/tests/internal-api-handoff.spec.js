import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { buildInternalApiHandoff, handoffEndpoints } from '../src/utils/internalApiHandoff';

const client = {
  name: '知识库', client_id: 'intapi_example', status: 'active', approval_status: 'approved',
  expires_at: '2027-12-31T15:59:59Z', allowed_cidrs: ['10.20.0.0/16'],
  resources: { products: ['id'], advertising_overview: ['id'] },
  client_secret: 'actual-secret', secret_hash: 'stored-secret-hash',
  allow_sso_login: true, sso_redirect_uris: ['https://knowledge.example.com/login/callback'],
};

describe('调用方接入资料', () => {
  it('生成数据和共用登录的明确端点，保留 API 前缀', () => {
    expect(handoffEndpoints('https://system.example.com', '/gateway')).toEqual({
      readonly_base_url: 'https://system.example.com/gateway/api/internal-readonly/v1/',
      sso_authorize_url: 'https://system.example.com/sso/authorize',
      sso_token_url: 'https://system.example.com/gateway/api/internal-readonly/v1/auth/token/',
    });
  });

  it('区分已接入和待接入数据块，绝不从列表回显密钥', () => {
    const result = buildInternalApiHandoff(client, ['products'], 'https://system.example.com', '');
    expect(result.data_read.ready_resources).toEqual(['products']);
    expect(result.data_read.pending_resources).toEqual(['advertising_overview']);
    expect(result.shared_login.redirect_uris).toEqual(client.sso_redirect_uris);
    expect(result.shared_login.pkce_method).toBe('S256');
    expect(result.client_secret).toContain('单独安全交付');
    expect(result.caller_must_configure.CLIENT_ID).toBe('intapi_example');
    expect(result.caller_must_configure.LOGIN_PKCE_METHOD).toBe('S256');
    expect(result.caller_must_configure.READABLE_RESOURCE_CODES).toEqual(['products']);
    expect(JSON.stringify(result)).not.toContain('actual-secret');
    expect(JSON.stringify(result)).not.toContain('stored-secret-hash');
  });

  it('SSO-only 无数据读取合同；页面提供复制入口和一次性密钥说明', () => {
    const result = buildInternalApiHandoff({ ...client, resources: {} }, [], 'https://system.example.com', '');
    expect(result.data_read).toBeNull();
    const page = fs.readFileSync(path.resolve(process.cwd(), 'src/views/integrations/AIExternalApiSettings.vue'), 'utf8');
    expect(page).toContain('接入资料');
    expect(page).toContain('复制接入参数（不含密钥）');
    expect(page).toContain('调用方需要修改或填写');
    expect(page).toContain('复制密钥');
    expect(page).toContain('navigator.clipboard.writeText(oneTimeCredential.value.client_secret)');
    expect(page).toContain('Client Secret');
    expect(page).toContain('调用暂不可用');
  });
});
