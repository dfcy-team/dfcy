<template>
  <section class="production-settings-page" :aria-busy="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">系统治理 · API 数据接入</p>
        <h1>生产环境配置</h1>
        <p>系统管理员维护平台生产只读安全门、密钥托管引用和各平台 API 端点；提交后由具备审批权限的人员审批生效。</p>
      </div>
      <div class="header-actions">
        <el-tag :type="runtime.ready ? 'success' : 'warning'" effect="plain">{{ runtime.ready ? '生产只读已就绪' : '生产只读未就绪' }}</el-tag>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-alert
      title="本页面绝不接收或回显 Token、Secret、Cookie、Session 等密钥原文。凭据仅通过受控密钥托管服务引用；API 同步写入关闭，全球刊登使用独立受控生产通道。"
      type="warning"
      :closable="false"
      show-icon
    />

    <section class="overview-grid" aria-label="生产环境配置状态">
      <article ref="writeOverview" class="overview-card">
        <span>有效来源</span>
        <strong>{{ sourceLabel }}</strong>
        <small>{{ runtime.message || '以服务端 effective 配置为准' }}</small>
      </article>
      <article class="overview-card">
        <span>当前生效版本</span>
        <strong>{{ versionLabel(currentVersion) }}</strong>
        <small>{{ actorLabel(currentVersion?.approved_by || currentVersion?.approved_by_id, '尚未审批') }} · {{ dateLabel(currentVersion?.effective_at) }}</small>
      </article>
      <article class="overview-card is-pending">
        <span>待审批版本</span>
        <strong>{{ pendingVersion ? versionLabel(pendingVersion) : '无' }}</strong>
        <small>{{ pendingVersion ? `${actorLabel(pendingVersion.created_by || pendingVersion.created_by_id, '未知创建人')} 创建 · 待审批` : '当前没有待审批变更' }}</small>
      </article>
      <article class="overview-card">
        <span>生产写入</span>
        <strong>{{ listingWriteLabel }}</strong>
        <small>API 同步写入关闭；全球刊登按平台、店铺、动作和批次独立受控</small>
      </article>
    </section>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <section class="runtime-card">
      <header>
        <div><h2>运行时安全门</h2><p>这些状态由服务端校验，页面只提交版本草稿，不直接改写进程环境变量。</p></div>
        <el-tag :type="runtime.ready ? 'success' : 'danger'">{{ runtime.status === 'ready' ? '已通过' : '需处理' }}</el-tag>
      </header>
      <dl class="runtime-grid">
        <div><dt>运行环境</dt><dd>{{ runtime.environment || 'production' }}</dd></div>
        <div><dt>网络模式</dt><dd>{{ modeLabel(form.network.mode) }}</dd></div>
        <div><dt>安全审批</dt><dd><el-tag :type="form.network.security_approved ? 'success' : 'danger'">{{ form.network.security_approved ? '已通过' : '未通过' }}</el-tag></dd></div>
        <div><dt>只读同步</dt><dd><el-tag :type="form.network.readonly_sync_enabled ? 'success' : 'danger'">{{ form.network.readonly_sync_enabled ? '已启用' : '未启用' }}</el-tag></dd></div>
        <div><dt>密钥托管</dt><dd><el-tag :type="form.custody.token_available ? 'success' : 'danger'">{{ form.custody.token_available ? '可用' : '不可用' }}</el-tag></dd></div>
        <div><dt>最近检查</dt><dd>{{ dateLabel(runtime.checked_at) }}</dd></div>
      </dl>
    </section>

    <el-form :model="form" label-position="top" class="settings-form">
      <fieldset ref="networkSection" class="settings-section">
        <legend>网络与安全门</legend>
        <p class="section-note">生产环境只允许 approved-live-test 只读模式；启用安全审批或只读同步会触发二次确认，并创建待审批版本。</p>
        <div class="form-grid">
          <el-form-item label="网络模式">
            <el-select v-model="form.network.mode" placeholder="关闭生产访问" style="width: 100%">
              <el-option label="关闭生产访问" value="" />
              <el-option label="批准的生产只读" value="approved-live-test" />
            </el-select>
          </el-form-item>
          <el-form-item label="安全审批状态">
            <el-switch v-model="form.network.security_approved" active-text="已批准" inactive-text="未批准" />
          </el-form-item>
          <el-form-item label="只读同步开关">
            <el-switch v-model="form.network.readonly_sync_enabled" active-text="启用" inactive-text="关闭" />
          </el-form-item>
          <el-form-item label="连接超时秒数">
            <el-input-number v-model="form.connection.connect_timeout_seconds" :min="0.1" :max="10" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="读取超时秒数">
            <el-input-number v-model="form.connection.read_timeout_seconds" :min="0.1" :max="30" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="最大重试次数">
            <el-input-number v-model="form.connection.max_retries" :min="0" :max="5" controls-position="right" />
          </el-form-item>
          <el-form-item label="基础退避秒数">
            <el-input-number v-model="form.connection.backoff_base_seconds" :min="0.1" :max="60" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="最大单次等待秒数">
            <el-input-number v-model="form.connection.max_retry_wait_seconds" :min="0.1" :max="60" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="最大总等待秒数">
            <el-input-number v-model="form.connection.max_total_wait_seconds" :min="0.1" :max="60" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="出站域名白名单 *" class="wide">
            <el-input v-model="allowedHostsText" type="textarea" :rows="3" placeholder="每行填写一个 HTTPS 平台域名，例如 api.example.com" />
            <small>对应 allowed_hosts；仅允许域名，不要填写 URL、路径、Token 或 Secret。</small>
          </el-form-item>
          <el-form-item label="OAuth 回调白名单 *" class="wide">
            <el-input v-model="redirectAllowlistText" type="textarea" :rows="3" placeholder="每行填写一个完整 HTTPS 回调地址" />
            <small>对应 oauth_redirect_allowlist；平台回调地址必须与下方配置完全一致。</small>
          </el-form-item>
        </div>
      </fieldset>

      <fieldset ref="custodySection" class="settings-section">
        <legend>密钥托管服务</legend>
        <p class="section-note">只维护托管服务的连接元数据；Token 是否可用由服务端返回 masked_status.custody.token_available，页面不提供 Token 输入框。</p>
        <div class="form-grid">
          <el-form-item label="托管后端 *">
            <el-select v-model="form.custody.backend" style="width: 100%">
              <el-option label="拒绝/关闭生产凭据托管" value="refuse" />
              <el-option label="独立 HTTPS 托管服务" value="http" />
              <el-option label="本地文件（仅开发/测试）" value="file" />
            </el-select>
          </el-form-item>
          <el-form-item label="Token 可用状态">
            <div class="readonly-value"><el-tag :type="form.custody.token_available ? 'success' : 'danger'">{{ form.custody.token_available ? '可用' : '不可用' }}</el-tag><small>只读状态，不能在此录入 Token</small></div>
          </el-form-item>
          <el-form-item :label="'服务 URL' + (form.custody.backend === 'http' ? ' *' : '')"><el-input v-model="form.custody.service_url" type="url" autocomplete="off" placeholder="https://custody.example.com" /></el-form-item>
          <el-form-item :label="'服务 Host' + (form.custody.backend === 'http' ? ' *' : '')"><el-input v-model="form.custody.service_host" autocomplete="off" placeholder="custody.example.com" /></el-form-item>
          <el-form-item :label="'认证文件路径' + (form.custody.backend === 'http' ? ' *' : '')"><el-input v-model="form.custody.auth_file_path" autocomplete="off" placeholder="/etc/saas/custody/auth.json" /></el-form-item>
          <el-form-item label="CA 文件路径"><el-input v-model="form.custody.ca_file_path" autocomplete="off" placeholder="/etc/saas/custody/ca.pem" /></el-form-item>
        </div>
        <small v-if="form.custody.backend === 'http'" class="section-note">HTTPS 托管后端需要服务 URL、Host 和认证文件路径与生产挂载一致；Token 原文只能由托管服务提供。</small>
        <small v-else-if="form.custody.backend === 'file'" class="section-note">本地文件仅用于开发/测试，生产安全门会拒绝该后端。</small>
        <small v-else class="section-note">拒绝托管会保持生产只读能力关闭，适合尚未完成密钥托管的部署。</small>
      </fieldset>

      <fieldset ref="listingWriteSection" class="settings-section listing-write-section">
        <legend>全球刊登生产写入策略</legend>
        <p class="section-note">这是与 API 数据同步隔离的受控通道，仅用于全球刊登创建、更新和暂停；API 同步仍保持只读。配置通过只代表允许进入内部生产队列，不代表外部平台执行器已经接通。</p>
        <div class="form-grid">
          <el-form-item label="生产刊登模式">
            <el-select v-model="form.listing_write.mode" style="width: 100%">
              <el-option label="关闭生产刊登" value="disabled" />
              <el-option label="受控生产刊登" value="controlled" />
            </el-select>
          </el-form-item>
          <el-form-item label="紧急停止">
            <el-switch v-model="form.listing_write.emergency_stop" active-text="已停止" inactive-text="允许运行" />
            <small>启用紧急停止时，所有 production 刊登请求都会安全拒绝。</small>
          </el-form-item>
          <el-form-item label="刊登资料审批 + 每批确认">
            <el-switch v-model="form.listing_write.require_batch_approval" active-text="强制" inactive-text="关闭" disabled />
            <small>受控模式始终要求刊登资料先审批、每批显式确认，不能在页面上关闭。</small>
          </el-form-item>
          <el-form-item label="单批上限">
            <el-input-number v-model="form.listing_write.max_batch_size" :min="1" :max="100" controls-position="right" />
            <small>每次生产刊登请求最多允许的商品数量，范围 1–100。</small>
          </el-form-item>
          <el-form-item label="允许平台" class="wide">
            <el-checkbox-group v-model="form.listing_write.allowed_platforms" class="check-group">
              <el-checkbox label="lazada">Lazada</el-checkbox>
              <el-checkbox label="shopee">Shopee</el-checkbox>
              <el-checkbox label="tiktok">TikTok Shop</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="允许动作" class="wide">
            <el-checkbox-group v-model="form.listing_write.allowed_actions" class="check-group">
              <el-checkbox label="create">创建</el-checkbox>
              <el-checkbox label="update">更新</el-checkbox>
              <el-checkbox label="pause">暂停/下架</el-checkbox>
            </el-checkbox-group>
            <small>删除商品、改价、库存、订单、退款和资金动作不在此策略范围内。</small>
          </el-form-item>
          <el-form-item label="允许生产刊登的店铺 ID" class="wide">
            <el-input v-model="allowedStoreIdsText" type="textarea" :rows="2" placeholder="每行或逗号分隔一个店铺 ID，例如 101, 102" />
            <small>必填白名单；ID 从“店铺档案”获取。空列表表示不允许任何店铺进入 production 队列。</small>
          </el-form-item>
        </div>
        <el-alert title="高风险操作：启用受控生产刊登或解除紧急停止会要求危险确认，并且仍须创建版本、刊登资料审批、每批显式确认，以及满足网络、合同、密钥托管等生产安全门。" type="warning" :closable="false" show-icon />
      </fieldset>

      <fieldset class="settings-section">
        <legend>平台生产 API 配置</legend>
        <p class="section-note">平台端点和合同审批是公开配置元数据；店铺授权统一在“店铺档案”的“API 接入”中完成。全球刊登是否可生产执行由上方独立受控策略决定，API 数据同步仍只读。</p>
        <div class="platform-grid">
          <article v-for="platform in platformKeys" :key="platform" :ref="(element) => setPlatformSectionRef(platform, element)" class="platform-card">
            <header><div><strong>{{ platformLabels[platform] }}</strong><small>{{ platformDescriptions[platform] }}</small></div><el-tag effect="plain" :type="form.platforms[platform].contract_approved ? 'success' : 'warning'">{{ form.platforms[platform].contract_approved ? '合同已批准' : '合同未批准' }}</el-tag></header>
            <el-form-item label="合同审批状态"><el-switch v-model="form.platforms[platform].contract_approved" active-text="已批准" inactive-text="未批准" /></el-form-item>
            <div class="form-grid compact">
              <el-form-item label="公开 App ID *"><el-input v-model="form.platforms[platform].app_id" autocomplete="off" placeholder="填写平台公开应用 ID" /></el-form-item>
              <el-form-item v-if="platform === 'tiktok'" label="Service ID"><el-input v-model="form.platforms[platform].service_id" autocomplete="off" placeholder="TikTok Shop Service ID" /></el-form-item>
              <el-form-item label="OAuth redirect_uri *"><el-input v-model="form.platforms[platform].redirect_uri" type="url" autocomplete="off" placeholder="https://.../callback" /></el-form-item>
              <el-form-item label="market *"><el-input v-model="form.platforms[platform].market" maxlength="40" placeholder="SG" /></el-form-item>
              <el-form-item v-if="platform === 'shopee'" label="region"><el-input v-model="form.platforms[platform].region" maxlength="40" placeholder="SG" /></el-form-item>
            </div>
            <details class="advanced-endpoints" :open="openEndpointPlatform === platform">
              <summary>高级 endpoint / path 配置（{{ platformEndpointFields[platform].length }} 项）</summary>
              <div class="form-grid compact endpoint-grid">
                <el-form-item v-for="field in platformEndpointFields[platform]" :key="field.key" :label="field.label">
                  <el-input
                    v-if="field.kind === 'mapping'"
                    type="textarea"
                    :rows="2"
                    :model-value="mappingText(form.platforms[platform][field.key])"
                    :placeholder="field.placeholder"
                    @update:model-value="setMapping(platform, field.key, $event)"
                  />
                  <el-input v-else v-model="form.platforms[platform][field.key]" :type="field.kind === 'url' ? 'url' : 'text'" autocomplete="off" :placeholder="field.placeholder" />
                  <small v-if="field.kind === 'mapping'">每行填写 MARKET=HTTPS 地址；不要填写任何 Token 或 Secret。</small>
                </el-form-item>
              </div>
            </details>
          </article>
        </div>
      </fieldset>

      <div class="submit-bar">
        <el-input v-model="changeReason" maxlength="240" show-word-limit placeholder="填写本次配置变更原因（至少 5 个字符）" />
        <el-button
          type="primary"
          class="danger-action"
          :loading="saving"
          :disabled="!manageAccess.allowed || saving"
          :title="manageAccess.allowed ? '创建待审批生产环境配置版本' : manageAccess.reason"
          @click="submitVersion"
        >提交待审批版本</el-button>
      </div>
      <p v-if="!manageAccess.allowed" class="permission-note">{{ manageAccess.reason }}</p>
    </el-form>

    <section class="versions-card">
      <header><div><h2>配置版本与审批记录</h2><p>版本不可直接覆盖；审批生成新的有效版本，回滚也会创建新的待审批版本。</p></div><span>{{ versions.length }} 个版本</span></header>
      <el-table v-loading="loading" :data="versions" row-key="id" empty-text="暂无配置版本">
        <el-table-column label="版本" min-width="90"><template #default="scope">v{{ scope.row.version || scope.row.number || '—' }}</template></el-table-column>
        <el-table-column label="状态" min-width="120"><template #default="scope"><el-tag :type="versionType(scope.row.status)">{{ versionStatusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="创建人" min-width="130"><template #default="scope">{{ actorLabel(scope.row.created_by || scope.row.creator || scope.row.created_by_id, '—') }}</template></el-table-column>
        <el-table-column label="审批人" min-width="130"><template #default="scope">{{ actorLabel(scope.row.approved_by || scope.row.approver || scope.row.approved_by_id, '待审批') }}</template></el-table-column>
        <el-table-column label="创建时间" min-width="175"><template #default="scope">{{ dateLabel(scope.row.created_at) }}</template></el-table-column>
        <el-table-column label="变更摘要" min-width="250" show-overflow-tooltip><template #default="scope">{{ scope.row.change_summary || scope.row.reason || '—' }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="230">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 'pending_approval'"
              link
              type="primary"
              :loading="actionLoading === `approve:${scope.row.id}`"
              :disabled="!approvalAccess.allowed || isOwnVersion(scope.row) || Boolean(actionLoading)"
              :title="approvalDisabledReason(scope.row)"
              @click="approveVersion(scope.row)"
            >审批生效</el-button>
            <el-button
              v-if="canRollback(scope.row)"
              link
              type="danger"
              :loading="actionLoading === `rollback:${scope.row.id}`"
              :disabled="!rollbackAccess.allowed || Boolean(actionLoading)"
              :title="rollbackAccess.allowed ? '以该版本创建新的待审批回滚版本' : rollbackAccess.reason"
              @click="rollbackVersion(scope.row)"
            >回滚到此版本</el-button>
            <span v-if="scope.row.id === currentVersion?.id" class="current-label">当前生效</span>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import {
  approveProductionIntegrationSettingsVersion,
  createProductionIntegrationSettingsVersion,
  fetchProductionIntegrationSettings,
  rollbackProductionIntegrationSettingsVersion
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const route = useRoute();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const actionLoading = ref('');
const changeReason = ref('完善生产只读 API 安全门与全球刊登受控策略');
const allowedHostsText = ref('');
const redirectAllowlistText = ref('');
const allowedStoreIdsText = ref('');
const currentConfig = ref(null);
const currentVersion = ref(null);
const pendingVersion = ref(null);
const pendingConfig = ref(null);
const versions = ref([]);
const runtime = ref({ environment: 'production', status: 'blocked', ready: false, write_enabled: false });
const source = ref('');
const networkSection = ref(null);
const custodySection = ref(null);
const listingWriteSection = ref(null);
const writeOverview = ref(null);
const platformSectionRefs = ref({});
const openEndpointPlatform = ref('');

const platformKeys = ['lazada', 'shopee', 'tiktok'];
const platformLabels = { lazada: 'Lazada', shopee: 'Shopee', tiktok: 'TikTok Shop' };
const platformDescriptions = { lazada: 'Lazada Open Platform', shopee: 'Shopee Partner API', tiktok: 'TikTok Shop Open API' };
const platformEndpointFields = {
  lazada: [
    { key: 'auth_url', label: '授权地址 auth_url', kind: 'url', placeholder: 'https://auth.lazada.com/oauth/authorize' },
    { key: 'api_host', label: 'API Host api_host', kind: 'url', placeholder: 'https://api.lazada.com' },
    { key: 'token_path', label: 'Token Path token_path', kind: 'path', placeholder: '/rest/auth/token/create' },
    { key: 'refresh_path', label: 'Refresh Path refresh_path', kind: 'path', placeholder: '/rest/auth/token/refresh' }
  ],
  shopee: [
    { key: 'auth_url', label: '授权地址 auth_url', kind: 'url', placeholder: 'https://partner.shopeemobile.com/api/v2/shop/auth_partner' },
    { key: 'api_host', label: 'API Host api_host', kind: 'url', placeholder: 'https://partner.shopeemobile.com' },
    { key: 'token_path', label: 'Token Path token_path', kind: 'path', placeholder: '/api/v2/auth/token/get' },
    { key: 'refresh_path', label: 'Refresh Path refresh_path', kind: 'path', placeholder: '/api/v2/auth/access_token/get' },
    { key: 'revoke_path', label: 'Revoke Path revoke_path', kind: 'path', placeholder: '/api/v2/shop/cancel_auth_partner' },
    { key: 'shop_path', label: 'Shop Path shop_path', kind: 'path', placeholder: '/api/v2/shop/get_shop_info' },
    { key: 'order_list_path', label: 'Order List Path order_list_path', kind: 'path', placeholder: '/api/v2/order/get_order_list' },
    { key: 'order_detail_path', label: 'Order Detail Path order_detail_path', kind: 'path', placeholder: '/api/v2/order/get_order_detail' },
    { key: 'return_list_path', label: 'Return List Path return_list_path', kind: 'path', placeholder: '/api/v2/returns/get_return_list' },
    { key: 'return_detail_path', label: 'Return Detail Path return_detail_path', kind: 'path', placeholder: '/api/v2/returns/get_return_detail' }
  ],
  tiktok: [
    { key: 'auth_url', label: '默认授权地址 auth_url', kind: 'url', placeholder: 'https://auth.tiktok-shops.com' },
    { key: 'api_host', label: '默认 API Host api_host', kind: 'url', placeholder: 'https://open-api.tiktokglobalshop.com' },
    { key: 'auth_urls', label: '分市场授权地址 auth_urls', kind: 'mapping', placeholder: 'SG=https://...' },
    { key: 'api_hosts', label: '分市场 API Host api_hosts', kind: 'mapping', placeholder: 'SG=https://...' },
    { key: 'token_host', label: 'Token Host token_host', kind: 'url', placeholder: 'https://auth.tiktok-shops.com' },
    { key: 'token_path', label: 'Token Path token_path', kind: 'path', placeholder: '/api/v2/token/get' },
    { key: 'refresh_path', label: 'Refresh Path refresh_path', kind: 'path', placeholder: '/api/v2/token/refresh' },
    { key: 'revoke_path', label: 'Revoke Path revoke_path', kind: 'path', placeholder: '/api/v2/token/revoke' },
    { key: 'authorized_shops_path', label: 'Authorized Shops Path authorized_shops_path', kind: 'path', placeholder: '/authorization/202309/shops' },
    { key: 'metadata_path', label: 'Metadata Path metadata_path', kind: 'path', placeholder: '/seller/202309/permissions' },
    { key: 'order_list_path', label: 'Order List Path order_list_path', kind: 'path', placeholder: '/order/202309/orders/search' },
    { key: 'order_detail_path', label: 'Order Detail Path order_detail_path', kind: 'path', placeholder: '/order/202309/orders' },
    { key: 'return_list_path', label: 'Return List Path return_list_path', kind: 'path', placeholder: '/return_refund/202602/returns/search' }
  ]
};
const platformPayloadKeys = {
  lazada: ['contract_approved', 'app_id', 'redirect_uri', 'auth_url', 'api_host', 'token_path', 'refresh_path', 'market'],
  shopee: ['contract_approved', 'app_id', 'redirect_uri', 'auth_url', 'api_host', 'token_path', 'refresh_path', 'revoke_path', 'shop_path', 'order_list_path', 'order_detail_path', 'return_list_path', 'return_detail_path', 'market', 'region'],
  tiktok: ['contract_approved', 'app_id', 'service_id', 'redirect_uri', 'market', 'auth_url', 'api_host', 'auth_urls', 'api_hosts', 'token_host', 'token_path', 'refresh_path', 'revoke_path', 'authorized_shops_path', 'metadata_path', 'order_list_path', 'order_detail_path', 'return_list_path']
};

function createEmptyConfig() {
  return {
    network: {
      mode: '',
      security_approved: false,
      readonly_sync_enabled: false,
      allowed_hosts: [],
      oauth_redirect_allowlist: []
    },
    connection: {
      connect_timeout_seconds: 3,
      read_timeout_seconds: 8,
      max_retries: 2,
      backoff_base_seconds: 0.5,
      max_retry_wait_seconds: 8,
      max_total_wait_seconds: 15
    },
    custody: { backend: 'refuse', service_url: '', service_host: '', auth_file_path: '', ca_file_path: '', token_available: false },
    listing_write: {
      mode: 'disabled',
      emergency_stop: true,
      require_batch_approval: true,
      allowed_platforms: [],
      allowed_actions: [],
      allowed_store_ids: [],
      max_batch_size: 20
    },
    platforms: Object.fromEntries(platformKeys.map((platform) => [platform, {
      contract_approved: false, app_id: '', service_id: '', redirect_uri: '', market: '', region: '',
      auth_url: '', api_host: '', auth_urls: {}, api_hosts: {}, token_host: '', token_path: '', refresh_path: '',
      revoke_path: '', shop_path: '', authorized_shops_path: '', metadata_path: '', order_list_path: '',
      order_detail_path: '', return_list_path: '', return_detail_path: ''
    }]))
  };
}

function clone(value) {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

function normalizeConfig(value = {}) {
  const defaults = createEmptyConfig();
  const network = value.network || {};
  const connection = value.connection || value.retry || value.connection_retry || {};
  const rawPlatforms = Array.isArray(value.platforms)
    ? Object.fromEntries(value.platforms.map((item) => [item.platform || item.platform_code, item]))
    : (value.platforms || value.platform_configs || {});
  return {
    network: {
      ...defaults.network,
      ...network,
      allowed_hosts: Array.isArray(network.allowed_hosts) ? [...network.allowed_hosts] : [],
      oauth_redirect_allowlist: Array.isArray(network.oauth_redirect_allowlist) ? [...network.oauth_redirect_allowlist] : []
    },
    connection: { ...defaults.connection, ...connection },
    custody: { ...defaults.custody, ...(value.custody || value.credential_custody || {}) },
    listing_write: {
      ...defaults.listing_write,
      ...(value.listing_write || {}),
      allowed_platforms: Array.isArray(value.listing_write?.allowed_platforms) ? [...value.listing_write.allowed_platforms] : [],
      allowed_actions: Array.isArray(value.listing_write?.allowed_actions) ? [...value.listing_write.allowed_actions] : [],
      allowed_store_ids: Array.isArray(value.listing_write?.allowed_store_ids) ? [...value.listing_write.allowed_store_ids] : []
    },
    platforms: Object.fromEntries(platformKeys.map((platform) => [platform, {
      ...defaults.platforms[platform],
      ...(rawPlatforms[platform] || {})
    }]))
  };
}

function unpackVersions(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.results)) return value.results;
  if (Array.isArray(value?.items)) return value.items;
  return [];
}

