<template>
  <section>
    <div class="head">
      <div>
        <h1>商品明细数据</h1>
        <p>查看 SKU 明细，将旧商品转换为新的编码体系。</p>
      </div>
      <div>
        <el-button @click="template">下载导入模板</el-button
        ><el-button v-if="canManage" type="primary" @click="$refs.file.click()"
          >导入旧商品</el-button
        ><input
          ref="file"
          hidden
          type="file"
          accept=".csv"
          @change="importFile"
        />
      </div>
    </div>
    <el-alert
      v-if="message"
      :title="message"
      :type="messageType"
      show-icon
      closable
      @close="message = ''"
    />
    <div class="filters">
      <span>显示状态</span>
      <el-select v-model="activeStatus" style="width: 150px" @change="load">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="inactive" />
        <el-option label="全部" value="all" />
      </el-select>
    </div>
    <el-table :data="rows" v-loading="loading" border style="margin-top: 16px"
      ><el-table-column
        prop="legacy_spu_code"
        label="旧 SPU 编码"
        min-width="130"
      /><el-table-column
        prop="legacy_sku_code"
        label="旧 SKU 编码"
        min-width="150"
      /><el-table-column
        prop="spu_code"
        label="新 SPU 编码"
        min-width="130"
      /><el-table-column
        prop="sku_code"
        label="新 SKU 编码"
        min-width="210"
      /><el-table-column
        prop="product_name"
        label="商品名称"
        min-width="180"
      /><el-table-column
        prop="category_name"
        label="分类"
        min-width="110"
      /><el-table-column
        prop="color_code"
        label="颜色"
        min-width="100"
      /><el-table-column
        prop="specification"
        label="规格"
        min-width="150"
      /><el-table-column
        prop="purchase_price"
        label="采购价格"
        min-width="110"
        align="right"
      /><el-table-column
        prop="status_name"
        label="状态"
        width="100"
      /><el-table-column label="操作" width="180"
        ><template #default="{ row }"
          ><el-button
            v-if="row.row_type === 'legacy' && canManage"
            link
            type="primary"
            @click="edit(row)"
            >调整并生成</el-button>
          <template v-if="row.row_type === 'sku' && canManage">
            <el-button link :type="row.is_active ? 'warning' : 'success'" @click="toggleStatus(row)">
              {{ row.is_active ? "停用" : "启用" }}
            </el-button>
            <el-button link type="danger" @click="removeSku(row)">删除</el-button>
          </template
          ></template
        ></el-table-column
      ></el-table
    >
    <el-dialog v-model="visible" title="调整旧商品并生成新编码" width="600px"
      ><el-form label-position="top"
        ><el-form-item label="商品名称"
          ><el-input v-model="form.product_name" /></el-form-item
        ><el-form-item label="末级分类"
          ><el-select
            v-model="form.category_node"
            filterable
            style="width: 100%"
            ><el-option
              v-for="x in leaves"
              :key="x.id"
              :label="`${x.code} ${x.name}`"
              :value="x.id" /></el-select></el-form-item
        ><el-form-item label="属性字段（选填，未填自动补 0）"
          ><el-select
            v-model="form.attribute_code"
            clearable
            style="width: 100%"
            ><el-option
              v-for="x in attributes"
              :key="x.id"
              :label="`${x.code} ${x.name}`"
              :value="x.code" /></el-select></el-form-item
        ><el-form-item label="颜色"
          ><el-select v-model="form.color_code" filterable style="width: 100%"
            ><el-option
              v-for="x in colors.filter((v) => v.is_active)"
              :key="x.id"
              :label="`${x.code} ${x.name}`"
              :value="x.code" /></el-select></el-form-item
        ><el-form-item label="规格"
          ><el-select
            v-if="specOptions.length"
            v-model="form.specification"
            filterable
            allow-create
            style="width: 100%"
            ><el-option
              v-for="x in specOptions"
              :key="x"
              :label="x"
              :value="x" /></el-select
          ><el-input
            v-else
            v-model="form.specification"
            placeholder="例如 150cm×220cm" /></el-form-item
        ><el-form-item label="采购价格（选填）"
          ><el-input-number v-model="form.purchase_price" :min="0" :precision="4" :step="1" style="width:100%" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="visible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="save"
          >生成新编码</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="errorVisible" title="导入异常明细" width="700px">
      <el-alert :title="`共 ${importErrors.length} 行导入异常，请按行号修正后重新导入。`" type="error" :closable="false" />
      <el-table :data="importErrors" border style="margin-top:12px" max-height="420">
        <el-table-column prop="line" label="CSV 行号" width="100" />
        <el-table-column prop="message" label="错误原因" min-width="480" />
      </el-table>
      <template #footer><el-button type="primary" @click="errorVisible=false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessageBox } from "element-plus";
import { useAuthStore } from "../../stores/auth";
import {
  fetchProductMasterList,
  fetchProductSkuList,
  fetchLegacyProductItems,
  importLegacyProductItems,
  updateLegacyProductItem,
  generateLegacyProductItem,
  fetchProductCategories,
  fetchProductColors,
  fetchProductAttributes,
  updateProductSku,
  deleteProductSku,
} from "../../api/products";
import { collectionRows } from "../../utils/businessResponse";
const auth = useAuthStore(),
  canManage = computed(() => auth.hasPermission("products.master.manage")),
  loading = ref(false),
  saving = ref(false),
  message = ref(""),
  messageType = ref("success"),
  rows = ref([]),
  activeStatus = ref("active"),
  categories = ref([]),
  colors = ref([]),
  attributes = ref([]),
  visible = ref(false),
  errorVisible = ref(false),
  importErrors = ref([]),
  form = reactive({
    id: null,
    product_name: "",
    category_node: null,
    attribute_code: "",
    color_code: "",
    specification: "",
    purchase_price: null,
  });
