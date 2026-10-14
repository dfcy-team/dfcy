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
        <el-input v-model="filters.search" clearable placeholder="搜索昵称 ID、账号昵称或数字外部 ID" @keyup.enter="applyFilters" />
        <el-select v-model="filters.platform" clearable placeholder="全部平台"><el-option v-for="(label, value) in INFLUENCER_PLATFORM_LABELS" :key="value" :label="label" :value="value" /></el-select>
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
        <el-table-column label="昵称 ID / 账号昵称" min-width="200" fixed="left"><template #default="{ row }"><b>{{ influencerDisplayName(row) }}</b><small>账号昵称：{{ accountNickname(row) }}</small><small v-if="sameNicknameFields(row)" class="muted">与昵称 ID 相同，待核实</small><small>{{ profileValue(row, 'external_influencer_id') }}</small><div class="platform-tags"><el-tag v-for="platform in registeredPlatforms(row)" :key="platform" size="small" effect="plain">{{ platformLabel(platform) }}</el-tag></div></template></el-table-column>
        <el-table-column label="等级 / 粉丝" min-width="120"><template #default="{ row }"><b>{{ profileValue(row, 'level') }}</b><small>{{ formatCount(row.follower_count) }} 粉丝 · {{ profileValue(row, 'tier') }}</small></template></el-table-column>
        <el-table-column label="平均播放" min-width="105"><template #default="{ row }">{{ formatCount(row.profile?.average_video_views) }}</template></el-table-column>
        <el-table-column label="市场 / 赛道" min-width="145"><template #default="{ row }"><b>{{ profileValue(row, 'market') }}</b><small>{{ displayValue(row.category) }}</small></template></el-table-column>
        <el-table-column label="首次合作" min-width="115"><template #default="{ row }">{{ formatDate(row.profile?.first_cooperation_at) }}</template></el-table-column>
        <el-table-column label="合作表现" min-width="125"><template #default="{ row }"><b>{{ formatCount(row.profile?.cooperation_count) }} 次合作</b><small>{{ formatCount(row.profile?.fulfilled_cooperation_count) }} 次履约</small></template></el-table-column>
        <el-table-column label="历史 GMV" min-width="125"><template #default="{ row }"><b>{{ formatMoney(row.profile?.historical_gmv) }}</b><small>{{ formatCount(row.profile?.historical_orders) }} 个订单</small></template></el-table-column>
        <el-table-column label="履约率" min-width="95"><template #default="{ row }">{{ formatRate(row.profile?.fulfillment_rate) }}</template></el-table-column>
        <el-table-column label="合作状态" width="110"><template #default="{ row }"><el-tag size="small" :type="cooperationTag(row.cooperation_status)">{{ cooperationLabel(row.cooperation_status) }}</el-tag></template></el-table-column>
        <el-table-column label="档案状态" width="95"><template #default="{ row }"><el-tag size="small" :type="row.is_blacklisted ? 'danger' : (row.status === 'active' ? 'success' : 'info')">{{ row.is_blacklisted ? '已拉黑' : (row.status === 'active' ? '正常' : '停用') }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="360" fixed="right"><template #default="{ row }"><el-button link @click.stop="openDetail(row)">详情</el-button><el-button link :disabled="!canManage" @click.stop="openEdit(row)">编辑</el-button><el-button link :disabled="!canManage || row.is_blacklisted || saving" @click.stop="openRelatedCreate(row)">新建关联档案</el-button><el-button link :type="row.is_blacklisted ? 'success' : 'danger'" :disabled="!canManage" @click.stop="toggleBlacklist(row)">{{ row.is_blacklisted ? '解除拉黑' : '加入黑名单' }}</el-button><el-button link :disabled="!canManage" @click.stop="changeStatus(row, row.status === 'active' ? 'inactive' : 'active')">{{ row.status === 'active' ? '停用' : '启用' }}</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > 0" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changePageSize" />
    </el-card>

    <el-dialog v-model="editVisible" :title="editing ? '编辑达人档案' : (relatedSource ? '新建关联档案' : '新建达人档案')" width="min(860px, 94vw)" :close-on-click-modal="false" :show-close="!saving" :close-on-press-escape="!saving" @closed="resetForm">
      <div v-if="editing" class="archive-navigation">
        <span class="muted">关联档案</span>
        <el-button v-for="archive in editing.related_archives" :key="archive.id" :type="archive.id === editing.id ? 'primary' : ''" plain :disabled="saving || archive.id === editing.id" @click="openEdit(archive)">{{ platformLabel(archive.platform) }} · {{ influencerDisplayName(archive) }}</el-button>
        <el-button class="archive-create-button" type="primary" :disabled="saving || editing.is_blacklisted" @click="openRelatedCreate(editing)">新建关联档案</el-button>
        <small class="muted">每个账号独立填写、独立保存；同平台可关联多个账号，仅新建时关联。</small>
      </div>
      <el-alert v-if="relatedSource" type="info" :title="`将关联到 ${platformLabel(relatedSource.platform)} · ${influencerDisplayName(relatedSource)}，新档案的身份和业务数据独立保存。`" show-icon :closable="false" class="list-error" />
      <el-alert v-if="createOutcomeUncertain" type="warning" title="上次创建结果尚未确认。请先按平台、昵称 ID 或账号昵称核对档案列表，再决定是否重新新建；不要重复提交。" show-icon :closable="false" class="list-error" />
      <el-form v-loading="editLoading" label-position="top"><div class="form-grid">
        <el-form-item label="平台" required><el-select v-model="form.platform" :disabled="Boolean(editing)" placeholder="请选择平台（必填）"><el-option v-for="(label, value) in selectablePlatforms" :key="value" :label="label" :value="value" /></el-select><small class="muted">一账号一份独立档案，同平台可建多个账号；已有档案的平台不可替换。</small></el-form-item>
        <el-form-item label="系统档案编码"><el-input :model-value="form.code" disabled placeholder="保存时由系统自动生成" /><small class="muted">无需填写，保存时自动生成唯一编码；已有编码和业务关联保持不变。</small></el-form-item>
        <el-form-item label="昵称 ID"><el-input v-model="form.nickname_id" :disabled="Boolean(editing)" maxlength="255" placeholder="平台用户名，不含或包含 @ 均可" /><small class="muted">用于昵称 ID 填写和列表主展示，不是平台数字 ID。</small></el-form-item>
        <el-form-item label="账号昵称"><el-input v-model="form.account_nickname" maxlength="160" placeholder="平台真实展示名，可包含装饰文字" /><small class="muted">独立保存真实展示名，不自动复制昵称 ID。</small></el-form-item>
        <el-form-item label="平台数字 ID"><el-input v-model="form.profile.external_influencer_id" :disabled="Boolean(editing?.profile?.external_influencer_id)" maxlength="160" placeholder="原档案没有 ID 时可补录" /></el-form-item>
        <el-form-item label="主页信息"><el-input v-model="form.profile.profile_url" maxlength="500" placeholder="填写任意内容，可留空" /><small class="muted">仅按文字保存，不校验网址格式，不访问填写的内容。</small></el-form-item>
        <el-form-item label="粉丝数"><el-input-number v-model="form.follower_count" :min="0" controls-position="right" /></el-form-item>
      </div>
      <el-alert v-if="editing && sameNicknameFields(form)" type="warning" title="当前账号昵称与昵称 ID 相同，待核实。部分历史导入只提供用户名，请按平台真实展示名补录；若平台上本来相同，也可保留。" show-icon :closable="false" class="list-error" />
      <el-divider content-position="left">基础档案</el-divider><div class="form-grid">
        <el-form-item label="内容赛道"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="合作分层"><el-select v-model="form.cooperation_status"><el-option v-for="(label, value) in INFLUENCER_COOPERATION_STATUS_LABELS" :key="value" :label="label" :value="value" /></el-select></el-form-item>
      </div><el-divider content-position="left">扩展档案</el-divider><div class="form-grid">
        <el-form-item label="等级"><el-input v-model="form.profile.level" /></el-form-item>
        <el-form-item label="层级"><el-input v-model="form.profile.tier" /></el-form-item>
        <el-form-item label="市场"><el-input v-model="form.profile.market" /></el-form-item>
        <el-form-item label="内容类型"><el-input v-model="form.profile.content_types" placeholder="多个值用逗号分隔" /></el-form-item>
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
      </div><el-divider content-position="left">联系渠道（不作为平台账号）</el-divider>
        <div v-for="(contact, index) in form.contacts" :key="contact.key" class="contact-row"><el-select v-model="contact.channel" filterable allow-create default-first-option placeholder="选择或输入联系渠道"><el-option v-for="(label, value) in selectableContactChannels" :key="value" :label="label" :value="value" /><el-option v-if="contact.channel && !Object.hasOwn(selectableContactChannels, contact.channel)" :label="`${INFLUENCER_CONTACT_CHANNEL_LABELS[contact.channel] || contact.channel}（已保存）`" :value="contact.channel" disabled /></el-select><el-input v-model="contact.value" placeholder="账号、手机号或邮箱"/><el-input v-model="contact.label" placeholder="备注"/><el-checkbox v-model="contact.is_primary">主渠道</el-checkbox><el-button link type="danger" @click="removeContact(index)">删除</el-button></div>
        <el-button link type="primary" @click="addContact">+ 新增联系方式</el-button>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="editVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="editLoading || createOutcomeUncertain" @click="save">{{ relatedSource ? '创建并关联档案' : '保存档案' }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :title="detail ? influencerDisplayName(detail) : '达人详情'" size="560px">
      <div v-if="detailLoading" class="drawer-state">正在加载达人详情...</div>
      <el-alert v-else-if="detailError" type="error" :title="detailError" show-icon :closable="false" />
      <template v-else-if="detail">
        <div class="drawer-actions"><el-button v-if="canManage" type="primary" plain @click="openEdit(detail)">编辑档案</el-button><el-button v-if="canManage" :type="detail.is_blacklisted ? 'success' : 'danger'" plain @click="toggleBlacklist(detail)">{{ detail.is_blacklisted ? '解除黑名单' : '加入黑名单' }}</el-button></div>
        <h3>关联档案</h3>
        <el-alert v-if="relatedError" type="warning" :title="relatedError" :closable="false" />
        <div class="archive-navigation"><el-button v-for="archive in detailRelated" :key="archive.id" plain :disabled="archive.id === detail.id" @click="openDetail(archive)">{{ platformLabel(archive.platform) }} · {{ influencerDisplayName(archive) }}</el-button><el-button v-if="canManage" class="archive-create-button" type="primary" :disabled="detail.is_blacklisted || saving" @click="openRelatedCreate(detail)">新建关联档案</el-button></div>
        <p class="muted">关联档案的送样、建联、绩效和黑名单规则各自独立。现有达人不会自动关联。</p>
        <h3>身份概览</h3>
        <div class="platform-tags"><el-tag v-for="platform in registeredPlatforms(detail)" :key="platform" effect="plain">{{ platformLabel(platform) }}</el-tag></div>
        <el-descriptions :column="2" border><el-descriptions-item label="昵称 ID">{{ influencerDisplayName(detail) }}</el-descriptions-item><el-descriptions-item label="数字外部 ID">{{ profileValue(detail, 'external_influencer_id') }}</el-descriptions-item><el-descriptions-item label="账号昵称">{{ accountNickname(detail) }}</el-descriptions-item><el-descriptions-item label="系统档案编码">{{ displayValue(detail.code) }}</el-descriptions-item><el-descriptions-item label="平台">{{ displayValue(detail.platform) }}</el-descriptions-item><el-descriptions-item label="市场">{{ profileValue(detail, 'market') }}</el-descriptions-item><el-descriptions-item label="等级 / 层级">{{ profileValue(detail, 'level') }} / {{ profileValue(detail, 'tier') }}</el-descriptions-item><el-descriptions-item label="档案状态">{{ detail.is_blacklisted ? '已拉黑' : (detail.status === 'active' ? '正常' : '停用') }}</el-descriptions-item></el-descriptions>
        <h3>内容能力</h3>
        <el-descriptions :column="2" border><el-descriptions-item label="内容赛道">{{ displayValue(detail.category) }}</el-descriptions-item><el-descriptions-item label="内容类型">{{ listValue(detail.profile?.content_types) }}</el-descriptions-item><el-descriptions-item label="粉丝数">{{ formatCount(detail.follower_count) }}</el-descriptions-item><el-descriptions-item label="平均视频播放">{{ formatCount(detail.profile?.average_video_views) }}</el-descriptions-item><el-descriptions-item label="平均直播观看">{{ formatCount(detail.profile?.average_live_views) }}</el-descriptions-item><el-descriptions-item label="主页信息">{{ displayValue(detail.profile?.profile_url) }}</el-descriptions-item></el-descriptions>
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
  INFLUENCER_PLATFORM_LABELS,
  fetchInfluencer,
  fetchInfluencerForm,
  fetchRelatedInfluencerArchives,
  createRelatedInfluencerArchive,
  fetchInfluencerBlacklistHistory,
  fetchInfluencerContacts,
  fetchInfluencers,
  formatInfluencerError,
  saveInfluencerForm,
  updateInfluencerBlacklist,
  updateInfluencerStatus
} from '../../api/influencers';

