<template>
  <section class="flash-page">
    <el-button link @click="$emit('back')">← 返回平台活动</el-button><header><div><small>营销管理 / 平台活动</small><h1>Shopee 店内闪购</h1><p>活动按店铺时区显示；计划、同步和执行时间为北京时间。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="data && !data.workers_enabled" title="执行服务尚未启用，已提交任务会保留在队列中。" type="info" :closable="false" />
    <el-skeleton v-if="!data && loading" :rows="6" animated />
    <el-tabs v-if="data" v-model="tab" @tab-change="rememberTab">
      <el-tab-pane name="stores" label="店铺运行">
        <header><div><h2>店铺运行总览</h2><small>{{ configuredStores.length }} 家店铺 · 活动时间按店铺当地时区展示，点击活动查看详情</small></div><div class="toolbar">
          <el-button :disabled="!data.latest_sync_batch" @click="openBatch(data.latest_sync_batch)">查看同步结果</el-button>
          <el-dropdown v-if="can.execute" trigger="click" @command="syncStores"><el-button :disabled="busy">同步店铺活动 ▾</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="selected" :disabled="!selectedStores.length">同步已选店铺</el-dropdown-item><el-dropdown-item command="all" :disabled="!configuredStores.length">同步所有店铺</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
          <el-button v-if="can.configure || can.notifications" @click="openNotifications">飞书通知设置</el-button><el-button v-if="can.plans" @click="plansOpen = true">定时计划</el-button><el-button v-if="can.configure" type="primary" @click="editConfig()">新增店铺</el-button>
        </div></header>
        <div class="toolbar"><span>已选 {{ selectedStores.length }} 家店铺</span><el-button v-if="can.execute" type="primary" :disabled="!runnableStores.length || busy" @click="submit('run', runnableStores)">运行已选 {{ selectedStores.length || '' }}</el-button><el-button :disabled="!data.latest_run_batch" @click="openBatch(data.latest_run_batch)">查看运行结果</el-button><small>最多 3 家店铺并发，同店串行；停用或正在处理的店铺跳过</small></div>
        <el-table :data="configuredStores" border max-height="560" empty-text="暂无闪购配置，请从已授权店铺中新增">
          <el-table-column width="46" fixed="left"><template #header><el-checkbox aria-label="全选店铺" :model-value="allStoresSelected" :indeterminate="selectedStores.length > 0 && !allStoresSelected" @update:model-value="selectAllStores"/></template><template #default="{row}"><el-checkbox :model-value="selectedStores.includes(row.id)" @update:model-value="value => selectRow(selectedStores, row.id, value)" :aria-label="`选择 ${row.name}`" /></template></el-table-column>
          <el-table-column label="店铺" width="150" fixed="left"><template #default="{row}"><strong>{{ row.code }}</strong><small>{{ row.name }}</small><el-tag v-if="!row.enabled" type="info">已停用</el-tag></template></el-table-column>
          <el-table-column prop="stock" label="活动库存" width="95"/><el-table-column prop="runs" label="每次开启时段数" width="125"/>
          <el-table-column label="处理状态" min-width="185"><template #default="{row}">{{ taskLabels[row.latest_task?.status] || '未运行' }}<small>{{ row.latest_task?.message }}</small><small v-if="row.latest_sync">活动同步：{{ taskLabels[row.latest_sync.status] || '待核对' }} · {{ row.latest_sync.message }}</small><el-button v-if="row.latest_task?.batch_id" link @click="openBatch(row.latest_task.batch_id)">查看结果</el-button></template></el-table-column>
          <el-table-column label="飞书接收人" min-width="180"><template #default="{row}"><el-button v-if="can.configure" link type="primary" @click="openNotifications(row)">{{ recipientText(row) }}</el-button><span v-else>{{ recipientText(row) }}</span></template></el-table-column>
          <el-table-column label="处理完成时间" width="175"><template #default="{row}">{{ flashTime(row.latest_task?.finished_at) }}<small>北京时间</small></template></el-table-column>
          <el-table-column label="最近同步（北京时间）" width="185"><template #default="{row}">{{ row.last_synced_at ? flashTime(row.last_synced_at) : '尚未成功同步' }}<small v-if="row.latest_sync && row.latest_sync.status !== 'succeeded'">最近尝试：{{ taskLabels[row.latest_sync.status] || '待核对' }}</small></template></el-table-column>
          <el-table-column label="正在进行的活动" min-width="255"><template #default="{row}"><el-button v-for="a in row.current || []" :key="a.id" class="activity-cell" link type="primary" @click="showActivity(a)">{{ activityRange(a) }}；{{ a.item_count ?? '未知' }} 商品</el-button><span v-if="!row.current?.length">{{ row.last_synced_at ? '—' : '未同步' }}</span></template></el-table-column>
          <el-table-column v-for="n in 5" :key="n" :label="'接下来的活动' + n" min-width="255"><template #default="{row}"><el-button v-if="row.upcoming?.[n-1]" class="activity-cell" link type="primary" @click="showActivity(row.upcoming[n-1])">{{ activityRange(row.upcoming[n-1]) }}；{{ row.upcoming[n-1].item_count ?? '未知' }} 商品</el-button><span v-else>{{ row.last_synced_at ? '—' : '未同步' }}</span></template></el-table-column>
          <el-table-column label="操作" min-width="225" fixed="right"><template #default="{row}"><el-button v-if="can.configure" link type="primary" :disabled="busy || storeBusy(row)" @click="editConfig(row)">编辑</el-button><el-button v-if="can.execute" link type="primary" :disabled="busy || !row.enabled || storeBusy(row)" @click="submit('run',[row.id])">运行</el-button><el-button v-if="can.configure" link :disabled="busy || storeBusy(row)" @click="toggleConfig(row)">{{ row.enabled ? '停用' : '启用' }}</el-button><el-button v-if="can.delete" link type="danger" :disabled="busy || row.enabled || storeBusy(row)" @click="deleteConfig(row)">删除配置</el-button></template></el-table-column>
        </el-table><p class="hint">活动格来自最近同步结果，未同步不等于没有活动。先停用才能删除；删除保留平台活动与历史记录。</p>
      </el-tab-pane>
      <el-tab-pane name="activities" label="活动管理">
        <section class="filter-panel"><div class="toolbar"><h2>筛选活动</h2><el-input v-model="filters.activity_id" placeholder="搜索活动编号" clearable style="max-width:320px" @change="queryActivities"/></div>
          <div class="toolbar"><span>店铺</span><el-button :type="!filters.store_id ? 'primary' : ''" text @click="filterStore(null)">全部</el-button><el-button v-for="store in data.stores" :key="store.id" :type="filters.store_id === store.id ? 'primary' : ''" text @click="filterStore(store.id)">{{ store.code }}（{{ store.activity_count || 0 }}）</el-button></div>
          <div class="toolbar"><span>活动时间</span><el-button v-for="preset in datePresets" :key="preset.value" :type="datePreset === preset.value ? 'primary' : ''" text @click="setDatePreset(preset.value)">{{ preset.label }}</el-button><template v-if="datePreset === 'custom'"><el-date-picker v-model="filters.date_from" value-format="YYYY-MM-DD" placeholder="活动开始日期（店铺当地）" @change="queryActivities"/><el-date-picker v-model="filters.date_to" value-format="YYYY-MM-DD" placeholder="结束日期（店铺当地）" @change="queryActivities"/></template><el-button text @click="resetActivities">重置筛选</el-button></div>
          <small>活动时间按店铺当地日期筛选；快捷日期包含今天。同步所有活动仍涵盖全部配置店铺。</small>
        </section>
        <el-tabs v-model="filters.activity_state" @tab-change="queryActivities"><el-tab-pane v-for="state in activityStates" :key="state.value" :name="state.value" :label="`${state.label} (${data.activity_counts?.[state.key] || 0})`"/></el-tabs>
        <div class="toolbar"><el-button :disabled="!data.latest_sync_batch" @click="openBatch(data.latest_sync_batch)">查看同步结果</el-button><el-button v-if="can.execute" :disabled="!selectedActivities.length || busy" @click="syncSelectedActivities">同步已选活动</el-button><el-button v-if="can.execute" :disabled="!configuredStores.length || busy" @click="syncStores('all')">同步所有活动</el-button><el-button v-if="can.execute" type="primary" :disabled="busy || !configuredStores.length" @click="openCopyPicker">复制已有活动</el-button></div>
        <div class="toolbar"><span>已选 {{ selectedActivities.length }} 场</span><el-button v-if="can.execute" :disabled="busy || !canToggleSelected" @click="toggleSelected(1)">批量开启</el-button><el-button v-if="can.execute" :disabled="busy || !canToggleSelected" @click="toggleSelected(2)">批量关闭</el-button><small v-if="bulkMessage">{{ bulkMessage }}</small></div>
        <el-table :data="data.activities" max-height="560" border empty-text="暂无活动，请先同步店铺">
          <el-table-column width="46"><template #header><el-checkbox aria-label="全选本页活动" :model-value="allActivitiesSelected" @update:model-value="selectAllActivities"/></template><template #default="{row}"><el-checkbox :model-value="selectedActivities.includes(row.id)" @update:model-value="value => selectRow(selectedActivities, row.id, value)" :aria-label="`选择活动 ${row.platform_id}`"/></template></el-table-column>
          <el-table-column label="活动时间（店铺时区）" min-width="225"><template #default="{row}">{{ flashTime(row.starts_at, row.timezone) }}<small>至 {{ flashTime(row.ends_at, row.timezone) }} · {{ row.timezone }}</small></template></el-table-column>
          <el-table-column label="店铺 / 活动编号" min-width="175"><template #default="{row}">{{ row.store_name }}<small>{{ row.platform_id }}</small></template></el-table-column>
          <el-table-column label="启用 / 总商品" min-width="125"><template #default="{row}"><el-button link type="primary" @click="showActivity(row)">{{ row.enabled_count ?? '未知' }} / {{ row.item_count ?? '未知' }}</el-button></template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{row}">{{ activityStatus(row) }}</template></el-table-column>
          <el-table-column label="最近同步（北京时间）" min-width="150"><template #default="{row}">{{ flashTime(row.synced_at) }}</template></el-table-column>
          <el-table-column label="平台开关" width="100"><template #default="{row}"><el-switch :model-value="row.status === 1" :disabled="!can.execute || busy || !future(row)" @change="value => submit('toggle',[row.store_id],{activity_id:row.platform_id,desired_status:value ? 1 : 2})"/></template></el-table-column>
          <el-table-column label="操作" min-width="235" fixed="right"><template #default="{row}"><el-button link type="primary" @click="showActivity(row)">商品详情</el-button><el-button v-if="can.execute" link type="primary" :disabled="busy || !row.item_count" @click="copyActivity = row">复制</el-button><el-button v-if="can.execute" link type="primary" :disabled="busy" @click="submit('sync',[row.store_id],{activity_ids:[row.id]})">同步</el-button><el-button v-if="can.delete" link type="danger" :disabled="busy || !future(row)" @click="deleteActivity(row)">删除</el-button></template></el-table-column>
        </el-table><el-pagination v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="[25,50,100]" :total="data.activity_total" layout="prev, pager, next, sizes, total" @size-change="queryActivities" @current-change="load"/>
      </el-tab-pane>
      <el-tab-pane name="history" label="执行记录">
        <div class="toolbar filters"><el-select v-model="filters.history_store_id" clearable placeholder="全部店铺（含已删除配置）" @change="queryHistory"><el-option v-for="store in data.stores" :key="store.id" :value="store.id" :label="store.code + ' · ' + store.name"/></el-select><el-select v-model="filters.history_source" clearable placeholder="全部触发方式" @change="queryHistory"><el-option value="manual" label="手动"/><el-option value="scheduled" label="定时"/></el-select><el-select v-model="filters.history_status" clearable placeholder="全部结果" @change="queryHistory"><el-option v-for="(label,status) in taskLabels" :key="status" :value="status" :label="label"/></el-select><el-button @click="load">刷新记录</el-button></div>
        <el-table :data="data.batches" border row-key="id" empty-text="暂无执行记录">
          <el-table-column type="expand"><template #default="{row:batch}"><el-table :data="batch.tasks" border><el-table-column prop="store_name" label="店铺"/><el-table-column label="已处理 / 计划时段"><template #default="{row}">{{ row.completed }} / {{ row.requested }}</template></el-table-column><el-table-column label="处理结果" min-width="220"><template #default="{row}">{{ taskLabels[row.status] || '待核对' }}<small>{{ row.message }}</small></template></el-table-column><el-table-column label="完成时间"><template #default="{row}">{{ flashTime(row.finished_at) }}</template></el-table-column><el-table-column label="操作"><template #default><el-button link type="primary" @click="openBatch(batch.id)">详情</el-button></template></el-table-column></el-table></template></el-table-column>
          <el-table-column label="批次 / 执行时间" min-width="210"><template #default="{row}">{{ flashTime(row.created_at) }}<small>{{ row.id }}</small></template></el-table-column><el-table-column label="触发方式" width="130"><template #default="{row}">{{ sourceLabel(row) }}</template></el-table-column><el-table-column label="店铺" min-width="200"><template #default="{row}">{{ row.tasks.length }} 家<small>{{ row.tasks.map(t => t.store_name).join('、') }}</small></template></el-table-column><el-table-column label="处理结果" min-width="180"><template #default="{row}">{{ batchSummary(row) }}</template></el-table-column><el-table-column label="完成时间（北京）" min-width="175"><template #default="{row}">{{ flashTime(row.finished_at) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{row}"><el-button link type="primary" @click="openBatch(row.id)">查看详情</el-button></template></el-table-column>
        </el-table><el-pagination v-model:current-page="filters.history_page" :page-size="50" :total="data.batch_total" layout="prev, pager, next, total" @current-change="load"/>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="configOpen" title="店铺闪购配置" append-to-body width="640px" class="flash-dialog"><el-form label-position="top"><el-form-item label="店铺"><el-select v-model="config.store_id" :disabled="Boolean(config.version)" filterable><el-option v-for="s in data?.stores || []" :key="s.id" :label="s.name" :value="s.id" :disabled="s.configured && !config.version"/></el-select></el-form-item><div class="form-grid"><el-form-item label="活动库存（1～999999）"><el-input-number v-model="config.stock" :min="1" :max="999999" :precision="0"/></el-form-item><el-form-item label="每次开启时段数"><el-input-number v-model="config.runs" :min="1" :max="999999" :precision="0"/></el-form-item></div><el-form-item label="通知接收方式"><el-radio-group v-model="config.notification_mode"><el-radio value="owner">店铺负责人</el-radio><el-radio value="custom">自定义人员</el-radio><el-radio value="fallback">使用兜底</el-radio></el-radio-group></el-form-item><el-form-item v-if="config.notification_mode === 'custom'" label="接收人（可多选）"><el-select v-model="config.recipient_ids" multiple filterable><el-option v-for="p in data?.people || []" :key="p.id" :label="p.name" :value="p.id"/></el-select></el-form-item><p>新增默认停用；运行中不能修改。负责人不可用时使用有效兜底人员。</p></el-form><template #footer><el-button @click="configOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveConfig">保存</el-button></template></el-dialog>
    <el-dialog v-model="plansOpen" title="定时计划" width="1100px" class="flash-dialog">
      <div class="toolbar"><p>先增加执行时间点，再选择该时间点运行的店铺。同一家店可加入多个时间点。</p><el-button type="primary" @click="editPlan()">新增执行时间点</el-button></div>
      <el-table :data="data?.plans || []" border max-height="480" empty-text="尚未设置时间点，新增后默认暂停"><el-table-column label="执行时间点（北京时间）" min-width="190"><template #default="{row}">{{ row.kind === 'daily' ? '每天' : row.date }} {{ row.time }}</template></el-table-column><el-table-column label="执行店铺" min-width="250"><template #default="{row}"><el-tag v-for="id in row.store_ids" :key="id">{{ storeName(id) }}</el-tag><span v-if="!row.store_ids.length">待选择店铺</span></template></el-table-column><el-table-column label="状态" width="100"><template #default="{row}">{{ row.enabled ? '已启用' : '已暂停' }}</template></el-table-column><el-table-column label="下次执行" min-width="175"><template #default="{row}">{{ row.enabled ? flashTime(row.next_due) : '—' }}</template></el-table-column><el-table-column label="操作" min-width="280"><template #default="{row}"><el-button link @click="editPlan(row)">编辑时间</el-button><el-button link type="primary" @click="editPlan(row, true)">选择店铺</el-button><el-button link :disabled="busy || (!row.enabled && !row.store_ids.length)" @click="enablePlan(row)">{{ row.enabled ? '暂停' : '启用' }}</el-button><el-button link type="danger" :disabled="busy || row.enabled" @click="deletePlan(row)">删除</el-button></template></el-table-column></el-table>
      <p>修改时间或店铺名单后计划暂停，需重新启用。服务器执行，错过时间不补跑；同店互斥。</p><template #footer><el-button @click="plansOpen = false">关闭</el-button></template>
    </el-dialog>
    <el-dialog v-model="planEditorOpen" :title="planMembersOnly ? '选择该时间点执行的店铺' : '执行时间点'" width="560px" class="flash-dialog" append-to-body><el-form label-position="top"><template v-if="!planMembersOnly"><el-form-item label="执行频率"><el-radio-group v-model="plan.kind"><el-radio value="once">单次</el-radio><el-radio value="daily">每天重复</el-radio></el-radio-group></el-form-item><el-form-item v-if="plan.kind === 'once'" label="执行日期"><el-date-picker v-model="plan.date" value-format="YYYY-MM-DD"/></el-form-item><el-form-item label="执行时间（北京时间 UTC+08:00）"><el-time-picker v-model="plan.time" format="HH:mm" value-format="HH:mm"/></el-form-item><p>先保存时间点，再点击“选择店铺”。计划保存后暂停。</p></template><template v-else><p>{{ plan.kind === 'daily' ? '每天' : plan.date }} {{ plan.time }} · 北京时间</p><el-form-item label="执行店铺"><el-select v-model="plan.store_ids" multiple filterable><el-option v-for="store in configuredStores" :key="store.id" :label="store.code + (store.enabled ? '' : '（已停用）')" :value="store.id" :disabled="!store.enabled && !plan.store_ids.includes(store.id)"/></el-select></el-form-item></template><p v-if="planConflict" class="warning">存在同店同时间计划；各计划分别执行，同店任务会排队。</p></el-form><template #footer><el-button @click="planEditorOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="savePlan">{{ planMembersOnly ? '保存店铺' : '保存时间点' }}</el-button></template></el-dialog>
    <el-dialog v-model="copyPickerOpen" title="选择已有活动" width="700px" class="flash-dialog"><div class="toolbar filters"><el-select v-model="copyStore" placeholder="店铺" @change="loadCopySources"><el-option v-for="store in configuredStores" :key="store.id" :value="store.id" :label="store.code"/></el-select><el-input v-model="copyQuery" placeholder="活动编号" @change="loadCopySources"/><el-button @click="loadCopySources">查询来源</el-button></div><el-table :data="copySources" max-height="400"><el-table-column label="来源活动"><template #default="{row}">{{ row.platform_id }}<small>{{ activityRange(row) }}</small></template></el-table-column><el-table-column prop="item_count" label="商品数"/><el-table-column label="操作"><template #default="{row}"><el-button link :disabled="!row.item_count" @click="copyActivity = row; copyPickerOpen = false">选择并复制</el-button></template></el-table-column></el-table><el-pagination v-model:current-page="copyPage" :page-size="50" :total="copyTotal" layout="prev, pager, next" @current-change="fetchCopySources"/></el-dialog>
    <el-dialog v-model="notificationsOpen" title="飞书通知设置" width="900px" class="flash-dialog" append-to-body :close-on-click-modal="false">
      <div class="toolbar"><p>默认跟随店铺负责人；自定义人员失效时转发全局兜底。</p><el-button :loading="loading" @click="load">刷新人员与负责人</el-button></div>
      <el-form label-position="top"><el-form-item label="全局兜底接收人（所有店铺共用）"><el-select :disabled="!can.notifications" v-model="fallbackIds" multiple filterable aria-label="兜底接收人"><el-option v-for="p in data?.people || []" :key="p.id" :label="p.name" :value="p.id"/></el-select></el-form-item></el-form>
      <el-table :data="visibleNotificationRows" max-height="420"><el-table-column prop="code" label="店铺" width="120"/><el-table-column label="接收方式" width="190"><template #default="{row}"><el-select v-model="row.notification_mode" :disabled="!can.configure" :aria-label="`${row.code} 接收方式`"><el-option value="owner" label="跟随店铺负责人"/><el-option value="custom" label="自定义人员"/><el-option value="fallback" label="使用全局兜底"/></el-select></template></el-table-column><el-table-column label="实际接收人员" min-width="280"><template #default="{row}"><el-select v-if="row.notification_mode === 'custom'" v-model="row.recipient_ids" :disabled="!can.configure" multiple filterable :aria-label="`${row.code} 接收人员`"><el-option v-for="person in data?.people || []" :key="person.id" :value="person.id" :label="person.name"/></el-select><small>{{ recipientText({...row,owner_id:data?.stores.find(store => store.id === row.id)?.owner_id},fallbackIds) }}</small></template></el-table-column></el-table>
      <p>仅使用当前租户有效飞书人员。修改只影响后续批次，已发送通知不补发；重试保留原批次接收人。</p><template #footer><el-button @click="notificationsOpen = false">取消</el-button><el-button v-if="can.configure || can.notifications" type="primary" :loading="busy" @click="saveNotifications">保存设置</el-button></template>
    </el-dialog>
    <FlashActivityDetail v-if="detailOpen && detail" :key="detail.id" :activity="detail" @close="detailOpen = false"/>
    <FlashCopyDialog v-if="copyActivity" :activity="copyActivity" @close="copyActivity = null" @submitted="id => { copyActivity = null; openBatch(id); load(); }"/>
    <FlashBatchDialog v-if="batchId" :batch-id="batchId" :can-execute="can.execute" @close="closeTask"/>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { flashRequest, flashTime, taskLabels } from '../../api/flashSales';
