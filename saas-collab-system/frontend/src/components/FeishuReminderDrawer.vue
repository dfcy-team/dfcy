<template>
  <el-drawer :model-value="modelValue" title="飞书业务提醒" size="min(580px, 96vw)" @update:model-value="emit('update:modelValue', $event)">
    <el-tabs v-model="tab">
      <el-tab-pane label="发起提醒" name="compose">
        <el-alert title="发送前按每位收件人的权限核对数据。留言请勿填写客户资料或敏感业务明细。" type="info" :closable="false" />
        <el-form label-position="top" :disabled="sending">
          <el-form-item label="数据范围">
            <el-radio-group v-model="form.mode">
              <el-radio value="selected" :disabled="!recordIds.length">所选 {{ recordIds.length }} 条记录</el-radio>
              <el-radio value="filtered" :disabled="!allowFiltered">已查询筛选范围</el-radio>
            </el-radio-group>
            <small class="reminder-note">所选记录最多100条；筛选范围最多31天，使用页面上次成功查询条件。<span v-if="!allowFiltered">从提醒链接打开时，请勾选具体记录后发送。</span></small>
          </el-form-item>
          <el-form-item label="提醒标题" required><el-input v-model="form.title" maxlength="100" /></el-form-item>
          <el-form-item label="收件人" required>
            <el-select v-model="form.recipient_user_ids" multiple filterable remote :remote-method="searchPeople" :loading="searching" placeholder="搜索可管理的人员" style="width:100%" :multiple-limit="50">
              <el-option v-for="person in people" :key="person.id" :value="person.id" :label="`${person.name}${person.bound ? '' : '（未绑定飞书）'}`" :disabled="!person.bound" />
            </el-select>
            <small v-if="truncated" class="reminder-note">人员较多，请输入姓名或账号搜索。</small>
          </el-form-item>
          <el-form-item label="留言"><el-input v-model="form.message" type="textarea" :rows="3" maxlength="1000" show-word-limit /></el-form-item>
          <el-form-item label="截止日期"><el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" clearable /></el-form-item>
          <el-button :loading="previewing" :disabled="!form.title.trim() || !form.recipient_user_ids.length || disabled || (form.mode === 'selected' && !recordIds.length)" @click="makePreview">生成发送预览</el-button>
        </el-form>
        <el-alert v-if="error" :title="error" type="error" :closable="false" class="reminder-gap" />
        <section v-if="preview" class="reminder-gap" aria-label="发送预览">
          <el-alert v-if="!preview.connection_ready" title="飞书应用连接尚未就绪，请联系管理员配置。" type="warning" :closable="false" />
          <article v-for="person in preview.recipients" :key="person.user_id" class="reminder-preview">
            <strong>{{ person.name }}</strong><p class="reminder-content">{{ person.eligible ? person.summary : person.reason }}</p>
          </article>
          <el-button type="primary" :loading="sending" :disabled="!preview.can_send || disabled" @click="submit">确认发送给 {{ form.recipient_user_ids.length }} 人</el-button>
        </section>
      </el-tab-pane>
      <el-tab-pane label="发送记录" name="history">
        <el-button :loading="historyLoading" @click="loadHistory">刷新记录</el-button>
        <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" class="reminder-gap" />
        <div v-if="!historyLoading && !history.length" class="reminder-note">暂无发送记录。</div>
        <article v-for="item in history" :key="item.id" class="reminder-preview">
          <el-button text type="primary" @click="loadStatus(item.id)">{{ item.title }}</el-button><small>{{ item.created_at }}</small>
        </article>
        <section v-if="status" class="reminder-gap">
          <strong>{{ status.title }}</strong><el-button text @click="loadStatus(status.id)">刷新投递结果</el-button>
          <div v-for="item in status.items" :key="item.operation_id" class="reminder-preview">
            {{ item.recipient }} · {{ statusLabels[item.status] || item.status }} · 已尝试 {{ item.attempts }} 次
            <el-button v-if="item.can_retry" text :loading="retrying === item.operation_id" @click="retry(item.operation_id)">重试</el-button>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { reminderOptions, previewReminder, sendReminder, reminderHistory, reminderStatus, retryReminder } from '../api/feishuReminders';
import { formatApiError } from '../api/request';