function mappingText(value) {
  return Object.entries(value || {}).map(([market, endpoint]) => `${market}=${endpoint}`).join('\n');
}

function parseMapping(value) {
  return String(value || '').split(/\r?\n|,/).reduce((result, line) => {
    const [market, ...endpointParts] = line.split('=');
    const key = String(market || '').trim().toUpperCase();
    const endpoint = endpointParts.join('=').trim();
    if (key && endpoint) result[key] = endpoint;
    return result;
  }, {});
}

function setMapping(platform, key, value) {
  form.platforms[platform][key] = parseMapping(value);
}

function runtimeReady(config, maskedStatus = {}) {
  const network = config?.network || {};
  const custody = config?.custody || {};
  const custodyMask = maskedStatus?.custody || {};
  const platforms = config?.platforms || {};
  return Boolean(
    network.mode === 'approved-live-test'
      && network.security_approved
      && network.readonly_sync_enabled
      && network.allowed_hosts?.length
      && network.oauth_redirect_allowlist?.length
      && custody.backend && custody.backend !== 'refuse'
      && custody.service_url && custody.service_host
      && custodyMask.token_available
      && platformKeys.every((platform) => {
        const item = platforms[platform] || {};
        return item.contract_approved && item.app_id && item.redirect_uri && (item.api_host || Object.keys(item.api_hosts || {}).length) && item.market;
      })
  );
}

