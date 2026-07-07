<script setup>
// 后续对接API路径：GET /api/internal/pricing/prices/
const rows = [
  {
    product_code: 'P-20260707001',
    sku: 'SKU-BAG-BLK-S',
    country: 'US',
    purchase_cost: '18.50',
    logistics_cost: '4.20',
    platform_commission: '15%',
    exchange_rate: '7.20',
    suggested_price: '29.99',
    approved_price: '28.99',
    page_price: '29.49',
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
          <h2>价格列表</h2>
          <el-button type="primary" disabled>批量测算</el-button>
        </div>
      </template>

      <el-table :data="rows" border>
        <el-table-column prop="product_code" label="商品编码" min-width="150" />
        <el-table-column prop="sku" label="SKU" min-width="150" />
        <el-table-column prop="country" label="国家" min-width="90" />
        <el-table-column prop="purchase_cost" label="采购成本" min-width="110" />
        <el-table-column prop="logistics_cost" label="物流成本" min-width="110" />
        <el-table-column prop="platform_commission" label="平台佣金" min-width="110" />
        <el-table-column prop="exchange_rate" label="汇率" min-width="90" />
        <el-table-column prop="suggested_price" label="建议价" min-width="100" />
        <el-table-column prop="approved_price" label="审批价" min-width="100" />
        <el-table-column prop="page_price" label="页面价" min-width="100" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default>
            <el-button link type="primary" disabled>查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
