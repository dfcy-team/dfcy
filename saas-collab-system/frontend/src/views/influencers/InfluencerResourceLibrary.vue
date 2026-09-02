<template>
  <section class="resource-library">
    <div class="metrics">
      <div><span>达人档案</span><strong>{{ displayValue(total) }}</strong><small>当前租户</small></div>
      <div><span>正常达人</span><strong>{{ displayValue(activeCount) }}</strong><small>当前页</small></div>
      <div><span>合作中</span><strong>{{ displayValue(cooperatingCount) }}</strong><small>当前页</small></div>
      <div><span>黑名单</span><strong>{{ displayValue(blacklistedCount) }}</strong><small>当前页</small></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <el-input v-model="filters.search" clearable placeholder="搜索达人 ID、名称或账号" @keyup.enter="applyFilters" />
        <el-select v-model="filters.platform" clearable placeholder="全部平台"><el-option label="TikTok" value="TikTok" /><el-option label="Instagram" value="Instagram" /><el-option label="YouTube" value="YouTube" /></el-select>
        <el-select v-model="filters.status" clearable placeholder="全部状态"><el-option label="正常" value="active" /><el-option label="停用" value="inactive" /></el-select>
        <el-select v-model="filters.cooperation_status" clearable placeholder="合作分层"><el-option v-for="(label, value) in INFLUENCER_COOPERATION_STATUS_LABELS" :key="value" :label="label" :value="value" /></el-select>
        <el-select v-model="filters.level" clearable placeholder="等级"><el-option v-for="level in ['S', 'A', 'B', 'C', 'D', 'E']" :key="level" :label="`${level} 级`" :value="level" /></el-select>
        <el-input v-model="filters.market" clearable placeholder="市场" />
        <el-input v-model="filters.tier" clearable placeholder="层级" />
        <el-select v-model="filters.is_blacklisted" clearable placeholder="黑名单"><el-option label="未拉黑" value="false" /><el-option label="已拉黑" value="true" /></el-select>
        <el-select v-model="filters.ordering" placeholder="排序"><el-option label="最近更新" value="-updated_at" /><el-option label="平均播放从高到低" value="-profile__average_video_views" /><el-option label="平均播放从低到高" value="profile__average_video_views" /><el-option label="历史 GMV 从高到低" value="-profile__historical_gmv" /><el-option label="历史 GMV 从低到高" value="profile__historical_gmv" /><el-option label="粉丝数从高到低" value="-follower_count" /><el-option label="名称正序" value="name" /></el-select>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :disabled="!canManage" @click="openCreate">新建达人</el-button>
      </div>

      <el-alert v-if="listError" type="error" :title="listError" show-icon :closable="false" class="list-error" />
      <el-table v-loading="loading" :data="rows" :empty-text="listError ? '达人档案加载失败，请重试' : '暂无达人档案'" @row-click="openDetail">
        <el-table-column label="达人" min-width="200" fixed="left"><template #default="{ row }"><b>{{ influencerDisplayName(row) }}</b><small>{{ profileValue(row, 'external_influencer_id') }} · {{ displayValue(row.platform) }}</small></template></el-table-column>
        <el-table-column label="等级 / 粉丝" min-width="120"><template #default="{ row }"><b>{{ profileValue(row, 'level') }}</b><small>{{ formatCount(row.follower_count) }} 粉丝 · {{ profileValue(row, 'tier') }}</small></template></el-table-column>
        <el-table-column label="平均播放" min-width="105"><template #default="{ row }">{{ formatCount(row.profile?.average_video_views) }}</template></el-table-column>
        <el-table-column label="市场 / 赛道" min-width="145"><template #default="{ row }"><b>{{ profileValue(row, 'market') }}</b><small>{{ displayValue(row.category) }}</small></template></el-table-column>
        <el-table-column label="首次合作" min-width="115"><template #default="{ row }">{{ formatDate(row.profile?.first_cooperation_at) }}</template></el-table-column>
        <el-table-column label="合作表现" min-width="125"><template #default="{ row }"><b>{{ formatCount(row.profile?.cooperation_count) }} 次合作</b><small>{{ formatCount(row.profile?.fulfilled_cooperation_count) }} 次履约</small></template></el-table-column>
        <el-table-column label="历史 GMV" min-width="125"><template #default="{ row }"><b>{{ formatMoney(row.profile?.historical_gmv) }}</b><small>{{ formatCount(row.profile?.historical_orders) }} 个订单</small></template></el-table-column>
        <el-table-column label="履约率" min-width="95"><template #default="{ row }">{{ formatRate(row.profile?.fulfillment_rate) }}</template></el-table-column>
        <el-table-column label="合作状态" width="110"><template #default="{ row }"><el-tag size="small" :type="cooperationTag(row.cooperation_status)">{{ cooperationLabel(row.cooperation_status) }}</el-tag></template></el-table-column>
        <el-table-column label="档案状态" width="95"><template #default="{ row }"><el-tag size="small" :type="row.is_blacklisted ? 'danger' : (row.status === 'active' ? 'success' : 'info')">{{ row.is_blacklisted ? '已拉黑' : (row.status === 'active' ? '正常' : '停用') }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="250" fixed="right"><template #default="{ row }"><el-button link @click.stop="openDetail(row)">详情</el-button><el-button link :disabled="!canManage" @click.stop="openEdit(row)">编辑</el-button><el-button link :type="row.is_blacklisted ? 'success' : 'danger'" :disabled="!canManage" @click.stop="toggleBlacklist(row)">{{ row.is_blacklisted ? '解除拉黑' : '加入黑名单' }}</el-button><el-button link :disabled="!canManage" @click.stop="changeStatus(row, row.status === 'active' ? 'inactive' : 'active')">{{ row.status === 'active' ? '停用' : '启用' }}</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > 0" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changePageSize" />
    </el-card>

    <el-dialog v-model="editVisible" :title="editing ? '编辑达人档案' : '新建达人档案'" width="760px" @closed="resetForm">
      <el-form label-position="top"><div class="form-grid">
        <el-form-item label="系统档案编码" required><el-input v-model="form.code" :disabled="Boolean(editing)" /></el-form-item>
        <el-form-item label="达人名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="平台" required><el-input v-model="form.platform" placeholder="例如 TikTok" /></el-form-item>
        <el-form-item label="账号"><el-input v-model="form.handle" placeholder="不含或包含 @ 均可" /></el-form-item>
        <el-form-item label="内容赛道"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="粉丝数"><el-input-number v-model="form.follower_count" :min="0" controls-position="right" /></el-form-item>
        <el-form-item label="合作分层"><el-select v-model="form.cooperation_status"><el-option v-for="(label, value) in INFLUENCER_COOPERATION_STATUS_LABELS" :key="value" :label="label" :value="value" /></el-select></el-form-item>
      </div><el-divider content-position="left">扩展档案</el-divider><div class="form-grid">
        <el-form-item label="展示名称"><el-input v-model="form.profile.display_name" /></el-form-item>
        <el-form-item label="外部达人 ID"><el-input v-model="form.profile.external_influencer_id" /></el-form-item>
        <el-form-item label="等级"><el-input v-model="form.profile.level" /></el-form-item>
        <el-form-item label="层级"><el-input v-model="form.profile.tier" /></el-form-item>
        <el-form-item label="市场"><el-input v-model="form.profile.market" /></el-form-item>
        <el-form-item label="档案平台"><el-input v-model="form.profile.platforms" placeholder="多个值用逗号分隔" /></el-form-item>
        <el-form-item label="内容类型"><el-input v-model="form.profile.content_types" placeholder="多个值用逗号分隔" /></el-form-item>
        <el-form-item label="档案链接"><el-input v-model="form.profile.profile_url" /></el-form-item>
        <el-form-item label="平均视频播放"><el-input-number v-model="form.profile.average_video_views" :min="0" controls-position="right" disabled /></el-form-item>
        <el-form-item label="平均直播观看"><el-input-number v-model="form.profile.average_live_views" :min="0" controls-position="right" disabled /></el-form-item>
        <el-form-item label="档案启用"><el-switch v-model="form.profile.is_active" /></el-form-item>
        <el-form-item label="重复说明"><el-input v-model="form.profile.duplicate_reason" /></el-form-item>
        <el-form-item label="商品合作次数"><el-input-number v-model="form.profile.product_cooperation_count" :min="0" disabled /></el-form-item>
        <el-form-item label="首次合作时间"><el-input :model-value="displayValue(form.profile.first_cooperation_at)" disabled /></el-form-item>
        <el-form-item label="合作次数"><el-input-number v-model="form.profile.cooperation_count" :min="0" disabled /></el-form-item>
        <el-form-item label="完成合作次数"><el-input-number v-model="form.profile.completed_cooperation_count" :min="0" disabled /></el-form-item>
        <el-form-item label="完成履约次数"><el-input-number v-model="form.profile.fulfilled_cooperation_count" :min="0" disabled /></el-form-item>
        <el-form-item label="履约率"><el-input :model-value="displayValue(form.profile.fulfillment_rate)" disabled /></el-form-item>
        <el-form-item label="内容完成率"><el-input :model-value="displayValue(form.profile.content_completion_rate)" disabled /></el-form-item>
        <el-form-item label="历史 GMV"><el-input :model-value="displayValue(form.profile.historical_gmv)" disabled /></el-form-item>
        <el-form-item label="历史订单数"><el-input-number v-model="form.profile.historical_orders" :min="0" disabled /></el-form-item>
        <el-form-item class="full-field" label="重复/其他备注"><el-input v-model="form.profile.profile_notes" type="textarea" :rows="2" /></el-form-item>
        <el-form-item class="full-field" label="历史表现 JSON"><el-input :model-value="formatJson(form.profile.historical_performance)" type="textarea" :rows="3" disabled /></el-form-item>
      </div><el-divider content-position="left">联系渠道</el-divider>
        <div v-for="(contact, index) in form.contacts" :key="contact.key" class="contact-row"><el-select v-model="contact.channel" filterable allow-create default-first-option placeholder="选择或输入平台"><el-option v-for="(label, value) in INFLUENCER_CONTACT_CHANNEL_LABELS" :key="value" :label="label" :value="value" /></el-select><el-input v-model="contact.value" placeholder="账号、手机号或邮箱"/><el-input v-model="contact.label" placeholder="备注"/><el-checkbox v-model="contact.is_primary">主渠道</el-checkbox><el-button link type="danger" @click="removeContact(index)">删除</el-button></div>
        <el-button link type="primary" @click="addContact">+ 新增联系方式</el-button>
      </el-form>
      <template #footer><el-button @click="editVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存档案</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :title="detail?.name || '达人详情'" size="560px">
      <div v-if="detailLoading" class="drawer-state">正在加载达人详情...</div>
      <el-alert v-else-if="detailError" type="error" :title="detailError" show-icon :closable="false" />
      <template v-else-if="detail">
        <div class="drawer-actions"><el-button v-if="canManage" type="primary" plain @click="openEdit(detail)">编辑档案</el-button><el-button v-if="canManage" :type="detail.is_blacklisted ? 'success' : 'danger'" plain @click="toggleBlacklist(detail)">{{ detail.is_blacklisted ? '解除黑名单' : '加入黑名单' }}</el-button></div>
        <h3>身份概览</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="TikTok用户名">{{ displayValue(detail.handle) }}</el-descriptions-item><el-descriptions-item label="达人 ID">{{ profileValue(detail, 'external_influencer_id') }}</el-descriptions-item><el-descriptions-item label="展示名称">{{ displayValue(detail.profile?.display_name || detail.display_name) }}</el-descriptions-item><el-descriptions-item label="系统档案编码">{{ displayValue(detail.code) }}</el-descriptions-item><el-descriptions-item label="平台">{{ displayValue(detail.platform) }}</el-descriptions-item><el-descriptions-item label="市场">{{ profileValue(detail, 'market') }}</el-descriptions-item><el-descriptions-item label="等级 / 层级">{{ profileValue(detail, 'level') }} / {{ profileValue(detail, 'tier') }}</el-descriptions-item><el-descriptions-item label="档案状态">{{ detail.is_blacklisted ? '已拉黑' : (detail.status === 'active' ? '正常' : '停用') }}</el-descriptions-item></el-descriptions>
        <h3>内容能力</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="内容赛道">{{ displayValue(detail.category) }}</el-descriptions-item><el-descriptions-item label="内容类型">{{ listValue(detail.profile?.content_types) }}</el-descriptions-item><el-descriptions-item label="粉丝数">{{ formatCount(detail.follower_count) }}</el-descriptions-item><el-descriptions-item label="平均视频播放">{{ formatCount(detail.profile?.average_video_views) }}</el-descriptions-item><el-descriptions-item label="平均直播观看">{{ formatCount(detail.profile?.average_live_views) }}</el-descriptions-item><el-descriptions-item label="档案链接">{{ displayValue(detail.profile?.profile_url) }}</el-descriptions-item></el-descriptions>
        <h3>合作表现</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="合作状态">{{ cooperationLabel(detail.cooperation_status) }}</el-descriptions-item><el-descriptions-item label="首次合作">{{ formatDate(detail.profile?.first_cooperation_at) }}</el-descriptions-item><el-descriptions-item label="合作次数">{{ formatCount(detail.profile?.cooperation_count) }}</el-descriptions-item><el-descriptions-item label="商品合作次数">{{ formatCount(detail.profile?.product_cooperation_count) }}</el-descriptions-item><el-descriptions-item label="完成合作次数">{{ formatCount(detail.profile?.completed_cooperation_count) }}</el-descriptions-item><el-descriptions-item label="完成履约次数">{{ formatCount(detail.profile?.fulfilled_cooperation_count) }}</el-descriptions-item><el-descriptions-item label="履约率">{{ formatRate(detail.profile?.fulfillment_rate) }}</el-descriptions-item><el-descriptions-item label="内容完成率">{{ formatRate(detail.profile?.content_completion_rate) }}</el-descriptions-item><el-descriptions-item label="历史 GMV">{{ formatMoney(detail.profile?.historical_gmv) }}</el-descriptions-item><el-descriptions-item label="历史订单数">{{ formatCount(detail.profile?.historical_orders) }}</el-descriptions-item><el-descriptions-item label="档案备注" :span="2">{{ displayValue(detail.profile?.profile_notes) }}</el-descriptions-item></el-descriptions>
        <h3>推荐与合作资源</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="推荐商品">{{ historyValue('recommended_product') }}</el-descriptions-item><el-descriptions-item label="合作店铺">{{ historyValue('partnered_shops') }}</el-descriptions-item><el-descriptions-item label="主要类目" :span="2">{{ listValue(detail.profile?.historical_performance?.top_categories) }}</el-descriptions-item></el-descriptions>
        <h3>历史经营指标</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="月 GMV">{{ formatMoney(historyNumber('monthly_gmv')) }}</el-descriptions-item><el-descriptions-item label="客单价">{{ formatMoney(historyNumber('average_order_value')) }}</el-descriptions-item><el-descriptions-item label="月销量">{{ formatCount(historyNumber('monthly_sales')) }}</el-descriptions-item><el-descriptions-item label="历史 ROI">{{ formatDecimal(historyNumber('historical_roi')) }}</el-descriptions-item><el-descriptions-item label="视频总 GMV">{{ formatMoney(historyNumber('video_total_gmv')) }}</el-descriptions-item><el-descriptions-item label="视频总订单">{{ formatCount(historyNumber('video_total_orders')) }}</el-descriptions-item><el-descriptions-item label="视频总播放">{{ formatCount(historyNumber('video_total_views')) }}</el-descriptions-item><el-descriptions-item label="视频数">{{ formatCount(historyNumber('video_count')) }}</el-descriptions-item><el-descriptions-item label="最新视频日期">{{ formatDate(detail.profile?.historical_performance?.video_latest_date) }}</el-descriptions-item><el-descriptions-item label="出单视频数">{{ formatCount(historyNumber('order_video_count')) }}</el-descriptions-item></el-descriptions>
        <h3>联系渠道</h3><div v-if="detail.contacts?.length" class="contact-list"><div v-for="contact in detail.contacts" :key="contact.id || contact.key"><b>{{ INFLUENCER_CONTACT_CHANNEL_LABELS[contact.channel] || contact.channel }}</b><span>{{ displayValue(contact.masked_value || contact.value) }}</span><small>{{ contact.label || (contact.is_primary ? '主渠道' : '') }}</small></div></div><p v-else class="muted">暂无联系渠道</p>
        <h3>黑名单历史</h3><el-timeline v-if="detail.blacklist_history?.length"><el-timeline-item v-for="event in detail.blacklist_history" :key="event.id || `${event.action}-${event.occurred_at}`" :timestamp="formatTime(event.occurred_at || event.created_at)">{{ event.action === 'blacklist' ? '加入黑名单' : '解除黑名单' }}：{{ event.reason || '未填写原因' }}</el-timeline-item></el-timeline><p v-else class="muted">暂无黑名单历史</p>
      </template>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { collectionRows, collectionTotal } from '../../utils/businessResponse';
