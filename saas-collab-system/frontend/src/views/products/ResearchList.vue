<script setup>
// 后续对接API路径：GET /api/internal/products/research/
const rows = [
  {
    research_no: 'RS-20260707001',
    product_name: '便携收纳包',
    platform: 'Amazon US',
    competitor_url: 'https://example.com/product/mock',
    estimated_sales: 1200,
    estimated_gross_profit: '28%',
    status: '待评估',
    creator: '产品专员',
    created_at: '2026-07-07 10:00',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="商品名称">
          <el-input placeholder="搜索商品名称" disabled />
        </el-form-item>
        <el-form-item label="平台">
          <el-select placeholder="全部平台" disabled>
            <el-option label="Amazon US" value="amazon_us" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" disabled>搜索</el-button>
          <el-button disabled>重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="mvp-table-card" shadow="never">
      <template #header>
        <div class="mvp-table-header">
          <h2>新品市调列表</h2>
          <el-button type="primary" disabled>新增市调</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="research_no" label="市调编号" min-width="150" />
        <el-table-column prop="product_name" label="商品名称" min-width="160" />
        <el-table-column prop="platform" label="平台" min-width="120" />
        <el-table-column prop="competitor_url" label="竞品链接" min-width="220" show-overflow-tooltip />
        <el-table-column prop="estimated_sales" label="预估销量" min-width="110" />
        <el-table-column prop="estimated_gross_profit" label="预估毛利" min-width="110" />
        <el-table-column prop="status" label="状态" min-width="100" />
        <el-table-column prop="creator" label="创建人" min-width="110" />
        <el-table-column prop="created_at" label="创建时间" min-width="160" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