import FlashCopyDialog from './FlashCopyDialog.vue';
import FlashActivityDetail from './FlashActivityDetail.vue';
import FlashBatchDialog from './FlashBatchDialog.vue';
defineEmits(['back']);
const route = useRoute(), router = useRouter();
const tab = ref(['stores','activities','history'].includes(route.query.tab) ? route.query.tab : 'stores');
const data = ref(null), loading = ref(false), busy = ref(false), error = ref('');
const can = computed(() => data.value?.capabilities || {});
const configuredStores = computed(() => data.value?.stores.filter(s => s.configured) || []);
function selectRow(rows, id, selected) {const index = rows.indexOf(id);if (selected && index < 0) rows.push(id);else if (!selected && index >= 0) rows.splice(index,1);}
const filters = reactive({store_id:null,activity_id:'',activity_state:'',date_from:null,date_to:null,page:1,page_size:50,history_page:1,history_store_id:null,history_source:'',history_status:''});
const selectedStores = ref([]), selectedActivities = ref([]), batchId = ref(route.query.batch || null);
watch(() => route.query.tab,value => {tab.value = ['stores','activities','history'].includes(value) ? value : 'stores';});
watch(() => route.query.batch,value => {batchId.value = typeof value === 'string' && value ? value : null;});
const configOpen = ref(false), config = reactive({}), plansOpen = ref(false), plan = reactive({});
const notificationsOpen = ref(false), fallbackIds = ref([]), copyActivity = ref(null), detailOpen = ref(false), detail = ref(null);
let sequence = 0, workspaceKey = '';
const activityStores = reactive({}), pendingRequests = reactive({});
function storageKey() {return workspaceKey ? `flash-sales:${workspaceKey}` : null;}
function persistSelection() {try {if (storageKey()) localStorage.setItem(storageKey(),JSON.stringify({stores:selectedStores.value,activities:selectedActivities.value,activityStores,pendingRequests}));} catch {/* Storage may be disabled; API idempotency still applies in this page. */}}
function restoreSelection(key) {
  if (workspaceKey === key) return;
  workspaceKey = key;
  selectedStores.value = [];selectedActivities.value = [];
  Object.keys(activityStores).forEach(k => delete activityStores[k]);
  Object.keys(pendingRequests).forEach(k => delete pendingRequests[k]);
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey()) || '{}');
    selectedStores.value = Array.isArray(saved.stores) ? saved.stores.filter(Number.isInteger) : [];
    selectedActivities.value = Array.isArray(saved.activities) ? saved.activities.filter(Number.isInteger) : [];
    Object.assign(activityStores,saved.activityStores || {});
    Object.assign(pendingRequests,saved.pendingRequests || {});
  } catch {/* Ignore an invalid local UI snapshot. */}
}
watch([selectedStores,selectedActivities,activityStores,pendingRequests],persistSelection,{deep:true});
const message = e => e?.response?.data?.message || e?.message || '操作未完成';
async function action(work) { if (busy.value) return; busy.value = true; try {await work();} catch(e) {ElMessage.error(message(e));} finally {busy.value = false;} }
async function load() { const seq = ++sequence; loading.value = true; try {const result = await flashRequest('workspace/', 'get', null, filters); if (seq === sequence) {restoreSelection(result.workspace_key || 'preview');data.value = result;
  const allowed = new Set(result.stores.map(s => s.id));
  selectedStores.value = selectedStores.value.filter(id => allowed.has(id));
  result.activities.forEach(a => {activityStores[a.id] = a.store_id;});
  selectedActivities.value = selectedActivities.value.filter(id => allowed.has(activityStores[id]));
  error.value = '';}} catch(e) {if (seq === sequence) error.value = message(e);} finally {if (seq === sequence) loading.value = false;} }