import { useAuthStore } from '../../stores/auth';
import {
  INFLUENCER_CONTACT_CHANNEL_LABELS,
  INFLUENCER_COOPERATION_STATUS_LABELS,
  createInfluencer,
  fetchInfluencer,
  fetchInfluencerBlacklistHistory,
  fetchInfluencerContacts,
  fetchInfluencers,
  updateInfluencer,
  updateInfluencerBlacklist,
  updateInfluencerContacts,
  updateInfluencerStatus
} from '../../api/influencers';

const auth = useAuthStore();
const rows = ref([]); const total = ref(null); const page = ref(1); const pageSize = ref(20); const loading = ref(false); const saving = ref(false); const listError = ref('');
const editVisible = ref(false); const detailVisible = ref(false); const detailLoading = ref(false); const detailError = ref(''); const detail = ref(null); const editing = ref(null);
const blankProfile = () => ({ display_name: '', external_influencer_id: '', level: '', tier: '', average_video_views: 0, average_live_views: 0, is_active: true, market: '', platforms: '', content_types: '', profile_url: '', duplicate_reason: '', product_cooperation_count: 0, first_cooperation_at: null, cooperation_count: 0, completed_cooperation_count: 0, fulfilled_cooperation_count: 0, fulfillment_rate: null, content_completion_rate: null, historical_gmv: '0.0000', historical_orders: 0, historical_performance: {}, profile_notes: '' });
const filters = reactive({ search: '', status: '', platform: '', cooperation_status: '', level: '', market: '', tier: '', is_blacklisted: '', ordering: '-updated_at' });
const blankContact = () => ({ key: `contact-${Date.now()}-${Math.random()}`, channel: 'email', value: '', label: '', is_primary: false });
const profileForm = (profile = {}) => ({ ...blankProfile(), ...profile, platforms: Array.isArray(profile.platforms) ? profile.platforms.join(', ') : (profile.platforms || ''), content_types: Array.isArray(profile.content_types) ? profile.content_types.join(', ') : (profile.content_types || '') });
const blankForm = () => ({ code: '', name: '', platform: 'TikTok', handle: '', category: '', follower_count: 0, cooperation_status: 'prospect', profile: profileForm(), contacts: [blankContact()] });
const form = reactive(blankForm());
const canManage = computed(() => auth.hasPermission('influencers.manage'));
const activeCount = computed(() => rows.value.filter((row) => row.status === 'active').length); const cooperatingCount = computed(() => rows.value.filter((row) => row.cooperation_status === 'cooperating').length); const blacklistedCount = computed(() => rows.value.filter((row) => row.is_blacklisted).length);
const displayValue = (value) => value === undefined || value === null || value === '' ? '—' : String(value);
const influencerDisplayName = (row) => row?.name || row?.profile?.display_name || row?.code || '—';
const profileValue = (row, field) => displayValue(row?.profile?.[field]);
const listValue = (value) => displayValue(Array.isArray(value) ? value.join('、') : value);
const formatCount = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN') : '—';
const formatMoney = (value) => Number.isFinite(Number(value)) ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
const formatRate = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
const formatDecimal = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '—';
const formatDate = (value) => value ? new Date(value).toLocaleDateString('zh-CN') : '—';
const historyValue = (field) => displayValue(detail.value?.profile?.historical_performance?.[field]);
const historyNumber = (field) => detail.value?.profile?.historical_performance?.[field];
const formatJson = (value) => { try { return JSON.stringify(value || {}, null, 2); } catch { return '—'; } };
const cooperationLabel = (status) => INFLUENCER_COOPERATION_STATUS_LABELS[status] || '未分层'; const cooperationTag = (status) => ({ contacted: 'warning', cooperating: 'success', paused: 'info' }[status] || '');
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';

