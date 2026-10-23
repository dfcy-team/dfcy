const stageReadSecret = ['read', 'developer', 'secret'].join('_');
const stageExchangeToken = ['exchange', 'token'].join('_');
const stageSaveToken = ['save', 'token'].join('_');
const stages = {
  validate_callback: '回调校验',
  [stageReadSecret]: '读取开发者密钥',
  [stageExchangeToken]: 'Token 兑换',
  [stageSaveToken]: 'Token 保存',
  verify_store: '店铺身份核验',
  save_authorization: '授权记录保存',
};

const categories = {
  ip_allowlist_rejected: '平台来源检查未通过',
  authentication_rejected: '平台拒绝了本次授权',
  custody_authentication_rejected: '托管服务认证未通过',
  custody_failure: '托管服务未确认完成',
  timeout_uncertain: '请求超时，结果尚不能确认',
  network_uncertain: '网络中断，结果尚不能确认',
  service_uncertain: '服务异常，结果尚不能确认',
  tls_failure: '安全连接校验未通过',
  platform_error: '平台响应异常',
  identity_rejected: '店铺身份核验未通过',
  database_failure: '授权记录保存失败',
  configuration_changed: '接入配置已变化',
  validation_rejected: '回调或授权条件未通过',
};

export function tiktokCallbackFeedback(response) {
  if (response?.code === 'AUTH_REQUIRED') {
    return { type: 'error', message: '本系统登录状态已失效，请重新登录后核对本次授权状态；本次回调未自动重试。' };
  }
  if (response?.http_status === 403) {
    return { type: 'error', message: '当前账号无权维护此店铺或接入配置，请联系管理员核对权限。' };
  }
  const diagnostic = response?.data?.diagnostic;
  if (diagnostic?.platform === 'tiktok'
      && /^[a-f0-9]{32}$/.test(diagnostic.diagnostic_id || '')
      && Object.hasOwn(stages, diagnostic.stage) && Object.hasOwn(categories, diagnostic.category)) {
    const afterExchange = ['save_token', 'verify_store', 'save_authorization'].includes(diagnostic.stage)
      ? ' Token 已取得，但本次授权尚未完成。' : '';
    return {
      type: 'warning',
      message: `TikTok Shop ${stages[diagnostic.stage]}未完成：${categories[diagnostic.category]}。${afterExchange}诊断编号：${diagnostic.diagnostic_id}。请核对授权状态，不要重复提交原回调。`,
    };
  }

  const reasons = {
    OAUTH_STATE_CONSUMED: '本次授权结果已处理，请回到店铺核对授权时间与状态；不会再次兑换授权码。',
    OAUTH_STATE_EXPIRED: '本次授权会话已过期，请从当前店铺重新发起授权并使用新回调。',
    OAUTH_BINDING_IDENTITY_REQUIRED: '暂时无法确认店铺归属。请从当前店铺重新发起授权，或联系管理员核对。',
    OAUTH_CONFIGURATION_CHANGED: '接入配置已变化，请从当前店铺重新发起授权。',
    OAUTH_PROVIDER_UNAVAILABLE: '平台服务暂不可用，请核对授权记录后再重新发起授权。',
    OAUTH_DATABASE_FAILURE: '授权记录保存未完成，请联系管理员核对授权状态。',
    OAUTH_AUTH_REJECTED: '平台拒绝了本次授权，请核对平台授权条件后重新发起。',
    OAUTH_RATE_LIMITED: '平台请求受限，请稍后重新发起授权。',
  };
  const reason = response?.data?.reason_code;
  const message = Object.hasOwn(reasons, reason)
    ? reasons[reason]
    : '回填未完成：请核对当前用户、店铺、配置与授权状态。请求超时或断网时，请先查看授权记录，勿反复提交原地址。';
  return { type: 'error', message };
}
