<template>
  <AppPage :title="isCategory ? 'Platform Category Mappings' : 'Product Attribute Mappings'" eyebrow="LISTING MAPPINGS" subtitle="Maintain tenant-scoped mappings without calling external platform APIs." capability="connected">
    <div class="toolbar"><el-button type="primary" @click="openCreate">Add mapping</el-button><el-button :loading="loading" @click="load">Refresh</el-button></div>
    <el-table :data="rows" v-loading="loading" border>
      <el-table-column prop="platform_name" label="Platform" width="140" /><el-table-column prop="country_code" label="Country" width="90" />
      <el-table-column :prop="isCategory ? 'source_category_code' : 'source_attribute_code'" :label="isCategory ? 'Internal category' : 'Internal attribute'" />
      <el-table-column :prop="isCategory ? 'target_category_code' : 'target_attribute_code'" :label="isCategory ? 'Platform category' : 'Platform field'" /><el-table-column prop="status" label="Status" width="110" />
      <el-table-column label="Actions" width="150"><template #default="{ row }"><el-button link type="primary" @click="edit(row)">Edit</el-button><el-button link type="danger" @click="remove(row)">Disable</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="dialog" :title="editing ? 'Edit mapping' : 'Add mapping'" width="560px">
      <el-form label-position="top"><el-form-item label="Platform ID" required><el-input-number v-model="form.platform" :min="1" /></el-form-item><el-form-item label="Country code"><el-input v-model="form.country_code" /></el-form-item>
        <template v-if="isCategory"><el-form-item label="Internal category code" required><el-input v-model="form.source_category_code" /></el-form-item><el-form-item label="Platform category code" required><el-input v-model="form.target_category_code" /></el-form-item><el-form-item label="Platform category name"><el-input v-model="form.target_category_name" /></el-form-item></template>
        <template v-else><el-form-item label="Internal attribute code" required><el-input v-model="form.source_attribute_code" /></el-form-item><el-form-item label="Platform attribute code" required><el-input v-model="form.target_attribute_code" /></el-form-item><el-form-item label="Required"><el-switch v-model="form.is_required" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="dialog = false">Cancel</el-button><el-button type="primary" :loading="saving" @click="save">Save</el-button></template>
    </el-dialog>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import { createAttributeMapping, createCategoryMapping, deleteAttributeMapping, deleteCategoryMapping, fetchAttributeMappings, fetchCategoryMappings, updateAttributeMapping, updateCategoryMapping } from '../../api/listings';
const props = defineProps({ mode: { type: String, default: 'category' } });
const isCategory = computed(() => props.mode === 'category'); const rows = ref([]); const loading = ref(false); const saving = ref(false); const dialog = ref(false); const editing = ref(null);
const blank = () => ({ platform: null, country_code: '', source_category_code: '', target_category_code: '', target_category_name: '', source_attribute_code: '', target_attribute_code: '', is_required: false });
const form = reactive(blank());
function collection(data) { return Array.isArray(data) ? data : data?.results || data?.items || []; }
async function load() { loading.value = true; const response = await (isCategory.value ? fetchCategoryMappings() : fetchAttributeMappings()); loading.value = false; rows.value = response.success ? collection(response.data) : []; }
function openCreate() { editing.value = null; Object.assign(form, blank()); dialog.value = true; }
function edit(row) { editing.value = row.id; Object.assign(form, row); dialog.value = true; }
async function save() { saving.value = true; const response = isCategory.value ? (editing.value ? await updateCategoryMapping(editing.value, form) : await createCategoryMapping(form)) : (editing.value ? await updateAttributeMapping(editing.value, form) : await createAttributeMapping(form)); saving.value = false; if (!response.success) return ElMessage.error(response.message || 'Save failed'); dialog.value = false; ElMessage.success('Mapping saved'); load(); }
async function remove(row) { try { await ElMessageBox.confirm('Disable this mapping? Historical drafts are retained.', 'Confirm'); } catch { return; } const response = isCategory.value ? await deleteCategoryMapping(row.id) : await deleteAttributeMapping(row.id); if (response.success) { ElMessage.success('Mapping disabled'); load(); } else ElMessage.error(response.message || 'Operation failed'); }
onMounted(load);
</script>
<style scoped>.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }</style>