async function load() {
  loading.value = true; listError.value = '';
  const params = { page: page.value, page_size: pageSize.value, ordering: filters.ordering, ...(filters.search.trim() ? { search: filters.search.trim() } : {}), ...(filters.status ? { status: filters.status } : {}), ...(filters.platform ? { platform: filters.platform } : {}), ...(filters.cooperation_status ? { cooperation_status: filters.cooperation_status } : {}), ...(filters.level ? { level: filters.level } : {}), ...(filters.market.trim() ? { market: filters.market.trim() } : {}), ...(filters.tier.trim() ? { tier: filters.tier.trim() } : {}), ...(filters.is_blacklisted ? { is_blacklisted: filters.is_blacklisted } : {}) };
  const response = await fetchInfluencers(params); loading.value = false;
  if (!response?.success) { rows.value = []; total.value = null; listError.value = response?.message || '达人档案加载失败，请稍后重试'; return; }
  rows.value = collectionRows(response.data); total.value = collectionTotal(response.data);
}
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { search: '', status: '', platform: '', cooperation_status: '', level: '', market: '', tier: '', is_blacklisted: '', ordering: '-updated_at' }); applyFilters(); }
function changePageSize() { page.value = 1; load(); }
function resetForm() { Object.assign(form, blankForm()); }
function addContact() { form.contacts.push(blankContact()); }
function removeContact(index) { if (form.contacts.length === 1) return; form.contacts.splice(index, 1); }
function openCreate() { if (!canManage.value) return; editing.value = null; resetForm(); editVisible.value = true; }
async function openEdit(row) {
  if (!canManage.value) return;
  const [profileResponse, contactsResponse] = await Promise.all([
    fetchInfluencer(row.id, { include_relations: 'false' }),
    fetchInfluencerContacts(row.id)
  ]);
  if (!profileResponse?.success) return ElMessage.error(profileResponse?.message || '达人档案加载失败');
  const record = profileResponse.data || row;
  const contacts = collectionRows(contactsResponse?.data || []);
  editing.value = record;
  Object.assign(form, { ...blankForm(), ...record, profile: profileForm(record.profile), contacts: (contacts.length ? contacts : [blankContact()]).map((contact) => ({ ...contact, key: contact.id || `${contact.channel}-${contact.value}` })) });
  editVisible.value = true;
}
function profilePayload() { const profile = form.profile; return { display_name: profile.display_name.trim(), external_influencer_id: profile.external_influencer_id.trim(), level: profile.level.trim(), tier: profile.tier.trim(), is_active: Boolean(profile.is_active), market: profile.market.trim(), platforms: profile.platforms.split(',').map((item) => item.trim()).filter(Boolean), content_types: profile.content_types.split(',').map((item) => item.trim()).filter(Boolean), profile_url: profile.profile_url.trim(), duplicate_reason: profile.duplicate_reason.trim(), profile_notes: profile.profile_notes.trim() }; }
function payload() {
  const data = { code: form.code.trim(), name: form.name.trim(), platform: form.platform.trim(), category: form.category.trim(), follower_count: Number(form.follower_count || 0), cooperation_status: form.cooperation_status, profile: profilePayload() };
  const handle = form.handle.trim();
  if (handle) data.handle = handle;
  return data;
}
function contactsPayload() { return form.contacts.filter((contact) => contact.value.trim()).map(({ key, id, ...contact }) => ({ ...contact, channel: contact.channel.trim(), value: contact.value.trim(), label: contact.label.trim() })); }
async function save() {
  if (!canManage.value) return;
  if (!form.code.trim() || !form.name.trim() || !form.platform.trim()) return ElMessage.warning('请填写达人编码、名称和平台');
  if (form.contacts.some((contact) => contact.value.trim() && !contact.channel.trim())) return ElMessage.warning('请为每条联系方式选择或输入平台');
  const wasEditing = Boolean(editing.value); saving.value = true;
  const response = wasEditing ? await updateInfluencer(editing.value.id, payload(), editing.value.updated_at) : await createInfluencer(payload());
  if (!response?.success) { saving.value = false; return ElMessage.error(response?.message || '达人档案保存失败'); }
  const influencerId = response.data?.id || editing.value?.id;
  const contactsResponse = await updateInfluencerContacts(influencerId, contactsPayload(), response.data?.updated_at || editing.value?.updated_at);
  saving.value = false;
  if (!contactsResponse?.success) return ElMessage.error(`达人档案已保存，但联系渠道保存失败：${contactsResponse?.message || '请重试'}`);
  editVisible.value = false; ElMessage.success(wasEditing ? '达人档案已更新' : '达人档案已创建'); await load();
}
async function openDetail(row) {
  detailVisible.value = true; detailLoading.value = true; detailError.value = ''; detail.value = { ...row, contacts: row.contacts || [], blacklist_history: row.blacklist_history || [] };
  const [profileResponse, contactsResponse, historyResponse] = await Promise.all([
    fetchInfluencer(row.id, { include_relations: 'false' }),
    fetchInfluencerContacts(row.id),
    fetchInfluencerBlacklistHistory(row.id)
  ]);
  detailLoading.value = false;
  if (!profileResponse?.success) { detailError.value = profileResponse?.message || '达人详情加载失败'; return; }
  const profile = profileResponse.data || {};
  detail.value = { ...detail.value, ...profile, contacts: collectionRows(contactsResponse?.data || profile.contacts || detail.value.contacts), blacklist_history: collectionRows(historyResponse?.data || profile.blacklist_history || detail.value.blacklist_history) };
}
async function toggleBlacklist(row) {
  if (!canManage.value) return;
  let reason = '';
  if (!row.is_blacklisted) { try { const result = await ElMessageBox.prompt('请填写加入黑名单原因，便于后续审计。', '加入黑名单', { inputPattern: /\S+/, inputErrorMessage: '原因不能为空' }); reason = result.value; } catch { return; } } else { try { await ElMessageBox.confirm('确认解除该达人的黑名单限制吗？', '解除黑名单', { type: 'warning' }); } catch { return; } }
  const response = await updateInfluencerBlacklist(row.id, { is_blacklisted: !row.is_blacklisted, reason }, row.updated_at);
  if (!response?.success) return ElMessage.error(response?.message || '黑名单状态更新失败');
  ElMessage.success(row.is_blacklisted ? '已解除黑名单' : '已加入黑名单'); await load();
  if (detail.value?.id === row.id) await openDetail({ ...row, is_blacklisted: !row.is_blacklisted });
}
async function changeStatus(row, status) {
  if (!canManage.value) return;
  if (status === 'inactive') { try { await ElMessageBox.confirm('停用后将暂不可用于业务操作，可稍后重新启用。确认停用该达人档案吗？', '确认停用', { type: 'warning' }); } catch { return; } }
  const response = await updateInfluencerStatus(row, status); if (!response?.success) return ElMessage.error(response?.message || '档案状态更新失败'); ElMessage.success('档案状态已更新'); load();
}
onMounted(load);
</script>

