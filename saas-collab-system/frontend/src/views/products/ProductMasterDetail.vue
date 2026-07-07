<script setup>
// 后续对接API路径：GET /api/internal/products/master/{id}/
const form = {
  product_code: 'P-20260707001',
  spu: 'SPU-BAG-001',
  sku: 'SKU-BAG-BLK-S',
  product_name: '便携收纳包',
  category: '户外收纳',
  size: 'S / M / L',
  material: '尼龙',
  selling_points: '轻便、防泼水、多隔层',
  carton_weight: '12kg / 箱',
}
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>基础属性</h2>
          <el-button type="warning" disabled>编码冻结</el-button>
        </div>
      </template>

      <el-form :model="form" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="商品编码">
              <el-input v-model="form.product_code" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商品名称">
              <el-input v-model="form.product_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="SPU">
              <el-input v-model="form.spu" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="SKU">
              <el-input v-model="form.sku" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类目">
              <el-input v-model="form.category" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="尺码">
              <el-input v-model="form.size" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="材质">
              <el-input v-model="form.material" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="箱规重量">
              <el-input v-model="form.carton_weight" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="卖点">
              <el-input v-model="form.selling_points" type="textarea" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">图片占位</h2>
      </template>
      <div class="image-placeholders">
        <div>主图占位</div>
        <div>细节图占位</div>
        <div>包装图占位</div>
      </div>
    </el-card>
  </section>
</template>