function rememberTab() {router.replace({query:{...route.query,activity:'flash',tab:tab.value}});}
function resetPlan() {Object.keys(plan).forEach(k => delete plan[k]); Object.assign(plan,{name:'',kind:'once',date:'',time:'09:00',store_ids:[]});} resetPlan();
const planConflict = computed(() => data.value?.plans.some(p => p.id !== plan.id && p.time === plan.time && (p.kind === 'daily' || plan.kind === 'daily' || p.date === plan.date) && p.store_ids.some(id => plan.store_ids.includes(id))));
function editConfig(row) {Object.keys(config).forEach(k => delete config[k]); Object.assign(config,{store_id:row?.id,stock:row?.stock ?? 1,runs:row?.runs ?? 1,version:row?.version,notification_mode:row?.notification_mode || 'owner',recipient_ids:[...(row?.recipient_ids || [])]}); configOpen.value = true;}
function saveConfig() {action(async () => {if (!config.store_id) throw new Error('请选择店铺'); const {store_id,...values} = config; await flashRequest(`configs/${store_id}/`,'put',values); configOpen.value = false; await load();});}
function toggleConfig(row) {action(async () => {await flashRequest(`configs/${row.id}/`,'put',{version:row.version,enabled:!row.enabled}); await load();});}
async function deleteConfig(row) {try {await ElMessageBox.confirm(`删除 ${row.name} 的闪购配置？活动和历史会保留。`,'删除配置',{type:'warning'});} catch {return;} action(async () => {await flashRequest(`configs/${row.id}/`,'delete',{version:row.version}); await load();});}
async function submit(operation,store_ids,extra={}) {await action(async () => {if (!store_ids.length) throw new Error('请选择店铺'); const values = {store_ids:[...store_ids].sort((a,b)=>a-b),operation,...extra};
  const key = JSON.stringify(values);
  const request_id = pendingRequests[key] || (pendingRequests[key] = crypto.randomUUID());persistSelection();
  let result;
  try {result = await flashRequest('batches/','post',{request_id,...values});}
  catch (e) {if (e?.response?.status >= 400 && e?.response?.status < 500) delete pendingRequests[key];throw e;}
  delete pendingRequests[key];persistSelection();openBatch(result.id); await load();});}