<style scoped>
.resource-library { display: grid; gap: 14px; min-width: 0; }
.list-error { margin-bottom: 12px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid #dce4e9; border-radius: 9px; background: #fff; }
.metrics > div { display: grid; gap: 5px; min-height: 86px; padding: 15px 16px; border-right: 1px solid #e2e8ec; }.metrics > div:last-child { border-right: 0; box-shadow: inset 3px 0 #14936f; }.metrics span, .metrics small { color: #6b7b86; font-size: 12px; }.metrics strong { color: #15232e; font-size: 24px; line-height: 1; }
.workspace-card { border-color: #dce4e9; }.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }.toolbar .el-input { flex: 1 1 260px; min-width: 220px; }.toolbar .el-select { width: 140px; }.toolbar .el-button { flex: 0 0 auto; }.el-table b, .el-table small { display: block; }.el-table small { margin-top: 3px; color: #7a8993; }.el-pagination { justify-content: flex-end; margin-top: 14px; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.form-grid .el-input-number, .form-grid .el-select { width: 100%; }.full-field { grid-column: 1 / -1; }.contact-row { display: grid; grid-template-columns: 130px 1fr 130px auto auto; align-items: center; gap: 8px; margin-bottom: 8px; }.contact-list { display: grid; gap: 8px; }.contact-list div { display: grid; grid-template-columns: 110px 1fr auto; gap: 8px; align-items: center; padding: 9px 10px; border: 1px solid #e6ecef; border-radius: 6px; }.contact-list small, .muted { color: #7a8993; }.drawer-actions { display: flex; gap: 8px; margin-bottom: 14px; }.drawer-state { min-height: 180px; display: grid; place-items: center; color: #768690; }.resource-library h3 { margin: 20px 0 10px; color: #20313d; font-size: 14px; }
@media (max-width: 900px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.toolbar .el-input, .toolbar .el-select { flex: 1 1 180px; width: auto; min-width: 160px; } }
@media (max-width: 620px) { .metrics, .form-grid { grid-template-columns: 1fr; }.metrics > div { border-right: 0; border-bottom: 1px solid #e2e8ec; }.contact-row { grid-template-columns: 1fr 1fr; }.full-field { grid-column: auto; } }
</style>
