import { successResponse } from './index';

// The local fixture mirrors the production-settings read model without ever
// carrying a token, secret or credential value.  Keeping this stateful makes
// the admin workflow executable in Mock mode while the real API is being
// wired to the VM.
const initialConfig = {
  modules: {
    core: 'enabled', masterdata: 'enabled', product_development: 'disabled', supply_chain: 'disabled',
    inventory: 'pilot_readonly', global_listing: 'disabled', sales: 'pilot_readonly', influencer: 'disabled',
    finance: 'pilot_readonly', analytics: 'pilot_readonly', decision: 'pilot_readonly', reports: 'pilot_readonly',
    workflow: 'disabled', rpa: 'disabled', api_integrations: 'pilot_readonly', system: 'enabled', governance: 'enabled'
  },
  network: {
    mode: '',
    security_approved: false,
    readonly_sync_enabled: false,
    allowed_hosts: ['api.shopee.sg', 'api.lazada.sg', 'open-api.tiktokglobalshop.com'],
    oauth_redirect_allowlist: ['https://saas.example.test/api/internal/integrations/store-authorizations/oauth/callback/']
  },
  connection: {
    connect_timeout_seconds: 3,
    read_timeout_seconds: 8,
    max_retries: 2,
    backoff_base_seconds: 0.5,
    max_retry_wait_seconds: 8,
    max_total_wait_seconds: 15
  },
  custody: {
    backend: 'refuse',
    service_url: '',
    service_host: '',
    auth_file_path: '',
    ca_file_path: ''
  },
  listing_write: {
    mode: 'disabled',
    emergency_stop: true,
    require_batch_approval: true,
    allowed_platforms: [],
    allowed_actions: [],
    allowed_store_ids: [],
    max_batch_size: 20
  },
  platforms: {
    lazada: {
      contract_approved: false,
      app_id: '',
      redirect_uri: 'https://saas.example.test/api/internal/integrations/store-authorizations/oauth/callback/lazada/',
      auth_url: 'https://auth.lazada.com/oauth/authorize',
      api_host: 'https://api.lazada.com',
      token_path: '/rest/auth/token/create',
      refresh_path: '/rest/auth/token/refresh',
      market: ''
    },
    shopee: {
      contract_approved: true,
      app_id: '',
      redirect_uri: 'https://saas.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
      auth_url: 'https://partner.shopeemobile.com/api/v2/shop/auth_partner',
      api_host: 'https://partner.shopeemobile.com',
      token_path: '/api/v2/auth/token/get',
      refresh_path: '/api/v2/auth/access_token/get',
      revoke_path: '/api/v2/shop/cancel_auth_partner',
      shop_path: '/api/v2/shop/get_shop_info',
      order_list_path: '/api/v2/order/get_order_list',
      order_detail_path: '/api/v2/order/get_order_detail',
      return_list_path: '/api/v2/returns/get_return_list',
      return_detail_path: '/api/v2/returns/get_return_detail',
      market: '',
      region: ''
    },
    tiktok: {
      contract_approved: false,
      app_id: '',
      service_id: '',
      redirect_uri: 'https://saas.example.test/api/internal/integrations/store-authorizations/oauth/callback/tiktok/',
      market: 'ROW',
      auth_url: '',
      api_host: '',
      auth_urls: {},
      api_hosts: {},
      token_host: 'https://auth.tiktok-shops.com',
      token_path: '/api/v2/token/get',
      refresh_path: '/api/v2/token/refresh',
      revoke_path: '',
      authorized_shops_path: '/authorization/202309/shops',
      metadata_path: '/seller/202309/permissions',
      order_list_path: '/order/202309/orders/search',
      order_detail_path: '/order/202309/orders',
      return_list_path: '/return_refund/202602/returns/search'
    }
  }
};

const initialMaskedStatus = {
  credentials_stored: false,
  custody: {
    backend: 'refuse',
    service_url_configured: false,
    service_host_configured: false,
    auth_file_path_configured: false,
    ca_file_path_configured: false,
    token_available: false
  }
};

