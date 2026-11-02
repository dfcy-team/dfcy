<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { apiBaseUrl } from '../../api/baseUrl';
import { developerRequest, downloadDeveloperDocs } from '../../api/developerApps';
import { useAuthStore } from '../../stores/auth';
import { isApiAccessAdmin } from '../../utils/apiAccessAdmin';
const auth = useAuthStore();
const apps = ref([]), catalog = ref({ connections: [], accounts: [], endpoints: [] });
const loading = ref(false), saving = ref(false), editor = ref(false), selected = ref(null), secret = ref('');
const debugVisible = ref(false), debugTarget = ref(null), debugToken = ref(''), debugEndpoint = ref(''), debugQuery = ref('{}'), debugBody = ref('{}'), debugResult = ref(''), debugBusy = ref(false);
const logs = ref([]), logsVisible = ref(false), registerVisible = ref(false);
const form = reactive({ name: '', description: '', endpoint_ids: [], expires_at: '' });
const endpoint = reactive({ code: '', name: '', connection_id: null, account_id: null, method: 'GET', base_url: '', path: '', auth_mode: 'bearer' });
const permissions = computed(() => new Set([...(auth.currentUser?.permissions || []), ...(auth.currentUser?.action_permission_codes || [])]));
const canManage = computed(() => isApiAccessAdmin(auth.currentUser) || permissions.value.has('integrations.developer_app.manage'));
const isOwner = row => row.owner_id === auth.currentUser?.user_id;
const canReview = computed(() => isApiAccessAdmin(auth.currentUser));
const canRegister = computed(() => isApiAccessAdmin(auth.currentUser));
const formatExpiry = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '—';
const statusLabel = row => ({ pending: '待审批', approved: '已批准', rejected: '已驳回' }[row.approval_status] || row.approval_status);
async function call(path, method, data) {
  const result = await developerRequest(path, method, data);
  if (!result.success) throw new Error(result.message || '操作失败，请稍后重试');
  return result.data;
}
async function load() {
  loading.value = true;
  try {
    const [list, resources] = await Promise.all([call('developer-apps/'), call('developer-catalog/')]);
    apps.value = list.items || []; catalog.value = resources;
  } catch (error) { ElMessage.error(error.message); }
  finally { loading.value = false; }
}
function edit(row = null) {
  selected.value = row;
  Object.assign(form, { name: row?.name || '', description: row?.description || '', endpoint_ids: [...(row?.requested_endpoint_ids || row?.endpoint_ids || [])], expires_at: row?.requested_expires_at || row?.expires_at || new Date(Date.now() + 7 * 86400000).toISOString() });
  editor.value = true;
}
async function submit() {
  if (!form.name.trim() || !form.endpoint_ids.length) return ElMessage.warning('请填写应用名称并选择接口');
  saving.value = true;
  try { await call(`developer-apps/${selected.value ? `${selected.value.id}/` : ''}`, selected.value ? 'patch' : 'post', { ...form }); editor.value = false; ElMessage.success('申请已提交，已有授权不受新增申请影响'); await load(); }
  catch (error) { ElMessage.error(error.message); } finally { saving.value = false; }
}
async function review(row, decision) {
  try {
    const { value } = await ElMessageBox.prompt(decision === 'approve' ? '确认批准该应用申请的接口和有效期？可填写审核说明。' : '请填写驳回原因', '审核应用', { inputValidator: value => decision === 'approve' || Boolean(value?.trim()) || '请填写原因' });
    await call(`developer-apps/${row.id}/review/`, 'post', { decision, reason: value || '' }); await load();
  } catch (error) { if (error instanceof Error) ElMessage.error(error.message); }
}
async function issue(row) {
  try {
    await ElMessageBox.confirm('生成新令牌后旧令牌失效。令牌仅展示一次，请保存到本地环境变量。', '领取／轮换开发令牌');
    const data = await call(`developer-apps/${row.id}/token/`, 'post'); secret.value = data.token; await load();
  } catch (error) { if (error instanceof Error) ElMessage.error(error.message); }
}
async function revoke(row) {
  try { await ElMessageBox.confirm('停用后本地调用将被拒绝。', '停用应用'); await call(`developer-apps/${row.id}/revoke/`, 'post'); await load(); }
  catch (error) { if (error instanceof Error) ElMessage.error(error.message); }
}
async function showLogs(row) {
  try { logs.value = (await call(`developer-apps/${row.id}/logs/`)).items || []; logsVisible.value = true; }
  catch (error) { ElMessage.error(error.message); }
}
async function download(row) {
  try {
    const result = await downloadDeveloperDocs(row.id);
    if (!result.success) throw new Error(result.message || '下载失败');
    const blob = result.blob;
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `developer-app-${row.id}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { ElMessage.error(error.message); }
}
async function registerEndpoint() {
  saving.value = true;
  try { await call('developer-catalog/', 'post', { ...endpoint }); registerVisible.value = false; await load(); }
  catch (error) { ElMessage.error(error.message); } finally { saving.value = false; }
}
function openDebug(row) { debugTarget.value = row; debugToken.value = ''; debugEndpoint.value = ''; debugResult.value = ''; debugVisible.value = true; }
async function runDebug() {
  if (!debugToken.value || !debugEndpoint.value) return ElMessage.warning('请选择接口并填写开发令牌');
  debugBusy.value = true;
  try {
    const data = { query: JSON.parse(debugQuery.value), body: JSON.parse(debugBody.value) };
    const response = await fetch(`${apiBaseUrl}/api/developer-gateway/v1/${debugTarget.value.id}/${debugEndpoint.value}/`, { method: 'POST', credentials: 'omit', headers: { Authorization: `Bearer ${debugToken.value}`, 'Content-Type': 'application/json' }, body: JSON.stringify(data), signal: AbortSignal.timeout(20000) });
    debugResult.value = JSON.stringify({ status: response.status, response: await response.json() }, null, 2);
  } catch (error) { ElMessage.error(error.message); } finally { debugBusy.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="developer-apps" v-loading="loading">
    <header><div><h1>内部开发对接</h1><p>创建并申请 → 获取令牌和资料，在本地调用已授权的平台接口。无需安装补丁包。</p></div><el-button v-if="canManage" type="primary" @click="edit()">新建应用</el-button></header>
    <el-alert title="系统尚未业务对接的接口也可登记后申请；实际可用范围以第三方平台授权及已配置的适配能力为准。" type="info" :closable="false" />
    <el-tabs>
      <el-tab-pane label="开发应用">
        <el-table :data="apps" empty-text="暂无应用，点击新建应用提交申请">
          <el-table-column prop="name" label="应用名称" min-width="140" /><el-table-column prop="owner_name" label="开发者" min-width="140" />
          <el-table-column label="申请接口" min-width="160"><template #default="{row}">{{ (row.requested_endpoint_ids || []).map(id => catalog.endpoints.find(e => e.id === id)?.name || id).join("、") }}</template></el-table-column><el-table-column label="审批状态" width="100"><template #default="{row}">{{ statusLabel(row) }}</template></el-table-column>
          <el-table-column label="启用状态" width="100"><template #default="{row}">{{ {pending:"待启用",active:"已启用",disabled:"已停用"}[row.status] || row.status }}</template></el-table-column>
          <el-table-column label="申请有效期" width="175"><template #default="{row}">{{ formatExpiry(row.requested_expires_at) }}</template></el-table-column><el-table-column label="生效有效期" width="175"><template #default="{row}">{{ formatExpiry(row.expires_at) }}</template></el-table-column>
          <el-table-column label="操作" min-width="350"><template #default="{row}">
            <el-button v-if="isOwner(row) && canManage" link @click="edit(row)">申请扩权／延期</el-button>
            <el-button v-if="isOwner(row) && canManage" link :disabled="row.status !== 'active' || !(row.approved_endpoint_ids?.length)" @click="issue(row)">领取令牌</el-button>
            <el-button link @click="download(row)">接入资料</el-button>
            <el-button v-if="isOwner(row)" link @click="openDebug(row)">调用调试</el-button><el-button link @click="showLogs(row)">调用日志</el-button>
            <el-button v-if="canManage && (isOwner(row) || canReview)" link type="danger" @click="revoke(row)">停用</el-button>
            <template v-if="canReview && !isOwner(row) && row.updated_by_id !== auth.currentUser?.user_id && row.approval_status === 'pending'"><el-button link type="success" @click="review(row, 'approve')">批准</el-button><el-button link type="danger" @click="review(row, 'reject')">驳回</el-button></template>
          </template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="接口资源">
        <el-button v-if="canRegister" @click="registerVisible = true">登记接口</el-button>
        <p>目录未收录的接口，请由管理员登记官方接口路径及平台连接。第三方尚未授权的能力须先完成平台授权。</p>
        <el-table :data="catalog.endpoints"><el-table-column prop="name" label="接口"/><el-table-column prop="code" label="代码"/><el-table-column prop="connection_id" label="连接"/><el-table-column prop="account_id" label="账号"/><el-table-column prop="method" label="方法"/><el-table-column prop="path" label="路径"/></el-table>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="editor" :title="selected ? '申请扩权／延期' : '创建并申请'" width="650px">
      <el-form label-position="top"><el-form-item label="应用名称" required><el-input v-model="form.name" maxlength="160"/></el-form-item><el-form-item label="开发用途"><el-input v-model="form.description" type="textarea" maxlength="1000"/></el-form-item>
        <el-form-item label="平台／账号／接口（可跨平台多选）" required><el-select v-model="form.endpoint_ids" multiple filterable style="width:100%"><el-option v-for="item in catalog.endpoints" :key="item.id" :value="item.id" :label="`${item.name} · 连接 ${item.connection_id} / 账号 ${item.account_id || '-'} · ${item.method}`"/></el-select></el-form-item>
        <el-collapse><el-collapse-item title="有效期等设置"><el-form-item label="有效期（默认 7 天）"><el-date-picker v-model="form.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"/></el-form-item></el-collapse-item></el-collapse>
      </el-form><template #footer><el-button @click="editor=false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">提交申请</el-button></template>
    </el-dialog>
    <el-dialog :model-value="Boolean(secret)" title="开发令牌 · 仅展示一次" @close="secret=''" :close-on-click-modal="false"><p>请保存到本地环境变量。接入资料包不包含此令牌。</p><el-input :model-value="secret" readonly type="textarea" :rows="3"/><template #footer><el-button @click="secret=''">已保存，关闭</el-button></template></el-dialog>
    <el-dialog v-model="debugVisible" title="调用调试" width="700px" @closed="debugToken=''">
      <el-alert title="请求会实际调用第三方接口；写入仅允许测试连接。令牌仅保留在本次窗口。" type="info" :closable="false"/>
      <el-form label-position="top"><el-form-item label="已授权接口"><el-select v-model="debugEndpoint"><el-option v-for="e in catalog.endpoints.filter(e => debugTarget?.approved_endpoint_ids?.includes(e.id))" :key="e.id" :value="e.code" :label="`${e.name} · ${e.method}`"/></el-select></el-form-item>
      <el-form-item label="开发令牌"><el-input v-model="debugToken" type="password" show-password autocomplete="off"/></el-form-item><el-form-item label="查询参数 JSON"><el-input v-model="debugQuery" type="textarea"/></el-form-item><el-form-item label="请求体 JSON"><el-input v-model="debugBody" type="textarea"/></el-form-item></el-form>
      <el-button type="primary" :loading="debugBusy" @click="runDebug">发送请求</el-button><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ debugResult }}</pre>
    </el-dialog>
    <el-dialog v-model="logsVisible" title="调用日志" width="850px"><el-table :data="logs"><el-table-column prop="created_at" label="时间"/><el-table-column prop="request_id" label="请求编号"/><el-table-column prop="endpoint_code" label="接口"/><el-table-column prop="status_code" label="状态码"/></el-table></el-dialog>
    <el-dialog v-model="registerVisible" title="登记第三方接口" width="600px"><el-form label-position="top">
      <el-form-item label="平台连接"><el-select v-model="endpoint.connection_id"><el-option v-for="item in catalog.connections" :key="item.id" :label="item.name" :value="item.id"/></el-select></el-form-item>
      <el-form-item label="账号"><el-select v-model="endpoint.account_id" clearable><el-option v-for="item in catalog.accounts.filter(a=>a.connection_id===endpoint.connection_id)" :key="item.id" :label="item.name" :value="item.id"/></el-select></el-form-item>
      <el-form-item label="接口代码"><el-input v-model="endpoint.code"/></el-form-item><el-form-item label="接口名称"><el-input v-model="endpoint.name"/></el-form-item>
      <el-form-item label="方法"><el-select v-model="endpoint.method"><el-option v-for="m in ['GET','POST','PUT','PATCH','DELETE']" :key="m" :value="m"/></el-select></el-form-item>
      <el-form-item label="已获准的平台 HTTPS 地址"><el-input v-model="endpoint.base_url" placeholder="https://api.example.com"/></el-form-item><el-form-item label="相对路径"><el-input v-model="endpoint.path" placeholder="/v1/orders"/></el-form-item><el-form-item label="鉴权方式"><el-select v-model="endpoint.auth_mode"><el-option label="Bearer" value="bearer"/><el-option label="API Key" value="api_key"/><el-option label="TikTok Shop" value="tiktok_shop"/><el-option label="Shopee 店铺" value="shopee_shop"/><el-option label="Lazada 查询" value="lazada"/></el-select></el-form-item>
    </el-form><template #footer><el-button type="primary" :loading="saving" @click="registerEndpoint">登记</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.developer-apps{padding:24px;max-width:1500px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}h1{margin:0;font-size:24px}p{color:#64748b;line-height:1.6}.el-tabs{margin-top:20px}.el-select{width:100%}
</style>