function hydrate(data = {}) {
  const effective = data.effective_config || data.config || data.runtime?.config || data.effective?.value || data.effective || data.current?.config || {};
  const normalized = normalizeConfig(effective);
  currentConfig.value = clone(normalized);
  Object.assign(form, normalized);
  allowedHostsText.value = normalized.network.allowed_hosts.join('\n');
  redirectAllowlistText.value = normalized.network.oauth_redirect_allowlist.join('\n');
  allowedStoreIdsText.value = normalized.listing_write.allowed_store_ids.join('\n');
  const maskedStatus = data.masked_status || data.runtime?.masked_status || {};
  form.custody.token_available = Boolean(maskedStatus?.custody?.token_available);
  const runtimePayload = data.runtime && typeof data.runtime === 'object' ? data.runtime : {};
  const ready = runtimePayload.ready ?? (runtimePayload.valid === false ? false : runtimeReady(normalized, maskedStatus));
  runtime.value = {
    environment: 'production',
    status: ready ? 'ready' : (runtimePayload.valid === false ? 'invalid' : 'blocked'),
    ready,
    write_enabled: false,
    checked_at: data.checked_at || runtimePayload.checked_at || null,
    message: data.validation_error || runtimePayload.validation_error || (ready ? '生产只读安全门已通过；全球刊登生产策略独立受控。' : 'API 同步写入关闭；全球刊登生产策略仍需配置与审批。'),
    ...runtimePayload,
    status: runtimePayload.status || (ready ? 'ready' : (runtimePayload.valid === false ? 'invalid' : 'blocked')),
    ready: runtimePayload.ready ?? ready,
    write_enabled: false
  };
  source.value = data.source || data.effective_source || runtimePayload.source || 'unknown';
  versions.value = unpackVersions(data.versions || data.version_history);
  const currentMeta = [data.current_version, data.effective].find((item) => item && typeof item === 'object' && !Array.isArray(item) && ('version' in item || 'number' in item));
  const effectiveVersionNumber = data.effective_version === null || data.effective_version === undefined || data.effective_version === '' ? null : Number(data.effective_version);
  currentVersion.value = currentMeta || (Number.isFinite(effectiveVersionNumber) ? { id: data.version_id, version: effectiveVersionNumber, status: 'effective' } : versions.value.find((item) => ['effective', 'active', 'approved'].includes(item.status))) || null;
  const pendingMeta = data.pending_version && typeof data.pending_version === 'object' ? data.pending_version : data.pending?.value && typeof data.pending.value === 'object' ? data.pending.value : null;
  pendingVersion.value = pendingMeta || versions.value.find((item) => ['pending_approval', 'pending', 'draft'].includes(item.status)) || null;
  pendingConfig.value = data.pending_config || data.pending?.value || data.pending?.config || pendingVersion.value?.value || null;
}

