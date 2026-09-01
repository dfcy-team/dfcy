<template>
  <section class="integration-workspace">
    <header class="workspace-header">
      <div>
        <h1 class="page-title">{{ contract.title }}</h1>
        <p>{{ contract.note }}</p>
      </div>
      <div class="header-actions">
        <el-tag type="success" effect="plain">SaaS MySQL 查询正常</el-tag>
        <template v-if="mode === 'configs'">
          <el-button @click="auditVisible = !auditVisible">{{ auditVisible ? '收起变更审计' : '查看变更审计' }}</el-button>
          <el-button class="handoff-action" @click="openCreateConfig">新建接入配置</el-button>
        </template>
        <template v-else-if="mode === 'sync-jobs'">
          <el-button @click="dueDialog = true">处理到期任务</el-button>
          <el-button @click="reconcileDialog = true">补齐缺失任务</el-button>
          <el-button class="handoff-action" @click="openCreateJob()">新增同步任务</el-button>
        </template>
        <el-button v-else :loading="loading" @click="load">刷新运行状态</el-button>
      </div>
    </header>

    <section class="flow-card" aria-label="API 接入进度">
      <ol class="flow-steps">
        <li v-for="(step, index) in flowSteps" :key="step.label" :class="{ complete: step.value > 0 }">
          <span>{{ index + 1 }}</span>
          <div><strong>{{ step.label }}</strong><small>{{ step.text }}</small></div>
        </li>
      </ol>
      <dl class="flow-metrics">
        <div v-for="metric in metrics" :key="metric.label"><dt>{{ metric.label }}</dt><dd>{{ number(metric.value) }}</dd></div>
      </dl>
    </section>

    <el-alert
      v-if="auditVisible"
      title="变更审计仍按租户、配置和操作人独立留痕；本页不展示凭据明文。"
      type="info"
      :closable="false"
      show-icon
    />

    <section v-if="mode !== 'configs'" class="health-card">
      <header>
        <div><h2>同步运行健康</h2><p>聚合到期队列、失败退避、并发锁和系统调度心跳，不读取或展示凭据明文。</p></div>
        <el-tag :type="healthAttention ? 'danger' : 'success'">{{ healthStatusText }}</el-tag>
      </header>
      <dl>
        <div><dt>到期模拟任务</dt><dd>{{ summary.due_job_count || 0 }}</dd></div>
        <div><dt>生产待确认</dt><dd>{{ summary.live_confirmation_job_count || 0 }}</dd></div>
        <div><dt>退避等待</dt><dd>{{ summary.retry_waiting_job_count || 0 }}</dd></div>
        <div><dt>重试已暂停</dt><dd>{{ summary.retry_exhausted_job_count || 0 }}</dd></div>
        <div><dt>超时运行锁</dt><dd>{{ summary.stale_running_job_count || 0 }}</dd></div>
        <div><dt>近 24 小时失败</dt><dd>{{ summary.failed_run_count || 0 }}</dd></div>
      </dl>
      <footer>
        <strong>系统调度：{{ schedulerText }}</strong>
        <nav aria-label="同步异常快捷入口">
          <button type="button" :aria-expanded="schedulerHistoryOpen" aria-controls="scheduler-audit-history" @click="toggleSchedulerHistory">{{ schedulerHistoryOpen ? '收起调度记录' : '查看调度记录' }}</button>
          <router-link to="/integrations/sync-jobs">查看任务队列</router-link>
          <router-link :to="{ path: '/integrations/sync-runs', query: { status: 'failed' } }">查看失败运行</router-link>
          <router-link to="/alerts/business">查看经营预警</router-link>
        </nav>
      </footer>
      <section v-if="schedulerHistoryOpen" id="scheduler-audit-history" class="scheduler-history" aria-label="最近调度记录">
        <header><div><strong>最近调度记录</strong><p>仅展示最近 20 次已认证调用的脱敏运行摘要。</p></div><span>{{ number(schedulerHistory.length) }} 条</span></header>
        <el-table v-if="schedulerHistory.length" :data="schedulerHistory" size="small">
          <el-table-column label="调用时间" min-width="165"><template #default="{ row }">{{ date(row.invoked_at) }}</template></el-table-column>
          <el-table-column label="结果" min-width="90"><template #default="{ row }"><status-tag :value="row.result" /></template></el-table-column>
          <el-table-column label="到期" prop="due_count" min-width="70" />
          <el-table-column label="已处理" prop="processed_count" min-width="75" />
          <el-table-column label="跳过" prop="skipped_count" min-width="70" />
          <el-table-column label="失败" prop="failed_count" min-width="70" />
          <el-table-column label="生产待确认" prop="live_confirmation_count" min-width="100" />
          <el-table-column label="耗时" min-width="100"><template #default="{ row }">{{ duration(row.duration_ms) }}</template></el-table-column>
        </el-table>
        <p v-else class="scheduler-history-empty">暂无调度调用记录。配置调度密钥并由系统计划任务成功调用后，这里会显示执行摘要。</p>
      </section>
    </section>

    <el-alert :title="contract.risk" type="warning" :closable="false" show-icon />

    <nav v-if="mode === 'sync-jobs'" class="job-tabs" aria-label="同步任务状态分组">
      <button
        v-for="tab in jobTabs"
        :key="tab.value"
        type="button"
        :class="{ active: query.job_state === tab.value }"
        @click="setJobState(tab.value)"
      >{{ tab.label }}<span v-if="tab.count !== undefined">{{ number(tab.count) }}</span></button>
    </nav>

    <el-form class="filter-card" label-position="top" @submit.prevent="applyFilters">
      <el-form-item v-for="filter in contract.filters" :key="filter.key" :label="filter.label">
        <el-input
          v-if="filter.type === 'text'"
          v-model="draft[filter.key]"
          clearable
          :placeholder="filter.placeholder"
        />
        <el-date-picker
          v-else-if="filter.type === 'date'"
          v-model="draft[filter.key]"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="年/月/日"
        />
        <el-select v-else v-model="draft[filter.key]" clearable :placeholder="`全部${filter.label}`">
          <el-option v-for="option in filterOptions(filter.key)" :key="option" :label="label(filter.key, option)" :value="option" />
        </el-select>
      </el-form-item>
      <div class="filter-actions"><el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button></div>
    </el-form>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <section class="table-card">
      <header><h2>{{ contract.title }}</h2><strong>{{ number(pagination.total) }} 条</strong></header>
      <div v-if="mode === 'sync-jobs' && selectedJobs.length" class="batch-bar">
        <strong>已选择 {{ selectedJobs.length }} 个任务</strong>
        <div><el-button size="small" @click="batchToggle(true)">批量启用</el-button><el-button size="small" @click="batchToggle(false)">批量停用</el-button><el-button size="small" @click="batchRunMock">运行模拟任务</el-button></div>
      </div>
      <el-table v-loading="loading" :data="rows" max-height="610" :empty-text="contract.empty" row-key="id" @selection-change="selectedJobs = $event">
        <el-table-column v-if="mode === 'sync-jobs'" type="selection" width="46" />

        <template v-if="mode === 'configs'">
          <el-table-column label="配置名称" prop="account_alias" min-width="190" />
          <el-table-column label="平台" min-width="110"><template #default="{ row }"><strong>{{ label('platform', row.platform) }}</strong></template></el-table-column>
          <el-table-column label="API 类型" min-width="110"><template #default="{ row }">{{ label('api_type', row.api_type) }}</template></el-table-column>
          <el-table-column label="环境" min-width="90"><template #default="{ row }">{{ label('environment', row.environment) }}</template></el-table-column>
          <el-table-column label="适用站点" min-width="120"><template #default="{ row }">{{ (row.regions || []).join('、') || '—' }}</template></el-table-column>
          <el-table-column label="状态" min-width="100"><template #default="{ row }"><status-tag :value="row.status" /></template></el-table-column>
          <el-table-column label="凭据引用" min-width="110"><template #default="{ row }"><status-tag :value="row.credential_status" /></template></el-table-column>
          <el-table-column label="凭据指纹" prop="credential_fingerprint" min-width="150" />
          <el-table-column label="任务引用" prop="reference_count" min-width="90" />
          <el-table-column label="最近引用检查" min-width="165"><template #default="{ row }">{{ date(row.last_verified_at) }}</template></el-table-column>
          <el-table-column label="操作" fixed="right" min-width="390">
            <template #default="{ row }">
              <el-button link type="primary" @click="openCredential(row)">维护凭据</el-button>
              <el-button link type="primary" @click="verify(row)">检查凭据</el-button>
              <el-button link type="primary" @click="checkConsistency(row)">本地一致性检查</el-button>
              <el-button link type="primary" @click="checkReadonly(row)">平台只读检查</el-button>
              <el-button v-if="row.status !== 'disabled'" link type="danger" @click="disableConfig(row)">禁用</el-button>
              <el-button v-else link type="danger" :loading="deletingConfigId === row.id" @click="deleteConfig(row)">删除</el-button>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="mode === 'sync-jobs'">
          <el-table-column label="店铺/仓库" min-width="190"><template #default="{ row }"><strong>{{ row.subject_name }}</strong><small class="cell-sub">{{ row.subject_code || '未绑定' }}</small></template></el-table-column>
          <el-table-column label="平台/站点" min-width="130"><template #default="{ row }"><strong>{{ label('platform', row.platform) }}</strong><small class="cell-sub">{{ row.region || '—' }} · {{ label('api_type', row.api_type) }}</small></template></el-table-column>
          <el-table-column label="同步资源" min-width="120"><template #default="{ row }">{{ label('resource_type', row.resource_type) }}</template></el-table-column>
          <el-table-column label="运行策略" min-width="180"><template #default="{ row }"><strong>{{ scheduleDescription(row) }}</strong><small class="cell-sub">{{ label('execution_mode', row.execution_mode) }} · {{ row.next_run_at ? `下次 ${date(row.next_run_at)}` : label('schedule_state', row.schedule_state) }}</small></template></el-table-column>
          <el-table-column label="任务状态" min-width="150"><template #default="{ row }"><status-tag :value="row.health_state" /><small class="cell-sub">{{ row.blocked_reason || label('schedule_state', row.schedule_state) }}</small></template></el-table-column>
          <el-table-column label="最近运行" min-width="180"><template #default="{ row }"><strong>{{ row.latest_run_status ? label('status', row.latest_run_status) : '尚未运行' }}</strong><small class="cell-sub">{{ row.latest_started_at ? date(row.latest_started_at) : '等待首次执行' }}</small></template></el-table-column>
          <el-table-column label="操作" fixed="right" min-width="180"><template #default="{ row }"><el-button link type="primary" :disabled="!rowRunAccess(row).allowed" :title="rowRunAccess(row).reason" @click="runJob(row)">{{ row.execution_mode === 'live_readonly' ? '确认并运行' : '立即运行' }}</el-button><el-button link type="primary" @click="openJobDetail(row)">详情</el-button><el-dropdown trigger="click" @command="command => handleJobCommand(command, row)"><el-button link type="primary">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="detail">查看任务详情</el-dropdown-item><el-dropdown-item command="edit">编辑同步策略</el-dropdown-item><el-dropdown-item command="clone">复制配置新建</el-dropdown-item><el-dropdown-item command="runs">查看运行记录</el-dropdown-item><el-dropdown-item command="business">查看业务数据</el-dropdown-item><el-dropdown-item command="toggle" :disabled="!row.is_enabled && Boolean(row.blocked_reason)">{{ row.is_enabled ? '停用任务' : (row.blocked_reason ? '暂不可启用' : '启用任务') }}</el-dropdown-item><el-dropdown-item v-if="!row.is_enabled && row.schedule_state !== 'running'" command="delete" divided>删除任务</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
        </template>

        <template v-else>
          <el-table-column label="执行 ID" prop="run_id" min-width="270" />
          <el-table-column label="店铺/仓库" min-width="190"><template #default="{ row }"><strong>{{ row.subject_name }}</strong><small class="cell-sub">{{ row.subject_code || '历史未绑定' }}</small></template></el-table-column>
          <el-table-column label="平台" min-width="110"><template #default="{ row }"><strong>{{ label('platform', row.platform) }}</strong></template></el-table-column>
          <el-table-column label="API 类型" min-width="105"><template #default="{ row }">{{ label('api_type', row.api_type) }}</template></el-table-column>
          <el-table-column label="资源类型" min-width="120"><template #default="{ row }">{{ label('resource_type', row.resource_type) }}</template></el-table-column>
          <el-table-column label="SaaS 数据目标" min-width="190"><template #default="{ row }"><el-link type="primary">{{ row.data_destination }}</el-link><small class="cell-sub">{{ row.data_table }}</small></template></el-table-column>
          <el-table-column label="运行模式" min-width="110"><template #default="{ row }"><status-tag :value="row.execution_mode" /></template></el-table-column>
          <el-table-column label="状态" min-width="90"><template #default="{ row }"><status-tag :value="row.status" /></template></el-table-column>
          <el-table-column label="开始时间" min-width="170"><template #default="{ row }">{{ date(row.started_at) }}</template></el-table-column>
          <el-table-column label="耗时" min-width="75"><template #default="{ row }">{{ row.duration_seconds === null ? '—' : `${row.duration_seconds}s` }}</template></el-table-column>
          <el-table-column label="抓取" prop="fetched_count" min-width="70" />
          <el-table-column label="新增" prop="created_count" min-width="70" />
          <el-table-column label="更新" prop="updated_count" min-width="70" />
          <el-table-column label="跳过" prop="skipped_count" min-width="70" />
          <el-table-column label="失败" prop="failed_count" min-width="70" />
          <el-table-column label="重试" min-width="80"><template #default="{ row }">{{ row.retry_count ? `第 ${row.retry_count} 次` : '首次' }}</template></el-table-column>
          <el-table-column label="脱敏错误" min-width="170"><template #default="{ row }">{{ row.masked_error_message || '—' }}</template></el-table-column>
          <el-table-column label="操作" fixed="right" min-width="170"><template #default="{ row }"><el-button link type="primary" @click="openRunDetail(row)">查看详情</el-button><el-button v-if="row.status === 'failed' && row.execution_mode === 'simulation'" link type="primary" :disabled="row.retry_count >= row.max_retry_count" @click="retryRun(row)">{{ row.retry_count >= row.max_retry_count ? '已达重试上限' : '重试失败任务' }}</el-button><el-button v-if="row.status === 'failed' && row.execution_mode === 'live_readonly'" link type="primary" @click="returnToJob(row)">返回任务确认重跑</el-button></template></el-table-column>
        </template>
      </el-table>
      <footer class="table-footer"><span>第 {{ pageStart }}–{{ pageEnd }} 条，共 {{ number(pagination.total) }} 条</span><el-pagination v-model:current-page="page" background layout="prev, pager, next" :page-size="pagination.page_size || 50" :total="pagination.total || 0" @current-change="load" /></footer>
    </section>

    <el-dialog v-model="configDialog" title="新建接入配置" width="min(760px, 92vw)">
      <p class="dialog-note">仅创建开发者配置引用，不在这里绑定店铺或仓库 Token</p>
      <el-form :model="configForm" label-position="top" class="dialog-grid">
        <el-form-item label="配置名称 *"><el-input v-model="configForm.account_alias" placeholder="例如 Shopee 商城生产配置" /></el-form-item>
        <el-form-item label="平台 *"><el-select v-model="configForm.platform" placeholder="请选择平台" @change="normalizeConfigApiType"><el-option v-for="platform in referencePlatforms" :key="platform.id || platform.value" :label="platform.label" :value="platform.value" :disabled="!platform.enabled" /></el-select></el-form-item>
        <el-form-item label="API 类型 *"><el-select v-model="configForm.api_type" placeholder="请选择 API 类型"><el-option v-for="option in configApiTypeOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item>
        <el-form-item label="环境 *"><el-select v-model="configForm.environment" placeholder="请选择环境"><el-option v-for="option in referenceEnvironments" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item>
        <el-form-item label="适用站点 *" class="wide">
          <el-select v-model="configForm.regions" multiple filterable collapse-tags collapse-tags-tooltip :max-collapse-tags="3" placeholder="请选择适用站点">
            <el-option v-for="region in configRegionOptions" :key="region.country_code" :label="region.label" :value="region.country_code" class="region-option">
              <el-checkbox
                :model-value="configForm.regions.includes(region.country_code)"
                tabindex="-1"
                @click.stop
                @change="setConfigRegion(region.country_code, $event)"
              >{{ region.label }}</el-checkbox>
            </el-option>
          </el-select>
          <small>已选择 {{ configForm.regions.length }} 个站点；可连续勾选多个国家，选项按平台可用范围联动。</small>
        </el-form-item>
      </el-form>
      <el-alert title="平台来自平台档案；服务端仍会校验平台能力、回调地址与可用 API 类型。" type="info" :closable="false" show-icon />
      <template #footer><el-button @click="configDialog = false">取消</el-button><el-button class="handoff-action" @click="prepareConfig">创建配置</el-button></template>
    </el-dialog>

    <el-dialog v-model="dueDialog" title="处理到期同步任务" width="min(700px, 92vw)">
      <p class="dialog-note">领取已到计划时间且未被其他执行器锁定的任务</p>
      <summary-grid :items="dueItems" />
      <el-alert title="当前没有需要领取的到期任务。" type="success" :closable="false" />
      <p class="safe-note">确认后只执行本地模拟任务。生产只读任务会继续保持待处理，必须回到任务行单独确认。</p>
      <template #footer><el-button @click="dueDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="reconcileDialog" title="补齐缺失同步任务" width="min(700px, 92vw)">
      <p class="dialog-note">按当前有效商城授权和仓库库存授权生成缺失任务</p>
      <summary-grid :items="reconcileItems" />
      <el-alert title="当前有效授权对应的同步任务已完整，无需补齐。" type="success" :closable="false" />
      <p class="safe-note">只创建缺失任务，不修改现有任务。新任务默认停用、手动调度、本地模拟。</p>
      <template #footer><el-button @click="reconcileDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="createJobDialog" width="min(920px, 92vw)">
      <template #header>
        <div class="dialog-heading">
          <strong>{{ creatingJobTemplate ? '复制策略并新建任务' : '新增同步任务' }}</strong>
          <small>可一次选择多个授权主体和资源；系统会逐项校验并排除重复任务</small>
        </div>
      </template>
      <div class="empty-job"><strong>没有可新增的同步任务</strong><p>已授权主体的必需资源任务均已存在，或尚未完成商城/库存授权和开发者凭据配置。</p><div><el-button class="handoff-action" @click="go('/master-data/stores')">检查店铺授权</el-button><el-button @click="go('/master-data/warehouses')">检查仓库授权</el-button></div></div>
      <template #footer><el-button @click="closeCreateJob">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="credentialDialog" title="填写/修改开发者凭据" width="min(760px, 92vw)" :close-on-click-modal="false">
      <p class="dialog-note">{{ activeConfig?.account_alias }} · {{ label('platform', activeConfig?.platform) }}</p>
      <el-alert title="仅填写需要修改的字段；留空将保留数据库现值或服务器环境变量。密钥提交后不会再次显示。" type="info" :closable="false" />
      <el-form :model="credentialForm" label-position="top" class="dialog-grid credential-grid">
        <template v-if="activeConfig?.platform === 'lazada'">
          <el-form-item label="App Key"><el-input v-model="credentialForm.app_key" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="App Secret"><el-input v-model="credentialForm.app_secret" type="password" autocomplete="new-password" placeholder="输入新的 App Secret" /></el-form-item>
          <el-form-item label="授权回调地址" class="wide"><el-input v-model="credentialForm.redirect_uri" type="url" maxlength="500" placeholder="https://your-domain.example/api/internal/integrations/store-authorizations/oauth/callback/lazada/" /></el-form-item>
        </template>
        <template v-else-if="activeConfig?.platform === 'shopee'">
          <el-form-item label="Partner ID"><el-input v-model="credentialForm.partner_id" inputmode="numeric" maxlength="32" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="Partner Key"><el-input v-model="credentialForm.partner_key" type="password" autocomplete="new-password" placeholder="输入新的 Partner Key" /></el-form-item>
          <el-form-item label="授权回调地址" class="wide"><el-input v-model="credentialForm.redirect_uri" type="url" maxlength="500" placeholder="https://your-domain.example/api/internal/integrations/store-authorizations/oauth/callback/shopee/" /></el-form-item>
        </template>
        <template v-else-if="activeConfig?.platform === 'tiktok' && activeConfig?.api_type === 'advertising'">
          <el-form-item label="App ID"><el-input v-model="credentialForm.ads_app_id" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="Secret"><el-input v-model="credentialForm.ads_secret" type="password" autocomplete="new-password" placeholder="输入新的 Secret" /></el-form-item>
          <el-form-item label="广告授权回调地址" class="wide"><el-input v-model="credentialForm.redirect_uri" type="url" maxlength="500" placeholder="https://dingfengchuangyu.com/tiktok-ads/callback" /></el-form-item>
        </template>
        <template v-else-if="activeConfig?.platform === 'tiktok'">
          <el-form-item label="App Key"><el-input v-model="credentialForm.app_key" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="Service ID"><el-input v-model="credentialForm.service_id" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="App Secret" class="wide"><el-input v-model="credentialForm.app_secret" type="password" autocomplete="new-password" placeholder="输入新的 App Secret" /></el-form-item>
        </template>
        <template v-else-if="activeConfig?.platform === 'jifeng_wms'">
          <el-form-item label="API Base URL" class="wide"><el-input v-model="credentialForm.api_base_url" type="url" maxlength="500" placeholder="https://api.example.com" /></el-form-item>
          <el-form-item label="Domain"><el-input v-model="credentialForm.domain" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="Client ID"><el-input v-model="credentialForm.client_id" maxlength="255" placeholder="留空保留现值" /></el-form-item>
          <el-form-item label="Client Secret" class="wide"><el-input v-model="credentialForm.client_secret" type="password" autocomplete="new-password" placeholder="输入新的 Client Secret" /></el-form-item>
        </template>
      </el-form>
      <p class="safe-note">密文由服务端安全保管；同表只记录引用、指纹和审计信息，接口不会返回明文。店铺或仓库 Token 仍在对应基础档案授权中维护。</p>
      <template #footer><el-button @click="credentialDialog = false">取消</el-button><el-button class="handoff-action" :loading="operating" @click="saveCredential">加密保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="jobDetailDialog" width="min(700px, 94vw)" class="job-detail-dialog">
      <template #header>
        <div v-if="activeJob" class="job-detail-heading">
          <strong>同步任务详情</strong>
          <small>{{ activeJob.subject_name }} · {{ label('resource_type', activeJob.resource_type) }} · 任务 #{{ activeJob.id }}</small>
        </div>
      </template>
      <template v-if="activeJob">
        <div class="job-detail-status">
          <status-tag :value="activeJob.health_state" />
          <span>{{ label('schedule_state', activeJob.schedule_state) }}</span>
        </div>
        <dl class="job-detail-grid">
          <div v-for="item in jobDetailItems" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>
        <el-alert v-if="activeJob.blocked_reason" :title="activeJob.blocked_reason" type="warning" :closable="false" show-icon />
      </template>
      <template #footer>
        <el-button @click="jobDetailDialog = false">关闭</el-button>
        <el-button @click="viewJobRuns(activeJob)">查看运行记录</el-button>
        <el-button @click="viewJobBusiness(activeJob)">查看业务数据</el-button>
        <el-button class="handoff-action" :disabled="activeJob?.schedule_state === 'running'" @click="openJobEditor(activeJob)">编辑策略</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="jobEditDialog" width="min(760px, 94vw)" :close-on-click-modal="false">
      <template #header>
        <div v-if="activeJob" class="dialog-heading"><strong>编辑同步策略</strong><small>{{ activeJob.subject_name }} · {{ label('resource_type', activeJob.resource_type) }}</small></div>
      </template>
      <el-form :model="jobForm" label-position="top" class="job-policy-form">
        <fieldset class="job-policy-section">
          <legend>调度与运行</legend>
          <div class="dialog-grid">
            <el-form-item label="调度方式 *"><el-select v-model="jobForm.schedule_type"><el-option label="手动运行" value="manual" /><el-option label="每小时" value="hourly" /><el-option label="固定间隔" value="interval" /><el-option label="每天定时" value="daily" /><el-option label="每周定时" value="weekly" /></el-select></el-form-item>
            <el-form-item label="最大重试次数 *"><el-input-number v-model="jobForm.max_retry_count" :min="0" :max="10" controls-position="right" /></el-form-item>
            <el-form-item v-if="jobForm.schedule_type === 'interval'" label="间隔分钟数 *"><el-input-number v-model="jobForm.interval_minutes" :min="15" :max="10080" controls-position="right" /></el-form-item>
            <el-form-item v-if="['daily', 'weekly'].includes(jobForm.schedule_type)" label="执行时间 *"><el-time-picker v-model="jobForm.local_time" value-format="HH:mm" format="HH:mm" /></el-form-item>
            <el-form-item v-if="jobForm.schedule_type === 'weekly'" label="每周执行日 *" class="wide"><el-checkbox-group v-model="jobForm.weekdays"><el-checkbox-button v-for="day in weekdayOptions" :key="day.value" :value="day.value">{{ day.label }}</el-checkbox-button></el-checkbox-group></el-form-item>
            <el-form-item label="执行时区 *"><el-input v-model="jobForm.timezone" /></el-form-item>
            <el-form-item label="错过执行"><el-select v-model="jobForm.catch_up"><el-option label="恢复后补跑一次" value="run_once" /><el-option label="跳过错过的计划" value="skip" /></el-select></el-form-item>
            <el-form-item label="暂停至"><el-date-picker v-model="jobForm.pause_until" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="不暂停" /></el-form-item>
            <el-form-item label="运行模式 *"><el-select v-model="jobForm.execution_mode"><el-option label="本地模拟（不调用平台）" value="simulation" /><el-option label="生产只读" value="live_readonly" /></el-select></el-form-item>
          </div>
        </fieldset>
        <fieldset class="job-policy-section">
          <legend>要同步哪些数据</legend>
          <p class="policy-intro">推荐保持默认值：首次补齐近期数据，之后从上次进度继续，不会每次重复查询全部历史。</p>
          <div class="dialog-grid">
            <el-form-item label="同步范围 *"><el-select v-model="jobForm.query_mode"><el-option label="按上次进度继续同步（推荐）" value="incremental" /><el-option label="指定时间范围" value="range" /></el-select></el-form-item>
            <el-form-item v-if="jobForm.query_mode === 'incremental'" label="首次同步最近多少天 *"><el-input-number v-model="jobForm.lookback_days" :min="1" :max="3650" controls-position="right" /><small>只在任务第一次运行时使用，推荐 30 天。</small></el-form-item>
            <el-form-item v-if="jobForm.query_mode === 'range'" label="开始时间 *"><el-date-picker v-model="jobForm.range_start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
            <el-form-item v-if="jobForm.query_mode === 'range'" label="结束时间 *"><el-date-picker v-model="jobForm.range_end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
          </div>
          <details class="job-policy-advanced">
            <summary>高级设置（一般无需修改）</summary>
            <div class="dialog-grid">
              <el-form-item label="重叠查询分钟数"><el-input-number v-model="jobForm.overlap_minutes" :min="0" :max="1440" controls-position="right" /></el-form-item>
              <el-form-item label="每页查询条数"><el-input-number v-model="jobForm.query_page_size" :min="1" :max="100" controls-position="right" /></el-form-item>
              <el-form-item label="单次最大页数"><el-input-number v-model="jobForm.max_pages" :min="1" :max="1000" controls-position="right" /></el-form-item>
              <el-form-item label="单次最大记录数"><el-input-number v-model="jobForm.max_records" :min="1" :max="100000" controls-position="right" /></el-form-item>
              <el-form-item label="查询状态" class="wide"><el-input v-model="jobForm.query_statuses" placeholder="多个状态用英文逗号分隔；留空表示全部" /></el-form-item>
            </div>
          </details>
        </fieldset>
      </el-form>
      <p class="safe-note policy-safe-note">保存策略不会调用外部平台。系统只自动处理本地模拟任务；生产只读任务每次仍要人工确认，TikTok Token 不自动刷新。</p>
      <template #footer><el-button @click="jobEditDialog = false">取消</el-button><el-button type="primary" :loading="operating" @click="saveJob">保存策略</el-button></template>
    </el-dialog>

    <el-dialog v-model="runDetailDialog" width="min(860px, 94vw)" class="run-detail-dialog">
      <template #header>
        <div class="run-detail-heading"><strong>同步运行详情</strong><small>展示脱敏后的调用、处理和写入结果</small></div>
      </template>
      <template v-if="activeRun">
        <dl class="run-detail-grid">
          <div v-for="item in runDetailItems" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div>
        </dl>
        <ol v-if="runStages.length" class="run-stages" aria-label="同步执行阶段">
          <li v-for="(stage, index) in runStages" :key="stage.code" :class="`is-${stage.status}`">
            <span>{{ index + 1 }}</span>
            <div><strong>{{ stage.label }}</strong><small>{{ runStageSummary(stage) }}</small></div>
          </li>
        </ol>
        <p v-else class="run-stage-empty">该历史运行尚无分阶段记录。</p>
      </template>
      <template #footer><el-button @click="runDetailDialog = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  checkIntegrationConsistency,
  checkIntegrationReadonlyConnection,
  checkIntegrationReference,
  createIntegrationConfig,
  deleteIntegrationConfig,
  deleteSyncJob,
  disableIntegrationConfig,
  fetchIntegrationWorkspace,
  fetchSyncRunDetail,
  previewSyncJobDelete,
  retrySyncRun,
  rotateIntegrationSecretValues,
  runSyncJob,
  runSyncJobMock,
  toggleSyncJob,
  updateSyncJob
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';

