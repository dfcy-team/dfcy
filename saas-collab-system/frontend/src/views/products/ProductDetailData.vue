<template>
  <section class="business-page">
    <header class="page-head">
      <div>
        <h1>商品明细数据</h1>
        <p>维护旧 SKU 与新 SPU/SKU 的对应关系。导入后可逐条补充信息，再生成新编码。</p>
      </div>
      <div class="header-actions">
        <el-button data-testid="detail-import-template" @click="downloadTemplate">下载导入模板</el-button>
        <el-select
          v-if="canManage"
          v-model="importMode"
          data-testid="detail-import-mode"
          class="import-mode-control"
          aria-label="导入模式"
        >
          <el-option label="自动导入（新增或更新）" value="auto" />
          <el-option label="仅导入新增" value="create" />
          <el-option label="仅更新已有记录" value="update" />
        </el-select>
        <el-button v-if="canManage" data-testid="image-batch-open" @click="openImageBatch">批量导入图片</el-button>
        <el-button v-if="canManage" data-testid="detail-import-button" type="primary" @click="$refs.file?.click()">导入商品</el-button>
        <el-button v-if="canManage" @click="openBulk">批量修改</el-button>
        <input ref="file" data-testid="detail-import-file" hidden type="file" accept=".csv,text/csv" @change="importFile" />
      </div>
    </header>

    <div class="workspace">
      <aside class="category-panel">
        <div class="panel-title">
          <strong>分类目录</strong>
          <el-button link @click="selectCategory(null)">全部</el-button>
        </div>
        <el-input
          v-model="categorySearch"
          clearable
          placeholder="搜索分类"
          @input="categoryTreeRef?.filter(categorySearch)"
        />
        <el-tree
          ref="categoryTreeRef"
          :data="categoryTree"
          node-key="id"
          :props="{ label: 'displayName', children: 'children' }"
          :filter-node-method="filterCategory"
          :expand-on-click-node="false"
          default-expand-all
          highlight-current
          @node-click="selectCategory"
        />
      </aside>

      <main class="content-panel">
        <el-form class="filters" inline @submit.prevent="search">
          <el-form-item label="全局搜索">
            <el-input
              v-model="filters.search"
              clearable
              class="search-control"
              placeholder="旧/新 SPU、SKU、SKU商品名称"
              @keyup.enter="search"
            />
          </el-form-item>
          <el-form-item label="商品状态">
            <el-select v-model="filters.sku_status" class="status-control">
              <el-option label="全部状态" value="all" />
              <el-option label="在售" value="active" />
              <el-option label="下架" value="inactive" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="search">查询</el-button>
            <el-button @click="reset">重置</el-button>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="message"
          :title="message"
          :type="messageType"
          show-icon
          closable
          @close="message = ''"
        />

        <el-table
          data-testid="product-detail-data-table"
          v-loading="loading"
          :data="rows"
          row-key="id"
          border
          stripe
          empty-text="暂无商品明细数据"
          class="detail-table"
          :row-class-name="productRowClassName"
          :row-style="productRowStyle"
          @selection-change="selectedRows = $event"
        >
          <el-table-column type="index" label="序号" width="70" fixed="left" :index="(page - 1) * pageSize + 1" />
          <el-table-column v-if="canManage" type="selection" width="48" fixed="left" reserve-selection />
          <el-table-column label="图片" width="92" align="center" fixed="left">
            <template #default="{ row }">
              <el-image
                v-if="row.image_url || row.image"
                :data-testid="`product-detail-image-${row.id}`"
                class="product-image-thumb"
                :src="resolveImageUrl(row.image_url || row.image)"
                :preview-src-list="[resolveImageUrl(row.image_url || row.image)]"
                preview-teleported
                fit="cover"
                loading="lazy"
              />
              <span
                v-else
                :data-testid="`product-detail-image-empty-${row.id}`"
                class="image-placeholder"
              >无图</span>
            </template>
          </el-table-column>
          <el-table-column prop="legacy_spu_code" label="旧 SPU 编码" min-width="125" show-overflow-tooltip />
          <el-table-column prop="legacy_sku_code" label="旧 SKU 编码" min-width="150" show-overflow-tooltip />
          <el-table-column prop="spu_code" label="新 SPU 编码" min-width="125" show-overflow-tooltip>
            <template #default="{ row }"><SpuCodeDisplay :code="row.spu_code" /></template>
          </el-table-column>
          <el-table-column prop="sku_code" label="新 SKU 编码" min-width="190" show-overflow-tooltip>
            <template #default="{ row }">{{ row.sku_code || '-' }}</template>
          </el-table-column>
          <el-table-column prop="sku_product_name" label="SKU商品名称" min-width="190" show-overflow-tooltip>
            <template #default="{ row }">{{ row.sku_product_name || row.product_name || '待生成' }}</template>
          </el-table-column>
          <el-table-column prop="spu_product_name" label="SPU商品名称" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.spu_product_name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="category_name" label="分类" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.category_name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="color_code" label="颜色" min-width="90" show-overflow-tooltip>
            <template #default="{ row }">{{ row.color_code || '-' }}</template>
          </el-table-column>
          <el-table-column prop="specification" label="规格" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.specification || '-' }}</template>
          </el-table-column>
          <el-table-column prop="package_weight" label="重量(g)" min-width="105" align="right">
            <template #default="{ row }">{{ formatPhysical(row.package_weight, 3) }}</template>
          </el-table-column>
          <el-table-column prop="package_volume" label="体积(m³)" min-width="110" align="right">
            <template #default="{ row }">{{ formatPhysical(row.package_volume, 6) }}</template>
          </el-table-column>
          <el-table-column prop="package_length_cm" label="长(cm)" min-width="95" align="right">
            <template #default="{ row }">{{ formatPhysical(row.package_length_cm, 3) }}</template>
          </el-table-column>
          <el-table-column prop="package_width_cm" label="宽(cm)" min-width="95" align="right">
            <template #default="{ row }">{{ formatPhysical(row.package_width_cm, 3) }}</template>
          </el-table-column>
          <el-table-column prop="package_height_cm" label="高(cm)" min-width="95" align="right">
            <template #default="{ row }">{{ formatPhysical(row.package_height_cm, 3) }}</template>
          </el-table-column>
          <el-table-column prop="origin_country" label="原产国" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">{{ row.origin_country || '-' }}</template>
          </el-table-column>
          <el-table-column prop="hs_code" label="HS编码" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.hs_code || '-' }}</template>
          </el-table-column>
          <el-table-column prop="purchase_price" label="采购价格" min-width="110" align="right">
            <template #default="{ row }">{{ formatPrice(row.purchase_price) }}</template>
          </el-table-column>
          <el-table-column prop="sku_status_name" label="商品状态" width="95">
            <template #default="{ row }">{{ row.sku_status_name || '未生成' }}</template>
          </el-table-column>
          <el-table-column prop="conversion_status_name" label="转换状态" width="100" />
          <el-table-column label="操作" min-width="230" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button link type="primary" @click="viewRow(row)">查看</el-button>
                <el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button
                  v-if="row.row_type === 'legacy' && row.status !== 'generated' && canManage"
                  link
                  type="primary"
                  @click="openGenerate(row)"
                >
                  调整并生成
                </el-button>
                <el-button
                  v-if="row.sku_id && canManage"
                  :data-testid="`detail-status-${row.id}`"
                  link
                  :type="row.sku_is_active ? 'warning' : 'success'"
                  @click="toggleStatus(row)"
                >
                  {{ row.sku_is_active ? '停用' : '启用' }}
                </el-button>
                <el-button
                  v-if="canManage"
                  :data-testid="`detail-delete-${row.id}`"
                  link
                  type="danger"
                  @click="deleteRow(row)"
                >删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <footer class="pager">
          <span>共 {{ total }} 条</span>
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
            :total="total"
            @current-change="load"
            @size-change="changePageSize"
          />
        </footer>
      </main>
    </div>

    <el-dialog v-model="viewVisible" title="旧商品与新编码对应关系" width="min(720px, 94vw)">
      <el-descriptions v-if="selectedRow" :column="2" border>
        <el-descriptions-item label="旧 SPU 编码">{{ selectedRow.legacy_spu_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="旧 SKU 编码">{{ selectedRow.legacy_sku_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="新 SPU 编码"><SpuCodeDisplay :code="selectedRow.spu_code" placeholder="待生成" /></el-descriptions-item>
        <el-descriptions-item label="新 SKU 编码">{{ selectedRow.sku_code || '待生成' }}</el-descriptions-item>
        <el-descriptions-item label="SKU商品名称">{{ selectedRow.sku_product_name || '待生成' }}</el-descriptions-item>
        <el-descriptions-item label="SPU商品名称">{{ selectedRow.spu_product_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="分类">{{ selectedRow.category_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="颜色/规格">{{ [selectedRow.color_code, selectedRow.specification].filter(Boolean).join(' / ') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="重量(g)">{{ formatPhysical(selectedRow.package_weight, 3) }}</el-descriptions-item>
        <el-descriptions-item label="体积(m³)">{{ formatPhysical(selectedRow.package_volume, 6) }}</el-descriptions-item>
        <el-descriptions-item label="长(cm)">{{ formatPhysical(selectedRow.package_length_cm, 3) }}</el-descriptions-item>
        <el-descriptions-item label="宽(cm)">{{ formatPhysical(selectedRow.package_width_cm, 3) }}</el-descriptions-item>
        <el-descriptions-item label="高(cm)">{{ formatPhysical(selectedRow.package_height_cm, 3) }}</el-descriptions-item>
        <el-descriptions-item label="原产国">{{ selectedRow.origin_country || '-' }}</el-descriptions-item>
        <el-descriptions-item label="HS编码">{{ selectedRow.hs_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="图片链接" :span="2">{{ selectedRow.image_url || selectedRow.image || '-' }}</el-descriptions-item>
        <el-descriptions-item label="商品状态">{{ selectedRow.sku_status_name || '未生成' }}</el-descriptions-item>
        <el-descriptions-item label="转换状态">{{ selectedRow.conversion_status_name || '-' }}</el-descriptions-item>
        <el-descriptions-item v-if="selectedRow.error_message" label="处理说明" :span="2">{{ selectedRow.error_message }}</el-descriptions-item>
      </el-descriptions>
      <template #footer><el-button @click="viewVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="visible" title="调整旧商品并生成新编码" width="min(600px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="SKU商品名称" required><el-input v-model="form.product_name" maxlength="200" /></el-form-item>
        <el-form-item label="末级分类" required>
          <el-tree-select
            v-model="form.category_node"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'displayName', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
          />
        </el-form-item>
        <el-form-item label="属性码（选填，未填按 0 处理）">
          <el-select v-model="form.attribute_code" clearable style="width: 100%">
            <el-option v-for="item in attributes" :key="item.id" :label="`${item.code} ${item.name}`" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色" required>
          <el-select v-model="form.color_code" filterable clearable style="width: 100%">
            <el-option v-for="item in activeColors" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格">
          <el-select v-if="specOptions.length" v-model="form.specification" filterable allow-create style="width: 100%">
            <el-option v-for="value in specOptions" :key="value" :label="value" :value="value" />
          </el-select>
          <el-input v-else v-model="form.specification" placeholder="例如 150cm×220cm" />
        </el-form-item>
        <el-form-item label="采购价格"><el-input v-model="form.purchase_price" placeholder="例如 12.50" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveGenerate">生成新编码</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑商品明细" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="SKU商品名称">
          <el-input v-model="editForm.product_name" maxlength="200" placeholder="留空则不修改" />
        </el-form-item>
        <el-form-item v-if="editForm.allowCategory" label="分类">
          <el-tree-select
            v-model="editForm.category_node"
            :data="categoryTree"
            node-key="id"
            :props="{ label: 'displayName', children: 'children', disabled: categoryDisabled }"
            check-strictly
            filterable
            clearable
          />
        </el-form-item>
        <el-form-item label="采购价格">
          <div class="editable-detail-field">
            <el-input v-model="editForm.purchase_price" :disabled="editForm.clearFields.includes('purchase_price')" placeholder="留空则不修改" />
            <el-checkbox v-model="editForm.clearFields" label="purchase_price">清空</el-checkbox>
          </div>
        </el-form-item>
        <el-form-item v-for="field in editableDetailFields" :key="field.key" :label="field.label">
          <div class="editable-detail-field">
            <el-input
              v-model="editForm[field.key]"
              :disabled="editForm.clearFields.includes(field.key)"
              :placeholder="editForm.clearFields.includes(field.key) ? '已选择清空' : '留空则不覆盖'"
            />
            <el-checkbox v-model="editForm.clearFields" :label="field.key">清空</el-checkbox>
          </div>
        </el-form-item>
        <el-form-item v-if="editForm.hasSku" label="商品状态">
          <el-select v-model="editForm.is_active" style="width: 100%">
            <el-option label="在售（启用）" :value="true" />
            <el-option label="下架（停用）" :value="false" />
          </el-select>
        </el-form-item>
        <el-alert v-if="editForm.generated" title="已生成编码的 SKU 不允许修改编码、颜色、规格和分类。" type="info" :closable="false" />
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bulkVisible" title="按 SPU 批量修改商品明细" width="min(620px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="匹配类型" required>
          <el-radio-group v-model="bulkForm.match_type">
            <el-radio value="old_spu">旧 SPU 编码</el-radio>
            <el-radio value="new_spu">新 SPU 编码</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="精确 SPU 编码" required>
          <el-input v-model="bulkForm.spu_code" placeholder="请输入完整 SPU 编码" @keyup.enter="previewBulk" />
        </el-form-item>
        <el-form-item label="批量修改字段">
          <el-input v-model="bulkForm.product_name" placeholder="SKU商品名称（留空不覆盖）" />
          <div class="bulk-detail-field">
            <el-input v-model="bulkForm.purchase_price" class="bulk-field" :disabled="bulkForm.clearFields.includes('purchase_price')" placeholder="采购价格（留空不覆盖）" />
            <el-checkbox v-model="bulkForm.clearFields" label="purchase_price">清空</el-checkbox>
          </div>
          <el-select v-model="bulkForm.status" class="bulk-field" clearable placeholder="商品状态（留空不覆盖）">
            <el-option label="在售（启用）" value="active" />
            <el-option label="下架（停用）" value="inactive" />
          </el-select>
        </el-form-item>
        <div class="bulk-detail-fields">
          <div v-for="field in editableDetailFields" :key="field.key" class="bulk-detail-field">
            <el-input
              v-model="bulkForm[field.key]"
              :placeholder="`${field.label}（留空不覆盖）`"
              :disabled="bulkForm.clearFields.includes(field.key)"
            />
            <el-checkbox v-model="bulkForm.clearFields" :label="field.key">清空</el-checkbox>
          </div>
        </div>
      </el-form>
      <el-alert
        v-if="bulkPreview !== null"
        :title="selectedRows.length ? `当前条件匹配 ${bulkPreview} 条，将修改已选择的 ${selectedRows.length} 条` : `当前条件匹配 ${bulkPreview} 条，未选择记录，将修改全部匹配记录（含其他分页）`"
        type="info"
        :closable="false"
      />
      <template #footer>
        <el-button :disabled="bulkSaving" @click="previewBulk">预览匹配数量</el-button>
        <el-button @click="bulkVisible = false">取消</el-button>
        <el-button type="primary" :loading="bulkSaving" @click="saveBulk">确认修改</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="imageBatchVisible"
      title="批量导入商品图片"
      width="min(920px, 94vw)"
      :close-on-click-modal="false"
      :close-on-press-escape="!imageBatchSaving && imageBatchPhase !== 'completed'"
      :show-close="!imageBatchSaving && imageBatchPhase !== 'completed'"
    >
      <div class="image-batch-toolbar">
        <input ref="imageBatchFile" data-testid="image-batch-file" hidden type="file" accept=".csv,text/csv" @change="parseImageBatchFile" />
        <el-button data-testid="image-batch-template" :disabled="imageBatchSaving" @click="downloadImageBatchTemplate">下载图片导入模板</el-button>
        <el-button data-testid="image-batch-file-button" :disabled="imageBatchSaving" @click="imageBatchFile?.click()">选择 CSV 文件</el-button>
        <span class="image-batch-hint">字段：旧SKU编码、新SKU编码、图片链接；旧/新 SKU 至少填写一个。</span>
      </div>
      <div v-if="imageBatchRows.length" class="image-batch-summary" data-testid="image-batch-summary">
        <strong>{{ imageBatchPhaseLabel }}</strong>
        <span>{{ imageBatchSummary.total }} 行</span>
        <span>待处理 {{ imageBatchSummary.pending }}</span>
        <span>缓存中 {{ imageBatchSummary.processing }}</span>
        <span>已更新 {{ imageBatchSummary.updated }}</span>
        <span>已存在 {{ imageBatchSummary.unchanged }}</span>
        <span>失败 {{ imageBatchSummary.error }}</span>
        <span v-if="imageBatchSummary.invalid">（其中 {{ imageBatchSummary.invalid }} 行需修正 CSV）</span>
      </div>
      <el-progress
        v-if="imageBatchRows.length && imageBatchPhase === 'processing'"
        class="image-batch-progress-bar"
        :percentage="imageBatchProgressPercent"
        :format="() => imageBatchProgress"
      />
      <div v-else-if="imageBatchProgress" class="image-batch-progress" data-testid="image-batch-progress">{{ imageBatchProgress }}</div>
      <el-alert v-if="imageBatchError" class="image-batch-error" :title="imageBatchError" type="warning" :closable="false" />
      <el-table v-if="imageBatchRows.length" :data="imageBatchRows" border max-height="360" class="image-batch-table">
        <el-table-column type="index" label="序号" width="70" />
        <el-table-column label="缓存图片" width="98" fixed="left">
          <template #default="{ row }">
            <el-image
              v-if="row.cached_url"
              :data-testid="`image-batch-preview-${row.line}`"
              class="image-batch-thumb"
              :src="resolveImageUrl(row.cached_url)"
              :preview-src-list="[resolveImageUrl(row.cached_url)]"
              preview-teleported
              fit="cover"
              loading="lazy"
            />
            <span v-else class="image-placeholder">待缓存</span>
          </template>
        </el-table-column>
        <el-table-column label="处理状态" width="112" fixed="left">
          <template #default="{ row }">
            <span :data-testid="`image-batch-state-${row.line}`" :class="`image-batch-state image-batch-state-${row.status}`">{{ imageBatchStatusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="legacy_sku_code" label="旧SKU编码" min-width="150" show-overflow-tooltip />
        <el-table-column prop="sku_code" label="新SKU编码" min-width="150" show-overflow-tooltip />
        <el-table-column prop="image_url" label="图片链接" min-width="280" show-overflow-tooltip />
        <el-table-column label="缓存文件信息" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ imageBatchFileInfo(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.message || '-' }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="请选择图片 CSV 文件预览" :image-size="70" />
      <template #footer>
        <el-button v-if="imageBatchPhase !== 'completed'" :disabled="imageBatchSaving" @click="imageBatchVisible = false">关闭</el-button>
        <el-button
          v-if="imageBatchPhase === 'completed' && imageBatchSummary.retryable"
          data-testid="image-batch-retry"
          :loading="imageBatchSaving"
          @click="retryImageBatch"
        >
          重试失败项
        </el-button>
        <el-button
          v-if="imageBatchPhase !== 'completed'"
          data-testid="image-batch-submit"
          type="primary"
          :loading="imageBatchSaving"
          :disabled="!imageBatchRows.some((row) => row.valid)"
          @click="submitImageBatch"
        >
          {{ imageBatchSaving ? '缓存中…' : '提交并缓存图片' }}
        </el-button>
        <el-button
          v-else
          data-testid="image-batch-save"
          type="primary"
          :loading="imageBatchSaving"
          @click="saveImageBatch"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importing" title="导入商品明细" width="min(560px, 94vw)" :close-on-click-modal="false" :show-close="false">
      <el-steps :active="importStep" finish-status="success" align-center>
        <el-step title="读取文件" />
        <el-step title="校验数据" />
        <el-step title="增量更新" />
        <el-step title="完成" />
      </el-steps>
      <el-progress class="import-progress" :percentage="importPercent" :indeterminate="importing" :duration="8" />
      <p class="import-status">{{ importStage }} · 已用时 {{ formatDuration(importElapsed) }}</p>
      <p class="import-hint">当前模式：{{ importModeLabel }}。新 SKU 编码只用于匹配已有商品；空白字段不会覆盖原值，待生成商品不能填写商品状态。</p>
    </el-dialog>

    <el-dialog v-model="summaryVisible" title="导入结果" width="min(720px, 94vw)">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="新增">{{ importResult.created || 0 }}</el-descriptions-item>
        <el-descriptions-item label="更新">{{ importResult.updated || 0 }}</el-descriptions-item>
        <el-descriptions-item label="无变化">{{ importResult.unchanged || 0 }}</el-descriptions-item>
        <el-descriptions-item label="跳过">{{ importResult.skipped || 0 }}</el-descriptions-item>
        <el-descriptions-item label="异常">{{ importResult.error_count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ formatDuration(importResult.duration_ms || importElapsed) }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="importResult.errors?.length" class="import-errors" title="请按行号修正异常数据后重新导入" type="warning" :closable="false" />
      <el-table v-if="importResult.errors?.length" :data="importResult.errors" border max-height="320">
        <el-table-column prop="line" label="CSV 行号" width="100" />
        <el-table-column prop="message" label="错误原因" min-width="460" />
      </el-table>
      <template #footer><el-button type="primary" @click="summaryVisible = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import {
  fetchProductCategories,
  fetchProductCategoryBackgroundColors,
  fetchProductColors,
  fetchProductAttributes,
  fetchProductDetailList,
  importLegacyProductItems,
  updateLegacyProductItem,
  generateLegacyProductItem,
  updateProductSku,
  updateProductSkuStatus,
  deleteProductSku,
  deleteProductLegacyItem,
  bulkUpdateProductDetails,
  bulkCacheProductImages,
} from '../../api/products';
import { collectionRows, collectionTotal } from '../../utils/businessResponse';
import { apiBaseUrl } from '../../api/baseUrl';
import {
  buildCategoryTree,
  categoryRowClass,
  categoryRowStyle,
  mergeCategoryBackgroundColors,
} from '../../utils/productCategoryPresentation';
import SpuCodeDisplay from '../../components/SpuCodeDisplay.vue';

const auth = useAuthStore();
const canManage = computed(() => auth.hasPermission('products.master.manage'));
const filters = reactive({ search: '', sku_status: 'all', category_id: '' });
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const message = ref('');
const messageType = ref('success');
const categories = ref([]);
const colors = ref([]);
const attributes = ref([]);
const categorySearch = ref('');
const categoryTreeRef = ref(null);
const visible = ref(false);
const viewVisible = ref(false);
const selectedRow = ref(null);
const selectedRows = ref([]);
const form = reactive({ id: null, product_name: '', category_node: null, attribute_code: '', color_code: '', specification: '', purchase_price: '' });
const editVisible = ref(false);
const editableDetailFields = [
  { key: 'package_weight', label: '重量(g)' },
  { key: 'package_volume', label: '体积(m³)' },
  { key: 'package_length_cm', label: '长(cm)' },
  { key: 'package_width_cm', label: '宽(cm)' },
  { key: 'package_height_cm', label: '高(cm)' },
  { key: 'origin_country', label: '原产国' },
  { key: 'hs_code', label: 'HS编码' },
  { key: 'image_url', label: '图片链接' },
];
const editForm = reactive({
  id: null, skuId: null, rowType: '', product_name: '', category_node: null, purchase_price: '', is_active: true,
  package_weight: '', package_volume: '', package_length_cm: '', package_width_cm: '', package_height_cm: '',
  origin_country: '', hs_code: '', image_url: '', clearFields: [], hasSku: false, allowCategory: false, generated: false,
  initial_is_active: null,
});
const bulkVisible = ref(false);
const bulkSaving = ref(false);
const bulkPreview = ref(null);
const bulkForm = reactive({
  match_type: 'old_spu', spu_code: '', product_name: '', purchase_price: '', status: '',
  package_weight: '', package_volume: '', package_length_cm: '', package_width_cm: '', package_height_cm: '',
  origin_country: '', hs_code: '', image_url: '', clearFields: [],
});
const importing = ref(false);
const summaryVisible = ref(false);
const importStep = ref(0);
const importPercent = ref(0);
const importStage = ref('准备导入');
const importElapsed = ref(0);
const importResult = ref({});
let importTimer = null;
const imageBatchVisible = ref(false);
const imageBatchSaving = ref(false);
const imageBatchRows = ref([]);
const imageBatchError = ref('');
const imageBatchFile = ref(null);
const imageBatchProgress = ref('');
const imageBatchPhase = ref('draft');
const imageBatchFileName = ref('');
const importMode = ref('auto');
const importModeLabel = computed(() => ({ auto: '自动导入（新增或更新）', create: '仅导入新增', update: '仅更新已有记录' })[importMode.value] || '自动导入（新增或更新）');

const categoryTree = computed(() => buildCategoryTree(categories.value));
const productRowClassName = ({ row }) => categoryRowClass(row, categories.value);
const productRowStyle = ({ row }) => categoryRowStyle(row, categories.value);
const activeColors = computed(() => colors.value.filter((item) => item?.is_active !== false));
const leaves = computed(() => categories.value.filter((item) => item.is_active !== false && [2, 3].includes(Number(item.level))));
const selectedCategory = computed(() => categories.value.find((item) => String(item.id) === String(form.category_node)));
const specOptions = computed(() => selectedCategory.value?.spec_dimensions?.[0]?.values || []);

watch(categorySearch, (value) => categoryTreeRef.value?.filter(value));

function show(value, type = 'success') { message.value = value; messageType.value = type; }
function formatPrice(value) { return value === null || value === undefined || value === '' ? '-' : Number.isFinite(Number(value)) ? Number(value).toFixed(4) : value; }
function formatPhysical(value, decimals = 3) {
  if (value === null || value === undefined || value === '') return '-';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '-';
  const fixed = numeric.toFixed(decimals);
  return fixed.replace(/\.0+$/, '').replace(/(\.[0-9]*?)0+$/, '$1') || '0';
}
function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value || 0) / 1000));
  return `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, '0')}秒`;
}
function resolveImageUrl(value) {
  const url = String(value || '').trim();
  if (!url) return '';
  if (/^(?:https?:)?\/\//i.test(url)) return url.startsWith('//') ? `${window.location.protocol}${url}` : url;
  return `${apiBaseUrl}${url.startsWith('/') ? url : `/${url}`}`;
}
function filterCategory(value, data) {
  if (!value) return true;
  return String(data.displayName || data.name || '').toLowerCase().includes(String(value).toLowerCase());
}
function categoryDisabled(data) { return Number(data.level) === 1 || Boolean(data.children?.length); }
function selectCategory(data) {
  filters.category_id = data?.id ? String(data.id) : '';
  page.value = 1;
  load();
}

function parseCsvRows(text) {
  const source = String(text || '').replace(/^\uFEFF/, '');
  const output = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];
    if (character === '"' && quoted && next === '"') { cell += '"'; index += 1; continue; }
    if (character === '"') { quoted = !quoted; continue; }
    if (character === ',' && !quoted) { row.push(cell.trim()); cell = ''; continue; }
    if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && next === '\n') index += 1;
      row.push(cell.trim());
      if (row.some((value) => value !== '')) output.push(row);
      row = []; cell = ''; continue;
    }
    cell += character;
  }
  row.push(cell.trim());
  if (row.some((value) => value !== '')) output.push(row);
  return output;
}

function normalizeImageHeader(value) {
  return String(value || '').replace(/\s+/g, '').toLowerCase();
}

function imageBatchField(row, headers, names) {
  const index = headers.findIndex((header) => names.includes(normalizeImageHeader(header)));
  return index >= 0 ? String(row[index] || '').trim() : '';
}

const imageBatchSummary = computed(() => {
  const all = imageBatchRows.value;
  const valid = all.filter((row) => row.valid);
  const invalid = all.filter((row) => !row.valid).length;
  const pending = valid.filter((row) => row.status === 'pending').length;
  const processing = valid.filter((row) => row.status === 'processing').length;
  const updated = valid.filter((row) => row.status === 'updated' || row.status === 'success').length;
  const unchanged = valid.filter((row) => row.status === 'unchanged').length;
  const error = all.filter((row) => row.status === 'error').length;
  return {
    total: all.length,
    valid: valid.length,
    invalid,
    pending,
    processing,
    updated,
    unchanged,
    error,
    completed: updated + unchanged + error,
    retryable: valid.some((row) => row.status === 'error'),
  };
});
const imageBatchPhaseLabel = computed(() => ({
  draft: '待提交',
  processing: '正在缓存图片',
  completed: '缓存完成，请保存',
}[imageBatchPhase.value] || '待提交'));
const imageBatchProgressPercent = computed(() => {
  const total = imageBatchSummary.value.total;
  if (!total) return 0;
  return Math.min(100, Math.round((imageBatchSummary.value.completed / total) * 100));
});

function openImageBatch() {
  if (!canManage.value) return;
  imageBatchRows.value = [];
  imageBatchError.value = '';
  imageBatchProgress.value = '';
  imageBatchPhase.value = 'draft';
  imageBatchFileName.value = '';
  imageBatchVisible.value = true;
}

function imageBatchStatusLabel(status) {
  return ({ pending: '待处理', processing: '缓存中', success: '已更新', updated: '已更新', unchanged: '已存在', error: '失败' })[status] || '待处理';
}

function imageBatchFileInfo(row) {
  const parts = [];
  if (row.file_name) parts.push(row.file_name);
  if (row.file_size !== undefined && row.file_size !== null && row.file_size !== '') {
    const size = Number(row.file_size);
    parts.push(Number.isFinite(size) && size >= 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`);
  }
  if (row.content_type) parts.push(row.content_type);
  if (row.cached_url) parts.push(row.cached_url);
  return parts.join(' · ') || (row.status === 'error' ? '未生成缓存文件' : '待缓存');
}

function validateImageBatchRow(row) {
  if (!row.legacy_sku_code && !row.sku_code) return '旧 SKU 编码和新 SKU 编码至少填写一个';
  if (!row.image_url) return '图片链接不能为空';
  if (!/^(?:https?:\/\/|\/media\/)/i.test(row.image_url)) return '图片链接需为 http(s) URL 或 /media/ 地址';
  return '';
}

async function parseImageBatchFile(event) {
  if (imageBatchSaving.value) return;
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    if (!/\.csv$/i.test(file.name)) {
      imageBatchError.value = '图片批量导入当前仅支持 CSV 文件，请先另存为 CSV。';
      return;
    }
    const bytes = await file.arrayBuffer();
    let text;
    try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { text = new TextDecoder('gb18030').decode(bytes); }
    const parsed = parseCsvRows(text);
    const headers = parsed.shift() || [];
    if (!headers.length) throw new Error('CSV 缺少表头。');
    const legacyNames = ['旧sku编码', '旧sku', 'legacy_skucode', 'legacy_sku_code'];
    const newNames = ['新sku编码', '新sku', 'sku编码', 'sku_code', 'new_sku_code'];
    const imageNames = ['图片链接', '图片url', '图片地址', 'image_url', 'image'];
    const rowsFromFile = parsed.map((values, index) => {
      const row = {
        line: index + 2,
        legacy_sku_code: imageBatchField(values, headers, legacyNames),
        sku_code: imageBatchField(values, headers, newNames),
        image_url: imageBatchField(values, headers, imageNames),
        status: 'pending',
        cached_url: '',
        file_name: '',
        file_size: '',
        content_type: '',
        message: '',
      };
      const error = validateImageBatchRow(row);
      return { ...row, valid: !error, status: error ? 'error' : 'pending', message: error };
    });
    imageBatchRows.value = rowsFromFile;
    imageBatchFileName.value = file.name;
    imageBatchPhase.value = 'draft';
    imageBatchProgress.value = rowsFromFile.length ? `待提交：可处理 ${rowsFromFile.filter((row) => row.valid).length} / ${rowsFromFile.length} 行` : '';
    imageBatchError.value = rowsFromFile.length ? '' : 'CSV 中没有可预览的数据行。';
  } catch (error) {
    imageBatchRows.value = [];
    imageBatchFileName.value = '';
    imageBatchPhase.value = 'draft';
    imageBatchProgress.value = '';
    imageBatchError.value = error?.message || 'CSV 解析失败，请检查文件编码和格式。';
  }
}

function downloadImageBatchTemplate() {
  const csv = '\ufeff旧SKU编码,新SKU编码,图片链接\r\nOLD-SKU-001,101010004-blue,https://example.com/product.jpg\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = '商品图片批量导入模板.csv'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function imageBatchResultAt(resultRows, index) {
  // The API index is relative to the current chunk.  Prefer it when present,
  // and only use response order for older servers that omit index entirely.
  const hasExplicitIndex = (item) => item && item.index !== undefined && item.index !== null && String(item.index).trim() !== '';
  const indexed = resultRows.find((item) => hasExplicitIndex(item) && Number.isInteger(Number(item.index)) && Number(item.index) === index);
  if (indexed) return indexed;
  if (resultRows.some(hasExplicitIndex)) return null;
  return resultRows[index] || null;
}

function applyImageBatchResult(row, result) {
  if (!result) {
    row.status = 'error';
    row.cached_url = '';
    row.message = '服务器未返回该行处理结果';
    return;
  }
  const resultStatus = String(result.status || '').toLowerCase();
  const cachedUrl = String(result.cached_url || result.image_url || result.url || '').trim();
  const failed = resultStatus === 'error' || result.success === false || result.error;
  // A positive status without the persisted media URL is not a successful
  // cache: the list could not show the concrete image that was saved.
  if (failed || !cachedUrl) {
    row.status = 'error';
    row.cached_url = '';
    row.file_name = result.file_name || '';
    row.file_size = result.file_size ?? '';
    row.content_type = result.content_type || '';
    row.message = result.message || (cachedUrl ? '服务器返回了失败状态' : '服务器未返回缓存图片地址');
    return;
  }
  const isKnownImageStatus = ['updated', 'unchanged'].includes(resultStatus);
  row.status = isKnownImageStatus && resultStatus === 'unchanged' ? 'unchanged' : 'updated';
  row.cached_url = cachedUrl;
  row.file_name = result.file_name || result.filename || '';
  row.file_size = result.file_size ?? result.size ?? '';
  row.content_type = result.content_type || result.mime_type || '';
  row.message = result.message || (row.status === 'unchanged' ? '图片已存在，已复用缓存文件' : '图片已缓存并更新商品信息');
}

function updateImageBatchProgress(processed, total) {
  const summary = imageBatchSummary.value;
  imageBatchProgress.value = `缓存中：${processed} / ${total} 行（已更新 ${summary.updated}，已存在 ${summary.unchanged}，失败 ${summary.error}）`;
}

async function processImageBatchRows(targetRows) {
  if (!targetRows.length || imageBatchSaving.value) return;
  imageBatchSaving.value = true;
  imageBatchPhase.value = 'processing';
  const batchSize = 5;
  let processed = 0;
  const total = imageBatchSummary.value.total;
  updateImageBatchProgress(processed, total);
  try {
    for (let offset = 0; offset < targetRows.length; offset += batchSize) {
      const batchRows = targetRows.slice(offset, offset + batchSize);
      batchRows.forEach((row) => { row.status = 'processing'; row.cached_url = row.cached_url || ''; row.message = ''; });
      const items = batchRows.map((row) => ({
        legacy_sku_code: row.legacy_sku_code,
        sku_code: row.sku_code,
        image_url: row.image_url,
      }));
      let response;
      try {
        response = await bulkCacheProductImages({ items });
      } catch (error) {
        response = { success: false, message: error?.message || '服务器缓存失败' };
      }
      const resultRows = Array.isArray(response?.data?.results)
        ? response.data.results
        : Array.isArray(response?.data?.items) ? response.data.items : [];
      if (!response?.success) {
        const message = response?.message || '服务器缓存失败';
        batchRows.forEach((row) => { row.status = 'error'; row.cached_url = ''; row.message = message; });
      } else if (!resultRows.length) {
        batchRows.forEach((row) => { row.status = 'error'; row.cached_url = ''; row.message = '服务器未返回逐行处理结果'; });
      } else {
        batchRows.forEach((row, index) => applyImageBatchResult(row, imageBatchResultAt(resultRows, index)));
      }
      processed += batchRows.length;
      updateImageBatchProgress(processed, total);
    }
    imageBatchPhase.value = 'completed';
    const summary = imageBatchSummary.value;
    imageBatchProgress.value = `处理完成：共 ${summary.total} 行，已更新 ${summary.updated}，已存在 ${summary.unchanged}，失败 ${summary.error}`;
    imageBatchError.value = summary.error ? `图片缓存完成：${summary.error} 行失败，请检查失败行说明后重试。` : '';
  } finally {
    imageBatchSaving.value = false;
  }
}

async function submitImageBatch() {
  if (imageBatchPhase.value === 'completed') return;
  const pendingRows = imageBatchRows.value.filter((row) => row.valid && row.status === 'pending');
  if (!pendingRows.length || imageBatchSaving.value) return;
  await processImageBatchRows(pendingRows);
}

async function retryImageBatch() {
  if (imageBatchPhase.value !== 'completed' || imageBatchSaving.value) return;
  imageBatchError.value = '';
  const failedRows = imageBatchRows.value.filter((row) => row.valid && row.status === 'error');
  if (!failedRows.length) return;
  await processImageBatchRows(failedRows);
}

async function saveImageBatch() {
  if (imageBatchPhase.value !== 'completed' || imageBatchSaving.value) return;
  imageBatchSaving.value = true;
  try {
    const refreshed = await load();
    if (refreshed) imageBatchVisible.value = false;
    else imageBatchError.value = '图片缓存结果已保留，商品列表刷新失败，请稍后再次点击保存。';
  } catch (error) {
    imageBatchError.value = error?.message || '刷新商品明细失败，请稍后再次点击保存。';
  } finally {
    imageBatchSaving.value = false;
  }
}
function search() { page.value = 1; load(); }
function reset() { filters.search = ''; filters.sku_status = 'all'; selectCategory(null); }
function changePageSize() { page.value = 1; load(); }

async function load() {
  loading.value = true;
  // Category settings own the row background color.  Refreshing the
  // dictionary together with every query makes a changed color visible
  // immediately without a full page reload.
  await loadDictionaries();
  const response = await fetchProductDetailList({
    search: filters.search.trim() || undefined,
    category_id: filters.category_id || undefined,
    sku_status: filters.sku_status,
    page: page.value,
    page_size: pageSize.value,
  });
  if (response.success) {
    rows.value = collectionRows(response.data);
    total.value = collectionTotal(response.data);
    loading.value = false;
    return true;
  } else {
    rows.value = [];
    total.value = 0;
    show(response.message || '商品明细加载失败', 'error');
  }
  loading.value = false;
  return false;
}

async function loadDictionaries() {
  const [categoryResponse, backgroundResponse, colorResponse, attributeResponse] = await Promise.all([
    fetchProductCategories({ page: 1, page_size: 500 }),
    fetchProductCategoryBackgroundColors(),
    fetchProductColors(),
    fetchProductAttributes(),
  ]);
  if (categoryResponse.success || backgroundResponse.success) {
    categories.value = mergeCategoryBackgroundColors(
      categoryResponse.success ? collectionRows(categoryResponse.data) : [],
      backgroundResponse.success ? collectionRows(backgroundResponse.data) : [],
    );
  }
  if (colorResponse.success) colors.value = collectionRows(colorResponse.data);
  if (attributeResponse.success) attributes.value = collectionRows(attributeResponse.data);
}

function viewRow(row) { selectedRow.value = row; viewVisible.value = true; }
function openGenerate(row) {
  Object.assign(form, {
    id: row.id,
    product_name: row.sku_product_name || row.product_name || '',
    category_node: row.category_node || null,
    attribute_code: row.attribute_code === '0' ? '' : row.attribute_code || '',
    color_code: row.color_code || '',
    specification: row.specification || '',
    purchase_price: row.purchase_price ?? '',
  });
  visible.value = true;
}

function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    skuId: row.sku_id || null,
    rowType: row.row_type,
    product_name: row.sku_product_name || row.product_name || '',
    category_node: row.category_node || null,
    purchase_price: row.purchase_price ?? '',
    package_weight: row.package_weight ?? '',
    package_volume: row.package_volume ?? '',
    package_length_cm: row.package_length_cm ?? '',
    package_width_cm: row.package_width_cm ?? '',
    package_height_cm: row.package_height_cm ?? '',
    origin_country: row.origin_country || '',
    hs_code: row.hs_code || '',
    image_url: row.image_url || row.image || '',
    clearFields: [],
    is_active: row.sku_is_active !== false,
    initial_is_active: row.sku_is_active === true || row.sku_is_active === false ? row.sku_is_active : null,
    hasSku: Boolean(row.sku_id),
    allowCategory: row.row_type === 'legacy' && row.status !== 'generated',
    generated: Boolean(row.sku_id || row.status === 'generated'),
  });
  editVisible.value = true;
}

async function saveEdit() {
  const payload = {};
  if (editForm.product_name.trim()) payload.product_name = editForm.product_name.trim();
  if (!editForm.clearFields.includes('purchase_price') && editForm.purchase_price !== '' && editForm.purchase_price !== null && editForm.purchase_price !== undefined) {
    payload.purchase_price = editForm.purchase_price;
  }
  for (const field of editableDetailFields) {
    if (editForm.clearFields.includes(field.key)) continue;
    const value = editForm[field.key];
    if (value !== '' && value !== null && value !== undefined) payload[field.key] = value;
  }
  if (editForm.allowCategory && editForm.category_node) payload.category_node = editForm.category_node;
  const statusChanged = Boolean(
    editForm.hasSku
      && (editForm.is_active === true || editForm.is_active === false)
      && editForm.initial_is_active !== null
      && editForm.is_active !== editForm.initial_is_active,
  );
  if (editForm.clearFields.length) payload.clear_fields = [...new Set(editForm.clearFields)];
  if (!Object.keys(payload).length && !payload.clear_fields?.length && !statusChanged) { show('请至少填写一个需要修改的字段', 'warning'); return; }
  saving.value = true;
  const response = Object.keys(payload).length || payload.clear_fields?.length
    ? editForm.rowType === 'sku'
      ? await updateProductSku(editForm.id, payload)
      : await updateLegacyProductItem(editForm.id, payload)
    : { success: true };
  saving.value = false;
  if (!response.success) { show(response.message || '保存失败', 'error'); return; }
  if (statusChanged) {
    const statusResponse = await updateProductSkuStatus(editForm.skuId || editForm.id, {
      is_active: editForm.is_active,
      reason: '商品明细编辑中手动调整商品状态',
    });
    if (!statusResponse.success) { show(statusResponse.message || '商品状态更新失败', 'error'); return; }
  }
  editVisible.value = false;
  show('商品明细已更新');
  await load();
}

function bulkPayload(preview = false) {
  const fields = {};
  if (bulkForm.product_name.trim()) fields.product_name = bulkForm.product_name.trim();
  if (!bulkForm.clearFields.includes('purchase_price') && bulkForm.purchase_price !== '' && bulkForm.purchase_price !== null) {
    fields.purchase_price = bulkForm.purchase_price;
  }
  if (bulkForm.status) fields.is_active = bulkForm.status === 'active';
  for (const field of editableDetailFields) {
    if (bulkForm.clearFields.includes(field.key)) continue;
    const value = bulkForm[field.key];
    if (value !== '' && value !== null && value !== undefined) fields[field.key] = value;
  }
  const payload = {
    match_type: bulkForm.match_type,
    spu_code: bulkForm.spu_code.trim(),
    fields,
    clear_fields: [...new Set(bulkForm.clearFields)],
    preview,
  };
  // No selection means all exact-SPU matches (including records on other
  // pages).  Only send ids when the user explicitly selected rows.
  if (selectedRows.value.length) {
    payload.ids = selectedRows.value.map((row) => ({ id: row.id, row_type: row.row_type }));
  }
  return payload;
}

function openBulk() {
  bulkPreview.value = null;
  bulkForm.clearFields = [];
  bulkVisible.value = true;
}

async function previewBulk() {
  if (!bulkForm.spu_code.trim()) { show('请输入精确 SPU 编码', 'warning'); return; }
  bulkSaving.value = true;
  const response = await bulkUpdateProductDetails(bulkPayload(true));
  bulkSaving.value = false;
  if (!response.success) { show(response.message || '匹配失败', 'error'); return; }
  bulkPreview.value = Number(response.data?.matched || 0);
}

async function saveBulk() {
  if (!bulkForm.spu_code.trim()) { show('请输入精确 SPU 编码', 'warning'); return; }
  const payload = bulkPayload(false);
  if (!Object.keys(payload.fields).length && !payload.clear_fields.length) { show('请至少填写一个需要修改的字段', 'warning'); return; }
  const matched = bulkPreview.value === null ? '尚未预览' : `${bulkPreview.value} 条`;
  const scope = selectedRows.value.length
    ? `仅修改已选择的 ${selectedRows.value.length} 条记录`
    : '未选择记录，将修改该精确 SPU 的全部匹配记录（含其他分页）';
  try {
    await ElMessageBox.confirm(`预览匹配 ${matched}。${scope}。确认继续吗？`, '批量修改确认', { type: 'warning' });
  } catch { return; }
  bulkSaving.value = true;
  const response = await bulkUpdateProductDetails(payload);
  bulkSaving.value = false;
  if (!response.success) { show(response.message || '批量修改失败', 'error'); return; }
  const result = response.data || {};
  bulkVisible.value = false;
  show(`批量修改完成：匹配 ${result.matched || 0} 条，更新 ${result.updated || 0} 条，无变化 ${result.unchanged || 0} 条${result.errors?.length ? `，失败 ${result.errors.length} 条` : ''}`, result.errors?.length ? 'warning' : 'success');
  selectedRows.value = [];
  await load();
}
async function saveGenerate() {
  if (!form.product_name.trim() || !form.category_node || !form.color_code) {
    show('请填写 SKU 商品名称并选择末级分类和颜色', 'warning');
    return;
  }
  saving.value = true;
  const updateResponse = await updateLegacyProductItem(form.id, {
    product_name: form.product_name.trim(), category_node: form.category_node,
    attribute_code: form.attribute_code || '0', color_code: form.color_code,
    specification: form.specification || '0', purchase_price: form.purchase_price === '' ? null : form.purchase_price,
  });
  const generateResponse = updateResponse.success ? await generateLegacyProductItem(form.id) : updateResponse;
  saving.value = false;
  if (!generateResponse.success) { show(generateResponse.message || '生成失败', 'error'); return; }
  visible.value = false;
  show('新 SPU/SKU 编码已生成');
  await load();
}

async function toggleStatus(row) {
  if (!row?.sku_id) return;
  const next = row.sku_is_active !== true;
  try {
    await ElMessageBox.confirm(`确认${next ? '启用' : '停用'} SKU“${row.sku_code}”？`, `${next ? '启用' : '停用'}确认`, { type: next ? 'info' : 'warning' });
  } catch { return; }
  const response = await updateProductSkuStatus(row.sku_id, {
    is_active: next,
    reason: '商品明细列表手动调整商品状态',
  });
  if (!response.success) { show(response.message || '商品状态更新失败', 'error'); return; }
  show(`SKU 已${next ? '启用（在售）' : '停用（下架）'}`);
  await load();
}

function isStateConflict(response) {
  return response?.http_status === 409 || response?.code === 'STATE_CONFLICT';
}

function referenceDescription(response) {
  const references = Array.isArray(response?.data?.references)
    ? response.data.references.filter(Boolean)
    : [];
  return references.length ? references.join('、') : '其他业务数据';
}

async function deactivateReferencedRow(row, response) {
  const skuId = row?.sku_id || response?.data?.sku_id;
  if (!response?.data?.can_deactivate || !skuId) {
    show(`商品存在引用（${referenceDescription(response)}），当前记录不能删除。`, 'warning');
    return;
  }
  try {
    await ElMessageBox.confirm(
      `该商品被以下数据引用：${referenceDescription(response)}。存在引用时不能删除，是否改为停用？`,
      '存在业务引用',
      { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  const statusResponse = await updateProductSkuStatus(skuId, {
    is_active: false,
    reason: '删除时存在业务引用，改为停用',
  });
  if (!statusResponse.success) {
    show(statusResponse.message || '商品停用失败', 'error');
    return;
  }
  show('商品存在引用，已改为停用');
  await load();
}

async function deleteRow(row) {
  if (!canManage.value || !row?.id) return;
  const label = row.sku_code || row.legacy_sku_code || row.id;
  try {
    await ElMessageBox.confirm(
      `确认删除商品明细“${label}”吗？删除后不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }

  const response = row.row_type === 'sku'
    ? await deleteProductSku(row.sku_id || row.id)
    : await deleteProductLegacyItem(row.id);
  if (response.success) {
    show('商品明细已删除');
    await load();
    return;
  }
  if (isStateConflict(response)) {
    await deactivateReferencedRow(row, response);
    return;
  }
  show(response.message || '商品明细删除失败', 'error');
}

function beginImportStatus() {
  importStep.value = 0;
  importPercent.value = 8;
  importStage.value = '正在读取文件';
  importElapsed.value = 0;
  importing.value = true;
  const started = Date.now();
  importTimer = window.setInterval(() => { importElapsed.value = Date.now() - started; }, 250);
}
function finishImportStatus() {
  if (importTimer) window.clearInterval(importTimer);
  importTimer = null;
  importElapsed.value = Math.max(importElapsed.value, 1);
  importing.value = false;
}
async function importFile(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!/\.csv$/i.test(file.name)) { show('请选择 CSV 文件', 'warning'); return; }
  beginImportStatus();
  try {
    importStep.value = 1;
    const bytes = await file.arrayBuffer();
    let csvText;
    try { csvText = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { csvText = new TextDecoder('gb18030').decode(bytes); }
    importPercent.value = 28;
    importStage.value = '文件解析完成，正在校验数据';
    importStep.value = 2;
    const response = await importLegacyProductItems(csvText, importMode.value);
    importPercent.value = 92;
    importStage.value = '服务端增量更新完成';
    importResult.value = response.success ? (response.data || {}) : { error_count: 1, errors: [{ line: '-', message: response.message || '导入失败' }] };
    importStep.value = 3;
    importPercent.value = 100;
    if (response.success) {
      show(`导入完成：新增 ${response.data?.created || 0} 条，更新 ${response.data?.updated || 0} 条，无变化 ${response.data?.unchanged || 0} 条`);
      await load();
    } else show(response.message || '导入失败', 'error');
  } catch (error) {
    importResult.value = { error_count: 1, errors: [{ line: '-', message: error?.message || '网络请求失败' }] };
    show(error?.message || '导入失败', 'error');
  } finally {
    finishImportStatus();
    summaryVisible.value = true;
  }
}

function downloadTemplate() {
  const headers = [
    '旧SPU编码', '旧SKU编码', '新SKU编码', '商品名称', '完整类目编码', '属性编码',
    '颜色英文编码', '规格', '采购价格', '单位', '商品图片', '重量(g)', '体积(m³)',
    '长(cm)', '宽(cm)', '高(cm)', '原产国', 'HS编码', '商品描述', '商品状态',
  ];
  const values = [
    'OLD-SPU-001', 'OLD-SKU-001', '', '示例 SKU 商品', '10101', '0', 'navy',
    '150cm×220cm', '35.8000', '件', 'https://example.com/product.jpg', '1200.000',
    '0.045000', '150.000', '220.000', '20.000', '中国', '940490', '床品示例，空白字段不会覆盖原值', '',
  ];
  const csv = `\ufeff${headers.join(',')}\n${values.join(',')}\n`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = '商品明细导入模板.csv'; anchor.click(); URL.revokeObjectURL(url);
}

onMounted(() => { load(); });
</script>

<style scoped>
.business-page { display: grid; gap: 16px; }
.page-head, .pager { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head h1 { margin: 0 0 8px; }
.page-head p { margin: 0; color: #64748b; }
.header-actions, .row-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.import-mode-control { width: 170px; }
.workspace { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 16px; align-items: start; }
.category-panel, .content-panel { border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.category-panel { padding: 14px; min-height: 640px; }
.panel-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.category-panel :deep(.el-tree) { margin-top: 12px; }
.content-panel { padding: 12px; min-width: 0; }
.filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0; }
.filters :deep(.el-form-item) { margin-bottom: 0; }
.search-control { width: min(420px, 38vw); }
.status-control { width: 140px; }
.detail-table { margin-top: 16px; width: 100%; }
.product-image-thumb { width: 48px; height: 48px; border-radius: 6px; border: 1px solid #dbe3ec; background: #f8fafc; }
.image-placeholder { color: #94a3b8; font-size: 12px; }
.detail-table :deep(.product-category-tone-warm > td) { background-color: #fff4e6 !important; }
.detail-table :deep(.product-category-tone-0 > td) { background-color: #f0f9ff !important; }
.detail-table :deep(.product-category-tone-1 > td) { background-color: #f5f3ff !important; }
.detail-table :deep(.product-category-tone-2 > td) { background-color: #f0fdf4 !important; }
.detail-table :deep(.product-category-tone-3 > td) { background-color: #fff1f2 !important; }
.detail-table :deep(.product-category-tone-4 > td) { background-color: #f0fdfa !important; }
.detail-table :deep(.product-category-custom > td) { background-color: var(--product-category-row-background) !important; }
.pager { color: #64748b; font-size: 13px; margin-top: 12px; }
.import-progress { margin: 28px 0 12px; }
.import-status { color: #334155; text-align: center; margin: 0; }
.import-hint { color: #64748b; text-align: center; font-size: 12px; }
.import-errors { margin-top: 16px; }
.bulk-field { margin-top: 8px; }
.editable-detail-field, .bulk-detail-field { display: flex; align-items: center; gap: 10px; width: 100%; }
.editable-detail-field .el-checkbox, .bulk-detail-field .el-checkbox { flex: 0 0 auto; margin-right: 0; }
.bulk-detail-fields { display: grid; gap: 8px; margin-top: 8px; }
.image-batch-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.image-batch-hint { color: #64748b; font-size: 12px; }
.image-batch-summary { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 14px; color: #475569; font-size: 13px; }
.image-batch-summary strong { color: #1d4ed8; }
.image-batch-progress-bar { margin-top: 12px; }
.image-batch-progress { margin-top: 12px; color: #334155; font-size: 13px; }
.image-batch-error { margin-top: 14px; }
.image-batch-table { margin-top: 14px; }
.image-batch-thumb { width: 52px; height: 52px; border-radius: 6px; border: 1px solid #dbe3ec; background: #f8fafc; }
.image-batch-state { font-size: 12px; font-weight: 600; }
.image-batch-state-pending { color: #64748b; }
.image-batch-state-processing { color: #2563eb; }
.image-batch-state-updated { color: #15803d; }
.image-batch-state-unchanged { color: #0f766e; }
.image-batch-state-error { color: #dc2626; }
@media (max-width: 1000px) { .workspace { grid-template-columns: 210px minmax(0, 1fr); } .search-control { width: 280px; } }
@media (max-width: 760px) { .workspace { grid-template-columns: 1fr; } .category-panel { min-height: 0; } .search-control { width: 100%; } .page-head, .pager { align-items: flex-start; flex-direction: column; } }
</style>