const initialVersions = [
  {
    id: 701,
    version: 7,
    status: 'effective',
    created_at: '2026-09-01T09:00:00Z',
    created_by: { id: 1, username: 'system-admin' },
    approved_at: '2026-09-01T10:00:00Z',
    approved_by: { id: 2, username: 'security-approver' },
    effective_at: '2026-09-01T10:00:00Z',
    change_summary: '启用平台生产只读配置基线'
  },
  {
    id: 702,
    version: 8,
    status: 'pending_approval',
    created_at: '2026-09-03T08:30:00Z',
    created_by: { id: 1, username: 'system-admin' },
    approved_at: null,
    approved_by: null,
    effective_at: null,
    change_summary: '更新平台生产端点与合同审批状态'
  }
];

let state = {
  effective_config: structuredClone(initialConfig),
  pending_config: structuredClone(initialConfig),
  source: 'database',
  masked_status: structuredClone(initialMaskedStatus),
  runtime: {
    environment: 'production',
    status: 'blocked',
    ready: false,
    write_enabled: false,
    checked_at: '2026-09-03T08:30:00Z',
    message: 'API 同步写入关闭；全球刊登生产策略仍需配置与审批。'
  },
  current_version: structuredClone(initialVersions[0]),
  pending_version: structuredClone(initialVersions[1]),
  versions: structuredClone(initialVersions)
};

function clone(value) {
  return structuredClone(value);
}

function canonicalConfig(value = {}) {
  const incoming = value && typeof value === 'object' ? value : {};
  const config = {
    ...clone(initialConfig),
    ...clone(incoming),
    network: { ...clone(initialConfig.network), ...(incoming.network || {}) },
    modules: { ...clone(initialConfig.modules), ...(incoming.modules || {}) },
    connection: { ...clone(initialConfig.connection), ...(incoming.connection || {}) },
    custody: { ...clone(initialConfig.custody), ...(incoming.custody || {}) },
    listing_write: { ...clone(initialConfig.listing_write), ...(incoming.listing_write || {}) },
    platforms: Object.fromEntries(['lazada', 'shopee', 'tiktok'].map((platform) => [
      platform,
      { ...clone(initialConfig.platforms[platform]), ...((incoming.platforms || {})[platform] || {}) }
    ]))
  };
  return config;
}

let versionConfigs = {
  701: clone(initialConfig),
  702: clone(initialConfig)
};

function unwrapConfig(payload) {
  return payload?.value || payload?.effective_config || payload?.config || payload?.settings || payload || {};
}

function updateRuntime() {
  const config = state.effective_config || {};
  const network = config.network || {};
  const custody = config.custody || {};
  const custodyMask = state.masked_status?.custody || {};
  const platforms = config.platforms || {};
  const platformReady = ['lazada', 'shopee', 'tiktok'].every((platform) => {
    const item = platforms[platform] || {};
    return Boolean(item.contract_approved && item.app_id && item.redirect_uri && (item.api_host || Object.keys(item.api_hosts || {}).length) && item.market);
  });
  const ready = Boolean(
    network.mode === 'approved-live-test'
      && network.security_approved
      && network.readonly_sync_enabled
      && Array.isArray(network.allowed_hosts)
      && network.allowed_hosts.length
      && Array.isArray(network.oauth_redirect_allowlist)
      && network.oauth_redirect_allowlist.length
      && custody.backend && custody.backend !== 'refuse'
      && custody.service_url
      && custody.service_host
      && custodyMask.token_available
      && platformReady
  );
  state.runtime = {
    ...state.runtime,
    status: ready ? 'ready' : 'blocked',
    ready,
    write_enabled: false,
    checked_at: new Date().toISOString(),
    message: ready ? '生产只读安全门已通过；全球刊登生产策略独立受控。' : 'API 同步写入关闭；全球刊登生产策略仍需配置与审批。',
    config: clone(state.effective_config || {}),
    listing_write: clone(config.listing_write || {}),
    source: state.source,
    valid: true,
    masked_status: clone(state.masked_status)
  };
}

