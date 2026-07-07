<script setup>
// 后续对接API路径：GET /api/internal/listings/site-profiles/
const rows = [
  {
    product_code: 'P-20260707001',
    sku: 'SKU-BAG-BLK-S',
    platform: 'Amazon',
    country: 'US',
    store: 'Mock Store US',
    title: 'Portable Storage Bag',
    category: 'Sports & Outdoors',
    listing_status: '待刊登',
    price_status: '待审批',
  },
]
</script>

<template>
  <section class="mvp-page">
    <el-card class="mvp-search" shadow="never">
      <el-form inline>
        <el-form-item label="商品编码">
          <el-input placeholder="搜索商品编码" disabled />
        </el-form-item>
        <el-form-item label="国家">
          <el-select placeholder="全部国家" disabled>
            <el-option label="US" value="US" />
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
          <h2>多国家刊登资料</h2>
          <el-button type="primary" disabled>新增站点资料</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="sku" label="SKU" min-width="150" />
        <el-table-column prop="platform" label="平台" min-width="100" />
        <el-table-column prop="country" label="国家" min-width="90" />
        <el-table-column prop="store" label="店铺" min-width="150" />
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="category" label="类目" min-width="160" />
        <el-table-column prop="listing_status" label="刊登状态" min-width="110" />
        <el-table-column prop="price_status" label="页面价格状态" min-width="130" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
