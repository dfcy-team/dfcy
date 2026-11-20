<template>
  <AdminResourcePage
    eyebrow="MASTER DATA"
    title="平台档案"
    subtitle="统一维护平台标识，供店铺、接口配置和业务模块引用。"
    boundary-note="平台档案不保存 API Key、Token 或登录凭据；存在启用店铺引用时禁止停用。"
    entity-label="平台"
    :loader="fetchPlatforms"
    :columns="columns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('platforms', payload)"
    :edit-handler="(id, payload, row) => updateMasterData('platforms', id, { ...payload, version: row.version })"
    :delete-handler="(id) => deleteMasterData('platforms', id)"
    :status-handler="(row, status) => updateMasterDataStatus('platforms', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    search-label="平台"
    show-filter-labels
    show-page-size
    :operation-width="190"
  />
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import { createMasterData, deleteMasterData, fetchPlatformCatalog, fetchPlatforms, updateMasterData, updateMasterDataStatus } from '../../api/masterData';

const WAREHOUSE_TYPES = new Set(['warehouse_owned', 'warehouse_third_party', 'warehouse_platform']);
const GROUP_ORDER = ['销售渠道/独立站', '仓储服务分类', 'ERP/其他'];
const GROUP_LABELS = { '仓储服务分类': '仓储服务分类（需选择库存连接器）' };
const WAREHOUSE_HELP = '选择库存连接器后，该平台才会出现在接入配置中。支持百世仓配和极风 WMS；保存选择不会启用真实 API 调用。';

const platformTypes = ref([
  { label: 'Lazada', value: 'lazada' }, { label: 'Shopee', value: 'shopee' },
  { label: 'Temu', value: 'temu' }, { label: 'TikTok', value: 'tiktok' },
  { label: '自营仓服务', value: 'warehouse_owned' },
  { label: '三方仓服务', value: 'warehouse_third_party' },
  { label: '平台仓服务', value: 'warehouse_platform' },
  { label: '其他', value: 'other' }
]);
const catalogItems = ref([]);
const platformTypeGroups = ref([
  { label: '销售渠道/独立站', options: platformTypes.value.slice(0, 4) },
  { label: '仓储服务分类', options: platformTypes.value.slice(4, 7) },
  { label: 'ERP/其他', options: platformTypes.value.slice(7) }
]);

function platformLabel(value) {
  const labels = { lazada: 'Lazada', shopee: 'Shopee', temu: 'Temu', tiktok: 'TikTok', 'tiktok shop': 'TikTok Shop', bigseller: 'BigSeller' };
  return labels[String(value || '').toLowerCase()] || value || '-';
}

function platformTypeLabel(value) {
  const label = catalogItems.value.find((item) => item.value === value)?.label || platformLabel(value);
  return WAREHOUSE_TYPES.has(value) ? `${label} · 分类` : label;
}

function connectorStatusLabel(value) {
  return {
    ACTIVE: '已支持',
    TESTING: '联调中',
    PENDING: '待确认',
    NONE: '暂不接入',
    NOT_IMPLEMENTED: '暂未实现',
    UNMAPPED: '待识别服务商'
  }[value] || value || '-';
}

function connectorDisplay(value, row = {}) {
  const name = row.connector_name || (row.connector_status === 'UNMAPPED' ? '待识别服务商' : '未指定连接器');
  return `${name} · ${connectorStatusLabel(row.connector_status || value)}`;
}

function optionLabel(item) {
  if (item.is_business_category || WAREHOUSE_TYPES.has(item.value)) return `${item.label}（业务分类）`;
  const statusHint = item.connector_status === 'NOT_IMPLEMENTED' ? ' · 连接器未实现' : '';
  return `${item.label}（${item.canonical_code} / ${item.priority_level}）${statusHint}`;
}

function groupCatalogItems(items) {
  const groups = new Map(GROUP_ORDER.map((label) => [label, []]));
  for (const item of items) {
    const group = item.option_group || (WAREHOUSE_TYPES.has(item.value) ? '仓储服务分类' : '销售渠道/独立站');
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push({ value: item.value, label: optionLabel(item) });
  }
  return Array.from(groups.entries())
    .filter(([, options]) => options.length)
    .map(([label, options]) => ({ label: GROUP_LABELS[label] || label, options }));
}

const columns = [
  { prop: 'code', label: '平台编码', width: 140 }, { prop: 'name', label: '平台名称', width: 160, format: platformLabel },
  { prop: 'platform_type', label: '平台类型', width: 190, options: () => platformTypes.value, format: platformTypeLabel },
  { prop: 'connector_status', label: '库存连接器', width: 190, format: connectorDisplay },
  { prop: 'status', label: '状态', type: 'status', width: 90, format: statusLabel }
];
function statusLabel(value) {
  return ({ active: '启用', inactive: '停用', disabled: '禁用', pending: '待处理' })[String(value || '').toLowerCase()] || value || '-';
}
const formFields = computed(() => [
  { key: 'code', label: '平台编码', required: true }, { key: 'name', label: '平台名称', required: true },
  {
    key: 'platform_type', label: '平台类型', type: 'select', required: true, default: 'other',
    options: () => platformTypeGroups.value,
    helpText: (form) => WAREHOUSE_TYPES.has(form.platform_type) ? WAREHOUSE_HELP : ''
  },
  { key: 'warehouse_connector_state', label: '库存 API 接入', type: 'select', required: true, default: 'pending',
    visible: form => WAREHOUSE_TYPES.has(form.platform_type), options: [
      { label: '待确认', value: 'pending' }, { label: '选择连接器', value: 'selected' }, { label: '暂不接入', value: 'none' }
    ] },
  { key: 'warehouse_connector_key', label: '库存连接器', type: 'select', required: true,
    visible: form => WAREHOUSE_TYPES.has(form.platform_type) && form.warehouse_connector_state === 'selected', options: [
      { label: '百世仓配 API (2.0)', value: 'best_ecapi' }, { label: '极风 WMS', value: 'jifeng_wms' }
    ] },
  { key: 'status', label: '状态', type: 'select', required: true, default: 'active', options: [
    { label: '启用', value: 'active' }, { label: '停用', value: 'inactive' }
  ] }
]);

onMounted(async () => {
  const response = await fetchPlatformCatalog();
  const items = response?.data?.results || [];
  if (!response?.success || !items.length) return;
  catalogItems.value = items;
  platformTypes.value = items.map((item) => ({ value: item.value, label: optionLabel(item) }));
  platformTypeGroups.value = groupCatalogItems(items);
});
</script>