const props = defineProps({ modelValue: Boolean, source: String, recordIds: { type: Array, default: () => [] }, filters: { type: Object, default: () => ({}) }, disabled: Boolean, allowFiltered: { type: Boolean, default: true } });
const emit = defineEmits(['update:modelValue']);
const form = reactive({ title: '', message: '', due_date: null, recipient_user_ids: [], mode: 'filtered' });
const tab = ref('compose'), people = ref([]), truncated = ref(false), searching = ref(false);
const preview = ref(null), error = ref(''), previewing = ref(false), sending = ref(false), requestKey = ref('');
const history = ref([]), status = ref(null), historyError = ref(''), historyLoading = ref(false), retrying = ref(null);
const statusLabels = { pending: '待发送', processing: '发送中', success: '已发送', failed: '失败', skipped: '已跳过' };
let searchTimer, searchSequence = 0, previewSequence = 0;
const checked = response => { if (!response?.success) throw new Error(formatApiError(response)); return response.data; };
const payload = () => ({ ...form, recipient_user_ids: [...form.recipient_user_ids], source: props.source, record_ids: form.mode === 'selected' ? [...props.recordIds] : [], filters: { ...props.filters } });

async function loadPeople(search = '') {
  const sequence = ++searchSequence; searching.value = true;
  try {
    const data = checked(await reminderOptions(search));
    if (sequence !== searchSequence) return;
    const retained = people.value.filter(p => form.recipient_user_ids.includes(p.id));
    people.value = [...new Map([...retained, ...data.recipients].map(p => [p.id, p])).values()];
    truncated.value = data.truncated;
  } catch (e) { if (sequence === searchSequence) error.value = e.message; }
  finally { if (sequence === searchSequence) searching.value = false; }
}
function searchPeople(search) { searchSequence++; clearTimeout(searchTimer); searchTimer = setTimeout(() => loadPeople(search), 300); }
function invalidate() { previewSequence++; preview.value = null; requestKey.value = ''; error.value = ''; }
watch(() => [form.title, form.message, form.due_date, form.mode, [...form.recipient_user_ids], props.source, props.recordIds, props.filters, props.disabled], invalidate, { deep: true });
watch(() => props.modelValue, open => {
  if (!open) return;
  form.mode = props.recordIds.length || !props.allowFiltered ? 'selected' : 'filtered';
  form.title = props.source === 'orders' ? '销售订单跟进提醒' : '退款退货跟进提醒';
  status.value = null;
  loadPeople();
});
watch(tab, value => { if (value === 'history') loadHistory(); });
async function makePreview() {
  const sequence = ++previewSequence; previewing.value = true; error.value = ''; preview.value = null;
  try {
    const data = checked(await previewReminder(payload()));
    if (sequence === previewSequence) { preview.value = data; requestKey.value = crypto.randomUUID(); }
  } catch (e) { if (sequence === previewSequence) error.value = e.message; }
  finally { previewing.value = false; }
}
async function submit() {
  if (sending.value || !preview.value?.can_send || props.disabled) return;
  sending.value = true; error.value = '';
  try {
    const data = checked(await sendReminder({ ...payload(), preview_token: preview.value.preview_token, idempotency_key: requestKey.value }));
    ElMessage.success('提醒已加入发送队列，可查看逐人投递结果。');
    invalidate(); tab.value = 'history'; await loadStatus(data.id);
  } catch (e) { error.value = e.message; }
  finally { sending.value = false; }
}
async function loadHistory() {
  historyLoading.value = true; historyError.value = '';
  try { history.value = checked(await reminderHistory()).items; }
  catch (e) { historyError.value = e.message; }
  finally { historyLoading.value = false; }
}
async function loadStatus(id) {
  historyError.value = '';
  try { status.value = checked(await reminderStatus(id)); }
  catch (e) { historyError.value = e.message; }
}
async function retry(operationId) {
  if (retrying.value) return;
  retrying.value = operationId;
  try { checked(await retryReminder(status.value.id, operationId)); await loadStatus(status.value.id); }
  catch (e) { historyError.value = e.message; }
  finally { retrying.value = null; }
}
onBeforeUnmount(() => { clearTimeout(searchTimer); searchSequence++; previewSequence++; });
</script>

<style scoped>
.reminder-gap { margin-top: 16px; }
.reminder-note { display: block; margin-top: 8px; color: #64748b; line-height: 1.6; }
.reminder-preview { padding: 12px 0; border-bottom: 1px solid #e2e8f0; overflow-wrap: anywhere; }
.reminder-preview small { display: block; color: #64748b; }
.reminder-content { white-space: pre-wrap; line-height: 1.7; }
</style>
