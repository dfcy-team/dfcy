<template>
  <section class="effective-panel" aria-label="有效权限">
    <div class="workspace">
      <nav class="module-rail" aria-label="权限模块"><h3>业务模块</h3><el-input v-model="moduleSearch" clearable placeholder="搜索业务模块" aria-label="搜索有效权限模块"/>
        <button v-for="item in visibleModules" :key="item.key" :class="{ active: module === item.key }" @click="selectModule(item.key)"><span>{{ item.label }}</span><small>{{ item.count }}</small></button>
      </nav>
      <el-select class="module-mobile" v-model="module" aria-label="选择权限模块"><el-option v-for="item in visibleModules" :key="item.key" :label="`${item.label}（${item.count}）`" :value="item.key" /></el-select>
      <div class="permission-content">    <div class="filters">
      <el-input v-model="query" clearable placeholder="搜索权限名称或编码" aria-label="搜索权限" />
      <el-select v-model="type" aria-label="权限类型"><el-option label="全部类型" value="all"/><el-option label="菜单权限" value="menu"/><el-option label="操作权限" value="action"/><el-option label="字段权限" value="field"/></el-select>
      <el-select v-model="result" aria-label="授权结果"><el-option label="全部结果" value="all"/><el-option label="允许" value="allowed"/><el-option label="拒绝" value="denied"/></el-select>
      <el-checkbox v-model="showInactive">查看停用项</el-checkbox>
    </div>

        <div v-if="loading" class="state-panel" role="status">正在加载权限…</div>
        <div v-else-if="!filtered.length" class="state-panel">{{ permissions.length ? '没有符合条件的权限' : '暂无有效权限' }}</div>
        <template v-else><div class="permission-table-head" aria-hidden="true"><span>权限名称</span><span>类型</span><span>结果</span><span>授权来源</span><span>操作</span></div>
          <div v-for="permission in page.items" :key="permission.code" class="permission-row">
            <div class="permission-main">
              <strong class="permission-name">{{ adminPermissionLabel(permission.code) }}</strong>
              <span class="permission-type">{{ effectivePermissionTypeLabel(permission.permission_type).replace('权限','') }}</span>
              <span class="permission-result"><el-tag size="small" :type="isInactiveEffectivePermission(permission) ? 'info' : (permission.allowed ? 'success' : 'danger')">{{ permission.module_disabled ? '模块停用' : isInactiveEffectivePermission(permission) ? '停用' : permission.allowed ? '允许' : '拒绝' }}</el-tag></span>
              <span class="permission-source">{{ effectivePermissionSourceLabels(permission, roles).join('、') || '直接授权' }}</span>
              <el-button link type="primary" @click="toggleDetail(permission.code)" :aria-expanded="expanded === permission.code">{{ expanded === permission.code ? '收起' : '详情' }}</el-button>
            </div>
            <div v-if="expanded === permission.code" class="permission-detail">
              <p v-if="permission.module_disabled">模块已停用，此授权记录保留用于历史核对。</p>
              <p><span>权限编码</span><code>{{ permission.code }}</code></p>
              <div v-for="(source, index) in formatEffectivePermissionDetail(permission, roles)" :key="`${permission.code}-${index}`" class="source-detail">
                <strong>{{ source.role }}</strong><span>{{ source.source }}</span><span>范围：{{ source.scope }}</span><span>有效期：{{ source.validUntil }}</span><span>授权人：{{ source.assignedBy }}</span>
              </div>
            </div>
          </div>
          <div class="pagination"><span>共 {{ page.total }} 项</span><el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[10, 20, 50]" :total="page.total" layout="sizes, prev, pager, next" small /></div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { adminPermissionLabel } from '../../utils/adminDisplayLabels';
import { effectivePermissionModule, effectivePermissionModuleLabel, effectivePermissionSourceLabels, effectivePermissionTypeLabel, filterEffectivePermissions, formatEffectivePermissionDetail, paginateEffectivePermissions, annotateEffectivePermissionAvailability, isInactiveEffectivePermission } from '../../utils/effectivePermissionDisplay';
import { useAuthStore } from '../../stores/auth';

const props = defineProps({ permissions: { type: Array, default: () => [] }, roles: { type: Array, default: () => [] }, loading: { type: Boolean, default: false } });
const auth = useAuthStore();
const displayedPermissions = computed(() => annotateEffectivePermissionAvailability(props.permissions, auth.currentUser?.module_statuses || {}));
const moduleSearch = ref('');
const query = ref(''), type = ref('all'), result = ref('all'), module = ref('all'), showInactive = ref(false), currentPage = ref(1), pageSize = ref(20), expanded = ref('');
const modules = computed(() => {
  const counts = new Map();
  filterEffectivePermissions(displayedPermissions.value, { showInactive: showInactive.value, roles: props.roles }).forEach(permission => { const key = effectivePermissionModule(permission); counts.set(key, (counts.get(key) || 0) + 1); });
  const items = [...counts].map(([key, count]) => ({ key, count, label: effectivePermissionModuleLabel({ module: key }) })).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
  return [{ key: 'all', label: '全部模块', count: [...counts.values()].reduce((sum, count) => sum + count, 0) }, ...items];
});
const visibleModules = computed(()=>modules.value.filter(item=>!moduleSearch.value.trim() || item.label.includes(moduleSearch.value.trim())));
const filtered = computed(() => filterEffectivePermissions(displayedPermissions.value, { query: query.value, module: module.value, type: type.value, result: result.value, showInactive: showInactive.value, roles: props.roles }));
const page = computed(() => paginateEffectivePermissions(filtered.value, currentPage.value, pageSize.value));
watch([query, type, result, module, showInactive, pageSize], () => { currentPage.value = 1; expanded.value = ''; });
watch(() => props.permissions, () => { currentPage.value = 1; expanded.value = ''; });
function selectModule(key) { module.value = key; }
function toggleDetail(code) { expanded.value = expanded.value === code ? '' : code; }
</script>

