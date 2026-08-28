<template>
  <section class="business-page">
    <header class="page-head">
      <div>
        <h1>商品明细数据</h1>
        <p>维护旧 SKU 与新 SPU/SKU 的对应关系。导入后可逐条补充信息，再生成新编码。</p>
      </div>
      <div class="header-actions">
        <el-button @click="downloadTemplate">下载导入模板</el-button>
        <el-button v-if="canManage" @click="openImageBatch">批量导入图片</el-button>
        <el-button v-if="canManage" type="primary" @click="$refs.file?.click()">导入旧商品</el-button>
        <el-button v-if="canManage" @click="openBulk">批量修改</el-button>
        <input ref="file" hidden type="file" accept=".csv,text/csv" @change="importFile" />
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
          <el-table-column type="index" label="序号" width="70" :index="(page - 1) * pageSize + 1" />
          <el-table-column v-if="canManage" type="selection" width="48" reserve-selection />
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
          <el-table-column label="图片" width="92" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.image_url || row.image"
                class="product-image-thumb"
                :src="resolveImageUrl(row.image_url || row.image)"
                :preview-src-list="[resolveImageUrl(row.image_url || row.image)]"
                preview-teleported
                fit="cover"
                loading="lazy"
              />
              <span v-else class="image-placeholder">无图</span>
            </template>
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
                  link
                  :type="row.sku_is_active ? 'warning' : 'success'"
                  @click="toggleStatus(row)"
                >
                  {{ row.sku_is_active ? '停用' : '启用' }}
                </el-button>
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

    <el-dialog v-model="imageBatchVisible" title="批量导入商品图片" width="min(920px, 94vw)" :close-on-click-modal="false">
      <div class="image-batch-toolbar">
        <input ref="imageBatchFile" hidden type="file" accept=".csv,text/csv" @change="parseImageBatchFile" />
        <el-button @click="downloadImageBatchTemplate">下载图片导入模板</el-button>
        <el-button @click="imageBatchFile?.click()">选择 CSV 文件</el-button>
        <span class="image-batch-hint">字段：旧SKU编码、新SKU编码、图片链接；旧/新 SKU 至少填写一个。</span>
        <span v-if="imageBatchProgress" class="image-batch-progress">{{ imageBatchProgress }}</span>
      </div>
      <el-alert v-if="imageBatchError" class="image-batch-error" :title="imageBatchError" type="warning" :closable="false" />
      <el-table v-if="imageBatchRows.length" :data="imageBatchRows" border max-height="360" class="image-batch-table">
        <el-table-column type="index" label="序号" width="70" />
        <el-table-column prop="legacy_sku_code" label="旧SKU编码" min-width="150" show-overflow-tooltip />
        <el-table-column prop="sku_code" label="新SKU编码" min-width="150" show-overflow-tooltip />
        <el-table-column prop="image_url" label="图片链接" min-width="280" show-overflow-tooltip />
        <el-table-column prop="status" label="处理状态" width="110">
          <template #default="{ row }">{{ imageBatchStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column prop="cached_url" label="服务器缓存地址" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.cached_url || '-' }}</template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.message || '-' }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="请选择图片 CSV 文件预览" :image-size="70" />
      <template #footer>
        <el-button @click="imageBatchVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="imageBatchSaving"
          :disabled="!imageBatchRows.some((row) => row.valid)"
          @click="submitImageBatch"
        >
          提交并缓存图片
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importing" title="导入旧商品" width="min(560px, 94vw)" :close-on-click-modal="false" :show-close="false">
      <el-steps :active="importStep" finish-status="success" align-center>
        <el-step title="读取文件" />
        <el-step title="校验数据" />
        <el-step title="增量更新" />
        <el-step title="完成" />
      </el-steps>
      <el-progress class="import-progress" :percentage="importPercent" :indeterminate="importing" :duration="8" />
      <p class="import-status">{{ importStage }} · 已用时 {{ formatDuration(importElapsed) }}</p>
      <p class="import-hint">重复的旧 SKU 不会新增记录；有变化的字段才会更新。</p>
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
  fetchProductColors,
  fetchProductAttributes,
  fetchProductDetailList,
  importLegacyProductItems,
  updateLegacyProductItem,
  generateLegacyProductItem,
  updateProductSku,
  bulkUpdateProductDetails,
  bulkCacheProductImages,
} from '../../api/products';
import { collectionRows, collectionTotal } from '../../utils/businessResponse';
import { apiBaseUrl } from '../../api/baseUrl';
import { buildCategoryTree, categoryRowClass, categoryRowStyle } from '../../utils/productCategoryPresentation';
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
  id: null, rowType: '', product_name: '', category_node: null, purchase_price: '', is_active: true,
  package_weight: '', package_volume: '', package_length_cm: '', package_width_cm: '', package_height_cm: '',
  origin_country: '', hs_code: '', image_url: '', clearFields: [], hasSku: false, allowCategory: false, generated: false,
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