const leaves = computed(() => {
    return categories.value.filter((x) => x.is_active && (x.level === 2 || x.level === 3));
  }),
  selectedCategory = computed(() =>
    categories.value.find((x) => x.id === form.category_node),
  ),
  specOptions = computed(
    () => selectedCategory.value?.spec_dimensions?.[0]?.values || [],
  );
async function load() {
  loading.value = true;
  const [s, k, l, c, o, a] = await Promise.all([
      fetchProductMasterList({ page_size: 100 }),
      fetchProductSkuList({ page_size: 100, active_status: activeStatus.value }),
    fetchLegacyProductItems(),
    fetchProductCategories(),
    fetchProductColors(),
    fetchProductAttributes(),
  ]);
  categories.value = collectionRows(c.data);
  colors.value = collectionRows(o.data);
  attributes.value = collectionRows(a.data);
  const spus = collectionRows(s.data),
    map = new Map(spus.map((x) => [x.id, x]));
  const skus = collectionRows(k.data).map((x) => {
    const p = map.get(x.spu) || {};
    return {
      row_type: "sku",
      legacy_spu_code: p.legacy_spu_code || "",
      legacy_sku_code: x.legacy_sku_code || "",
      spu_code: p.spu_code,
      sku_code: x.sku_code,
      product_name: p.product_name,
      category_name: p.category,
      color_code: x.color_code,
      specification: x.specification,
      purchase_price: x.purchase_price,
      status_name: x.is_active ? "启用" : "停用",
      is_active: x.is_active,
      id: x.id,
    };
  });
  const old = collectionRows(l.data)
    .filter((x) => x.status !== "generated")
    .map((x) => ({
      ...x,
      row_type: "legacy",
      spu_code: "-",
      sku_code: "-",
      status_name: x.status === "error" ? "生成失败" : "待转换",
    }));
  rows.value = [...(activeStatus.value === "inactive" ? [] : old), ...skus];
  loading.value = false;
}
async function toggleStatus(row) {
  const next = !row.is_active;
  await ElMessageBox.confirm(
    `确认${next ? "启用" : "停用"} SKU“${row.sku_code}”？停用不会修改历史业务数据。`,
    `${next ? "启用" : "停用"}确认`,
    { type: next ? "info" : "warning" },
  );
  const response = await updateProductSku(row.id, { is_active: next });
  if (!response.success) return show(response.message || "状态更新失败", "error");
  show(`SKU 已${next ? "启用" : "停用"}`);
  load();
}
async function removeSku(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除 SKU“${row.sku_code}”？仅没有任何业务关联时可以删除。`,
      "删除 SKU",
      { type: "warning" },
    );
  } catch {
    return;
  }
  const response = await deleteProductSku(row.id);
  if (!response.success) return show(response.message || "删除失败，请改为停用", "warning");
  show("SKU 已删除");
  load();
}
function edit(x) {
  Object.assign(form, {
    id: x.id,
    product_name: x.product_name,
    category_node: x.category_node,
    attribute_code: x.attribute_code === "0" ? "" : x.attribute_code,
    color_code: x.color_code,
    specification: x.specification,
    purchase_price: x.purchase_price == null ? null : Number(x.purchase_price),
  });
  visible.value = true;
}
function show(v, t = "success") {
  message.value = v;
  messageType.value = t;
}
async function save() {
  if (!form.category_node || !form.color_code)
    return show("请选择末级分类和颜色", "warning");
  saving.value = true;
  const u = await updateLegacyProductItem(form.id, {
      product_name: form.product_name,
      category_node: form.category_node,
      attribute_code: form.attribute_code || "",
      color_code: form.color_code,
      specification: form.specification || "",
      purchase_price: form.purchase_price,
    }),
    g = u.success ? await generateLegacyProductItem(form.id) : u;
  saving.value = false;
  if (g.success) {
    visible.value = false;
    show("新 SPU/SKU 编码已生成");
    load();
  } else show(g.message || "生成失败", "error");
}
async function importFile(e) {
  const f = e.target.files?.[0];
  if (!f) return;
  const bytes = await f.arrayBuffer();
  let csvText;
  try {
    csvText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    csvText = new TextDecoder("gb18030").decode(bytes);
  }
  const r = await importLegacyProductItems(csvText);
  e.target.value = "";
  if (r.success) {
    const generated = r.data?.generated || 0;
    importErrors.value = Array.isArray(r.data?.errors) ? r.data.errors : [];
    if (importErrors.value.length) {
      errorVisible.value = true;
      show(`导入完成：生成 ${generated} 个 SKU，${importErrors.value.length} 行异常。`, "warning");
    } else {
      show(generated ? `旧商品已导入并自动生成 ${generated} 个 SKU` : "旧商品已导入；信息不完整的记录请继续调整");
    }
    load();
  } else {
    importErrors.value = Array.isArray(r.data?.errors) ? r.data.errors : [];
    if (importErrors.value.length) errorVisible.value = true;
    show(r.message || "导入失败", "error");
  }
}
function template() {
  const csv =
      "\ufeff旧SPU编码,旧SKU编码,商品名称,完整类目编码,属性码,颜色英文编码,规格,采购价格\nOLD-SPU-001,OLD-SKU-001,示例商品,10101,0,navy,150cm×220cm,35.8000\n",
    a = document.createElement("a");
  a.href = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  a.download = "旧商品导入模板.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
onMounted(load);
</script>
<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.head h1 {
  margin: 0 0 8px;
}
.head p {
  margin: 0;
  color: #64748b;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  color: #475569;
}
</style>