const props = defineProps({
  mode: { type: String, required: true },
  runPermission: { type: String, default: '' },
  mockRunPermission: { type: String, default: '' }
});
const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const loading = ref(false);
const error = ref('');
const data = ref({ summary: {}, options: {}, reference_options: {}, previews: {}, regions: [], pagination: {}, results: [] });
const rows = computed(() => data.value.results || []);
const summary = computed(() => data.value.summary || {});
const pagination = computed(() => data.value.pagination || {});
const page = ref(1);
const auditVisible = ref(false);
const configDialog = ref(false);
const dueDialog = ref(false);
const reconcileDialog = ref(false);
const createJobDialog = ref(false);
const schedulerHistoryOpen = ref(false);
const credentialDialog = ref(false);
const jobDetailDialog = ref(false);
const jobEditDialog = ref(false);
const runDetailDialog = ref(false);
const operating = ref(false);
const deletingConfigId = ref(null);
const selectedJobs = ref([]);
const activeConfig = ref(null);
const activeJob = ref(null);
const activeRun = ref(null);
const creatingJobTemplate = ref(null);
const draft = reactive({ platform: '', status: '', environment: '', api_type: '', resource_type: '', schedule_type: '', subject: '', run_id: '', started_from: '', started_to: '' });
const query = reactive({ ...draft, job_state: '' });
const configForm = reactive({ account_alias: '', platform: '', api_type: '', environment: '', regions: [] });
const referencePlatforms = computed(() => data.value.reference_options?.platforms || []);
const referenceEnvironments = computed(() => data.value.reference_options?.environments || []);
const selectedReferencePlatform = computed(() => referencePlatforms.value.find(option => option.value === configForm.platform));
const configApiTypeOptions = computed(() => selectedReferencePlatform.value?.api_types || []);
const configRegionOptions = computed(() => {
  const regions = data.value.reference_options?.countries || data.value.regions || [];
  const allowed = selectedReferencePlatform.value?.allowed_regions;
  if (!Array.isArray(allowed)) return regions;
  const supported = new Set(allowed.map(value => String(value).toUpperCase()));
  return regions.filter(region => supported.has(String(region.country_code || '').toUpperCase()));
});
const credentialForm = reactive({
  partner_id: '', partner_key: '', ads_app_id: '', ads_secret: '', redirect_uri: '',
  app_key: '', service_id: '', app_secret: '', api_base_url: '', domain: '', client_id: '', client_secret: '',
  reason: '按运用交接计划维护开发者凭据'
});
const jobForm = reactive({
  schedule_type: 'manual', max_retry_count: 3, execution_mode: 'simulation',
  interval_minutes: 60, local_time: '02:00', weekdays: [1, 2, 3, 4, 5, 6, 7], timezone: 'Asia/Shanghai', catch_up: 'run_once', pause_until: null,
  query_mode: 'incremental', lookback_days: 30, overlap_minutes: 5, query_page_size: 50, max_pages: 100, max_records: 50000,
  range_start_at: null, range_end_at: null, query_statuses: ''
});
const weekdayOptions = [{ label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 }, { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 7 }];
const liveRunAccess = computed(() => getActionAccess(auth, { permission: props.runPermission }));
const mockRunAccess = computed(() => getActionAccess(auth, { permission: props.mockRunPermission }));

