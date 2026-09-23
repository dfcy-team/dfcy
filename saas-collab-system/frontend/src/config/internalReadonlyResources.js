export const internalReadonlyModules = [
  { code: 'master_data', label: '基础档案' },
  { code: 'listing', label: '商品刊登' },
  { code: 'supply_chain', label: '采购与供应链' },
  { code: 'sales_inventory', label: '销售与库存' },
  { code: 'influencer_collaboration', label: '达人协作' },
];

export const internalReadonlyResources = [
  { module: 'master_data', code: 'products', label: '商品主数据', fields: ['id', 'sku', 'name', 'status', 'updated_at'] },
  { module: 'listing', code: 'platform_products', label: '平台商品', fields: ['id', 'platform', 'store_id', 'platform_sku', 'title', 'status', 'updated_at'] },
  { module: 'master_data', code: 'suppliers', label: '供应商档案', fields: ['id', 'code', 'name', 'status', 'updated_at'] },
  { module: 'master_data', code: 'stores', label: '店铺档案', fields: ['id', 'platform', 'code', 'name', 'status', 'updated_at'] },
  { module: 'master_data', code: 'warehouses', label: '仓库档案', fields: ['id', 'code', 'name', 'status', 'updated_at'] },
  { module: 'supply_chain', code: 'purchase_orders', label: '采购订单', fields: ['id', 'order_number', 'supplier_id', 'status', 'ordered_at', 'updated_at'] },
  { module: 'supply_chain', code: 'supplier_shipments', label: '供应商发货', fields: ['id', 'purchase_order_id', 'tracking_number', 'status', 'shipped_at', 'updated_at'] },
  { module: 'sales_inventory', code: 'sales_orders', label: '销售订单', fields: ['id', 'order_number', 'store_id', 'status', 'ordered_at', 'updated_at'] },
  { module: 'sales_inventory', code: 'sales_returns', label: '退款退货', fields: ['id', 'sales_order_id', 'return_number', 'status', 'created_at', 'updated_at'] },
  { module: 'sales_inventory', code: 'inventory_snapshots', label: '库存快照', fields: ['id', 'warehouse_id', 'sku', 'available_quantity', 'reserved_quantity', 'snapshot_at', 'updated_at'] },
  { module: 'supply_chain', code: 'shipments', label: '出库发运', fields: ['id', 'shipment_number', 'warehouse_id', 'tracking_number', 'status', 'shipped_at', 'updated_at'] },
  { module: 'influencer_collaboration', code: 'influencers', label: '达人档案', fields: ['id', 'platform', 'handle', 'display_name', 'status', 'updated_at'] },
  { module: 'influencer_collaboration', code: 'outreach_tasks', label: '建联任务', fields: ['id', 'influencer_id', 'owner_id', 'status', 'due_at', 'updated_at'] },
  { module: 'influencer_collaboration', code: 'sample_fulfillments', label: '送样履约', fields: ['id', 'influencer_id', 'sku', 'tracking_number', 'status', 'shipped_at', 'updated_at'] },
];

export const internalReadonlyResourceFields = Object.fromEntries(
  internalReadonlyResources.map(({ code, fields }) => [code, fields]),
);
