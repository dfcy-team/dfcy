<script setup>
// 后续对接API路径：GET /api/internal/listings/site-profiles/{id}/
const form = {
  product_code: 'P-20260707001',
  sku: 'SKU-BAG-BLK-S',
  platform: 'Amazon',
  country: 'US',
  store: 'Mock Store US',
  title: 'Portable Storage Bag',
  keywords: 'storage, travel, outdoor',
  description: 'Mock localized listing description.',
  size_rule: 'US size rule placeholder',
  platform_category: 'Sports & Outdoors',
}
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>国家站点资料</h2>
          <el-button type="primary" disabled>生成RPA刊登任务</el-button>
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
            <el-form-item label="SKU">
              <el-input v-model="form.sku" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="平台">
              <el-input v-model="form.platform" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="国家">
              <el-input v-model="form.country" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="店铺">
              <el-input v-model="form.store" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">平台差异字段</h2>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="尺码规则">{{ form.size_rule }}</el-descriptions-item>
        <el-descriptions-item label="平台类目">{{ form.platform_category }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">本地化内容</h2>
      </template>
      <el-form :model="form" label-width="120px" disabled>
        <el-form-item label="本地化标题">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="本地关键词">
          <el-input v-model="form.keywords" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">图片资料</h2>
      </template>
      <div class="image-placeholders">
        <div>主图资料占位</div>
        <div>场景图资料占位</div>
        <div>平台图片规则占位</div>
      </div>
    </el-card>
  </section>
</template>