const contracts = {
  configs: {
    title: '平台接入配置', note: '管理平台开发者配置和调用能力；店铺授权与仓库 Token 分别在对应档案中维护。',
    risk: 'Partner Key、App Secret 等开发者凭据经服务端加密后写入 SaaS MySQL；页面只显示状态和指纹，不回显明文。', empty: '暂无平台接入配置',
    filters: [{ key: 'platform', label: '平台' }, { key: 'api_type', label: 'API 类型' }, { key: 'environment', label: '环境' }, { key: 'status', label: '状态' }]
  },
  'sync-jobs': {
    title: '同步任务', note: '任务绑定业务主体、API 类型和接入配置；未完成档案授权的任务不能启用。',
    risk: '任务默认使用本地模拟；只有明确切换为“生产只读”并在运行前再次确认，才会调用外部平台。任何模式都不会自动刷新 TikTok Token。', empty: '暂无同步任务',
    filters: [{ key: 'platform', label: '平台' }, { key: 'api_type', label: 'API 类型' }, { key: 'resource_type', label: '资源类型' }, { key: 'status', label: '状态' }, { key: 'schedule_type', label: '调度类型' }, { key: 'subject', label: '店铺/仓库', type: 'text', placeholder: '输入店铺或仓库名称' }]
  },
  'sync-runs': {
    title: '同步运行记录', note: '统一追踪平台调用、标准化和业务表写入结果。',
    risk: '运行记录仅显示脱敏错误和数量；生产只读任务的原始响应以 TXT 保存在服务端，不会返回到浏览器。', empty: '暂无同步运行记录',
    filters: [{ key: 'platform', label: '平台' }, { key: 'api_type', label: 'API 类型' }, { key: 'resource_type', label: '资源类型' }, { key: 'status', label: '状态' }, { key: 'subject', label: '店铺/仓库', type: 'text', placeholder: '输入店铺或仓库名称' }, { key: 'run_id', label: '执行 ID', type: 'text', placeholder: '输入完整或部分执行 ID' }, { key: 'started_from', label: '开始日期', type: 'date' }, { key: 'started_to', label: '结束日期', type: 'date' }]
  }
};
const contract = computed(() => contracts[props.mode]);
const flowSteps = computed(() => {
  const s = summary.value;
  return [
    { label: '开发者配置', value: s.config_count || 0, text: `${s.config_count || 0} 项平台配置` },
    { label: '凭据可用', value: s.ready_credential_count || 0, text: `${s.ready_credential_count || 0} 项引用就绪` },
    { label: '主体授权', value: (s.store_authorization_count || 0) + (s.warehouse_authorization_count || 0), text: `${(s.store_authorization_count || 0) + (s.warehouse_authorization_count || 0)} 个主体已绑定` },
    { label: '同步执行', value: s.run_count || 0, text: `${s.run_count || 0} 次运行记录` }
  ];
});
const metrics = computed(() => props.mode === 'sync-runs'
  ? [{ label: '全部运行', value: summary.value.run_count }, { label: '成功', value: summary.value.successful_run_count }, { label: '运行中', value: summary.value.running_run_count }, { label: '需处理', value: summary.value.failed_run_count }]
  : [{ label: '已启用任务', value: summary.value.enabled_job_count }, { label: '成功运行', value: summary.value.successful_run_count }, { label: '需处理运行', value: summary.value.failed_run_count }, { label: '当前查询结果', value: pagination.value.total }]);