export const mockProductionIntegrationSettings = () => {
  updateRuntime();
  const current = state.current_version ? clone(state.current_version) : null;
  const pending = state.pending_version ? clone(state.pending_version) : null;
  const versions = clone(state.versions || []);
  const effective = clone(state.effective_config || {});
  return successResponse({
    api_status: 'mock',
    effective_config: effective,
    // Compatibility aliases allow the UI to consume the same read model if
    // the VM serializer calls this field `config` or `effective`.
    config: clone(effective),
    effective: current,
    source: state.source,
    runtime: clone(state.runtime),
    valid: true,
    masked_status: clone(state.masked_status),
    status: state.runtime.status,
    current_version: current,
    pending_version: pending,
    pending_config: clone(state.pending_config || null),
    versions,
    version: current?.version || null,
    production_write_enabled: false,
    listing_write_policy: clone(effective.listing_write || {})
  });
};

export const mockCreateProductionIntegrationSettingsVersion = (payload = {}) => {
  const nextVersion = Math.max(...(state.versions || []).map((item) => Number(item.version || 0)), 0) + 1;
  const config = canonicalConfig(unwrapConfig(payload));
  const version = {
    id: 702 + nextVersion,
    version: nextVersion,
    status: 'pending_approval',
    created_at: new Date().toISOString(),
    created_by: { id: 1, username: 'system-admin' },
    approved_at: null,
    approved_by: null,
    effective_at: null,
    change_summary: String(payload.reason || payload.change_reason || '提交生产环境配置变更').slice(0, 240)
  };
  state.pending_version = version;
  state.pending_config = config;
  versionConfigs[version.id] = clone(config);
  state.versions = [...(state.versions || []), clone(version)];
  return successResponse({ ...clone(version), api_status: 'mock' });
};

export const mockApproveProductionIntegrationSettingsVersion = (id) => {
  const version = (state.versions || []).find((item) => String(item.id) === String(id));
  if (!version || version.status !== 'pending_approval') {
    return { success: false, code: 'VERSION_NOT_PENDING', message: '只有待审批版本可以审批。', data: null };
  }
  version.status = 'effective';
  version.approved_at = new Date().toISOString();
  version.approved_by = { id: 2, username: 'security-approver' };
  version.effective_at = version.approved_at;
  state.effective_config = clone(versionConfigs[version.id] || state.pending_config || state.effective_config);
  state.pending_config = null;
  state.current_version = clone(version);
  state.pending_version = null;
  state.versions = (state.versions || []).map((item) => (item.id === version.id ? clone(version) : item));
  updateRuntime();
  return successResponse({ ...clone(version), api_status: 'mock' });
};

export const mockRollbackProductionIntegrationSettingsVersion = (id) => {
  const target = (state.versions || []).find((item) => String(item.id) === String(id));
  if (!target) return { success: false, code: 'VERSION_NOT_FOUND', message: '目标配置版本不存在。', data: null };
  const nextVersion = Math.max(...(state.versions || []).map((item) => Number(item.version || 0)), 0) + 1;
  const rollback = {
    id: 702 + nextVersion,
    version: nextVersion,
    status: 'pending_approval',
    created_at: new Date().toISOString(),
    created_by: { id: 1, username: 'system-admin' },
    approved_at: null,
    approved_by: null,
    effective_at: null,
    rollback_from_version: target.version,
    change_summary: `回滚到版本 v${target.version}`
  };
  state.pending_version = rollback;
  state.pending_config = clone(versionConfigs[target.id] || state.effective_config);
  versionConfigs[rollback.id] = clone(state.pending_config);
  state.versions = [...(state.versions || []), clone(rollback)];
  return successResponse({ ...clone(rollback), api_status: 'mock' });
};