<style scoped>
.effective-panel{color:#24364b;background:#fff;border:1px solid #e5edf6;border-radius:12px;overflow:hidden}.panel-heading{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid #edf2f7}.panel-heading h3{margin:0;font-size:17px}.panel-heading p{margin:5px 0 0;color:#7b8da3;font-size:13px}.total-count{color:#53749b;font-size:13px}.filters{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 20px;border-bottom:1px solid #edf2f7}.filters .el-input{width:min(290px,100%)}.filters .el-select{width:145px}.filters :deep(.el-checkbox){margin-left:auto}.workspace{display:grid;grid-template-columns:190px minmax(0,1fr);min-height:260px}.module-rail{padding:12px;border-right:1px solid #edf2f7;background:#f8fbff}.module-rail button{width:100%;display:flex;justify-content:space-between;align-items:center;border:0;background:transparent;color:#586c83;border-radius:7px;padding:10px 11px;text-align:left;cursor:pointer}.module-rail button.active{background:#e8f2ff;color:#2364aa;font-weight:600}.module-rail small{color:#91a3b8}.module-mobile{display:none}.permission-content{min-width:0}.permission-row{border-bottom:1px solid #edf2f7}.permission-main{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:14px 18px;border:0;background:white;text-align:left;cursor:pointer;color:inherit}.permission-main:hover{background:#f9fbfe}.permission-copy{min-width:0;display:grid;gap:6px}.permission-copy strong{font-size:14px;font-weight:600}.permission-copy small{color:#8798ab;white-space:normal}.row-badges{display:flex;align-items:center;gap:7px;flex:none}.chevron{font-size:12px;color:#6280a1}.permission-detail{padding:2px 18px 15px 22px;background:#fbfdff}.permission-detail p{display:flex;gap:12px;align-items:center;margin:0 0 10px;color:#73849a;font-size:12px}.permission-detail code{color:#4c6078;word-break:break-all}.source-detail{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:8px;padding:10px 12px;border:1px solid #eaf0f6;border-radius:7px;color:#63758a;font-size:12px}.source-detail strong{color:#344b64}.state-panel{display:grid;place-items:center;min-height:240px;color:#8999ab}.pagination{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 16px;color:#8493a5;font-size:12px}@media(max-width:700px){.workspace{display:block}.module-rail{display:none}.module-mobile{display:block;width:calc(100% - 28px);margin:14px}.filters{padding:12px 14px}.filters .el-input,.filters .el-select{width:100%}.filters :deep(.el-checkbox){margin-left:0}.permission-main{align-items:flex-start;padding:13px 14px}.row-badges{flex-wrap:wrap;justify-content:flex-end}.pagination{align-items:flex-start;flex-direction:column}.pagination :deep(.el-pagination){max-width:100%;flex-wrap:wrap}.source-detail{gap:7px}}

.effective-panel{border:0;border-radius:0}.workspace{grid-template-columns:205px minmax(0,1fr);min-height:520px}.module-rail{background:white;padding:20px 18px 20px 0}.module-rail h3{font-size:15px;margin:0 0 12px;color:#172033}.module-rail .el-input{margin-bottom:14px}.module-rail button{min-height:44px;font-size:14px;border-radius:5px;color:#485875}.module-rail button.active{background:#edf3ff;color:#2463eb}.permission-content{padding:16px 0 12px 20px}.filters{padding:0 0 18px;border:0;gap:10px}.filters .el-input{flex:1;width:auto;min-width:190px}.filters .el-select{width:120px}.permission-table-head,.permission-main{display:grid;grid-template-columns:minmax(140px,1.8fr) 65px 65px minmax(100px,1.1fr) 42px;gap:12px;align-items:center;padding:16px}.permission-table-head{font-size:13px;font-weight:600;color:#485875;background:#f8faff;border:1px solid #e4eaf3;border-radius:6px 6px 0 0}.permission-row{border:1px solid #e4eaf3;border-top:0}.permission-main{cursor:default;min-height:60px;font-size:13px}.permission-name{font-size:14px;line-height:1.6;font-weight:500;color:#24334f;overflow-wrap:anywhere}.permission-type,.permission-source{color:#63758a;line-height:1.6;overflow-wrap:anywhere}.permission-detail{padding-top:14px;background:#f8faff}.permission-detail p{flex-wrap:wrap}.pagination{padding:18px 0}.module-rail button:focus-visible{outline:2px solid #2463eb;outline-offset:2px}
@media(max-width:760px){.workspace{display:block;min-height:0}.module-rail{display:none}.module-mobile{display:block;width:100%;margin:12px 0}.permission-content{padding:0}.permission-table-head{display:none}.permission-main{grid-template-columns:1fr auto auto;gap:10px;padding:14px}.permission-name{grid-column:1/-1}.permission-source{grid-column:1/3}.permission-main>.el-button{justify-self:end}.filters .el-input{min-width:100%}.filters .el-select{width:calc(50% - 5px)}.filters :deep(.el-checkbox){margin-left:0}.pagination{gap:10px}.pagination :deep(.el-pagination){flex-wrap:wrap}.permission-source{font-size:12px}}
</style>
<style scoped>.permission-name{font-size:16px;font-weight:600}.permission-main{font-size:14px}.permission-table-head{font-size:14px}.source-detail{font-size:13px}@media(max-width:760px){.permission-name{font-size:14px}}</style>