const jobTabs = computed(() => [
  { value: '', label: '全部任务', count: summary.value.job_count || 0 }, { value: 'enabled', label: '已启用', count: summary.value.enabled_job_count || 0 },
  { value: 'disabled', label: '已停用' }, { value: 'running', label: '运行中' }, { value: 'due', label: '等待执行', count: summary.value.due_job_count || 0 },
  { value: 'failed', label: '运行失败' }, { value: 'authorization', label: '授权异常' }
]);
const scheduler = computed(() => data.value.scheduler || {});
const schedulerHistory = computed(() => data.value.scheduler_history || []);
const healthIssueCount = computed(() => Number(summary.value.retry_exhausted_job_count || 0) + Number(summary.value.stale_running_job_count || 0) + Number(summary.value.failed_run_count || 0));
const schedulerIssue = computed(() => Boolean(scheduler.value.configured && ['stale', 'failed'].includes(scheduler.value.heartbeat_state)));
const healthAttention = computed(() => Boolean(healthIssueCount.value || schedulerIssue.value));
const healthStatusText = computed(() => healthIssueCount.value ? `${number(healthIssueCount.value)} 项需处理` : (schedulerIssue.value ? '调度需检查' : '运行健康'));
const schedulerText = computed(() => {
  const value = scheduler.value;
  const state = value.heartbeat_state || (value.configured ? 'awaiting_first_tick' : 'disabled');
  if (state === 'disabled') return '未启用 · 仍可在同步任务页手动处理';
  if (state === 'awaiting_first_tick') return '已配置 · 等待系统计划任务首次调用';
  if (state === 'failed') return `最近调用失败 · ${date(value.last_invoked_at)}`;
  if (state === 'stale') return `超过 ${number(value.stale_after_minutes || 120)} 分钟未调用 · 上次 ${date(value.last_invoked_at)}`;
  return Number(value.last_due_count || 0) === 0
    ? `运行正常 · ${date(value.last_invoked_at)} · 最近一次无到期任务`
    : `运行正常 · ${date(value.last_invoked_at)} · 最近处理 ${number(value.last_processed_count)} / ${number(value.last_due_count)} 个任务`;
});
const dueItems = computed(() => { const p = data.value.previews?.due || {}; return [{ label: '到期任务', value: p.due_count || 0 }, { label: '可自动处理', value: p.automatic_count || 0 }, { label: '需人工确认', value: p.confirmation_count || 0 }, { label: '单批上限', value: p.batch_limit || 20 }]; });
const reconcileItems = computed(() => { const p = data.value.previews?.reconcile || {}; return [{ label: '符合条件的主体', value: p.eligible_subject_count || 0 }, { label: '应有任务', value: p.total_required || 0 }, { label: '已存在', value: p.existing_count || 0 }, { label: '待补齐', value: p.missing_count || 0 }]; });
const pageStart = computed(() => pagination.value.total ? ((pagination.value.page - 1) * pagination.value.page_size) + 1 : 0);
const pageEnd = computed(() => Math.min(pagination.value.total || 0, (pagination.value.page || 1) * (pagination.value.page_size || 50)));
const jobDetailItems = computed(() => {
  const row = activeJob.value;
  if (!row) return [];
  const destination = businessDestination(row.resource_type);
  const latestRun = row.latest_run_status
    ? `${label('status', row.latest_run_status)} · 抓取 ${number(row.latest_fetched_count)} / 新增 ${number(row.latest_created_count)} / 更新 ${number(row.latest_updated_count)} / 失败 ${number(row.latest_failed_count)}`
    : '尚未运行';
  return [
    { label: '任务状态', value: `${label('status', row.health_state)}${row.blocked_reason ? ` · ${row.blocked_reason}` : ''}` },
    { label: '业务主体', value: `${row.subject_code || '—'} · ${row.subject_name || '未绑定'}` },
    { label: '平台与站点', value: `${label('platform', row.platform)} · ${row.region || '—'} · ${label('api_type', row.api_type)}` },
    { label: '同步资源', value: `${label('resource_type', row.resource_type)} → ${row.data_destination || destination.label}` },
    { label: '接入配置', value: `${row.account_alias || row.config_name || '—'} · ${label('status', row.credential_status)}` },
    { label: '主体授权', value: label('status', row.authorization_status) },
    { label: '运行策略', value: `${scheduleDescription(row)} · ${label('execution_mode', row.execution_mode)}` },
    { label: '查询范围', value: row.query_mode === 'range' ? `${date(row.range_start_at)} 至 ${date(row.range_end_at)}` : `首次回溯 ${number(row.lookback_days || 30)} 天 · 重叠 ${number(row.overlap_minutes ?? 5)} 分钟` },
    { label: '单次安全上限', value: `${number(row.query_page_size || 50)} 条/页 · ${number(row.max_pages || 100)} 页 · ${number(row.max_records || 50000)} 条` },
    { label: '最大重试次数', value: number(row.max_retry_count) },
    { label: 'Token 策略', value: row.token_policy === 'auto_refresh' ? '到期自动刷新' : '不自动刷新' },
    { label: '上次/下次运行', value: `${date(row.last_run_at)} / ${date(row.next_run_at)}` },
    { label: '最近运行', value: latestRun },
    { label: '同步检查点', value: row.checkpoint_version ? `版本 ${number(row.checkpoint_version)} · 水位 ${date(row.checkpoint_watermark)}` : '尚未生成' },
    { label: '最近错误', value: row.latest_error_message || row.latest_error_code || '—' },
    { label: '数据写入表', value: row.data_table || destination.tables }
  ];
});
const runLog = computed(() => {
  const value = activeRun.value?.masked_log;
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string') return {};
  try { return JSON.parse(value); } catch { return {}; }
});
const runDetailItems = computed(() => {
  const row = activeRun.value;
  if (!row) return [];
  const log = runLog.value;
  const retryCount = Number(row.retry_count || 0);
  const retryOf = row.retry_of || log.retry_of;
  const checkpoint = log.checkpoint && typeof log.checkpoint === 'object' ? log.checkpoint : {};
  const checkpointVersion = row.checkpoint_version ?? checkpoint.version;
  const checkpointAdvanced = row.checkpoint_advanced ?? checkpoint.advanced;
  const archiveCount = row.archive_file_count ?? (Array.isArray(log.archive_files) ? log.archive_files.length : 0);
  return [
    { label: '执行 ID', value: row.run_id || row.id || '—' },
    { label: '业务主体', value: row.subject_name || '历史未绑定' },
    { label: '平台/API', value: `${label('platform', row.platform)} · ${label('api_type', row.api_type)}` },
    { label: '资源类型', value: label('resource_type', row.resource_type) },
    { label: '执行状态', value: label('status', row.status) },
    { label: '开始时间', value: date(row.started_at) },
    { label: '结束时间', value: date(row.finished_at) },
    { label: '执行耗时', value: row.duration_seconds === null || row.duration_seconds === undefined ? '—' : `${number(row.duration_seconds)} 秒` },
    { label: '运行模式', value: label('execution_mode', row.execution_mode) },
    { label: '外部平台调用', value: booleanValue(row.external_api_called ?? log.external_api_called) ? '是' : '否' },
    { label: 'Token 刷新/替换', value: booleanValue(row.token_refreshed ?? log.token_refreshed) ? '是（需检查）' : '否' },
    { label: '重试链路', value: retryCount ? `第 ${number(retryCount)} 次重试${retryOf ? ` · 来源 ${retryOf}` : ''}` : '首次运行' },
    { label: '同步检查点', value: checkpointVersion ? `版本 ${number(checkpointVersion)} · ${booleanValue(checkpointAdvanced) ? '已推进' : '未推进'}` : '未生成' },
    { label: '原始响应归档', value: archiveCount ? `${number(archiveCount)} 个服务端 TXT 文件` : '无' },
    { label: '数据结果', value: `抓取 ${number(row.fetched_count)} / 新增 ${number(row.created_count)} / 更新 ${number(row.updated_count)} / 跳过 ${number(row.skipped_count)} / 失败 ${number(row.failed_count)}` },
    { label: '错误代码', value: row.error_code || '—' },
    { label: '脱敏错误', value: row.masked_error_message || log.masked_error_message || '—' }
  ];
});
const runStages = computed(() => {
  const stages = runLog.value.stages;
  if (!Array.isArray(stages)) return [];
  return stages.filter(stage => stage && typeof stage === 'object' && stage.code && stage.label && stage.status);
});
const StatusTag = defineComponent({ props: { value: String }, setup(p) { const type = computed(() => ({ success: 'success', healthy: 'success', active: 'success', authorized: 'success', referenced: 'success', verified: 'success', configured: 'success', failed: 'danger', error: 'danger', authorization: 'danger', configuration: 'warning', due: 'warning', pending_review: 'warning', unconfigured: 'info', disabled: 'info', simulation: 'info', live_readonly: 'warning' }[p.value] || 'info')); return () => h('span', { class: ['status-pill', `is-${type.value}`] }, label('status', p.value)); } });
const SummaryGrid = defineComponent({ props: { items: Array }, setup(p) { return () => h('dl', { class: 'summary-grid' }, (p.items || []).map(item => h('div', [h('dt', item.label), h('dd', number(item.value))]))); } });

