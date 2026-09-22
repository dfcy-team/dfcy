<template>
  <section class="bd-config-page">
    <header class="hero">
      <div>
        <p class="eyebrow">CREATOR OPERATIONS</p>
        <h1>BD 配置</h1>
        <p>设置绩效指标视图、每日归因补偿及送样逾期提醒。</p>
      </div>
      <el-tag :type="apiStatus === 'connected' ? 'success' : 'warning'">
        {{ apiStatus === 'connected' ? '配置服务已连接' : '配置服务不可用' }}
      </el-tag>
    </header>

    <el-alert
      v-if="latestStatus === 'pending_approval'"
      title="新配置正在等待审批，当前报表继续使用已生效版本。"
      type="warning"
      :closable="false"
      show-icon
    />

    <div class="content-grid">
      <el-card shadow="never" class="editor-card">
        <template #header>
          <div class="card-heading">
            <div>
              <strong>绩效默认设置</strong>
              <span>新设置提交后生成不可变版本</span>
            </div>
            <el-tag effect="plain">{{ versionLabel }}</el-tag>
          </div>
        </template>

        <el-form label-position="top" :model="form" class="settings-form">
          <div class="field-grid">
            <el-form-item label="默认指标视图">
              <el-radio-group v-model="form.default_metrics">
                <el-radio-button value="core">核心</el-radio-button>
                <el-radio-button value="full">完整</el-radio-button>
              </el-radio-group>
              <small>{{ form.default_metrics === 'core' ? '优先展示 GMV、投入和 ROI' : '展示全部绩效指标' }}</small>
            </el-form-item>

            <el-form-item label="每日归因补偿">
              <div class="switch-line">
                <el-switch v-model="form.daily_attribution_reconciliation_enabled" />
                <span>{{ form.daily_attribution_reconciliation_enabled ? '已开启' : '已关闭' }}</span>
              </div>
              <small>开启后每天处理近期增量，并分批回扫历史遗漏。</small>
            </el-form-item>

            <el-form-item label="送样逾期时长">
              <el-input-number
                v-model="form.sample_video_overdue_days"
                :min="1"
                :max="365"
                :step="1"
                class="full-width"
              />
              <small>新建、发货或同步重算截止时间时，从送样或发货日起计算；已存在的截止时间不变。</small>
            </el-form-item>

            <el-form-item label="送样逾期提醒">
              <div class="switch-line">
                <el-switch v-model="form.sample_overdue_notification_enabled" />
                <span>{{ form.sample_overdue_notification_enabled ? '已开启' : '已关闭' }}</span>
              </div>
              <small>逾期状态生成时，向该送样负责人创建一条站内提醒；同一送样仅提醒一次。</small>
            </el-form-item>
          </div>

          <el-form-item label="生效时间">
            <el-date-picker
              v-model="effectiveAt"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ssZ"
              class="full-width"
              placeholder="选择生效时间"
            />
          </el-form-item>

          <div class="form-actions">
            <span>配置需要审批，审批通过并到达生效时间后自动启用。</span>
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!createAccess.allowed || apiStatus !== 'connected'"
              @click="saveVersion"
            >提交新版本</el-button>
          </div>
        </el-form>
      </el-card>

      <el-card shadow="never" class="status-card">
        <template #header><strong>当前版本</strong></template>
        <dl>
          <div><dt>版本</dt><dd>{{ versionLabel }}</dd></div>
          <div><dt>状态</dt><dd><el-tag :type="statusType">{{ statusLabel }}</el-tag></dd></div>
          <div><dt>生效时间</dt><dd>{{ latestVersion?.effective_at || '尚未设置' }}</dd></div>
          <div><dt>需要审批</dt><dd>{{ definition?.requires_approval ? '是' : '否' }}</dd></div>
        </dl>
        <el-button
          v-if="latestStatus === 'pending_approval' && approveAccess.visible"
          type="success"
          plain
          :loading="approving"
          :disabled="!approveAccess.allowed"
          @click="approveLatest"
        >审批当前版本</el-button>
      </el-card>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { approveConfigValue, createConfigValue, fetchConfigDefinitions, fetchConfigValues } from '../../api/configCenter';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const CONFIG_KEY = 'influencers.bd.performance';
