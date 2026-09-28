import { apiBaseUrl } from '../api/baseUrl';

export function handoffEndpoints(frontendOrigin, backendBase = apiBaseUrl) {
  const apiRoot = new URL(backendBase || '/', frontendOrigin).toString().replace(/\/+$/, '');
  return {
    readonly_base_url: `${apiRoot}/api/internal-readonly/v1/`,
    sso_authorize_url: `${new URL('/sso/authorize', frontendOrigin)}`,
    sso_token_url: `${apiRoot}/api/internal-readonly/v1/auth/token/`,
  };
}

export function buildInternalApiHandoff(client, readyCodes, frontendOrigin, backendBase = apiBaseUrl) {
  const endpoints = handoffEndpoints(frontendOrigin, backendBase);
  const selected = Object.keys(client.resources || {});
  const ready = selected.filter(code => readyCodes.includes(code));
  const pending = selected.filter(code => !readyCodes.includes(code));
  return {
    system_name: client.name,
    client_id: client.client_id,
    client_secret: '<创建或轮换时单独安全交付；本页不可再次查看>',
    caller_must_configure: {
      CLIENT_ID: client.client_id,
      CLIENT_SECRET: '<粘贴一次性复制的密钥，仅放调用方服务端>',
      SERVER_EGRESS_IP: '<调用方提供实际出口 IP，管理员将其登记为允许来源>',
      ...(selected.length ? { READONLY_API_BASE_URL: endpoints.readonly_base_url, READABLE_RESOURCE_CODES: ready } : {}),
      ...(client.allow_sso_login ? {
        LOGIN_AUTHORIZE_URL: endpoints.sso_authorize_url,
        LOGIN_TOKEN_URL: endpoints.sso_token_url,
        LOGIN_CALLBACK_URL: '<调用方实现回调并将其精确地址提交管理员登记>',
        LOGIN_PKCE_METHOD: 'S256',
      } : {}),
    },
    approval_status: client.approval_status,
    status: client.status,
    expires_at: client.expires_at,
    allowed_source_cidrs: client.allowed_cidrs || [],
    data_read: selected.length ? {
      base_url: endpoints.readonly_base_url,
      request: 'GET {base_url}{resource}/?limit=100&cursor=0',
      authentication: 'HTTP Basic: client_id:client_secret（仅服务端保存）',
      ready_resources: ready,
      pending_resources: pending,
    } : null,
    shared_login: client.allow_sso_login ? {
      authorize_url: endpoints.sso_authorize_url,
      token_url: endpoints.sso_token_url,
      redirect_uris: client.sso_redirect_uris || [],
      browser_parameters: ['client_id', 'redirect_uri', 'state', 'code_challenge'],
      pkce_method: 'S256',
      token_request: ['code', 'redirect_uri', 'code_verifier'],
      token_authentication: 'HTTP Basic: client_id:client_secret（调用方服务端发起）',
      result_fields: ['user_id', 'username', 'full_name', 'tenant_id'],
    } : null,
  };
}