const labels = {
  platform: { lazada: 'Lazada', shopee: 'Shopee', tiktok: 'TikTok Shop', jifeng_wms: '极风 WMS' }, api_type: { marketplace: '商城 API', advertising: '广告 API', inventory: '库存 API' },
  environment: { sandbox: '沙箱', pilot: '试运行', production: '生产', mock: '模拟' }, resource_type: { sales_order: '销售订单', refund_return: '退款退货', inventory_snapshot: '库存快照', inbound: '入库单', shipment: '出库单' },
  schedule_type: { manual: '手动', hourly: '每小时', interval: '间隔', daily: '每天定时', weekly: '每周定时', cron: '定时' }, execution_mode: { simulation: '本地模拟', live_readonly: '生产只读' }, schedule_state: { disabled: '已停用', running: '运行中', manual: '手动触发', unscheduled: '尚未排期', due: '等待执行', scheduled: '已排期', retry_waiting: '退避等待', retry_exhausted: '重试暂停' },
  status: { success: '成功', failed: '失败', running: '运行中', active: '已启用', configured: '已配置', verified: '已验证', referenced: '已引用', unconfigured: '未配置', disabled: '已停用', idle: '空闲', pending_review: '待审核', healthy: '运行正常', authorization: '授权异常', configuration: '配置待处理', due: '等待执行', simulation: '本地模拟', live_readonly: '生产只读' }
};
function label(group, value) { return labels[group]?.[value] || value || '—'; }
function number(value) { return Number(value || 0).toLocaleString('zh-CN'); }
function date(value) { if (!value) return '—'; return String(value).replace('T', ' ').slice(0, 19); }
function duration(value) { const milliseconds = Number(value || 0); return milliseconds < 1000 ? `${number(milliseconds)} 毫秒` : `${(milliseconds / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 秒`; }
function booleanValue(value) { return value === true || ['1', 'true', 'yes', 'on'].includes(String(value || '').toLowerCase()); }
function runStageSummary(stage) {
  if (stage.status === 'success') {
    if (stage.code === 'checkpoint' && !booleanValue(stage.advanced)) return '已记录，游标未推进';
    return stage.finished_at ? `完成于 ${date(stage.finished_at)}` : '已完成';
  }
  if (stage.status === 'skipped') return ({ simulation_mode: '本地模拟未调用外部平台', no_external_payload: '无外部响应待处理', previous_stage_failed: '前序阶段失败', run_failed: '运行失败，检查点未推进' })[stage.reason] || '已跳过';
  return ({ running: '运行中', pending: '等待执行', failed: '失败', cancelled: '已取消' })[stage.status] || label('status', stage.status);
}
function scheduleDescription(row) {
  if (row.schedule_type === 'hourly') return '每小时';
  if (row.schedule_type === 'interval') return `每 ${number(row.interval_minutes || 60)} 分钟`;
  if (row.schedule_type === 'daily') return `每天 ${row.local_time || '02:00'} · ${row.timezone || 'Asia/Shanghai'}`;
  if (row.schedule_type === 'weekly') return `每周指定日 ${row.local_time || '02:00'} · ${row.timezone || 'Asia/Shanghai'}`;
  return `${label('schedule_type', row.schedule_type)}运行`;
}
function filterOptions(key) { const map = { platform: 'platforms', status: 'statuses', environment: 'environments', api_type: 'api_types', resource_type: 'resource_types', schedule_type: 'schedule_types' }; return data.value.options?.[map[key]] || []; }
async function load() { loading.value = true; error.value = ''; try { const response = await fetchIntegrationWorkspace(props.mode, { ...query, page: page.value, page_size: 50 }); if (!response.success) throw new Error(response.message || '读取失败'); data.value = response.data; page.value = response.data.pagination?.page || 1; } catch (e) { error.value = e?.message || '读取 API 数据接入记录失败'; } finally { loading.value = false; } }
function applyFilters() { Object.assign(query, draft); page.value = 1; load(); }
function resetFilters() { Object.keys(draft).forEach(key => { draft[key] = ''; query[key] = ''; }); query.job_state = ''; page.value = 1; load(); }
function setJobState(value) { query.job_state = value; page.value = 1; load(); }
function hydrateRouteFilters() { Object.keys(draft).forEach(key => { const value = route.query[key]; draft[key] = typeof value === 'string' ? value : ''; query[key] = draft[key]; }); }
function toggleSchedulerHistory() { schedulerHistoryOpen.value = !schedulerHistoryOpen.value; }
function operationFailed(response, fallback = '操作失败。') { ElMessage.error(response?.message || fallback); return false; }
const credentialFields = ['partner_id', 'partner_key', 'ads_app_id', 'ads_secret', 'redirect_uri', 'app_key', 'service_id', 'app_secret', 'api_base_url', 'domain', 'client_id', 'client_secret'];
const secretCredentialFields = ['partner_key', 'ads_secret', 'app_secret', 'client_secret'];
function clearCredentialForm() { credentialFields.forEach(key => { credentialForm[key] = ''; }); credentialForm.reason = '按运用交接计划维护开发者凭据'; }
function normalizeConfigApiType() {
  configForm.api_type = configApiTypeOptions.value[0]?.value || '';
  configForm.regions = [];
}
function setConfigRegion(countryCode, selected) {
  const regions = new Set(configForm.regions);
  selected ? regions.add(countryCode) : regions.delete(countryCode);
  configForm.regions = [...regions];
}
function openCreateConfig() {
  const platform = referencePlatforms.value.find(option => option.enabled);
  Object.assign(configForm, {
    account_alias: '',
    platform: platform?.value || '',
    api_type: platform?.api_types?.[0]?.value || '',
    environment: referenceEnvironments.value.find(option => option.value === 'production')?.value || referenceEnvironments.value[0]?.value || '',
    regions: [],
  });
  configDialog.value = true;
}
function openCredential(row) { activeConfig.value = row; clearCredentialForm(); credentialDialog.value = true; }
function credentialPayload() {
  const platform = activeConfig.value?.platform;
  const apiType = activeConfig.value?.api_type;
  const keys = platform === 'lazada'
    ? ['app_key', 'app_secret', 'redirect_uri']
    : platform === 'shopee'
    ? ['partner_id', 'partner_key', 'redirect_uri']
    : platform === 'jifeng_wms'
      ? ['api_base_url', 'domain', 'client_id', 'client_secret']
      : apiType === 'advertising'
        ? ['ads_app_id', 'ads_secret', 'redirect_uri']
        : ['app_key', 'service_id', 'app_secret'];
  return Object.fromEntries(keys.filter(key => credentialForm[key] !== '').map(key => [key, credentialForm[key]]));
}
async function saveCredential() {
  const credentials = credentialPayload();
  if (!Object.keys(credentials).length) { ElMessage.warning('请至少填写一个需要修改的凭据字段。'); return; }
  operating.value = true;
  const idempotencyKey = globalThis.crypto?.randomUUID?.() || `credential-${Date.now()}-${activeConfig.value.id}`;
  const response = await rotateIntegrationSecretValues(activeConfig.value.id, { version: activeConfig.value.config_version, reason: credentialForm.reason, credentials, verify_after_save: false }, idempotencyKey);
  secretCredentialFields.forEach(key => { credentialForm[key] = ''; });
  operating.value = false;
  if (!response.success) { operationFailed(response, '凭据保存失败。'); return; }
  credentialDialog.value = false;
  clearCredentialForm();
  ElMessage.success('开发者凭据已由服务端安全保存，页面未保留原文。');
  await load();
}
async function verify(row) { const response = await checkIntegrationReference(row.id); if (!response.success) { operationFailed(response, '凭据引用检查失败。'); return; } ElMessage.success('凭据引用完整；未调用外部平台。'); await load(); }
async function checkConsistency(row) { const response = await checkIntegrationConsistency(row.id); if (!response.success) { operationFailed(response, '本地一致性检查未通过。'); return; } ElMessage.success(`本地一致性检查通过：${number(response.data.binding_count)} 个授权绑定、${number(response.data.job_reference_count)} 个任务引用。`); await load(); }
async function checkReadonly(row) {
  try { await ElMessageBox.confirm('将使用一个已授权主体调用一次平台只读接口；不会刷新或替换 Token。是否继续？', '平台只读检查', { type: 'warning' }); } catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; }
  const response = await checkIntegrationReadonlyConnection(row.id);
  if (!response.success) { operationFailed(response, '平台只读检查失败。'); return; }
  ElMessage.success('平台只读连通检查通过；Token 未刷新、未替换。');
  await load();
}
async function disableConfig(row) {
  try { await ElMessageBox.confirm(`确认禁用“${row.account_alias}”及其关联任务？`, '禁用接入配置', { type: 'warning' }); } catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; }
  const response = await disableIntegrationConfig(row.id);
  if (!response.success) { operationFailed(response, '接入配置禁用失败。'); return; }
  ElMessage.success('接入配置已禁用。');
  await load();
}
async function deleteConfig(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除“${row.account_alias}”？删除后将从配置列表移除，历史审计和运行记录继续保留。`,
      '删除接入配置',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    );
  } catch (reason) {
    if (reason === 'cancel' || reason === 'close') return;
    throw reason;
  }
  deletingConfigId.value = row.id;
  const response = await deleteIntegrationConfig(row.id);
  deletingConfigId.value = null;
  if (!response.success) { operationFailed(response, '接入配置删除失败。'); return; }
  ElMessage.success('接入配置已删除，历史记录继续保留。');
  await load();
}
function rowRunAccess(row) { return row.execution_mode === 'live_readonly' ? liveRunAccess.value : mockRunAccess.value; }
async function runJob(row) {
  const access = rowRunAccess(row);
  if (!access.allowed) { ElMessage.warning(access.reason); return; }
  if (!row.is_enabled || row.blocked_reason) { ElMessage.warning(row.blocked_reason || '请先启用同步任务。'); return; }
  if (row.execution_mode === 'live_readonly') {
    try {
      await ElMessageBox.confirm('将发起一次生产只读平台调用；不会写回平台或自动刷新 TikTok Token。是否继续？', '确认生产只读同步', { type: 'warning' });
    } catch (error) { if (error === 'cancel' || error === 'close') return; throw error; }
  }
  const response = row.execution_mode === 'live_readonly' ? await runSyncJob(row.id) : await runSyncJobMock(row.id);
  response.success ? ElMessage.success('同步任务已提交。') : ElMessage.warning(response.message || '任务提交失败。');
  await load();
}
async function prepareConfig() {
  if (!configForm.account_alias.trim() || !configForm.platform || !configForm.api_type || !configForm.environment || !configForm.regions.length) { ElMessage.warning('请填写配置名称，并选择平台、API 类型、环境和适用站点。'); return; }
  operating.value = true;
  const response = await createIntegrationConfig({ account_alias: configForm.account_alias.trim(), platform: configForm.platform, api_type: configForm.api_type, environment: configForm.environment, regions: configForm.regions });
  operating.value = false;
  if (!response.success) { operationFailed(response, '接入配置创建失败。'); return; }
  configDialog.value = false;
  ElMessage.success('接入配置已创建，请继续维护开发者凭据。');
  await load();
}
function openJobDetail(row) { activeJob.value = row; jobDetailDialog.value = true; }
function openJobEditor(row) {
  if (!row) return;
  activeJob.value = row;
  Object.assign(jobForm, {
    schedule_type: row.schedule_type || 'manual', max_retry_count: row.max_retry_count ?? 3, execution_mode: row.execution_mode || 'simulation',
    interval_minutes: row.interval_minutes ?? 60, local_time: row.local_time || '02:00', weekdays: [...(row.weekdays || [1, 2, 3, 4, 5, 6, 7])],
    timezone: row.timezone || 'Asia/Shanghai', catch_up: row.catch_up || 'run_once', pause_until: row.pause_until || null,
    query_mode: row.query_mode || 'incremental', lookback_days: row.lookback_days ?? 30, overlap_minutes: row.overlap_minutes ?? 5,
    query_page_size: row.query_page_size ?? 50, max_pages: row.max_pages ?? 100, max_records: row.max_records ?? 50000,
    range_start_at: row.range_start_at || null, range_end_at: row.range_end_at || null,
    query_statuses: Array.isArray(row.query_statuses) ? row.query_statuses.join(', ') : (row.query_statuses || '')
  });
  jobDetailDialog.value = false;
  jobEditDialog.value = true;
}
async function saveJob() {
  if (!jobForm.timezone.trim()) { ElMessage.warning('请填写执行时区。'); return; }
  if (['daily', 'weekly'].includes(jobForm.schedule_type) && !jobForm.local_time) { ElMessage.warning('请填写执行时间。'); return; }
  if (jobForm.schedule_type === 'weekly' && !jobForm.weekdays.length) { ElMessage.warning('请至少选择一个每周执行日。'); return; }
  if (jobForm.query_mode === 'range' && (!jobForm.range_start_at || !jobForm.range_end_at)) { ElMessage.warning('请填写完整的同步开始和结束时间。'); return; }
  operating.value = true;
  const response = await updateSyncJob(activeJob.value.id, { ...jobForm });
  operating.value = false;
  if (!response.success) { operationFailed(response, '同步策略保存失败。'); return; }
  jobEditDialog.value = false;
  ElMessage.success('同步策略已更新。');
  await load();
}
function businessDestination(resourceType) {
  if (resourceType === 'refund_return') return { label: '退款退货', path: '/sales-management/returns', tables: 'refund_return / refund_return_item' };
  if (resourceType === 'inventory_snapshot') return { label: '库存分析', path: '/analytics/inventory', tables: 'inventory_snapshot' };
  return { label: '销售订单', path: '/sales-management/orders', tables: 'sales_order / sales_order_item' };
}
function businessPath(resourceType) { return businessDestination(resourceType).path; }
function viewJobRuns(row) { if (!row) return; jobDetailDialog.value = false; router.push({ path: '/integrations/sync-runs', query: { subject: row.subject_name } }); }
function viewJobBusiness(row) { if (!row) return; jobDetailDialog.value = false; router.push(businessPath(row.resource_type)); }
function returnToJob(row) { router.push({ path: '/integrations/sync-jobs', query: { subject: row.subject_name || '' } }); }
async function handleJobCommand(command, row) {
  if (command === 'detail') { openJobDetail(row); return; }
  if (command === 'edit') { openJobEditor(row); return; }
  if (command === 'clone') { openCreateJob(row); return; }
  if (command === 'runs') { router.push({ path: '/integrations/sync-runs', query: { subject: row.subject_name } }); return; }
  if (command === 'business') { router.push(businessPath(row.resource_type)); return; }
  if (command === 'toggle') {
    if (row.is_enabled) { try { await ElMessageBox.confirm('确认停用该同步任务？', '停用任务', { type: 'warning' }); } catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; } }
    const response = await toggleSyncJob(row.id, !row.is_enabled);
    if (!response.success) { operationFailed(response, '任务状态切换失败。'); return; }
    ElMessage.success(row.is_enabled ? '同步任务已停用。' : '同步任务已启用。');
    await load();
    return;
  }
  if (command === 'delete') {
    const preview = await previewSyncJobDelete(row.id);
    if (!preview.success) { operationFailed(preview, '删除检查失败。'); return; }
    if (!preview.data.can_delete) { ElMessage.warning(preview.data.blockers?.join('；') || '任务当前不能删除。'); return; }
    try { await ElMessageBox.confirm('确认删除该任务？授权、配置和平台 Token 不受影响。', '删除同步任务', { type: 'warning' }); } catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; }
    const response = await deleteSyncJob(row.id);
    if (!response.success) { operationFailed(response, '同步任务删除失败。'); return; }
    ElMessage.success('同步任务已删除。');
    await load();
  }
}
async function batchToggle(enabled) {
  let succeeded = 0;
  for (const row of selectedJobs.value) { const response = await toggleSyncJob(row.id, enabled); if (response.success) succeeded += 1; }
  ElMessage.success(`批量操作完成：成功 ${succeeded} 个，失败 ${selectedJobs.value.length - succeeded} 个。`);
  await load();
}
async function batchRunMock() {
  const candidates = selectedJobs.value.filter(row => row.execution_mode === 'simulation' && row.is_enabled && !row.blocked_reason);
  let succeeded = 0;
  for (const row of candidates) { const response = await runSyncJobMock(row.id); if (response.success) succeeded += 1; }
  ElMessage.success(`模拟运行完成：成功 ${succeeded} 个；生产只读或不可运行任务已跳过。`);
  await load();
}
async function openRunDetail(row) {
  const response = await fetchSyncRunDetail(row.id);
  activeRun.value = response.success ? { ...row, ...response.data, execution_mode: row.execution_mode, max_retry_count: row.max_retry_count } : row;
  runDetailDialog.value = true;
}
async function retryRun(row) {
  try { await ElMessageBox.confirm('将创建一条新的本地模拟重试运行，原运行记录保持不变。是否继续？', '重试失败任务', { type: 'warning' }); } catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; }
  const response = await retrySyncRun(row.id);
  if (!response.success) { operationFailed(response, '创建重试运行失败。'); return; }
  runDetailDialog.value = false;
  ElMessage.success('已创建新的本地模拟重试运行。');
  await load();
}
function openCreateJob(template = null) { creatingJobTemplate.value = template; createJobDialog.value = true; }
function closeCreateJob() { createJobDialog.value = false; creatingJobTemplate.value = null; }
function go(path) { closeCreateJob(); router.push(path); }
watch(() => route.query, () => { hydrateRouteFilters(); page.value = 1; load(); });
onMounted(() => { hydrateRouteFilters(); load(); });
</script>

<style scoped>
.integration-workspace { display: grid; gap: 16px; color: #14213a; }
.workspace-header, .health-card header, .table-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.workspace-header p, .health-card p { margin: -6px 0 0; color: #64748b; font-size: 13px; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.handoff-action { color: #fff !important; border-color: #dc4a2b !important; background: #dc4a2b !important; }
.flow-card, .health-card, .filter-card, .table-card { overflow: hidden; border: 1px solid #d8e2ee; border-radius: 8px; background: #fff; }
.flow-steps { display: grid; grid-template-columns: repeat(4, 1fr); list-style: none; margin: 0; padding: 18px 20px; }
.flow-steps li { position: relative; display: flex; align-items: center; gap: 12px; min-width: 0; }
.flow-steps li:not(:last-child)::after { content: ''; position: absolute; left: 48px; right: 10px; top: 17px; height: 1px; background: #dbe4ee; }
.flow-steps li > span { z-index: 1; display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 auto; border: 1px solid #83d6b7; border-radius: 50%; color: #087a58; background: #effbf6; font-weight: 700; }
.flow-steps li div { z-index: 1; min-width: 0; padding-right: 10px; background: #fff; }
.flow-steps small, .cell-sub { display: block; margin-top: 4px; color: #6b7a90; font-size: 11px; font-weight: 400; }
.flow-metrics { display: grid; grid-template-columns: repeat(4, 1fr); margin: 0; border-top: 1px solid #e3e9f0; background: #f8fafc; }
.flow-metrics div { padding: 12px 20px; border-right: 1px solid #e3e9f0; }.flow-metrics div:last-child { border: 0; }.flow-metrics dt { color: #66758c; font-size: 12px; }.flow-metrics dd { margin: 4px 0 0; font-size: 20px; font-weight: 750; }
.health-card header { padding: 14px 16px 10px; }.health-card h2, .table-card h2 { margin: 0; font-size: 16px; }.health-card dl { display: grid; grid-template-columns: repeat(6, 1fr); margin: 0; border-top: 1px solid #e4eaf1; border-bottom: 1px solid #e4eaf1; }.health-card dl div { padding: 12px 16px; border-right: 1px solid #e4eaf1; }.health-card dt { color: #64748b; font-size: 12px; }.health-card dd { margin: 5px 0 0; font-size: 18px; font-weight: 700; }.health-card footer { display: flex; justify-content: space-between; gap: 16px; padding: 10px 16px; color: #087a58; font-size: 12px; }.health-card footer nav { display: flex; justify-content: flex-end; gap: 16px; flex-wrap: wrap; }.health-card footer nav a, .health-card footer nav button { border: 0; padding: 0; color: #0877d1; background: transparent; cursor: pointer; font: inherit; text-decoration: none; }.health-card footer nav a:hover, .health-card footer nav button:hover { color: #075ea7; text-decoration: underline; }.health-card footer nav a:focus-visible, .health-card footer nav button:focus-visible { outline: 2px solid #409eff; outline-offset: 3px; border-radius: 2px; }
.scheduler-history { border-top: 1px solid #e4eaf1; }.scheduler-history > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 13px 16px; }.scheduler-history > header p { margin: 4px 0 0; }.scheduler-history > header span { color: #607087; font-size: 12px; }.scheduler-history-empty { margin: 0; padding: 18px 16px; border-top: 1px solid #edf1f5; color: #64748b; font-size: 12px; }
.job-tabs { display: flex; gap: 6px; padding: 6px; border: 1px solid #d8e2ee; border-radius: 8px; background: #fff; }.job-tabs button { border: 0; border-radius: 6px; padding: 8px 10px; color: #526279; background: transparent; cursor: pointer; }.job-tabs button.active { color: #1677ff; background: #eaf3ff; font-weight: 700; }.job-tabs span { margin-left: 5px; padding: 1px 6px; border-radius: 10px; background: #dcecff; }
.filter-card { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)) auto; align-items: end; gap: 10px; padding: 12px 14px 14px; }.filter-card :deep(.el-form-item) { margin: 0; }.filter-card :deep(.el-form-item__label) { padding: 0 0 5px; line-height: 18px; }.filter-card :deep(.el-select), .filter-card :deep(.el-date-editor) { width: 100%; }.filter-actions { display: flex; gap: 8px; }
.table-card > header { padding: 15px 16px; }.table-card > header strong { color: #536279; font-size: 12px; }.batch-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; border-top: 1px solid #e3e9f0; background: #f4f9ff; }.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; color: #607087; font-size: 12px; }.table-card :deep(.el-table th.el-table__cell) { color: #40516a; background: #f4f7fa; }.table-card :deep(.el-table .cell) { line-height: 1.35; }
.status-pill { display: inline-flex; padding: 3px 7px; border-radius: 5px; font-size: 11px; font-weight: 700; }.status-pill.is-success { color: #07835c; background: #e7f7f0; }.status-pill.is-danger { color: #c43333; background: #fff0ef; }.status-pill.is-warning { color: #9a6700; background: #fff6da; }.status-pill.is-info { color: #526172; background: #eef2f5; }
.dialog-note { margin: -12px 0 18px; color: #7a8798; font-size: 12px; }.dialog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }.dialog-grid .wide { grid-column: 1 / -1; }.dialog-grid :deep(.el-select) { width: 100%; }.dialog-grid small { display: block; margin-top: 5px; color: #7a8798; }.safe-note { color: #607087; font-size: 12px; line-height: 1.7; }.empty-job { display: grid; place-items: center; min-height: 180px; text-align: center; }.empty-job strong { font-size: 18px; }.empty-job p { color: #64748b; }
.region-option :deep(.el-checkbox) { width: 100%; height: 100%; margin-right: 0; }.region-option :deep(.el-checkbox__label) { color: inherit; }
.dialog-heading { display: grid; gap: 4px; }.dialog-heading strong { color: #1f2937; font-size: 18px; }.dialog-heading small { color: #7a8798; font-size: 12px; font-weight: 400; }
.job-policy-form { display: grid; gap: 16px; }.job-policy-section { min-width: 0; margin: 0; padding: 17px 16px 4px; border: 1px solid #d9e2ec; border-radius: 7px; }.job-policy-section legend { padding: 0 7px; color: #26364d; font-size: 14px; font-weight: 700; }.job-policy-section :deep(.el-select), .job-policy-section :deep(.el-date-editor), .job-policy-section :deep(.el-input-number) { width: 100%; }.policy-intro { margin: 0 0 14px; color: #607087; font-size: 12px; line-height: 1.6; }.job-policy-advanced { grid-column: 1 / -1; margin: 0 0 12px; border: 1px solid #d9e2ec; border-radius: 6px; background: #f8fafc; }.job-policy-advanced summary { padding: 11px 13px; color: #40516a; cursor: pointer; font-size: 13px; font-weight: 650; }.job-policy-advanced[open] summary { border-bottom: 1px solid #d9e2ec; }.job-policy-advanced .dialog-grid { padding: 14px 13px 0; }.policy-safe-note { margin: 14px 2px 0; padding-left: 19px; position: relative; }.policy-safe-note::before { content: 'ⓘ'; position: absolute; left: 0; color: #409eff; }
.job-detail-heading { display: grid; gap: 4px; }.job-detail-heading strong { color: #1f2937; font-size: 18px; }.job-detail-heading small { color: #7a8798; font-size: 12px; font-weight: 400; }.job-detail-status { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -2px 0 14px; color: #64748b; font-size: 12px; }.job-detail-grid { display: grid; grid-template-columns: 1fr 1fr; margin: 0; border-top: 1px solid #d9e2ec; border-left: 1px solid #d9e2ec; }.job-detail-grid div { min-width: 0; padding: 11px 13px; border-right: 1px solid #d9e2ec; border-bottom: 1px solid #d9e2ec; }.job-detail-grid dt { margin-bottom: 5px; color: #66758c; font-size: 12px; }.job-detail-grid dd { margin: 0; overflow-wrap: anywhere; color: #26364d; font-size: 13px; line-height: 1.45; }.job-detail-grid + :deep(.el-alert) { margin-top: 14px; }
.run-detail-heading { display: grid; gap: 4px; }.run-detail-heading strong { color: #1f2937; font-size: 18px; }.run-detail-heading small { color: #7a8798; font-size: 12px; font-weight: 400; }
.run-detail-grid { display: grid; grid-template-columns: 1fr 1fr; margin: 0; border-top: 1px solid #d9e2ec; border-left: 1px solid #d9e2ec; }.run-detail-grid div { min-width: 0; padding: 12px 14px; border-right: 1px solid #d9e2ec; border-bottom: 1px solid #d9e2ec; }.run-detail-grid dt { margin-bottom: 5px; color: #66758c; font-size: 12px; }.run-detail-grid dd { margin: 0; overflow-wrap: anywhere; color: #26364d; font-size: 13px; line-height: 1.45; }
.run-stages { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); margin: 16px 0 0; padding: 0; overflow-x: auto; list-style: none; }.run-stages li { position: relative; display: grid; justify-items: center; min-width: 120px; padding: 0 8px; text-align: center; }.run-stages li:not(:last-child)::after { content: ''; position: absolute; z-index: 0; top: 15px; left: calc(50% + 16px); width: calc(100% - 32px); height: 1px; background: #ccd7e2; }.run-stages li > span { z-index: 1; display: grid; place-items: center; width: 30px; height: 30px; border: 1px solid #aab8c7; border-radius: 50%; color: #607087; background: #fff; font-size: 12px; font-weight: 700; }.run-stages li.is-success > span { border-color: #75caaa; color: #087a58; background: #effbf6; }.run-stages li.is-failed > span { border-color: #ef9b98; color: #c43333; background: #fff1f0; }.run-stages li.is-running > span { border-color: #76aef5; color: #1677d2; background: #eff6ff; }.run-stages li div { margin-top: 8px; }.run-stages strong { display: block; color: #34445a; font-size: 12px; }.run-stages small { display: block; margin-top: 4px; color: #738197; font-size: 10px; line-height: 1.45; }.run-stage-empty { margin: 16px 0 0; padding: 14px; border: 1px dashed #d9e2ec; color: #738197; font-size: 12px; text-align: center; }
:deep(.summary-grid) { display: grid; grid-template-columns: 1fr 1fr; margin: 0 0 16px; border: 1px solid #d9e2ec; border-radius: 6px; overflow: hidden; }:deep(.summary-grid div) { padding: 13px; border-right: 1px solid #d9e2ec; border-bottom: 1px solid #d9e2ec; }:deep(.summary-grid div:nth-child(2n)) { border-right: 0; }:deep(.summary-grid div:nth-last-child(-n+2)) { border-bottom: 0; }:deep(.summary-grid dt) { color: #66758c; font-size: 12px; }:deep(.summary-grid dd) { margin: 5px 0 0; font-weight: 700; }
@media (max-width: 1100px) { .filter-card { grid-template-columns: repeat(3, 1fr); }.health-card dl { grid-template-columns: repeat(3, 1fr); }.health-card footer { flex-direction: column; }.workspace-header { flex-direction: column; }.header-actions { justify-content: flex-start; } }
@media (max-width: 760px) { .flow-steps { grid-template-columns: 1fr 1fr; gap: 16px; }.flow-steps li::after { display: none; }.flow-metrics { grid-template-columns: 1fr 1fr; }.filter-card { grid-template-columns: 1fr; }.health-card dl { grid-template-columns: 1fr 1fr; }.dialog-grid, .job-detail-grid, .run-detail-grid { grid-template-columns: 1fr; }.table-footer { align-items: flex-start; flex-direction: column; } }
</style>