const auth = useAuthStore();
const rows = ref([]); const total = ref(null); const page = ref(1); const pageSize = ref(20); const loading = ref(false); const saving = ref(false); const listError = ref('');
const editVisible = ref(false); const detailVisible = ref(false); const detailLoading = ref(false); const detailError = ref(''); const detail = ref(null); const editing = ref(null);
const relatedSource = ref(null); const editLoading = ref(false); const createOutcomeUncertain = ref(false); const detailRelated = ref([]); const relatedError = ref('');
let editRequestId = 0;
let detailRequestId = 0; let formSnapshot = '';
const blankProfile = () => ({ display_name: '', external_influencer_id: '', level: '', tier: '', average_video_views: 0, average_live_views: 0, is_active: true, market: '', platforms: '', content_types: '', profile_url: '', duplicate_reason: '', product_cooperation_count: 0, first_cooperation_at: null, cooperation_count: 0, completed_cooperation_count: 0, fulfilled_cooperation_count: 0, fulfillment_rate: null, content_completion_rate: null, historical_gmv: '0.0000', historical_orders: 0, historical_performance: {}, profile_notes: '' });
const filters = reactive({ search: '', status: '', platform: '', cooperation_status: '', level: '', market: '', tier: '', is_blacklisted: '', ordering: '-updated_at' });
const blankContact = () => ({ key: `contact-${Date.now()}-${Math.random()}`, channel: 'email', value: '', label: '', is_primary: false });
const profileForm = (profile = {}) => ({ ...blankProfile(), ...profile, platforms: Array.isArray(profile.platforms) ? profile.platforms.join(', ') : (profile.platforms || ''), content_types: Array.isArray(profile.content_types) ? profile.content_types.join(', ') : (profile.content_types || '') });
const blankForm = () => ({ code: '', nickname_id: '', account_nickname: '', platform: '', category: '', follower_count: 0, cooperation_status: 'prospect', profile: profileForm(), contacts: [blankContact()] });
const form = reactive(blankForm());
const normalizePlatform = (value) => String(value || '').trim().toLowerCase();
const platformLabel = (value) => INFLUENCER_PLATFORM_LABELS[normalizePlatform(value)] || displayValue(value);
const registeredPlatforms = (row) => [...new Set([row?.platform, ...(row?.registered_platforms || [])].map(normalizePlatform).filter(Boolean))];
const selectablePlatforms = INFLUENCER_PLATFORM_LABELS;
const selectableContactChannels = Object.fromEntries(Object.entries(INFLUENCER_CONTACT_CHANNEL_LABELS).filter(([channel]) => !['telegram', 'tiktok', 'instagram', 'messenger'].includes(channel)));
const canManage = computed(() => auth.hasPermission('influencers.manage'));
const activeCount = computed(() => rows.value.filter((row) => row.status === 'active').length); const cooperatingCount = computed(() => rows.value.filter((row) => row.cooperation_status === 'cooperating').length); const blacklistedCount = computed(() => rows.value.filter((row) => row.is_blacklisted).length);
const displayValue = (value) => value === undefined || value === null || value === '' ? '—' : String(value);
const influencerDisplayName = (row) => typeof row?.nickname_id === 'string' && row.nickname_id.trim() ? row.nickname_id : '未确认';
const accountNickname = (row) => row?.account_nickname?.trim() ? row.account_nickname : '未填写';
const sameNicknameFields = (row) => {
  const normalized = (value) => String(value || '').trim().replace(/^@/, '').toLowerCase();
  return Boolean(normalized(row?.nickname_id)) && normalized(row?.nickname_id) === normalized(row?.account_nickname);
};
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
  const params = { page: page.value, page_size: pageSize.value, include_nickname_id: 'true', ordering: filters.ordering, ...(filters.search.trim() ? { search: filters.search.trim() } : {}), ...(filters.status ? { status: filters.status } : {}), ...(filters.platform ? { platform: filters.platform } : {}), ...(filters.cooperation_status ? { cooperation_status: filters.cooperation_status } : {}), ...(filters.level ? { level: filters.level } : {}), ...(filters.market.trim() ? { market: filters.market.trim() } : {}), ...(filters.tier.trim() ? { tier: filters.tier.trim() } : {}), ...(filters.is_blacklisted ? { is_blacklisted: filters.is_blacklisted } : {}) };
  const response = await fetchInfluencers(params); loading.value = false;
  if (!response?.success) { rows.value = []; total.value = null; listError.value = response?.message || '达人档案加载失败，请稍后重试'; return; }
  rows.value = collectionRows(response.data); total.value = collectionTotal(response.data);
}
function applyFilters() { page.value = 1; load(); }
function resetFilters() { Object.assign(filters, { search: '', status: '', platform: '', cooperation_status: '', level: '', market: '', tier: '', is_blacklisted: '', ordering: '-updated_at' }); applyFilters(); }
function changePageSize() { page.value = 1; load(); }
function resetForm() { editRequestId += 1; editLoading.value = false; createOutcomeUncertain.value = false; editing.value = null; relatedSource.value = null; Object.assign(form, blankForm()); formSnapshot = JSON.stringify(form); }
async function confirmDraftSwitch() {
  if (!editVisible.value || JSON.stringify(form) === formSnapshot) return true;
  try { await ElMessageBox.confirm('切换档案会放弃当前未保存的修改，确认继续吗？', '未保存的档案', { type: 'warning' }); return true; } catch { return false; }
}
function addContact() { form.contacts.push(blankContact()); }
function removeContact(index) { if (form.contacts.length === 1) return; form.contacts.splice(index, 1); }
async function openCreate() { if (!canManage.value || saving.value || !(await confirmDraftSwitch())) return; resetForm(); editVisible.value = true; }
function completeRelatedArchives(results, id) {
  return Array.isArray(results) && results.some((archive) => String(archive?.id) === String(id)) && results.every((archive) => archive && Number.isSafeInteger(archive.id) && archive.id > 0 && ['code', 'platform', 'nickname_id', 'account_nickname', 'updated_at'].every((field) => typeof archive[field] === 'string'));
}
function completeEditRecord(record, id) {
  const owns = (value, field) => value != null && Object.prototype.hasOwnProperty.call(value, field);
  const strings = (value, fields) => fields.every((field) => owns(value, field) && typeof value[field] === 'string');
  if (!record || String(record.id) !== String(id) || !strings(record, ['code', 'name', 'platform', 'nickname_id', 'account_nickname', 'category', 'cooperation_status', 'updated_at']) || !Number.isFinite(record.follower_count)) return false;
  if (!owns(record, 'profile') || !Array.isArray(record.contacts) || !Array.isArray(record.platform_accounts) || record.platform_accounts.some((account) => !account || typeof account !== 'object')) return false;
  // Defaults are safe for a known absent profile, never for unloaded fields.
  if (record.profile !== null && (!strings(record.profile, ['display_name', 'external_influencer_id', 'level', 'tier', 'market', 'profile_url', 'duplicate_reason', 'profile_notes']) || !Array.isArray(record.profile.content_types) || typeof record.profile.is_active !== 'boolean')) return false;
  if (!record.contacts.every((contact) => strings(contact, ['channel', 'value', 'label']) && typeof contact.is_primary === 'boolean')) return false;
  return completeRelatedArchives(record.related_archives, id);
}
async function loadEditRecord(row) {
  const requestId = ++editRequestId;
  editLoading.value = true;
  let profileResponse;
  try { profileResponse = await fetchInfluencerForm(row.id); }
  catch { profileResponse = { success: false, message: '达人档案加载失败' }; }
  if (requestId !== editRequestId) return;
  editLoading.value = false;
  if (!profileResponse?.success) { ElMessage.error(profileResponse?.message || '达人档案加载失败'); return null; }
  const record = profileResponse.data;
  if (!completeEditRecord(record, row.id) || !record.updated_at) { ElMessage.error('完整编辑数据加载失败，已取消编辑以保护现有数据'); return null; }
  return record;
}
async function openEdit(row) {
  if (!canManage.value || saving.value || !(await confirmDraftSwitch())) return;
  const record = await loadEditRecord(row);
  if (!record) return;
  const contacts = record.contacts;
  createOutcomeUncertain.value = false;
  relatedSource.value = null;
  editing.value = record;
  Object.assign(form, { ...blankForm(), code: record.code, nickname_id: record.nickname_id, account_nickname: record.account_nickname, platform: normalizePlatform(record.platform), category: record.category, follower_count: record.follower_count, cooperation_status: record.cooperation_status, profile: profileForm(record.profile || {}), contacts: (contacts.length ? contacts : [blankContact()]).map((contact) => ({ ...contact, key: contact.id || `${contact.channel}-${contact.value}` })) });
  formSnapshot = JSON.stringify(form);
  editVisible.value = true;
}
async function openRelatedCreate(row) {
  if (!canManage.value || saving.value || row.is_blacklisted || !(await confirmDraftSwitch())) return;
  const source = await loadEditRecord(row);
  if (!source) return;
  if (source.is_blacklisted) return ElMessage.warning('该档案已加入黑名单，不能据此新建关联档案');
  Object.assign(form, blankForm());
  createOutcomeUncertain.value = false;
  editing.value = null; relatedSource.value = source;
  formSnapshot = JSON.stringify(form);
  editVisible.value = true;
}
function profilePayload() { const profile = form.profile; return { external_influencer_id: profile.external_influencer_id.trim(), level: profile.level.trim(), tier: profile.tier.trim(), is_active: Boolean(profile.is_active), market: profile.market.trim(), content_types: profile.content_types.split(',').map((item) => item.trim()).filter(Boolean), profile_url: profile.profile_url.trim(), duplicate_reason: profile.duplicate_reason.trim(), profile_notes: profile.profile_notes.trim() }; }
function payload() {
  const data = { platform: form.platform.trim(), category: form.category.trim(), follower_count: Number(form.follower_count || 0), cooperation_status: form.cooperation_status, profile: profilePayload() };
  if (!editing.value || form.account_nickname !== editing.value.account_nickname) data.account_nickname = form.account_nickname.trim();
  const nicknameId = form.nickname_id.trim();
  if (!editing.value && nicknameId) data.nickname_id = nicknameId;
  data.contacts = contactsPayload();
  // Omit the legacy child-account section so editing cannot deactivate historical rows.
  return data;
}
function contactsPayload() { return form.contacts.filter((contact) => contact.value.trim()).map(({ key, id, ...contact }) => ({ ...contact, channel: contact.channel.trim(), value: contact.value.trim(), label: contact.label.trim() })); }
async function save() {
  if (!canManage.value || editLoading.value || createOutcomeUncertain.value) return;
  if (!form.platform.trim() || (!editing.value && !form.nickname_id.trim() && !form.account_nickname.trim())) return ElMessage.warning('请填写平台及昵称 ID 或账号昵称');
  if (saving.value) return;
  if (form.contacts.some((contact) => contact.value.trim() && !contact.channel.trim())) return ElMessage.warning('请为每条联系方式选择或输入平台');
  if (relatedSource.value && !Object.hasOwn(selectablePlatforms, normalizePlatform(form.platform))) return ElMessage.warning('关联档案请选择支持的平台');
  const wasEditing = Boolean(editing.value); saving.value = true;
  let response;
  try { response = relatedSource.value ? await createRelatedInfluencerArchive(relatedSource.value.id, payload(), relatedSource.value.updated_at) : await saveInfluencerForm(editing.value?.id, payload(), editing.value?.updated_at); }
  catch { response = { success: false, message: '保存结果未确认，请先按平台和昵称核对档案列表，不要重复创建' }; }
  finally { saving.value = false; }
  if (!response?.success) {
    const rejected = [400, 401, 403, 404, 405, 409, 422, 429].includes(Number(response?.http_status));
    createOutcomeUncertain.value = !wasEditing && !rejected;
    return ElMessage.error(`${formatInfluencerError(response, '保存结果未确认')}${createOutcomeUncertain.value ? '。请先按平台和昵称核对档案列表，不要重复创建。' : ''}`);
  }
  editVisible.value = false; ElMessage.success(wasEditing ? '达人档案已更新' : '达人档案已创建'); await load();
  if (detailVisible.value && detail.value) await openDetail(detail.value);
}
async function openDetail(row) {
  const requestId = ++detailRequestId;
  detailVisible.value = true; detailLoading.value = true; detailError.value = ''; detail.value = { ...row, contacts: row.contacts || [], blacklist_history: row.blacklist_history || [] };
  detailRelated.value = []; relatedError.value = '';
  const [profileResponse, contactsResponse, historyResponse, relatedResponse] = await Promise.all([
    fetchInfluencer(row.id, { include_relations: 'false', include_nickname_id: 'true' }),
    fetchInfluencerContacts(row.id),
    fetchInfluencerBlacklistHistory(row.id),
    fetchRelatedInfluencerArchives(row.id)
  ]);
  if (requestId !== detailRequestId) return;
  detailLoading.value = false;
  if (!profileResponse?.success) { detailError.value = profileResponse?.message || '达人详情加载失败'; return; }
  const profile = profileResponse.data || {};
  detail.value = { ...detail.value, ...profile, contacts: collectionRows(contactsResponse?.data || profile.contacts || detail.value.contacts), blacklist_history: collectionRows(historyResponse?.data || profile.blacklist_history || detail.value.blacklist_history) };
  if (relatedResponse?.success && completeRelatedArchives(relatedResponse.data?.results, row.id)) detailRelated.value = relatedResponse.data.results;
  else relatedError.value = relatedResponse?.message || '关联档案加载失败';
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
.platform-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
.archive-navigation { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.archive-navigation .el-button { margin-left: 0; max-width: 100%; white-space: normal; height: auto; min-height: 32px; overflow-wrap: anywhere; }
.archive-navigation small { flex-basis: 100%; line-height: 1.7; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid #dce4e9; border-radius: 9px; background: #fff; }
.metrics > div { display: grid; gap: 5px; min-height: 86px; padding: 15px 16px; border-right: 1px solid #e2e8ec; }.metrics > div:last-child { border-right: 0; box-shadow: inset 3px 0 #14936f; }.metrics span, .metrics small { color: #6b7b86; font-size: 12px; }.metrics strong { color: #15232e; font-size: 24px; line-height: 1; }
.workspace-card { border-color: #dce4e9; }.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }.toolbar .el-input { flex: 1 1 260px; min-width: 220px; }.toolbar .el-select { width: 140px; }.toolbar .el-button { flex: 0 0 auto; }.el-table b, .el-table small { display: block; }.el-table small { margin-top: 3px; color: #7a8993; }.el-pagination { justify-content: flex-end; margin-top: 14px; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.form-grid .el-input-number, .form-grid .el-select { width: 100%; }.full-field { grid-column: 1 / -1; }.contact-row { display: grid; grid-template-columns: 130px 1fr 130px auto auto; align-items: center; gap: 8px; margin-bottom: 8px; }.contact-list { display: grid; gap: 8px; }.contact-list div { display: grid; grid-template-columns: 110px 1fr auto; gap: 8px; align-items: center; padding: 9px 10px; border: 1px solid #e6ecef; border-radius: 6px; }.contact-list small, .muted { color: #7a8993; }.drawer-actions { display: flex; gap: 8px; margin-bottom: 14px; }.drawer-state { min-height: 180px; display: grid; place-items: center; color: #768690; }.resource-library h3 { margin: 20px 0 10px; color: #20313d; font-size: 14px; }
@media (max-width: 900px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.toolbar .el-input, .toolbar .el-select { flex: 1 1 180px; width: auto; min-width: 160px; } }
@media (max-width: 620px) { .metrics, .form-grid { grid-template-columns: 1fr; }.metrics > div { border-right: 0; border-bottom: 1px solid #e2e8ec; }.contact-row { grid-template-columns: 1fr 1fr; }.full-field { grid-column: auto; } }
</style>