const form = reactive(createEmptyConfig());
const sourceLabel = computed(() => ({
  system_database: '系统数据库', database: '系统数据库', environment: '部署环境', env: '部署环境', default: '默认值', unknown: '未标明', invalid_environment: '部署环境无效', invalid_database: '系统数据库无效'
}[source.value] || source.value || '未标明'));
const viewerAccess = computed(() => systemActionAccess('config.view'));
const manageAccess = computed(() => systemActionAccess('config.manage'));
const approvalAccess = computed(() => systemActionAccess('config.approve'));
const rollbackAccess = computed(() => systemActionAccess('config.rollback'));

function systemActionAccess(permission) {
  const missing = [permission, 'config.system.manage'].filter((code) => !auth.hasPermission(code));
  return { allowed: missing.length === 0, disabled: missing.length > 0, reason: missing.length ? `缺少操作权限：${missing.join('、')}` : '' };
}

function splitLines(value) {
  return [...new Set(String(value || '').split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean))];
}

function parseStoreIdInput(value) {
  const tokens = String(value || '').split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
  const invalid = tokens.filter((item) => !/^[1-9]\d*$/.test(item) || !Number.isSafeInteger(Number(item)));
  return {
    invalid,
    values: [...new Set(tokens.filter((item) => !invalid.includes(item)).map((item) => Number(item)))]
  };
}

