<script setup>
// 后续对接API路径：GET /api/internal/products/research/{id}/
const form = {
  research_no: 'RS-20260707001',
  product_name: '便携收纳包',
  platform: 'Amazon US',
  estimated_sales: 1200,
  estimated_gross_profit: '28%',
  status: '待评估',
}

const competitors = [
  { name: '竞品A', platform: 'Amazon US', price: '$19.99', url: 'https://example.com/mock-a' },
  { name: '竞品B', platform: 'Amazon US', price: '$22.50', url: 'https://example.com/mock-b' },
]
</script>

<template>
  <section class="detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>市调基础信息</h2>
          <el-button type="primary" disabled>提交审批</el-button>
        </div>
      </template>

      <el-form :model="form" label-width="120px" disabled>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="市调编号">
              <el-input v-model="form.research_no" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商品名称">
              <el-input v-model="form.product_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="平台">
              <el-input v-model="form.platform" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-input v-model="form.status" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="预估销量">
              <el-input v-model="form.estimated_sales" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="预估毛利">
              <el-input v-model="form.estimated_gross_profit" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">竞品资料区</h2>
      </template>
      <el-table :data="competitors" border>
        <el-table-column prop="name" label="竞品名称" min-width="140" />
        <el-table-column prop="platform" label="平台" min-width="120" />
        <el-table-column prop="price" label="价格" min-width="100" />
        <el-table-column prop="url" label="竞品链接" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <h2 class="section-title">附件上传占位</h2>
      </template>
      <el-upload action="#" disabled drag>
        <div>附件上传将在后续对接真实接口后启用</div>
      </el-upload>
    </el-card>
  </section>
</template>