function openImageBatch() {
  if (!canManage.value) return;
  imageBatchRows.value = [];
  imageBatchError.value = '';
  imageBatchProgress.value = '';
  imageBatchVisible.value = true;
}

function imageBatchStatusLabel(status) {
  return ({ pending: '待提交', processing: '处理中', success: '成功', updated: '已更新', unchanged: '无变化', error: '失败' })[status] || '待提交';
}

function validateImageBatchRow(row) {
  if (!row.legacy_sku_code && !row.sku_code) return '旧 SKU 编码和新 SKU 编码至少填写一个';
  if (!row.image_url) return '图片链接不能为空';
  if (!/^(?:https?:\/\/|\/media\/)/i.test(row.image_url)) return '图片链接需为 http(s) URL 或 /media/ 地址';
  return '';
}

async function parseImageBatchFile(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!/\.csv$/i.test(file.name)) {
    imageBatchError.value = '图片批量导入当前仅支持 CSV 文件，请先另存为 CSV。';
    return;
  }
  const bytes = await file.arrayBuffer();
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { text = new TextDecoder('gb18030').decode(bytes); }
  const parsed = parseCsvRows(text);
  const headers = parsed.shift() || [];
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
      message: '',
    };
    const error = validateImageBatchRow(row);
    return { ...row, valid: !error, status: error ? 'error' : 'pending', message: error };
  });
  imageBatchRows.value = rowsFromFile;
  imageBatchError.value = rowsFromFile.length ? '' : 'CSV 中没有可预览的数据行。';
}

function downloadImageBatchTemplate() {
  const csv = '\ufeff旧SKU编码,新SKU编码,图片链接\r\nOLD-SKU-001,101010004-blue,https://example.com/product.jpg\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = '商品图片批量导入模板.csv'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function submitImageBatch() {
  const validRows = imageBatchRows.value.filter((row) => row.valid);
  if (!validRows.length || imageBatchSaving.value) return;
  imageBatchSaving.value = true;
  validRows.forEach((row) => { row.status = 'processing'; row.message = ''; });
  // Keep each request small enough for the reverse proxy timeout while still
  // allowing the dialog to report progress and retain per-row results.
  const batchSize = 5;
  let completed = 0;
  let failed = 0;
  let succeeded = 0;
  imageBatchProgress.value = `处理中：0 / ${validRows.length}`;
  try {
    const resultKey = (item) => `${item.legacy_sku_code || item.old_sku_code || ''}::${item.sku_code || item.new_sku_code || ''}`;
    for (let offset = 0; offset < validRows.length; offset += batchSize) {
      const batchRows = validRows.slice(offset, offset + batchSize);
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
        batchRows.forEach((row) => { row.status = 'error'; row.message = message; });
        failed += batchRows.length;
      } else if (!resultRows.length) {
        batchRows.forEach((row) => { row.status = 'error'; row.message = '服务器未返回逐行处理结果'; });
        failed += batchRows.length;
      } else {
        const resultMap = new Map(resultRows.map((item) => [resultKey(item), item]));
        batchRows.forEach((row, index) => {
          const result = resultMap.get(resultKey(row)) || resultRows[index];
          if (!result) {
            row.status = 'error';
            row.message = '服务器未返回该行处理结果';
            failed += 1;
            return;
          }
          const resultStatus = String(result.status || '').toLowerCase();
          row.status = resultStatus === 'error' || result.success === false || result.error
            ? 'error'
            : ['updated', 'unchanged'].includes(resultStatus) ? resultStatus : 'success';
          row.cached_url = result.cached_url || result.image_url || result.url || '';
          row.message = result.message || (resultStatus === 'unchanged' ? '图片地址未变化' : row.status !== 'error' ? '已提交服务器缓存' : '服务器未返回缓存地址');
          if (row.status === 'error') failed += 1;
          else succeeded += 1;
        });
      }
      completed += batchRows.length;
      imageBatchProgress.value = `处理中：${completed} / ${validRows.length}`;
    }
    imageBatchProgress.value = `处理完成：成功 ${succeeded} 条，失败 ${failed} 条`;
    imageBatchError.value = failed ? `图片缓存完成：成功 ${succeeded} 条，失败 ${failed} 条，请检查失败行说明。` : '';
    if (succeeded) await load();
  } finally {
    imageBatchSaving.value = false;
  }
}
function search() { page.value = 1; load(); }
function reset() { filters.search = ''; filters.sku_status = 'all'; selectCategory(null); }
function changePageSize() { page.value = 1; load(); }