const defaults = {
  default_metrics: 'core',
  daily_attribution_reconciliation_enabled: true,
  sample_video_overdue_days: 20,
  sample_overdue_notification_enabled: false
};
const CONFIG_FIELDS = Object.freeze(Object.keys(defaults));
const auth = useAuthStore();
const form = reactive({ ...defaults });
const definition = ref(null);
const versions = ref([]);
const effectiveAt = ref(new Date().toISOString());
const apiStatus = ref('pending');
const saving = ref(false);
const approving = ref(false);
const createAccess = computed(() => getActionAccess(auth, { permission: 'config.manage' }));
const approveAccess = computed(() => getActionAccess(auth, { permission: 'config.approve' }));
const latestVersion = computed(() => [...versions.value].sort((a, b) => Number(b.version || 0) - Number(a.version || 0))[0] || null);
const latestStatus = computed(() => latestVersion.value?.status || 'not_configured');
const versionLabel = computed(() => latestVersion.value ? `v${latestVersion.value.version}` : '默认配置');
const statusLabel = computed(() => ({
  pending_approval: '待审批', approved: '已批准', effective: '生效中', superseded: '已替代', not_configured: '使用默认值'
}[latestStatus.value] || latestStatus.value));
const statusType = computed(() => ({ pending_approval: 'warning', approved: 'primary', effective: 'success', superseded: 'info' }[latestStatus.value] || 'info'));

function items(response) {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function applyValue(value) {
  const safe = value && typeof value === 'object' ? value : {};
  const supported = Object.fromEntries(
    CONFIG_FIELDS
      .filter((key) => Object.prototype.hasOwnProperty.call(safe, key))
      .map((key) => [key, safe[key]])
  );
  Object.assign(form, defaults, supported);
}

function configValuePayload() {
  return {
    default_metrics: form.default_metrics,
    daily_attribution_reconciliation_enabled: form.daily_attribution_reconciliation_enabled,
    sample_video_overdue_days: form.sample_video_overdue_days,
    sample_overdue_notification_enabled: form.sample_overdue_notification_enabled
  };
}

async function load() {
  const [definitionResponse, valueResponse] = await Promise.all([
    fetchConfigDefinitions({ config_key: CONFIG_KEY }),
    fetchConfigValues({ config_key: CONFIG_KEY, page: 1, page_size: 100 })
  ]);
  if (!definitionResponse?.success || !valueResponse?.success) {
    apiStatus.value = 'degraded';
    return ElMessage.error('BD 配置加载失败');
  }
  definition.value = items(definitionResponse).find((item) => item.config_key === CONFIG_KEY) || null;
  versions.value = items(valueResponse).filter((item) => item.config_key === CONFIG_KEY);
  apiStatus.value = 'connected';
  applyValue(latestVersion.value?.value || definition.value?.default_value);
}

async function saveVersion() {
  if (!createAccess.value.allowed || saving.value) return;
  saving.value = true;
  const response = await createConfigValue({
    config_key: CONFIG_KEY,
    value: configValuePayload(),
    effective_at: effectiveAt.value
  });
  saving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '配置版本创建失败');
  ElMessage.success('配置版本已提交审批');
  await load();
}

async function approveLatest() {
  if (!approveAccess.value.allowed || !latestVersion.value?.id || approving.value) return;
  approving.value = true;
  const response = await approveConfigValue(latestVersion.value.id);
  approving.value = false;
  if (!response?.success) return ElMessage.error(response?.message || '审批失败');
  ElMessage.success('配置版本已审批');
  await load();
}

onMounted(load);
</script>

<style scoped>
.bd-config-page { padding: 24px; min-height: 100%; background: #f3f6f4; color: #172620; }
.hero { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding: 28px 32px; border-radius: 20px; color: #fff; background: linear-gradient(125deg, #0b3d33, #167b66); box-shadow: 0 18px 40px rgba(16, 83, 69, .16); }
.hero h1 { margin: 4px 0 6px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 34px; }
.hero p { margin: 0; opacity: .82; }
.hero .eyebrow { font-size: 12px; letter-spacing: .16em; opacity: .7; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 18px; margin-top: 18px; }
.editor-card, .status-card { border: 1px solid #dce7e1; border-radius: 16px; }
.card-heading { display: flex; align-items: center; justify-content: space-between; }
.card-heading div { display: grid; gap: 4px; }
.card-heading span { color: #718079; font-size: 13px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 24px; }
.settings-form small { display: block; margin-top: 7px; color: #7b8983; }
.full-width { width: 100%; }
.switch-line { display: flex; align-items: center; gap: 10px; min-height: 32px; }
.form-actions { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding-top: 18px; border-top: 1px solid #e7eeea; color: #718079; font-size: 13px; }
.status-card dl { margin: 0 0 22px; }
.status-card dl div { display: flex; justify-content: space-between; gap: 16px; padding: 13px 0; border-bottom: 1px solid #edf1ef; }
.status-card dt { color: #77847e; }
.status-card dd { margin: 0; text-align: right; }
@media (max-width: 900px) { .content-grid, .field-grid { grid-template-columns: 1fr; } .bd-config-page { padding: 14px; } .hero { padding: 22px; } .form-actions { align-items: stretch; flex-direction: column; } }
</style>