function buildPayload() {
  const { token_available: _tokenAvailable, ...custody } = form.custody;
  const platforms = Object.fromEntries(platformKeys.map((platform) => [
    platform,
    Object.fromEntries(platformPayloadKeys[platform].map((key) => [key, clone(form.platforms[platform][key])]))
  ]));
  return {
    network: {
      ...clone(form.network),
      allowed_hosts: splitLines(allowedHostsText.value),
      oauth_redirect_allowlist: splitLines(redirectAllowlistText.value)
    },
    connection: clone(form.connection),
    custody: clone(custody),
    listing_write: {
      ...clone(form.listing_write),
      require_batch_approval: true,
      allowed_store_ids: parseStoreIdInput(allowedStoreIdsText.value).values
    },
    platforms
  };
}

function isDangerousChange() {
  const previous = currentConfig.value || createEmptyConfig();
  return Boolean(
    (form.network.mode === 'approved-live-test' && previous.network.mode !== 'approved-live-test')
      || (form.network.security_approved && !previous.network.security_approved)
      || (form.network.readonly_sync_enabled && !previous.network.readonly_sync_enabled)
      || platformKeys.some((platform) => form.platforms[platform].contract_approved && !previous.platforms[platform].contract_approved)
      || (form.listing_write.mode === 'controlled' && previous.listing_write.mode !== 'controlled')
      || (form.listing_write.emergency_stop === false && previous.listing_write.emergency_stop !== false)
  );
}