async function load() {
  loading.value = true;
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
  } else {
    rows.value = [];
    total.value = 0;
    show(response.message || '商品明细加载失败', 'error');
  }
  loading.value = false;
}

async function loadDictionaries() {
  const [categoryResponse, colorResponse, attributeResponse] = await Promise.all([
    fetchProductCategories(), fetchProductColors(), fetchProductAttributes(),
  ]);
  if (categoryResponse.success) categories.value = collectionRows(categoryResponse.data);
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
  if (editForm.hasSku) payload.is_active = editForm.is_active;
  if (editForm.clearFields.length) payload.clear_fields = [...new Set(editForm.clearFields)];
  if (!Object.keys(payload).length && !payload.clear_fields?.length) { show('请至少填写一个需要修改的字段', 'warning'); return; }
  saving.value = true;
  const response = editForm.rowType === 'sku'
    ? await updateProductSku(editForm.id, payload)
    : await updateLegacyProductItem(editForm.id, payload);
  saving.value = false;
  if (!response.success) { show(response.message || '保存失败', 'error'); return; }
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
  const next = !row.sku_is_active;
  try {
    await ElMessageBox.confirm(`确认${next ? '启用' : '停用'} SKU“${row.sku_code}”？`, `${next ? '启用' : '停用'}确认`, { type: next ? 'info' : 'warning' });
  } catch { return; }
  const response = await updateProductSku(row.sku_id, { is_active: next });
  if (!response.success) { show(response.message || '商品状态更新失败', 'error'); return; }
  show(`SKU 已${next ? '启用（在售）' : '停用（下架）'}`);
  await load();
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
    const response = await importLegacyProductItems(csvText);
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
  const csv = '\ufeff旧SPU编码,旧SKU编码,商品名称,完整类目编码,属性码,颜色英文编码,规格,采购价格\nOLD-SPU-001,OLD-SKU-001,示例 SKU 商品,10101,0,navy,150cm×220cm,35.8000\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = '旧商品导入模板.csv'; anchor.click(); URL.revokeObjectURL(url);
}

onMounted(() => { loadDictionaries(); load(); });
</script>

<style scoped>
.business-page { display: grid; gap: 16px; }
.page-head, .pager { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head h1 { margin: 0 0 8px; }
.page-head p { margin: 0; color: #64748b; }
.header-actions, .row-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
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
.image-batch-error { margin-top: 14px; }
.image-batch-table { margin-top: 14px; }
@media (max-width: 1000px) { .workspace { grid-template-columns: 210px minmax(0, 1fr); } .search-control { width: 280px; } }
@media (max-width: 760px) { .workspace { grid-template-columns: 1fr; } .category-panel { min-height: 0; } .search-control { width: 100%; } .page-head, .pager { align-items: flex-start; flex-direction: column; } }
</style>
