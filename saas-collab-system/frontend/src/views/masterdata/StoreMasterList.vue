<template>
  <AdminResourcePage
    v-if="!mappingOnly"
    ref="resourcePage"
    eyebrow="MASTER DATA"
    title="店铺档案"
    subtitle="按平台和国家查找店铺；点击店铺查看完整档案。"
    entity-label="店铺"
    :loader="loadStores"
    :external-filters="storeScopeFilters"
    :columns="columns"
    :detail-columns="detailColumns"
    :form-fields="formFields"
    :create-handler="(payload) => createMasterData('stores', storePayload(payload))"
    :edit-handler="(id, payload) => updateMasterData('stores', id, storePayload(payload))"
    :delete-handler="(id) => deleteMasterData('stores', id)"
    :status-handler="(row, status) => updateMasterDataStatus('stores', row.id, status)"
    create-permission="masterdata.manage"
    manage-permission="masterdata.manage"
    :operation-width="194"
    :compact-actions="true"
    :show-summary="false"
    :show-page-size="true"
    :stack-sidebar-at-narrow="true"
    search-label="店铺名称、编码或平台店铺名"
    search-placeholder="搜索店铺名称、编码或平台店铺名"
    @reset="clearStoreScope"
  >
    <template #sidebar>
      <nav class="store-scope-tree" aria-label="按平台和国家查找店铺">
        <div class="store-scope-tree__heading">
          <div>
            <strong>平台 / 国家</strong>
            <small>{{ storeFacets.platforms.length }} 个平台 · {{ countryGroupCount }} 个国家分组</small>
          </div>
        </div>
        <button
          type="button"
          class="store-scope-tree__all"
          :class="{ 'is-selected': selectedPlatformId === null }"
          :aria-current="selectedPlatformId === null ? 'true' : undefined"
          @click="selectAllStores"
        >
          <span>全部店铺</span><span class="store-scope-tree__count">{{ storeFacets.total }}</span>
        </button>
        <p v-if="!storeFacets.platforms.length" class="store-scope-tree__empty">暂无可查看的平台店铺</p>
        <div v-for="platform in platformTree" :key="platform.platform_id" class="store-scope-tree__group">
          <div class="store-scope-tree__platform-line">
            <button
              type="button"
              class="store-scope-tree__platform"
              :class="{ 'is-selected': selectedPlatformId === platform.platform_id && !selectedCountryCode }"
              :aria-current="selectedPlatformId === platform.platform_id && !selectedCountryCode ? 'true' : undefined"
              @click="selectPlatform(platform)"
            >
              <span class="store-scope-tree__platform-name">{{ platform.platform_name || '未命名平台' }}</span>
              <span class="store-scope-tree__count">{{ platform.count }}</span>
            </button>
            <button
              type="button"
              class="store-scope-tree__toggle"
              :aria-label="`${expandedPlatforms.has(platform.platform_id) ? '收起' : '展开'}${platform.platform_name || '未命名平台'}的国家`"
              :aria-expanded="expandedPlatforms.has(platform.platform_id)"
              @click="togglePlatform(platform.platform_id)"
            ><el-icon><ArrowDown v-if="expandedPlatforms.has(platform.platform_id)" /><ArrowRight v-else /></el-icon></button>
          </div>
          <div v-if="expandedPlatforms.has(platform.platform_id)" class="store-scope-tree__countries">
            <button
              v-for="country in platform.countries"
              :key="country.country_code"
              type="button"
              class="store-scope-tree__country"
              :class="{ 'is-selected': selectedPlatformId === platform.platform_id && selectedCountryCode === country.country_code }"
              :aria-current="selectedPlatformId === platform.platform_id && selectedCountryCode === country.country_code ? 'true' : undefined"
              @click="selectCountry(platform, country)"
            >
              <span>{{ countryLabel(country.country_code) }}</span>
              <span class="store-scope-tree__count">{{ country.count }}</span>
            </button>
          </div>
        </div>
        <p class="store-scope-tree__note">数量按当前可查看范围统计，包含启用和停用店铺。</p>
      </nav>
    </template>
    <template #before-filters="{ total }">
      <div class="store-scope-summary">
        <div>
          <span>当前范围</span>
          <strong>{{ currentScopeLabel }}</strong>
        </div>
        <p>当前条件下共 <strong>{{ total }}</strong> 家店铺</p>
      </div>
    </template>
    <template #cell="{ column, row }">
      <div v-if="column.prop === 'name'" class="store-cell store-cell--identity">
        <strong>{{ row.name || row.platform_store_name || '-' }}</strong>
        <span>{{ row.code || '-' }}</span>
        <small v-if="row.platform_store_name && row.platform_store_name !== row.name">平台店铺：{{ row.platform_store_name }}</small>
      </div>
      <div v-else-if="column.prop === 'platform_name'" class="store-cell">
        <strong>{{ row.platform_name || '-' }}</strong>
        <span>{{ countryLabel(row.country_code) }}<template v-if="row.platform_site_name"> · {{ row.platform_site_name }}</template></span>
      </div>
      <span v-else-if="column.prop === 'operator_name'">{{ row.operator_name || '-' }}</span>
      <el-tag v-else-if="column.prop === 'is_connected'" :type="row.is_connected ? 'success' : 'info'" effect="plain">{{ row.is_connected ? '已建联' : '未建联' }}</el-tag>
      <el-tag v-else-if="column.prop === 'status'" :type="row.status === 'active' ? 'success' : 'info'" effect="plain">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
    </template>
    <template #actions>
      <el-button
        v-if="masterDataManageAccess.visible"
        type="primary"
        plain
        :disabled="masterDataManageAccess.disabled"
        :title="masterDataManageAccess.reason"
        @click="openImportDialog"
      >导入店铺档案</el-button>
      <el-dropdown trigger="click" @command="handlePageAction">
        <el-button plain>更多操作<el-icon class="store-page-actions__arrow"><ArrowDown /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="template">下载 CSV 导入模板</el-dropdown-item>
            <el-dropdown-item command="migration">站点映射预览</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
    <template #row-actions="{ row, edit, remove, toggleStatus }">
      <el-button
        v-if="storeApiViewAccess.visible"
        link
        type="primary"
        :disabled="storeApiViewAccess.disabled"
        :title="storeApiViewAccess.reason || '选择已就绪配置并发起授权；开发者凭据仍统一在连接配置中维护。'"
        @click.stop="openApiAccess(row)"
      >API 接入</el-button>
      <el-dropdown
        v-if="masterDataManageAccess.visible || storeViewAccess.visible || storeMappingViewAccess.visible"
        trigger="click"
        @command="(command) => handleStoreAction(command, row, { edit, remove, toggleStatus })"
      >
        <el-button link type="primary" @click.stop>更多</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-if="masterDataManageAccess.visible" command="edit" :disabled="masterDataManageAccess.disabled">编辑资料</el-dropdown-item>
            <el-dropdown-item v-if="storeMappingViewAccess.visible" command="mapping" :disabled="storeMappingViewAccess.disabled">平台关联</el-dropdown-item>
            <el-dropdown-item v-if="storeViewAccess.visible" command="capability" :disabled="storeViewAccess.disabled">能力矩阵</el-dropdown-item>
            <el-dropdown-item v-if="masterDataManageAccess.visible" command="status" :disabled="masterDataManageAccess.disabled" divided>{{ row.status === 'active' ? '停用' : '启用' }}</el-dropdown-item>
            <el-dropdown-item v-if="masterDataManageAccess.visible" command="delete" :disabled="masterDataManageAccess.disabled">删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
  </AdminResourcePage>

  <StoreMappingPanel
    v-else-if="mappingOnly"
    :store-id="route.query.store_id || null"
    standalone
    :show-api-access="false"
  />

  <el-drawer
    v-model="storeWorkspaceOpen"
    :title="`${selectedStore?.name || '店铺'} · 平台运营工作区`"
    size="min(1180px, 96vw)"
    destroy-on-close
  >
    <el-tabs v-if="selectedStore" v-model="workspaceTab" class="store-workspace-tabs">
      <el-tab-pane label="基本资料" name="profile">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="店铺编码">{{ selectedStore.code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="店铺名称">{{ selectedStore.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ selectedStore.platform_name || selectedStore.platform || '-' }}</el-descriptions-item>
          <el-descriptions-item label="平台站点">{{ selectedStore.platform_site_name || selectedStore.country_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="外部店铺 ID">{{ selectedStore.external_store_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="业务模式">{{ selectedStore.business_model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="币种/时区">{{ selectedStore.currency || '-' }} / {{ selectedStore.timezone || '-' }}</el-descriptions-item>
          <el-descriptions-item label="档案状态">{{ selectedStore.status || '-' }}</el-descriptions-item>
        </el-descriptions>
        <p class="workspace-note">基础资料由店铺档案维护；平台授权、关联状态和同步能力在其他区域处理。</p>
      </el-tab-pane>

      <el-tab-pane label="平台身份与授权" name="identity">
        <el-alert
          title="平台身份由授权回调产生，页面只展示脱敏信息；授权历史、刷新、撤销和重新授权沿用现有 API 接入抽屉。"
          type="info"
          show-icon
          :closable="false"
        />
        <div class="workspace-summary-grid">
          <div><span>平台</span><strong>{{ selectedStore.platform_name || selectedStore.platform || '-' }}</strong></div>
          <div><span>授权身份</span><strong>{{ apiConnectionSummary.identityName || '尚未读取' }}</strong></div>
          <div><span>平台店铺 ID</span><strong>{{ apiConnectionSummary.platformStoreId || '授权后生成' }}</strong></div>
          <div><span>业务建联</span><strong>{{ selectedStore.is_connected ? '已登记' : '未登记' }}</strong></div>
        </div>
        <div class="workspace-actions">
          <el-button type="primary" :disabled="storeApiViewAccess.disabled" :title="storeApiViewAccess.reason" @click="openApiAccess(selectedStore)">打开 API 接入</el-button>
          <el-button plain :disabled="storeViewAccess.disabled" :title="storeViewAccess.reason" @click="openCapabilityMatrix(selectedStore)">查看连接能力</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="API连接状态" name="api-status">
        <el-alert
          :title="apiConnectionSummary.message"
          :type="apiConnectionSummary.type"
          show-icon
          :closable="false"
        />
        <el-descriptions :column="1" border class="workspace-descriptions">
          <el-descriptions-item label="API 授权状态">{{ apiConnectionSummary.statusLabel }}</el-descriptions-item>
          <el-descriptions-item label="有效连接 / 历史授权">{{ apiConnectionSummary.activeCount }} / {{ apiConnectionSummary.historyCount }}</el-descriptions-item>
          <el-descriptions-item label="最近验证时间">{{ formatDateTime(apiConnectionSummary.lastVerifiedAt) }}</el-descriptions-item>
          <el-descriptions-item label="失败/异常记录">{{ apiConnectionSummary.failureCount }}</el-descriptions-item>
          <el-descriptions-item label="平台/站点">{{ selectedStore.platform_name || selectedStore.platform || '-' }} · {{ selectedStore.platform_site_name || selectedStore.country_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="业务建联状态">{{ selectedStore.is_connected ? '已登记' : '未登记' }}（不等同于 API 授权）</el-descriptions-item>
          <el-descriptions-item label="接入入口">开发者凭据保存在连接配置；店铺授权和授权历史在 API 接入抽屉维护。</el-descriptions-item>
        </el-descriptions>
        <div class="workspace-actions">
          <el-button type="primary" :disabled="storeApiViewAccess.disabled || apiConnectionLoading" :title="storeApiViewAccess.reason" @click="loadApiConnectionStatus(selectedStore, true)">{{ apiConnectionLoading ? '刷新中…' : '刷新 API 授权状态' }}</el-button>
          <el-button plain :disabled="storeApiViewAccess.disabled" :title="storeApiViewAccess.reason" @click="openApiAccess(selectedStore)">打开授权与历史</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="映射及验证历史" name="mapping">
        <StoreMappingPanel :store="selectedStore" @open-api="openApiAccess" />
      </el-tab-pane>

      <el-tab-pane label="同步能力与异常" name="sync">
        <el-alert
          title="同步任务、运行记录和异常处置均通过现有 API 数据接入菜单进入，并沿用平台、店铺和权限范围。"
          type="info"
          show-icon
          :closable="false"
        />
        <div class="workspace-actions workspace-actions--stack">
          <el-button type="primary" :disabled="storeViewAccess.disabled" :title="storeViewAccess.reason" @click="openCapabilityMatrix(selectedStore)">维护同步能力矩阵</el-button>
          <el-button plain :disabled="!syncViewAccess.allowed" :title="syncViewAccess.reason" @click="openStoreSyncJobs(selectedStore)">查看同步任务</el-button>
          <el-button
            plain
            :disabled="!storeProductSyncAccess.allowed || storeProductSyncLoading"
            :title="storeProductSyncAccess.reason"
            @click="openStoreProductSyncJobs(selectedStore)"
          >{{ storeProductSyncLoading ? '校验中…' : '平台商品同步任务' }}</el-button>
          <el-button plain :disabled="!syncViewAccess.allowed" :title="syncViewAccess.reason" @click="openStoreSyncIncidents(selectedStore)">查看同步异常</el-button>
        </div>
        <p class="workspace-note">当前店铺的授权状态、能力开关、同步任务和异常记录均在目标页面中重新按权限查询。</p>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>

  <el-dialog v-model="migrationOpen" title="历史店铺 · 站点映射预览" width="min(1240px, 96vw)" :close-on-click-modal="false">
    <el-alert
      title="预览只读取当前租户中尚未关联平台站点的店铺；只有同租户、同平台、同国家代码且唯一命中的 exact 项可应用。不会创建站点、覆盖已有站点或自动处理 ambiguous / unmatched。"
      type="info"
      :closable="false"
      show-icon
    />
    <div class="migration-toolbar">
      <div class="migration-counts" aria-label="映射预览统计">
        <span>exact <strong>{{ migrationCounts.exact }}</strong></span>
        <span>ambiguous <strong>{{ migrationCounts.ambiguous }}</strong></span>
        <span>unmatched <strong>{{ migrationCounts.unmatched }}</strong></span>
      </div>
      <div class="migration-actions">
        <el-checkbox
          :model-value="allExactSelected"
          :indeterminate="exactSelectionIndeterminate"
          :disabled="!exactRows.length"
          @change="toggleAllExact"
        >全选 exact</el-checkbox>
        <el-button plain :loading="migrationLoading" @click="loadMigrationPreview">刷新预览</el-button>
      </div>
    </div>
    <el-alert v-if="migrationError" :title="migrationError" type="error" :closable="false" show-icon />
    <el-table
      ref="migrationTable"
      v-loading="migrationLoading"
      :data="migrationRows"
      row-key="store_id"
      border
      empty-text="暂无待映射的历史店铺"
      @selection-change="handleMigrationSelection"
    >
      <el-table-column type="selection" width="54" :selectable="isExactMigrationRow" />
      <el-table-column label="匹配状态" width="112" fixed="left">
        <template #default="{ row }">
          <el-tag :type="migrationStatusType(row)" effect="plain">{{ migrationStatus(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="店铺" min-width="210">
        <template #default="{ row }">
          <div>{{ row.store_name || row.name || '-' }}</div>
          <small>{{ row.store_code || row.code || `#${row.store_id}` }}</small>
        </template>
      </el-table-column>
      <el-table-column prop="platform_name" label="平台" min-width="140" />
      <el-table-column prop="country_code" label="国家" width="90" />
      <el-table-column label="候选站点" min-width="230">
        <template #default="{ row }">
          <div v-if="migrationCandidates(row).length" class="candidate-list">
            <span v-for="candidate in migrationCandidates(row)" :key="candidate.id || candidate.site_code">
              {{ candidate.name || candidate.site_code || `#${candidate.id}` }}<small v-if="candidate.site_code">（{{ candidate.site_code }}）</small>
            </span>
          </div>
          <span v-else class="muted">无候选</span>
        </template>
      </el-table-column>
      <el-table-column label="变更前" min-width="150">
        <template #default="{ row }">{{ migrationSiteLabel(row, 'before') }}</template>
      </el-table-column>
      <el-table-column label="变更后" min-width="150">
        <template #default="{ row }">{{ migrationSiteLabel(row, 'after') }}</template>
      </el-table-column>
      <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
      <el-table-column label="置信度" width="100">
        <template #default="{ row }">{{ migrationConfidence(row) }}</template>
      </el-table-column>
    </el-table>
    <div class="migration-selection-note">
      已选择 {{ selectedMigrationStoreIds.length }} 条 exact；应用前后端会重新计算匹配状态，并跳过已有关联或发生冲突的店铺。
    </div>
    <template #footer>
      <el-button @click="migrationOpen = false">关闭</el-button>
      <el-button
        type="primary"
        :loading="migrationApplying"
        :disabled="migrationManageAccess.disabled || !selectedMigrationStoreIds.length"
        :title="migrationManageAccess.reason"
        @click="confirmMigration"
      >应用选中的 exact 映射</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="importOpen" title="导入店铺档案" width="min(680px, 94vw)">
    <el-alert title="支持 CSV / XLSX；按店铺档案编码幂等更新。导入列：店铺档案编码、店铺名称、平台、平台店铺名、类目、负责运营、BD、组长、是否建联、战斧客户端、国家代码、币种、时区。" type="info" :closable="false" show-icon />
    <el-upload drag :auto-upload="false" :limit="1" accept=".csv,.xlsx" :on-change="onFileChange" :on-remove="() => (importFile = null)">
      <el-icon><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或点击选择</div>
    </el-upload>
    <template #footer>
      <el-button @click="importOpen = false">取消</el-button>
      <el-button
        type="primary"
        :loading="importing"
        :disabled="masterDataManageAccess.disabled || !importFile"
        :title="masterDataManageAccess.reason"
        @click="submitImport"
      >开始导入</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="capabilityOpen" :title="`${selectedStore?.name || ''} · 连接能力矩阵`" width="min(980px, 96vw)">
    <el-alert v-if="!authorizationOptions.length && !capabilityLoading" title="该店铺尚无授权连接，不能配置同步能力。" type="warning" :closable="false" show-icon />
    <el-select v-if="authorizationOptions.length > 1" v-model="selectedAuthorizationId" placeholder="选择授权连接" @change="loadCapabilities">
      <el-option v-for="item in authorizationOptions" :key="item.id" :label="authorizationSourceLabel(item)" :value="item.id" />
    </el-select>
    <el-alert v-if="selectedAuthorization && !capabilityEditAllowed" title="只有有效授权（active/authorized）且具备授权权限时可以保存能力矩阵；当前仅允许查看。" type="warning" :closable="false" show-icon />
    <el-alert v-if="capabilitySuggestions.length" :title="`检测到 ${capabilitySuggestions.length} 条能力建议；载入后只覆盖本地表单，仍需复核 scopes/evidence 并点击保存确认。`" type="info" :closable="false" show-icon />
    <el-table v-loading="capabilityLoading" :data="capabilityRows" border empty-text="暂无能力数据">
      <el-table-column label="能力代码 · 中文名称" min-width="180"><template #default="{ row }">{{ capabilityLabel(row.capability_code) }}</template></el-table-column>
      <el-table-column label="读取" width="90"><template #default="{ row }"><el-switch v-model="row.read_enabled" :disabled="!capabilityEditAllowed" /></template></el-table-column>
      <el-table-column label="写入" width="90"><template #default="{ row }"><el-switch :model-value="false" disabled /></template></el-table-column>
      <el-table-column label="同步方式" min-width="130"><template #default="{ row }"><el-select v-model="row.sync_mode" :disabled="!capabilityEditAllowed"><el-option label="定时" value="scheduled"/><el-option label="实时" value="realtime"/><el-option label="Webhook" value="webhook"/><el-option label="人工" value="manual"/></el-select></template></el-table-column>
      <el-table-column label="来源优先级" width="130"><template #default="{ row }"><el-input-number v-model="row.source_priority" :min="1" :max="65535" controls-position="right" :disabled="!capabilityEditAllowed" /></template></el-table-column>
      <el-table-column label="状态" min-width="120"><template #default="{ row }"><el-select v-model="row.status" :disabled="!capabilityEditAllowed"><el-option label="禁用" value="disabled"/><el-option label="已配置" value="configured"/><el-option label="启用" value="active"/><el-option label="错误" value="error"/></el-select></template></el-table-column>
    </el-table>
    <template #footer><el-button @click="capabilityOpen = false">关闭</el-button><el-button plain :disabled="!capabilitySuggestions.length || capabilityLoading || !capabilityEditAllowed" :title="capabilityEditAllowed ? '' : capabilityEditReason" @click="applyCapabilitySuggestions">载入建议</el-button><el-button type="primary" :loading="capabilitySaving" :disabled="capabilitySaveAccess.disabled || !selectedAuthorizationId || !capabilityEditAllowed" :title="capabilityEditReason || capabilitySaveAccess.reason" @click="saveCapabilities">确认保存</el-button></template>
  </el-dialog>

  <SubjectApiAccessDialog
    v-model="apiAccessOpen"
    subject-type="store"
    :row="selectedStore"
    @changed="handleApiAccessChanged"
  />
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ArrowDown, ArrowRight, UploadFilled } from '@element-plus/icons-vue';
import AdminResourcePage from '../../components/AdminResourcePage.vue';
import StoreMappingPanel from '../../components/StoreMappingPanel.vue';
import SubjectApiAccessDialog from '../../components/SubjectApiAccessDialog.vue';
import { fetchUsers } from '../../api/systemAdmin';
import { fetchProductCategories } from '../../api/products';
import { fetchConnectionCapabilities, fetchStoreAuthorizations, fetchSubjectApiAccess, updateConnectionCapabilities } from '../../api/integrations';
import { getActionAccess } from '../../utils/actionAccess';
import { authorizationSourceLabel, capabilityLabel } from '../../utils/integrationCapabilityLabels';
import { useAuthStore } from '../../stores/auth';
import { useRoute, useRouter } from 'vue-router';
import {
  applyPlatformSiteMigration, createMasterData, deleteMasterData, fetchCountrySites, fetchPlatforms, fetchPlatformSiteMigrationPreview,
  fetchMasterDataDetail, fetchPlatformSites, fetchStores, importStores,
  updateMasterData, updateMasterDataStatus,
} from '../../api/masterData';

const detailColumns = [
  { prop: 'code', label: '店铺档案编码', width: 170 }, { prop: 'name', label: '店铺名称', width: 190 },
  { prop: 'platform_store_name', label: '平台店铺名', width: 180 }, { prop: 'platform_name', label: '所属平台', width: 150 },
  { prop: 'platform_site_name', label: '平台站点', width: 170 }, { prop: 'external_store_id', label: '外部店铺 ID', width: 150 },
  { prop: 'business_model', label: '业务模式', width: 130 }, { prop: 'fulfillment_modes', label: '履约模式', type: 'list', width: 210 },
  { prop: 'category_name', label: '类目', width: 130 }, { prop: 'operator_name', label: '负责运营', width: 120 },
  { prop: 'bd_name', label: 'BD', width: 120 }, { prop: 'leader_name', label: '组长', width: 120 },
  { prop: 'is_connected', label: '是否建联', type: 'boolean', width: 100 },
  { prop: 'tactical_client', label: '战斧客户端', width: 150 }, { prop: 'country_code', label: '国家' },
  { prop: 'currency', label: '币种' }, { prop: 'settlement_currency', label: '结算币种' }, { prop: 'timezone', label: '时区', width: 170 },
  { prop: 'status', label: '状态', type: 'status' },
];
const columns = [
  { prop: 'name', label: '店铺', width: 280 },
  { prop: 'platform_name', label: '平台 / 国家', width: 220 },
  { prop: 'status', label: '状态', width: 86 },
];

const platformOptions = ref([]); const platformSites = ref([]); const platformSiteOptions = ref([]); const countryOptions = ref([]); const categoryOptions = ref([]); const userOptions = ref([]);
const importOpen = ref(false); const importFile = ref(null); const importing = ref(false); const apiAccessOpen = ref(false);
const capabilityOpen = ref(false); const capabilityLoading = ref(false); const capabilitySaving = ref(false);
const selectedStore = ref(null); const authorizationOptions = ref([]); const selectedAuthorizationId = ref(null); const capabilityRows = ref([]);
const capabilitySuggestions = ref([]);
const storeProductSyncLoading = ref(false);
const capabilityCodes = ['PRODUCT', 'CATEGORY', 'LISTING', 'PRICE', 'ORDER', 'INVENTORY', 'FULFILLMENT', 'WAREHOUSE', 'RETURN_REFUND', 'SETTLEMENT', 'PAYMENT', 'ADVERTISING', 'AFFILIATE', 'REVIEW', 'REPORT', 'WEBHOOK'];
const selectedAuthorization = computed(() => authorizationOptions.value.find((item) => item.id === selectedAuthorizationId.value));

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const resourcePage = ref(null);
const storeFacets = ref({ total: 0, platforms: [] });
const countryGroupCount = computed(() => storeFacets.value.platforms.reduce((total, platform) => total + platform.countries.length, 0));
const platformTree = computed(() => [...storeFacets.value.platforms]
  .sort((left, right) => right.count - left.count || String(left.platform_name).localeCompare(String(right.platform_name)))
  .map((platform) => ({
    ...platform,
    countries: [...platform.countries].sort((left, right) => right.count - left.count || String(left.country_code).localeCompare(String(right.country_code))),
  })));
const selectedPlatformId = ref(null);
const selectedCountryCode = ref('');
const expandedPlatforms = ref(new Set());
const storeScopeFilters = computed(() => ({
  ...(selectedPlatformId.value === null ? {} : { platform_id: selectedPlatformId.value }),
  ...(selectedCountryCode.value ? { country_code: selectedCountryCode.value } : {}),
}));
let storeFacetRequestSequence = 0;
const currentScopeLabel = computed(() => {
  const platform = storeFacets.value.platforms.find((item) => item.platform_id === selectedPlatformId.value);
  if (!platform) return '全部平台 · 全部国家';
  return selectedCountryCode.value
    ? `${platform.platform_name || '未命名平台'} / ${countryLabel(selectedCountryCode.value)}`
    : `${platform.platform_name || '未命名平台'} / 全部国家`;
});
const regionNames = typeof Intl.DisplayNames === 'function'
  ? new Intl.DisplayNames(['zh-CN'], { type: 'region' })
  : null;

function countryLabel(value) {
  const code = String(value || '').trim().toUpperCase();
  if (!code || code === '__UNSET__') return '未设置国家';
  try {
    const name = regionNames?.of(code);
    return name && name !== code ? `${name} (${code})` : code;
  } catch {
    return code;
  }
}

async function loadStores(params) {
  const requestSequence = ++storeFacetRequestSequence;
  const response = await fetchStores(params);
  if (requestSequence !== storeFacetRequestSequence) return response;
  if (!response?.success) {
    storeFacets.value = { total: 0, platforms: [] };
    return response;
  }
  const facets = response.data?.store_facets;
  storeFacets.value = facets && Array.isArray(facets.platforms)
    ? facets
    : { total: 0, platforms: [] };
  return response;
}

function togglePlatform(platformId) {
  const next = new Set(expandedPlatforms.value);
  if (next.has(platformId)) next.delete(platformId);
  else next.add(platformId);
  expandedPlatforms.value = next;
}

async function selectAllStores() {
  selectedPlatformId.value = null;
  selectedCountryCode.value = '';
  await nextTick();
  resourcePage.value?.queryData?.();
}

function clearStoreScope() {
  selectedPlatformId.value = null;
  selectedCountryCode.value = '';
}

async function selectPlatform(platform) {
  selectedPlatformId.value = platform.platform_id;
  selectedCountryCode.value = '';
  expandedPlatforms.value = new Set([platform.platform_id]);
  await nextTick();
  resourcePage.value?.queryData?.();
}

async function selectCountry(platform, country) {
  selectedPlatformId.value = platform.platform_id;
  selectedCountryCode.value = country.country_code;
  expandedPlatforms.value = new Set([platform.platform_id]);
  await nextTick();
  resourcePage.value?.queryData?.();
}

function handleStoreAction(command, row, actions) {
  if (command === 'edit') actions.edit();
  else if (command === 'mapping') openStoreWorkspace(row, 'mapping');
  else if (command === 'capability') openCapabilityMatrix(row);
  else if (command === 'status') actions.toggleStatus();
  else if (command === 'delete') actions.remove();
}

function handlePageAction(command) {
  if (command === 'template') downloadTemplate();
  else if (command === 'migration') openMigrationPreview();
}
const storeWorkspaceOpen = ref(false); const workspaceTab = ref('profile');
const apiConnectionLoading = ref(false);
const apiConnectionSummary = ref({
  status: 'unknown',
  statusLabel: '尚未检查',
  type: 'info',
  message: '打开工作区后将读取真实 API 授权状态。',
  activeCount: 0,
  historyCount: 0,
  failureCount: 0,
  lastVerifiedAt: '',
  identityName: '',
  platformStoreId: '',
});
const migrationTable = ref(null);
const migrationOpen = ref(false); const migrationLoading = ref(false); const migrationApplying = ref(false); const migrationError = ref('');
const migrationRows = ref([]); const migrationSummary = ref({}); const selectedMigrationRows = ref([]);
const masterDataViewAccess = computed(() => getActionAccess(auth, { permission: 'masterdata.view', unauthorizedBehavior: 'disable' }));
const masterDataManageAccess = computed(() => getActionAccess(auth, { permission: 'masterdata.manage', unauthorizedBehavior: 'disable' }));
const storeMappingViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store_mapping.view', unauthorizedBehavior: 'disable' }));
const mappingOnly = computed(() => !masterDataViewAccess.value.allowed && storeMappingViewAccess.value.allowed);
const integrationViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view', unauthorizedBehavior: 'disable' }));
const storeViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.view', unauthorizedBehavior: 'disable' }));
const syncViewAccess = computed(() => getActionAccess(auth, { permission: 'integrations.view', unauthorizedBehavior: 'disable' }));
// `hasPermission(...codes)` is an OR operation, so combine the two
// permissions explicitly for the store API entry point.
const storeApiViewAccess = computed(() => {
  const allowed = integrationViewAccess.value.allowed && storeViewAccess.value.allowed;
  return {
    allowed,
    visible: integrationViewAccess.value.visible && storeViewAccess.value.visible,
    disabled: !allowed,
    reason: integrationViewAccess.value.allowed
      ? storeViewAccess.value.reason
      : integrationViewAccess.value.reason,
  };
});
const productSyncPlatforms = new Set(['shopee', 'tiktok']);
const storeProductSyncAccess = computed(() => {
  if (!syncViewAccess.value.allowed) return { allowed: false, reason: syncViewAccess.value.reason || '当前角色无权查看同步任务。' };
  if (!storeApiViewAccess.value.allowed) return { allowed: false, reason: storeApiViewAccess.value.reason || '需要店铺 API 查看权限才能验证授权状态。' };
  const platform = storePlatformCode(selectedStore.value);
  if (!productSyncPlatforms.has(platform)) return { allowed: false, reason: '当前平台尚未登记已验证的平台商品同步连接器。' };
  if (selectedStore.value?.product_sync_supported === false || selectedStore.value?.connector_supported === false) {
    return { allowed: false, reason: '当前店铺平台商品同步连接器未实现或未启用。' };
  }
  if (apiConnectionSummary.value.status !== 'healthy') {
    return { allowed: false, reason: apiConnectionSummary.value.status === 'loading' ? '正在验证店铺授权状态，请稍候。' : '店铺 API 尚未验证为有效授权，暂不能进入平台商品同步任务。' };
  }
  return { allowed: true, reason: '仅进入当前已验证授权店铺的平台商品同步任务。' };
});
const storeAuthorizeAccess = computed(() => getActionAccess(auth, { permission: 'integrations.store.authorize', unauthorizedBehavior: 'disable' }));
const capabilitySaveAccess = computed(() => storeAuthorizeAccess.value);
const migrationManageAccess = masterDataManageAccess;
const capabilityEditAllowed = computed(() => Boolean(
  storeAuthorizeAccess.value.allowed
  && ['active', 'authorized'].includes(selectedAuthorization.value?.status),
));
const capabilityEditReason = computed(() => {
  if (!storeAuthorizeAccess.value.allowed) return storeAuthorizeAccess.value.reason || '当前角色无权修改连接能力';
  if (!selectedAuthorization.value) return '尚未选择授权连接';
  if (!['active', 'authorized'].includes(selectedAuthorization.value.status)) return '只有有效授权（active/authorized）可以保存能力矩阵';
  return '';
});

function applyCountryDefaults(value, form) {
  const countryCode = String(value || '').trim().toUpperCase();
  const country = countryOptions.value.find((option) => option.value === countryCode);
  if (!country) return;
  form.currency = country.currency || ''; form.timezone = country.timezone || '';
}

function toPlatformSiteOption(item) { return { label: `${item.platform_name || ''} · ${item.name || item.site_code} (${item.site_code})`, value: item.id }; }
function applyPlatform(value, form) {
  platformSiteOptions.value = platformSites.value.filter((item) => item.platform_id === value).map(toPlatformSiteOption);
  if (!platformSiteOptions.value.some((item) => item.value === form.platform_site_id)) form.platform_site_id = null;
}
function applyPlatformSite(value, form) {
  const site = platformSites.value.find((item) => item.id === value); if (!site) return;
  form.country_code = site.country_code || form.country_code || '';
  form.currency = site.currency_code || form.currency || '';
  form.settlement_currency = site.currency_code || form.settlement_currency || '';
  form.timezone = site.timezone || form.timezone || 'UTC';
}

function openApiAccess(row) {
  if (!integrationViewAccess.value.allowed || !storeViewAccess.value.allowed) {
    const reason = integrationViewAccess.value.allowed
      ? storeViewAccess.value.reason
      : integrationViewAccess.value.reason;
    ElMessage.warning(reason || '当前角色无权查看店铺 API 接入');
    return;
  }
  selectedStore.value = row;
  apiAccessOpen.value = true;
}

function formatDateTime(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('zh-CN', { hour12: false });
}

function emptyApiConnectionSummary(overrides = {}) {
  return {
    status: 'unknown',
    statusLabel: '尚未检查',
    type: 'info',
    message: '打开工作区后将读取真实 API 授权状态。',
    activeCount: 0,
    historyCount: 0,
    failureCount: 0,
    lastVerifiedAt: '',
    identityName: '',
    platformStoreId: '',
    ...overrides,
  };
}

function summarizeApiConnection(response) {
  const data = response?.data || {};
  const bindings = Array.isArray(data.bindings) ? data.bindings : [];
  const activeBindings = bindings.filter((item) => ['active', 'authorized'].includes(String(item.status || '').toLowerCase()));
  const failedBindings = bindings.filter((item) => (
    ['error', 'expired', 'revoked', 'failed', 'invalid'].includes(String(item.status || '').toLowerCase())
    || item.last_error_code
    || item.masked_error_message
  ));
  const verifiedValues = bindings
    .flatMap((item) => [item.last_verified_at, item.refreshed_at])
    .filter(Boolean)
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime());
  const identity = activeBindings[0] || bindings[0] || {};
  const activeCount = activeBindings.length;
  const historyCount = bindings.length;
  const failureCount = failedBindings.length;
  let status = 'unauthorized';
  let statusLabel = '未授权';
  let type = 'warning';
  let message = '当前没有有效 API 授权，请进入“打开授权与历史”完成授权。';
  if (activeCount && failureCount) {
    status = 'partial';
    statusLabel = '部分异常';
    type = 'warning';
    message = `存在 ${activeCount} 个有效 API 授权，同时有 ${failureCount} 条历史异常，请检查授权历史。`;
  } else if (activeCount) {
    status = 'healthy';
    statusLabel = '已授权';
    type = 'success';
    message = `API 授权有效（${activeCount} 个连接），可继续检查同步能力。`;
  } else if (historyCount) {
    status = 'error';
    statusLabel = '授权异常';
    type = 'error';
    message = '没有有效 API 授权，请检查失败、过期或已撤销的授权记录。';
  }
  return emptyApiConnectionSummary({
    status,
    statusLabel,
    type,
    message,
    activeCount,
    historyCount,
    failureCount,
    lastVerifiedAt: verifiedValues[0] || '',
    identityName: identity.account_alias || identity.platform_store_name || identity.store_name || '',
    platformStoreId: identity.platform_store_id || identity.platform_store_id_masked || '',
  });
}

async function loadApiConnectionStatus(row = selectedStore.value, force = false) {
  if (!row?.id || !storeApiViewAccess.value.allowed) {
    apiConnectionSummary.value = emptyApiConnectionSummary({
      status: 'permission',
      statusLabel: '无权查看',
      type: 'info',
      message: storeApiViewAccess.value.reason || '当前角色无权读取 API 授权状态。',
    });
    return;
  }
  if (apiConnectionLoading.value && !force) return;
  apiConnectionLoading.value = true;
  apiConnectionSummary.value = emptyApiConnectionSummary({
    status: 'loading',
    statusLabel: '读取中',
    type: 'info',
    message: '正在读取真实 API 授权状态，请稍候。',
  });
  try {
    const response = await fetchSubjectApiAccess('store', row.id);
    if (!response?.success) throw new Error(response?.message || 'API 授权状态读取失败');
    apiConnectionSummary.value = summarizeApiConnection(response);
  } catch (error) {
    apiConnectionSummary.value = emptyApiConnectionSummary({
      status: 'error',
      statusLabel: '读取失败',
      type: 'error',
      message: error?.message || 'API 授权状态读取失败，请重试或打开授权历史。',
    });
  } finally {
    apiConnectionLoading.value = false;
  }
}

async function handleApiAccessChanged() {
  await resourcePage.value?.loadData?.();
  await loadApiConnectionStatus(selectedStore.value, true);
}

function openStoreWorkspace(row, tab = 'profile') {
  if (!row || !masterDataViewAccess.value.allowed || !storeMappingViewAccess.value.allowed) {
    ElMessage.warning(storeMappingViewAccess.value.reason || '当前角色无权查看店铺平台关联');
    return;
  }
  selectedStore.value = row;
  workspaceTab.value = tab;
  storeWorkspaceOpen.value = true;
  if (storeApiViewAccess.value.allowed) loadApiConnectionStatus(row);
}

function storePlatformCode(row) {
  const value = row?.platform_code || row?.platform_key || row?.platform_type || row?.platform;
  return typeof value === 'string' ? value : '';
}

function openStoreSyncJobs(row) {
  if (!syncViewAccess.value.allowed) {
    ElMessage.warning(syncViewAccess.value.reason || '当前角色无权查看同步任务');
    return;
  }
  router.push({ path: '/integrations/sync-jobs', query: {
    platform: storePlatformCode(row),
    subject: row?.name || row?.code || '',
  } });
}

async function openStoreProductSyncJobs(row) {
  if (!storeProductSyncAccess.value.allowed) {
    ElMessage.warning(storeProductSyncAccess.value.reason || '当前店铺暂不能进入平台商品同步任务');
    return;
  }
  if (!row?.id) {
    ElMessage.warning('当前店铺缺少主体标识，暂不能进入平台商品同步任务');
    return;
  }
  storeProductSyncLoading.value = true;
  try {
    // Re-check the exact store authorization and PRODUCT read-only capability
    // at navigation time; a healthy summary may be stale or may not include
    // the capability that the product task requires.
    const accessResponse = await fetchSubjectApiAccess('store', row.id);
    if (!accessResponse?.success) throw new Error(accessResponse?.message || '店铺 API 授权读取失败');
    const access = accessResponse.data || {};
    const platform = storePlatformCode(row);
    const binding = (access.bindings || []).find((item) => (
      String(item.api_type || '').toLowerCase() === 'marketplace'
      && String(item.platform || platform).toLowerCase() === platform
      && ['active', 'authorized'].includes(String(item.status || '').toLowerCase())
    ));
    if (!binding?.id) throw new Error('当前店铺没有有效的平台授权，请先完成店铺 API 授权。');
    const capabilityResponse = await fetchConnectionCapabilities(binding.id);
    const productCapability = (capabilityResponse?.data?.results || []).find((item) => (
      String(item.capability_code || '').toUpperCase() === 'PRODUCT'
      && item.read_enabled === true
      && item.write_enabled !== true
      && item.status === 'active'
    ));
    if (!productCapability) throw new Error('当前店铺的平台商品只读能力尚未验证或未启用。');
    router.push({ path: '/integrations/sync-jobs', query: {
      platform,
      api_type: 'marketplace',
      resource_type: 'platform_product',
      store_id: String(row.id),
      subject: row?.name || row?.code || '',
    } });
  } catch (error) {
    ElMessage.warning(error?.message || '当前店铺暂不能进入平台商品同步任务。');
  } finally {
    storeProductSyncLoading.value = false;
  }
}

function openStoreSyncIncidents(row) {
  if (!syncViewAccess.value.allowed) {
    ElMessage.warning(syncViewAccess.value.reason || '当前角色无权查看同步异常');
    return;
  }
  router.push({ path: '/integrations/incidents', query: {
    store_id: row?.id ? String(row.id) : '',
    store_name: row?.name || row?.code || '',
  } });
}

async function openRouteStoreContext() {
  if (mappingOnly.value || !route.query.store_id) return;
  const storeId = Number(route.query.store_id);
  if (!Number.isInteger(storeId) || storeId < 1) return;
  try {
    const response = await fetchMasterDataDetail('stores', storeId);
    if (!response?.success) return;
    const row = response.data && typeof response.data === 'object' && !Array.isArray(response.data)
      ? response.data
      : null;
    if (!row) return;
    if (route.query.panel === 'api') openApiAccess(row);
    else openStoreWorkspace(row, route.query.panel === 'mapping' ? 'mapping' : 'profile');
  } catch {
    // The destination page remains usable even when an optional deep-link lookup fails.
  }
}

function openImportDialog() {
  if (!masterDataManageAccess.value.allowed) {
    ElMessage.warning(masterDataManageAccess.value.reason || '当前角色无权导入店铺档案');
    return;
  }
  importOpen.value = true;
}

function downloadTemplate() {
  const headers = ['code', 'name', 'platform_store_name', 'platform', 'country_code', 'currency', 'timezone', 'category', 'operator', 'bd', 'leader', 'is_connected', 'tactical_client', 'status'];
  const blob = new Blob([`\uFEFF${headers.join(',')}\r\n`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'stores-import-template.csv';
  link.click();
  URL.revokeObjectURL(url);
}

function storePayload(payload) {
  const data = { ...payload };
  if (data.platform_site_id === '') data.platform_site_id = null;
  return data;
}

const formFields = computed(() => [
  { key: 'platform_id', label: '平台', type: 'select', required: true, default: platformOptions.value[0]?.value || '', options: platformOptions.value, onChange: applyPlatform },
  { key: 'platform_site_id', label: '平台站点', type: 'select', options: platformSiteOptions.value, onChange: applyPlatformSite, placeholder: '可选；旧店铺可继续使用国家档案' },
  { key: 'code', label: '店铺档案编码', required: true }, { key: 'name', label: '店铺名称', required: true },
  { key: 'platform_store_name', label: '平台店铺名' },
  { key: 'external_store_id', label: '外部店铺 ID' }, { key: 'seller_entity_id', label: '经营主体 ID' },
  { key: 'business_model', label: '业务模式', type: 'select', default: 'other', options: [{ label: '本土店', value: 'local' }, { label: '跨境店', value: 'cross_border' }, { label: '全托管', value: 'full_managed' }, { label: '半托管', value: 'semi_managed' }, { label: '其他', value: 'other' }] },
  { key: 'fulfillment_modes', label: '履约模式', type: 'select', multiple: true, default: [], options: [{ label: '平台履约', value: 'platform_fulfillment' }, { label: '第三方仓', value: 'third_party_warehouse' }, { label: '本地自发货', value: 'local_self_fulfillment' }, { label: '跨境直发', value: 'cross_border_direct' }, { label: '混合', value: 'hybrid' }] },
  { key: 'category_id', label: '类目（大类）', type: 'select', options: categoryOptions.value },
  { key: 'operator_id', label: '负责运营', type: 'select', options: userOptions.value },
  { key: 'bd_id', label: 'BD', type: 'select', options: userOptions.value },
  { key: 'leader_id', label: '组长', type: 'select', options: userOptions.value },
  { key: 'is_connected', label: '是否建联', type: 'select', default: false, options: [{ label: '否', value: false }, { label: '是', value: true }] },
  { key: 'tactical_client', label: '战斧客户端' },
  { key: 'country_code', label: '国家', type: 'select', required: true, options: countryOptions.value, placeholder: '请选择国家档案', onChange: applyCountryDefaults },
  { key: 'currency', label: '币种', required: true, placeholder: '例如 SGD' }, { key: 'settlement_currency', label: '结算币种', placeholder: '例如 SGD' }, { key: 'timezone', label: '时区', required: true, default: 'UTC' },
]);

function results(response) {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function migrationStatus(row) {
  const value = row?.match_status || row?.mapping_status || row?.classification || row?.status || 'unmatched';
  return String(value).toLowerCase();
}

function migrationStatusType(row) {
  return { exact: 'success', ambiguous: 'warning', unmatched: 'info', applied: 'success' }[migrationStatus(row)] || 'info';
}

function migrationCandidates(row) {
  if (Array.isArray(row?.candidates)) return row.candidates;
  if (Array.isArray(row?.candidate_sites)) return row.candidate_sites;
  if (Array.isArray(row?.matches)) return row.matches;
  if (row?.candidate && typeof row.candidate === 'object') return [row.candidate];
  return [];
}

function migrationSiteLabel(row, side) {
  const snapshot = row?.[side] || {};
  if (typeof snapshot === 'string') return snapshot || '-';
  const id = snapshot.platform_site_id ?? snapshot.site_id ?? snapshot.id;
  const name = snapshot.platform_site_name || snapshot.site_name || snapshot.name || '';
  if (name) return id ? `${name} (#${id})` : name;
  return id ? `#${id}` : '-';
}

function migrationConfidence(row) {
  const value = row?.confidence;
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'number') return `${Math.round(value <= 1 ? value * 100 : value)}%`;
  return String(value);
}

function isExactMigrationRow(row) {
  return migrationStatus(row) === 'exact';
}

const exactRows = computed(() => migrationRows.value.filter(isExactMigrationRow));
const selectedMigrationStoreIds = computed(() => selectedMigrationRows.value.map((row) => row.store_id ?? row.id).filter((id) => id !== null && id !== undefined));
const allExactSelected = computed(() => exactRows.value.length > 0 && exactRows.value.every((row) => selectedMigrationStoreIds.value.includes(row.store_id ?? row.id)));
const exactSelectionIndeterminate = computed(() => selectedMigrationStoreIds.value.length > 0 && !allExactSelected.value);
const migrationCounts = computed(() => {
  const count = (status) => {
    const reported = migrationSummary.value?.[status];
    if (reported !== undefined && reported !== null && Number.isFinite(Number(reported))) return Number(reported);
    return migrationRows.value.filter((row) => migrationStatus(row) === status).length;
  };
  return { exact: count('matched') || count('exact'), ambiguous: count('ambiguous'), unmatched: count('unmatched') };
});

function normalizeMigrationRow(row = {}) {
  const status = migrationStatus(row);
  const storeId = row.store_id ?? row.store?.id ?? row.id;
  return {
    ...row,
    store_id: storeId,
    match_status: status,
    status,
    candidates: migrationCandidates(row),
    before: row.before || row.before_data || { platform_site_id: row.before_platform_site_id ?? null },
    after: row.after || row.after_data || { platform_site_id: row.after_platform_site_id ?? null },
  };
}

function resetMigrationSelection() {
  selectedMigrationRows.value = [];
  migrationTable.value?.clearSelection?.();
}

function handleMigrationSelection(rows) {
  selectedMigrationRows.value = rows.filter(isExactMigrationRow);
}

function toggleAllExact(checked) {
  if (migrationTable.value?.toggleRowSelection) {
    exactRows.value.forEach((row) => migrationTable.value.toggleRowSelection(row, checked));
  } else {
    selectedMigrationRows.value = checked ? exactRows.value.slice() : [];
  }
}

async function loadMigrationPreview() {
  migrationLoading.value = true;
  migrationError.value = '';
  try {
    const response = await fetchPlatformSiteMigrationPreview();
    if (!response?.success) {
      migrationRows.value = [];
      migrationSummary.value = {};
      migrationError.value = response?.message || '站点映射预览加载失败';
      return;
    }
    const payload = response.data;
    const rows = Array.isArray(payload)
      ? payload
      : (payload?.rows || payload?.results || payload?.items || []);
    migrationRows.value = rows.map(normalizeMigrationRow);
    migrationSummary.value = Array.isArray(payload) ? {} : payload || {};
    resetMigrationSelection();
  } catch (error) {
    migrationRows.value = [];
    migrationSummary.value = {};
    migrationError.value = error?.message || '站点映射预览加载失败';
  } finally {
    migrationLoading.value = false;
  }
}

async function openMigrationPreview() {
  migrationOpen.value = true;
  await loadMigrationPreview();
}

function migrationIdempotencyKey() {
  return `platform-site-migration-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

async function confirmMigration() {
  if (!migrationManageAccess.value.allowed) {
    ElMessage.warning(migrationManageAccess.value.reason || '当前角色无权应用站点映射');
    return;
  }
  const storeIds = selectedMigrationStoreIds.value.filter((id) => isExactMigrationRow(migrationRows.value.find((row) => (row.store_id ?? row.id) === id)));
  if (!storeIds.length) {
    ElMessage.warning('请先选择至少一条 exact 映射');
    return;
  }
  try {
    await ElMessageBox.confirm(
      `请再次确认：仅应用 ${storeIds.length} 条当前 exact 映射。后端会重新计算并跳过已有关联、ambiguous 或 unmatched 店铺；不会创建站点或覆盖已有站点。`,
      '二次确认站点映射',
      { type: 'warning', confirmButtonText: '确认应用', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }

  migrationApplying.value = true;
  try {
    const payload = { confirmed: true, store_ids: storeIds, idempotency_key: migrationIdempotencyKey() };
    const response = await applyPlatformSiteMigration(payload);
    if (!response?.success) {
      ElMessage.error(response?.message || '站点映射应用失败');
      return;
    }
    const result = response.data || {};
    ElMessage.success(`站点映射完成：应用 ${result.applied ?? storeIds.length} 条`);
    await resourcePage.value?.loadData?.();
    await loadMigrationPreview();
  } catch (error) {
    ElMessage.error(error?.message || '站点映射应用失败');
  } finally {
    migrationApplying.value = false;
  }
}

async function loadReferenceOptions() {
  const [platformResponse, platformSiteResponse, siteResponse, categoryResponse, usersResponse] = await Promise.all([
    fetchPlatforms({ status: 'active', page: 1, page_size: 100 }), fetchPlatformSites({ page: 1, page_size: 100, status: 'active' }), fetchCountrySites({ status: 'active', page: 1, page_size: 100 }),
    fetchProductCategories({ page: 1, page_size: 100, level: 1 }), fetchUsers({ page: 1, page_size: 100, status: 'active' }),
  ]);
  const platforms = results(platformResponse); platformSites.value = results(platformSiteResponse); const sites = results(siteResponse); const categories = results(categoryResponse); const users = results(usersResponse);
  platformOptions.value = platforms
    .filter((row) => !String(row.platform_type || '').startsWith('warehouse_'))
    .map((item) => ({ label: `${item.name || item.code} · ${item.code}`, value: item.id }));
  platformSiteOptions.value = platformSites.value.map(toPlatformSiteOption);
  countryOptions.value = sites.map((item) => ({ label: `${item.name || item.code} · ${String(item.country_code || '').toUpperCase()}`, value: String(item.country_code || '').toUpperCase(), currency: String(item.currency || '').trim().toUpperCase(), timezone: String(item.timezone || '').trim() })).filter((item) => item.value);
  categoryOptions.value = categories.filter((item) => item.level === 1 && item.is_active !== false).map((item) => ({ label: `${item.code} · ${item.name}`, value: item.id }));
  userOptions.value = users.filter((item) => item.is_active !== false).map((item) => ({ label: item.full_name || item.username, value: item.id }));
}

async function openCapabilityMatrix(row) {
  if (!storeViewAccess.value.allowed) {
    ElMessage.warning(storeViewAccess.value.reason || '当前角色无权查看店铺连接能力');
    return;
  }
  selectedStore.value = row;
  capabilityOpen.value = true;
  capabilityLoading.value = true;
  capabilityRows.value = [];
  capabilitySuggestions.value = [];
  authorizationOptions.value = [];
  selectedAuthorizationId.value = null;
  try {
    const response = await fetchStoreAuthorizations({ store_id: row.id, page: 1, page_size: 100 });
    if (!response?.success) throw new Error(response?.message || '授权连接加载失败');
    authorizationOptions.value = results(response);
    selectedAuthorizationId.value = authorizationOptions.value[0]?.id || null;
    if (selectedAuthorizationId.value) await loadCapabilities(selectedAuthorizationId.value);
  } catch (error) {
    ElMessage.error(error?.message || '授权连接加载失败');
  } finally {
    capabilityLoading.value = false;
  }
}

async function loadCapabilities(authorizationId) {
  if (!storeViewAccess.value.allowed || !authorizationId) {
    capabilityRows.value = [];
    capabilitySuggestions.value = [];
    return;
  }
  capabilityLoading.value = true;
  capabilitySuggestions.value = [];
  try {
    const response = await fetchConnectionCapabilities(authorizationId);
    if (!response?.success) throw new Error(response?.message || '能力矩阵加载失败');
    const existing = new Map((response.data?.results || []).map((item) => [item.capability_code, item]));
    const codes = response.data?.available_codes || capabilityCodes;
    capabilitySuggestions.value = Array.isArray(response.data?.suggestions) ? response.data.suggestions : [];
    capabilityRows.value = codes.map((code) => ({ capability_code: code, read_enabled: false, write_enabled: false, sync_mode: 'manual', source_priority: 100, status: 'disabled', ...(existing.get(code) || {}), write_enabled: false }));
  } catch (error) {
    capabilityRows.value = [];
    ElMessage.error(error?.message || '能力矩阵加载失败');
  } finally {
    capabilityLoading.value = false;
  }
}

function applyCapabilitySuggestions() {
  if (!capabilitySuggestions.value.length) return;
  const suggestions = new Map(capabilitySuggestions.value.map((item) => [item.capability_code, item]));
  capabilityRows.value = capabilityRows.value.map((row) => {
    const suggestion = suggestions.get(row.capability_code);
    if (!suggestion) return row;
    return {
      ...row,
      read_enabled: Boolean(suggestion.read_enabled),
      write_enabled: false,
      sync_mode: suggestion.sync_mode || row.sync_mode,
      source_priority: suggestion.source_priority ?? row.source_priority,
      status: suggestion.status || row.status,
      suggestion_confidence: suggestion.confidence,
      suggestion_scope_verification: suggestion.scope_verification,
      suggestion_evidence: suggestion.evidence,
      suggestion_reason: suggestion.reason,
    };
  });
  ElMessage.info('建议已载入本地表单；请复核 scopes/evidence 后点击“确认保存”。');
}

async function saveCapabilities() {
  if (!storeAuthorizeAccess.value.allowed) {
    ElMessage.warning(storeAuthorizeAccess.value.reason || '当前角色无权保存能力矩阵');
    return;
  }
  if (!selectedAuthorizationId.value) {
    ElMessage.warning('请先选择授权连接');
    return;
  }
  if (!['active', 'authorized'].includes(selectedAuthorization.value?.status)) {
    ElMessage.warning('只有有效授权（active/authorized）可以保存能力矩阵');
    return;
  }
  try { await ElMessageBox.confirm('仅保存读取能力和同步配置；平台写入能力继续保持关闭。是否继续？', '确认能力配置', { type: 'warning' }); } catch { return; }
  capabilitySaving.value = true;
  try {
    const payload = capabilityRows.value.map(({ capability_code, read_enabled, sync_mode, source_priority, status }) => ({ capability_code, read_enabled, write_enabled: false, sync_mode, source_priority, status }));
    const response = await updateConnectionCapabilities(selectedAuthorizationId.value, payload);
    if (!response?.success) throw new Error(response?.message || '能力矩阵保存失败');
    ElMessage.success('能力矩阵已保存，写入能力仍保持关闭。');
    await loadCapabilities(selectedAuthorizationId.value);
  } catch (error) {
    ElMessage.error(error?.message || '能力矩阵保存失败');
  } finally {
    capabilitySaving.value = false;
  }
}

function onFileChange(uploadFile) { importFile.value = uploadFile?.raw || null; }
async function submitImport() {
  if (!masterDataManageAccess.value.allowed) {
    ElMessage.warning(masterDataManageAccess.value.reason || '当前角色无权导入店铺档案');
    return;
  }
  if (!importFile.value || importing.value) return;
  importing.value = true;
  try {
    const response = await importStores(importFile.value);
    if (!response?.success) throw new Error(response?.message || '导入失败');
    const result = response.data || {};
    if (result.errors?.length) throw new Error(`导入失败：${result.errors[0].message}`);
    ElMessage.success(`导入完成：新增 ${result.created || 0} 条，更新 ${result.updated || 0} 条`);
    importOpen.value = false; importFile.value = null;
    await resourcePage.value?.loadData?.();
  } catch (error) {
    ElMessage.error(error?.message || '导入失败');
  } finally {
    importing.value = false;
  }
}

onMounted(async () => {
  if (mappingOnly.value) return;
  await loadReferenceOptions();
  await openRouteStoreContext();
});
</script>

<style scoped>
.store-scope-tree {
  max-height: calc(100vh - 180px);
  overflow-y: auto;
  padding: 14px 10px 12px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}
.store-scope-tree__heading { padding: 2px 10px 12px; }
.store-scope-tree__heading strong,
.store-scope-tree__heading small { display: block; }
.store-scope-tree__heading strong { color: #172033; font-size: 15px; }
.store-scope-tree__heading small { margin-top: 4px; color: #64748b; font-size: 12px; }
.store-scope-tree button { font: inherit; cursor: pointer; }
.store-scope-tree button:focus-visible { outline: 2px solid #409eff; outline-offset: 2px; }
.store-scope-tree__all,
.store-scope-tree__platform,
.store-scope-tree__country {
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #334155;
  text-align: left;
}
.store-scope-tree__all { margin-bottom: 8px; font-weight: 600; }
.store-scope-tree__platform-line { display: flex; align-items: center; }
.store-scope-tree__platform { min-width: 0; font-weight: 600; }
.store-scope-tree__platform-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.store-scope-tree__toggle {
  flex: 0 0 28px;
  height: 32px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #64748b;
}
.store-scope-tree__countries { margin: 1px 0 9px 10px; border-left: 1px solid #e5eaf0; padding-left: 8px; }
.store-scope-tree__country { min-height: 34px; font-size: 13px; }
.store-scope-tree__country > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.store-scope-tree__all:hover,
.store-scope-tree__platform:hover,
.store-scope-tree__country:hover,
.store-scope-tree__toggle:hover { background: #f3f7fc; }
.store-scope-tree__all.is-selected,
.store-scope-tree__platform.is-selected,
.store-scope-tree__country.is-selected { background: #ecf4ff; color: #1b5fbf; }
.store-scope-tree__count { flex-shrink: 0; color: #64748b; font-size: 12px; font-weight: 500; }
.store-scope-tree__empty,
.store-scope-tree__note { margin: 10px; color: #77869b; font-size: 12px; line-height: 1.5; }
.store-scope-tree__note { padding-top: 12px; border-top: 1px solid #edf0f4; }
.store-scope-summary {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  padding: 5px 0 12px;
  border-bottom: 1px solid #e5eaf0;
}
.store-scope-summary span { display: block; margin-bottom: 5px; color: #64748b; font-size: 12px; }
.store-scope-summary strong { color: #172033; font-size: 18px; }
.store-scope-summary p { margin: 0; color: #64748b; font-size: 13px; white-space: nowrap; }
.store-scope-summary p strong { color: #1b5fbf; font-size: 16px; }
.store-cell { display: flex; min-width: 0; flex-direction: column; gap: 4px; line-height: 1.35; }
.store-cell strong { overflow: hidden; color: #24334f; font-size: 14px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.store-cell span,
.store-cell small { overflow: hidden; color: #64748b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.store-page-actions__arrow { margin-left: 6px; }
.migration-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 16px 0 12px;
}

.migration-counts,
.migration-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.migration-counts span {
  color: #64748b;
  font-size: 13px;
}

.migration-counts strong {
  margin-left: 4px;
  color: #172033;
  font-size: 16px;
}

.migration-selection-note {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.candidate-list {
  display: grid;
  gap: 3px;
}

.candidate-list span {
  display: block;
}

.candidate-list small,
.resource-table small {
  color: #64748b;
}

.muted {
  color: #94a3b8;
}

.store-workspace-tabs {
  min-height: 520px;
}

.workspace-note {
  margin: 14px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.workspace-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-top: 16px;
}

.workspace-summary-grid > div {
  min-width: 0;
  padding: 14px;
  border: 1px solid #d9e2ef;
  border-radius: 8px;
  background: #f8fafc;
}

.workspace-summary-grid span,
.workspace-summary-grid strong {
  display: block;
}

.workspace-summary-grid span {
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.workspace-summary-grid strong {
  color: #27364a;
  overflow-wrap: anywhere;
}

.workspace-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.workspace-actions--stack {
  align-items: flex-start;
  flex-direction: column;
}

.workspace-descriptions {
  margin-top: 16px;
}

@media (max-width: 1199px) {
  .store-scope-tree { max-height: 320px; }
}
@media (max-width: 760px) {
  .store-scope-tree { max-height: 300px; }
  .store-scope-summary { align-items: flex-start; flex-direction: column; gap: 6px; }
  .migration-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .workspace-summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