const listingWriteLabel = computed(() => (
  currentConfig.value?.listing_write?.mode === 'controlled'
    && currentConfig.value?.listing_write?.emergency_stop === false
    ? '受控已生效'
    : '当前关闭'
));

async function load() {
  loading.value = true;
  error.value = '';
  if (!viewerAccess.value.allowed) {
    error.value = viewerAccess.value.reason;
    loading.value = false;
    return;
  }
  try {
    const response = await fetchProductionIntegrationSettings();
    if (!response?.success) throw new Error(response?.message || '读取生产环境配置失败。');
    hydrate(response.data || {});
  } catch (loadError) {
    error.value = loadError?.message || '读取生产环境配置失败。';
  } finally {
    loading.value = false;
  }
}

async function submitVersion() {
  if (!manageAccess.value.allowed || saving.value) {
    if (!manageAccess.value.allowed) ElMessage.warning(manageAccess.value.reason);
    return;
  }
  if (changeReason.value.trim().length < 5) return ElMessage.warning('请填写至少 5 个字符的配置变更原因。');
  const storeIdInput = parseStoreIdInput(allowedStoreIdsText.value);
  if (storeIdInput.invalid.length) return ElMessage.warning(`店铺 ID 必须为正整数：${storeIdInput.invalid.slice(0, 3).join('、')}`);
  if (storeIdInput.values.length > 500) return ElMessage.warning('允许生产刊登的店铺最多配置 500 个。');
  const payload = { value: buildPayload(), change_reason: changeReason.value.trim() };
  if (!payload.value.custody.backend) return ElMessage.warning('请选择密钥托管后端；若尚未配置可选择拒绝/关闭。');
  saving.value = true;
  try {
    if (isDangerousChange()) {
      await ElMessageBox.confirm(
        '本次变更将启用全球刊登独立受控生产通道或解除紧急停止。提交后不会立即生效，仍需版本审批、刊登资料审批、每批显式确认以及网络、合同和密钥托管安全门；API 数据同步写入仍保持关闭。是否继续？',
        '确认提交高风险配置',
        { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消' }
      );
    }
    const response = await createProductionIntegrationSettingsVersion(payload);
    if (!response?.success) return ElMessage.error(response?.message || '生产环境配置版本创建失败。');
    ElMessage.success('待审批配置版本已创建。');
    await load();
  } catch (submitError) {
    if (submitError === 'cancel' || submitError === 'close') return;
    ElMessage.error(submitError?.message || '生产环境配置版本创建失败。');
  } finally {
    saving.value = false;
  }
}

async function approveVersion(version) {
  if (isOwnVersion(version)) {
    ElMessage.warning('创建人不能审批自己的版本。');
    return;
  }
  if (!approvalAccess.value.allowed || actionLoading.value || !version?.id) {
    if (!approvalAccess.value.allowed) ElMessage.warning(approvalAccess.value.reason);
    return;
  }
  try {
    await ElMessageBox.confirm(`确认审批生产环境配置 v${version.version}？审批后 API 数据同步仍只读；全球刊登是否进入生产队列由独立策略、刊登资料审批和每批显式确认控制。`, '审批生产环境配置', { type: 'warning', confirmButtonText: '确认审批', cancelButtonText: '取消' });
  } catch (reason) {
    if (reason === 'cancel' || reason === 'close') return;
    throw reason;
  }
  actionLoading.value = `approve:${version.id}`;
  try {
    const response = await approveProductionIntegrationSettingsVersion(version.id);
    if (!response?.success) return ElMessage.error(response?.message || '配置版本审批失败。');
    ElMessage.success('生产环境配置版本已审批。');
    await load();
  } finally {
    actionLoading.value = '';
  }
}

async function rollbackVersion(version) {
  if (!rollbackAccess.value.allowed || actionLoading.value || !version?.id) {
    if (!rollbackAccess.value.allowed) ElMessage.warning(rollbackAccess.value.reason);
    return;
  }
  try {
    await ElMessageBox.confirm(`确认以 v${version.version} 创建新的回滚待审批版本？原始版本和审计记录不会被覆盖。`, '回滚生产环境配置', { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' });
  } catch (reason) {
    if (reason === 'cancel' || reason === 'close') return;
    throw reason;
  }
  actionLoading.value = `rollback:${version.id}`;
  try {
    const response = await rollbackProductionIntegrationSettingsVersion(version.id);
    if (!response?.success) return ElMessage.error(response?.message || '配置版本回滚失败。');
    ElMessage.success('回滚待审批版本已创建。');
    await load();
  } finally {
    actionLoading.value = '';
  }
}

function versionLabel(version) { return version?.version || version?.number ? `v${version.version || version.number}` : '—'; }
function actorLabel(actor, fallback = '—') {
  if (actor === null || actor === undefined || actor === '') return fallback;
  if (typeof actor === 'string' || typeof actor === 'number') return String(actor);
  return actor.username || actor.name || actor.email || actor.id || actor.user_id || fallback;
}
function isOwnVersion(version) {
  const currentUser = auth.currentUser || {};
  const currentIds = [currentUser.id, currentUser.user_id, currentUser.username].filter((value) => value !== undefined && value !== null && value !== '');
  const creator = version?.created_by || version?.creator;
  const creatorIds = [version?.created_by_id, creator?.id, creator?.user_id, creator?.username].filter((value) => value !== undefined && value !== null && value !== '');
  return currentIds.length > 0 && creatorIds.some((value) => currentIds.some((current) => String(current) === String(value)));
}
function approvalDisabledReason(version) {
  if (isOwnVersion(version)) return '创建人不能审批自己的版本';
  return approvalAccess.value.allowed ? '审批该生产环境配置版本' : approvalAccess.value.reason;
}
function dateLabel(value) { return value ? String(value).replace('T', ' ').slice(0, 19) : '—'; }
function modeLabel(value) { return ({ '': '关闭生产访问', 'approved-live-test': '批准的生产只读' }[value] || value || '—'); }
function versionStatusLabel(value) { return ({ effective: '当前生效', active: '当前生效', pending_approval: '待审批', pending: '待审批', approved: '已批准', superseded: '已替代', rolled_back: '已回滚' }[value] || value || '未知'); }
function versionType(value) { return ['effective', 'active', 'approved'].includes(value) ? 'success' : ['pending_approval', 'pending'].includes(value) ? 'warning' : 'info'; }
function canRollback(version) { return Boolean(version?.id && !['pending_approval', 'pending', 'draft'].includes(version.status) && String(version.id) !== String(currentVersion.value?.id)); }

function setPlatformSectionRef(platform, element) {
  if (element) platformSectionRefs.value[platform] = element;
  else delete platformSectionRefs.value[platform];
}

async function focusFromRoute() {
  const requestedPlatform = String(route.query.platform || '').toLowerCase();
  const requestedFocus = String(route.query.focus || '').toLowerCase();
  if (requestedPlatform && platformKeys.includes(requestedPlatform)) {
    openEndpointPlatform.value = requestedPlatform;
    await nextTick();
    platformSectionRefs.value[requestedPlatform]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  const target = requestedFocus === 'custody'
    ? custodySection.value
    : requestedFocus === 'write'
      ? (listingWriteSection.value || writeOverview.value)
      : requestedFocus
        ? networkSection.value
        : null;
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

onMounted(async () => {
  await load();
  await nextTick();
  await focusFromRoute();
});
watch(() => `${route.query.focus || ''}:${route.query.platform || ''}`, () => { focusFromRoute(); });
</script>

<style scoped>
.production-settings-page { display: grid; gap: 16px; color: #14213a; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.page-header h1 { margin: 0; color: #172033; font-size: 26px; }
.page-header > div:first-child > p:last-child { max-width: 760px; margin: 7px 0 0; color: #607087; line-height: 1.6; }
.eyebrow { margin: 0 0 6px; color: #64748b; font-size: 12px; font-weight: 700; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.overview-grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; }
.overview-card, .runtime-card, .settings-section, .versions-card { overflow: hidden; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.overview-card { min-height: 92px; padding: 15px 16px; }
.overview-card.is-pending { border-color: #f1c88a; background: #fffaf1; }
.overview-card span, .overview-card small { display: block; color: #64748b; font-size: 12px; }
.overview-card strong { display: block; margin: 7px 0 4px; color: #172033; font-size: 19px; }
.overview-card small { line-height: 1.45; }
.runtime-card > header, .versions-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 15px 16px; }
.runtime-card h2, .versions-card h2 { margin: 0; color: #273449; font-size: 17px; }
.runtime-card header p, .versions-card header p { margin: 6px 0 0; color: #718096; font-size: 12px; }
.runtime-card header > .el-tag, .versions-card > header > span { flex: 0 0 auto; color: #607087; font-size: 12px; }
.runtime-grid { display: grid; grid-template-columns: repeat(6, 1fr); margin: 0; border-top: 1px solid #e5ebf2; }
.runtime-grid div { min-width: 0; padding: 12px 14px; border-right: 1px solid #e5ebf2; }
.runtime-grid div:last-child { border-right: 0; }
.runtime-grid dt { color: #718096; font-size: 12px; }
.runtime-grid dd { margin: 5px 0 0; overflow-wrap: anywhere; font-size: 13px; font-weight: 650; }
.settings-form { display: grid; gap: 16px; }
.settings-section { min-width: 0; margin: 0; padding: 17px 16px 5px; }
.settings-section legend { padding: 0 8px; color: #26364d; font-size: 16px; font-weight: 700; }
.section-note { margin: -2px 0 15px; color: #718096; font-size: 12px; line-height: 1.6; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-grid.compact { gap: 0 12px; }
.form-grid .wide { grid-column: 1 / -1; }
.settings-section :deep(.el-input-number) { width: 100%; }
.settings-section :deep(.el-form-item) { margin-bottom: 16px; }
.settings-section :deep(.el-form-item__label) { padding-bottom: 5px; line-height: 18px; }
.settings-section small { display: block; margin-top: 5px; color: #7b8798; font-size: 11px; line-height: 1.5; }
.listing-write-section { border-color: #e6b566; }
.check-group { display: flex; flex-wrap: wrap; gap: 8px 18px; min-height: 32px; align-items: center; }
.readonly-value { display: flex; align-items: center; gap: 9px; min-height: 32px; }
.readonly-value small { margin: 0; }
.platform-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.platform-card { min-width: 0; padding: 14px; border: 1px solid #dce5ef; border-radius: 7px; background: #f9fbfd; }
.platform-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 13px; }
.platform-card > header strong, .platform-card > header small { display: block; }
.platform-card > header small { margin-top: 4px; color: #718096; font-size: 11px; }
.submit-bar { display: flex; align-items: center; gap: 12px; }
.submit-bar .el-input { flex: 1; }
.danger-action { color: #fff !important; border-color: #d94841 !important; background: #d94841 !important; }
.permission-note { margin: -7px 0 0; color: #b45309; font-size: 12px; }
.current-label { color: #07835c; font-size: 12px; }
.versions-card :deep(.el-table th.el-table__cell) { color: #40516a; background: #f4f7fa; }
.versions-card :deep(.el-table .cell) { line-height: 1.4; }
@media (max-width: 1100px) { .overview-grid { grid-template-columns: repeat(2, minmax(150px, 1fr)); }.runtime-grid { grid-template-columns: repeat(3, 1fr); }.runtime-grid div:nth-child(3) { border-right: 0; } .platform-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .page-header { flex-direction: column; }.overview-grid { grid-template-columns: 1fr; }.runtime-grid { grid-template-columns: 1fr 1fr; }.runtime-grid div:nth-child(3) { border-right: 1px solid #e5ebf2; }.runtime-grid div:nth-child(2n) { border-right: 0; }.form-grid { grid-template-columns: 1fr; }.form-grid .wide { grid-column: auto; }.submit-bar { align-items: stretch; flex-direction: column; }.submit-bar .el-button { width: 100%; } }
</style>