function syncSelectedActivities() {submit('sync',[...new Set(selectedActivities.value.map(id => activityStores[id]))],{activity_ids:[...selectedActivities.value]});}
function savePlan() {action(async () => {const {id,enabled,next_due,...values} = plan; await flashRequest(id ? `plans/${id}/` : 'plans/','post',values); planEditorOpen.value = false; resetPlan(); await load(); ElMessage.success('计划已保存并暂停');});}
function enablePlan(row) {action(async () => {await flashRequest(`plans/${row.id}/`,'post',{enabled:!row.enabled,version:row.version}); await load();});}
const notificationRows = ref([]), notificationOriginals = ref({}), notificationStoreId = ref(null);
let originalFallback = '';
const visibleNotificationRows = computed(() => notificationRows.value.filter(row => !notificationStoreId.value || row.id === notificationStoreId.value));
function notificationValues(row) {return {store_id:row.id,version:row.version,notification_mode:row.notification_mode,recipient_ids:row.notification_mode === 'custom' ? [...row.recipient_ids].sort((a,b)=>a-b) : []};}
function openNotifications(store) {fallbackIds.value = [...data.value.fallback_ids];originalFallback = JSON.stringify([...fallbackIds.value].sort((a,b)=>a-b));notificationStoreId.value = store?.id || null;notificationRows.value = configuredStores.value.map(row => ({...row,notification_mode:row.notification_mode || 'owner',recipient_ids:[...(row.recipient_ids || [])]}));notificationOriginals.value = Object.fromEntries(notificationRows.value.map(row => [row.id,JSON.stringify(notificationValues(row))]));notificationsOpen.value = true;}
function saveNotifications() {action(async () => {const values = {};
  if (can.value.notifications && JSON.stringify([...fallbackIds.value].sort((a,b)=>a-b)) !== originalFallback) values.user_ids = [...fallbackIds.value];
  if (can.value.configure) {const changed = notificationRows.value.map(notificationValues).filter(row => JSON.stringify(row) !== notificationOriginals.value[row.store_id]);if (changed.length) values.stores = changed;}
  if (Object.keys(values).length) await flashRequest('notifications/','put',values);
  notificationsOpen.value = false;await load();ElMessage.success('通知设置已保存，已提交批次的接收人保持不变');
});}
function future(row) {return new Date(row.starts_at).getTime() > Date.now() && row.status !== 0;}
function activityStatus(row) {return row.status === 0 ? '已删除' : new Date(row.ends_at) <= new Date() ? '已过期' : new Date(row.starts_at) > new Date() ? '未进行' : '进行中';}
async function deleteActivity(row) {try {await ElMessageBox.confirm(`确认删除 ${row.store_name} 活动 ${row.platform_id}？此操作会提交平台。`,'删除活动',{type:'warning',confirmButtonText:'确认删除'});} catch {return;} submit('delete',[row.store_id],{activity_id:row.platform_id,confirmed:true});}
function showActivity(row) {detail.value = row; detailOpen.value = true;}
function sourceLabel(row) {return row.source === 'post_sync' ? '执行后同步' : row.source === 'scheduled' ? '定时计划' : ({run:'手动运行',copy:'复制活动',sync:'同步活动',toggle:'修改活动状态',delete:'删除活动'}[row.operation] || '历史记录');}
function openBatch(id) {batchId.value = id; router.replace({query:{...route.query,batch:id}});}
function closeTask() {batchId.value = null; const {batch,...query} = route.query; router.replace({query});}
const datePreset = ref('all');
const datePresets = [{value:'all',label:'全部'},{value:'3',label:'未来3天'},{value:'7',label:'未来7天'},{value:'30',label:'未来30天'},{value:'custom',label:'自定义日期'}];
const activityStates = [{value:'',key:'all',label:'全部'},{value:'current',key:'current',label:'进行中'},{value:'upcoming',key:'upcoming',label:'未进行'},{value:'expired',key:'expired',label:'已过期'}];
const allStoresSelected = computed(() => configuredStores.value.length > 0 && configuredStores.value.every(s => selectedStores.value.includes(s.id)));
const allActivitiesSelected = computed(() => data.value?.activities.length > 0 && data.value.activities.every(a => selectedActivities.value.includes(a.id)));
const runnableStores = computed(() => configuredStores.value.filter(s => selectedStores.value.includes(s.id) && s.enabled && !storeBusy(s)).map(s => s.id));
function storeBusy(store) {return ['queued','running','waiting','confirming'].includes(store.latest_task?.status);}
function selectAllStores(value) {selectedStores.value = value ? configuredStores.value.map(s => s.id) : [];}
function selectAllActivities(value) {for (const a of data.value.activities) selectRow(selectedActivities.value,a.id,value);}
function syncStores(scope) {submit('sync',scope === 'all' ? configuredStores.value.map(s => s.id) : selectedStores.value);}
function activityRange(row) {return `${flashTime(row.starts_at,row.timezone)} — ${flashTime(row.ends_at,row.timezone)}`;}
function storeName(id) {return data.value?.stores.find(s => s.id === id)?.code || '未记录店铺';}
function recipientText(store, fallbackValues = data.value?.fallback_ids || []) {
  const people = new Map((data.value?.people || []).map(p => [p.id,p.name]));
  const fallback = fallbackValues.filter(id => people.has(id));
  const primary = store.notification_mode === 'custom' ? store.recipient_ids || [] : store.owner_id ? [store.owner_id] : [];
  const valid = primary.length && primary.every(id => people.has(id));
  if (store.notification_mode !== 'fallback' && valid) return primary.map(id => people.get(id)).join('、');
  return (store.notification_mode === 'fallback' ? '全局兜底：' : '主接收人不可用，兜底：') + (fallback.map(id => people.get(id)).join('、') || '无有效接收人');
}
function queryActivities() {filters.page = 1;selectedActivities.value = [];load();}
function filterStore(id) {filters.store_id = id;queryActivities();}
function setDatePreset(value) {
  datePreset.value = value;
  if (value === 'all' || value === 'custom') {filters.date_from = null;filters.date_to = null;}
  else {const start = new Date(), end = new Date();end.setDate(end.getDate() + Number(value) - 1);const fmt = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;filters.date_from = fmt(start);filters.date_to = fmt(end);}
  queryActivities();
}
function resetActivities() {Object.assign(filters,{store_id:null,activity_id:'',activity_state:'',date_from:null,date_to:null});datePreset.value = 'all';queryActivities();}
function queryHistory() {filters.history_page = 1;load();}
function batchSummary(batch) {const counts = {};for (const task of batch.tasks) {const label = taskLabels[task.status] || '待核对';counts[label] = (counts[label] || 0) + 1;}return Object.entries(counts).map(([label,count]) => `${label} ${count}`).join(' · ');}
const planEditorOpen = ref(false), planMembersOnly = ref(false);
function editPlan(row, membersOnly = false) {resetPlan();if (row) Object.assign(plan,{...row,store_ids:[...row.store_ids]});planMembersOnly.value = membersOnly;planEditorOpen.value = true;}
async function deletePlan(row) {try {await ElMessageBox.confirm('删除此时间点？已有执行记录会保留。','删除计划',{type:'warning'});} catch {return;}action(async () => {await flashRequest(`plans/${row.id}/`,'delete',{version:row.version});await load();});}
const canToggleSelected = computed(() => selectedActivities.value.length > 0 && selectedActivities.value.every(id => {const a = data.value?.activities.find(a => a.id === id);return !a || future(a);}));
const bulkMessage = ref('');
async function toggleSelected(status) {
  await action(async () => {
    if (!canToggleSelected.value) throw new Error('请选择尚未开始的活动');
    const rows = await Promise.all(selectedActivities.value.map(id => flashRequest(`activities/${id}/`)));
    if (rows.some(row => !future(row))) throw new Error('选中活动已有开始或删除，本次未提交，请刷新后重新选择');
    let accepted = 0;bulkMessage.value = '';
    for (const row of rows) {
      const values = {store_ids:[row.store_id],operation:'toggle',activity_id:row.platform_id,desired_status:status};
      const key = JSON.stringify(values);const request_id = pendingRequests[key] || (pendingRequests[key] = crypto.randomUUID());persistSelection();
      try {const result = await flashRequest('batches/','post',{request_id,...values});delete pendingRequests[key];selectRow(selectedActivities.value,row.id,false);openBatch(result.id);accepted++;}
      catch(e) {if (e?.response?.status >= 400 && e?.response?.status < 500) delete pendingRequests[key];bulkMessage.value = `已提交 ${accepted}/${rows.length} 场；后续未提交，可查看执行记录`;persistSelection();throw e;}
      persistSelection();
    }
    bulkMessage.value = `已提交 ${accepted} 场，平台结果请查看执行记录`;await load();
  });
}
const copyPickerOpen = ref(false), copyStore = ref(null), copyQuery = ref(''), copyPage = ref(1), copyTotal = ref(0), copySources = ref([]);
function openCopyPicker() {copyStore.value = filters.store_id || configuredStores.value[0]?.id;copyPickerOpen.value = true;loadCopySources();}
function loadCopySources() {copyPage.value = 1;fetchCopySources();}
function fetchCopySources() {action(async () => {if (!copyStore.value) return;const result = await flashRequest('workspace/','get',null,{store_id:copyStore.value,activity_id:copyQuery.value,page:copyPage.value});copySources.value = result.activities;copyTotal.value = result.activity_total;});}
let refreshTimer;
onMounted(() => {load();refreshTimer = setInterval(() => {if (!busy.value && !loading.value) load();},15000);});
onBeforeUnmount(() => {clearInterval(refreshTimer);sequence++;});
</script>

<style scoped>
.activity-cell {height:auto;white-space:normal;display:block;text-align:left;line-height:1.6;margin:4px 0!important}.filter-panel {padding:16px;border:1px solid var(--el-border-color);border-radius:6px;margin-bottom:16px}.hint {color:var(--el-text-color-secondary);font-size:13px}
.flash-page {padding:22px 22px 90px;color:var(--el-text-color-primary)} header,.toolbar {display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px} header {justify-content:space-between} h1 {font-size:24px;margin:6px 0 10px} p {line-height:1.6} small,header p {display:block;color:var(--el-text-color-secondary);font-size:13px;white-space:normal} small {margin-top:4px} .form-grid {display:grid;grid-template-columns:1fr 1fr;gap:16px} :deep(.el-select) {width:100%} :deep(.el-pagination .el-select) {width:110px} .filters :deep(.el-select),.filters :deep(.el-input) {width:180px} .plan-form {padding:16px 0} .warning {color:var(--el-color-warning-dark-2)} :deep(.el-alert) {margin-bottom:16px} :deep(.el-pagination) {margin-top:16px;flex-wrap:wrap} :deep(.el-table) {width:100%} @media(max-width:600px) {.flash-page {padding:12px 8px 90px}.form-grid {grid-template-columns:1fr;gap:0}.toolbar {gap:8px}.toolbar :deep(.el-button) {margin-left:0}}
</style>
<style>
.el-dialog.flash-dialog {max-width:calc(100vw - 24px);margin-top:5vh}.flash-dialog .el-dialog__body {max-height:70vh;overflow:auto}.flash-dialog .el-dialog__footer {display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.flash-dialog .el-dialog__footer .el-button {margin-left:0}
</style>
