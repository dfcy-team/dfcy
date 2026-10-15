<template>
  <AppPage :title="supplier ? '发货单' : '供应商发货单'" :subtitle="supplier ? '填写采购订单的分批发货信息，并上传包含全部箱号的文件。' : '协助供应商录入发货，核对价格与到仓状态。'" :capability="error ? 'degraded' : 'connected'">
    <template #action><el-button @click="load" :disabled="busy">刷新</el-button><el-button v-if="canManage" type="primary" @click="newShipment" :disabled="busy || !selectedOrder">新建发货草稿</el-button></template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="notice" />
    <section class="filters">
      <el-select v-model="orderId" filterable clearable :disabled="!!route.query.order_id" placeholder="选择采购订单" aria-label="选择采购订单" @change="onOrderChange">
        <el-option v-for="o in orders" :key="o.id" :label="`${o.number} · ${o.supplier_name || '供应商'} · ${o.country_code || ''}`" :value="o.id" />
        <template #footer><el-button v-if="orderOffset < orderTotal" link :loading="ordersLoadingMore" @click="loadMoreOrders">加载更多采购订单</el-button><span v-else class="sub">采购订单已加载完</span></template>
      </el-select>
      <el-select v-model="status" clearable placeholder="全部发货状态" aria-label="发货状态" @change="onOrderChange"><el-option label="草稿" value="draft"/><el-option label="已提交" value="submitted"/><el-option label="已作废" value="cancelled"/></el-select>
      <el-button @click="load" :disabled="busy">查询</el-button>
    </section>
    <div class="table-scroll" v-loading="loading">
      <el-table :data="shipments" border stripe empty-text="暂无发货单">
        <el-table-column prop="number" label="发货单号" min-width="160"/><el-table-column prop="order_number" label="采购订单" min-width="160"/><el-table-column v-if="!supplier" prop="supplier_name" label="供应商" min-width="150"/>
        <el-table-column label="发货方式" width="150"><template #default="{row}">{{ row.delivery_mode==='factory_loading' ? '货柜上门装载' : '送集货中心' }}</template></el-table-column><el-table-column prop="shipment_date" label="发货日期" width="130"/><el-table-column label="件数" width="90" align="right"><template #default="{row}">{{ totalQty(row) }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="row.status==='submitted'?'success':row.status==='cancelled'?'info':'warning'">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="集货到仓" width="110"><template #default="{row}">{{ row.delivery_mode==='factory_loading' ? '不经集货中心' : row.collection_arrived ? '已到仓' : '未到仓' }}</template></el-table-column><el-table-column label="箱号文件" width="110"><template #default="{row}">{{ row.attachments?.length || 0 }} 个</template></el-table-column>
        <el-table-column label="批次物流" width="120"><template #default="{row}">{{ logisticsText(row.logistics_stage) }}</template></el-table-column>
        <el-table-column label="操作" width="120" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openShipment(row)">查看 / 编辑</el-button></template></el-table-column>
      </el-table>
    </div>
    <el-pagination class="pagination" background layout="total, sizes, prev, pager, next" :total="total" :current-page="page" :page-size="limit" :page-sizes="[10,20,50]" @current-change="p=>{page=p;loadShipments()}" @size-change="s=>{limit=s;page=1;loadShipments()}"/>

    <el-drawer v-model="open" :title="current?.number || '新建发货草稿'" size="min(1080px, 96vw)" :before-close="closeDrawer">
      <template v-if="current">
        <el-alert v-if="current.status==='submitted'" title="发货单已提交；采购可调整价格，供应商可查看与下载箱号文件。" type="info" :closable="false" class="notice"/>
        <el-form-item v-if="!supplier && current.status==='submitted' && current.price_adjustment_requires_reason" label="调价原因（必填）"><el-input v-model="priceReason" placeholder="说明已集货后的价格调整原因" :disabled="busy"/></el-form-item>
        <CostSettlementLinkV2 v-if="!supplier && current.status==='submitted'" kind="shipment" :id="current.id" :version="current.version" @updated="onCostUpdated" />
        <div class="form-grid"><el-form-item label="采购订单"><el-input :model-value="current.order_number" disabled/></el-form-item><el-form-item label="发货日期 *"><el-date-picker v-model="form.shipment_date" type="date" value-format="YYYY-MM-DD" :disabled="!canEdit"/></el-form-item></div>
        <el-form-item label="发货方式 *"><el-select v-model="form.delivery_mode" :disabled="!canEdit" aria-label="发货方式"><el-option label="送集货中心" value="collection_center"/><el-option label="货柜上门装载" value="factory_loading"/></el-select></el-form-item><el-form-item v-if="form.delivery_mode==='factory_loading'" label="装柜地址（提交时必填）"><el-input v-model="form.loading_address" type="textarea" :disabled="!canEdit" maxlength="4000" aria-label="装柜地址" placeholder="未填写时带入供应商装柜地址或工厂地址"/></el-form-item><p v-if="form.delivery_mode==='factory_loading'" class="sub">货柜到供应商地址装载，无需集货到仓标识；提交后仍按发运批次跟踪开船、到港和目的仓到仓。</p><el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" :disabled="!canEdit"/></el-form-item>
        <el-descriptions border :column="2" class="notice">
          <el-descriptions-item label="批次物流状态">{{ logisticsText(current.logistics_stage) }}</el-descriptions-item>
          <el-descriptions-item label="开船时间">{{ logisticsDate(current.logistics_dates?.departed_at) }}</el-descriptions-item>
          <el-descriptions-item label="到港时间">{{ logisticsDate(current.logistics_dates?.arrived_port_at) }}</el-descriptions-item>
          <el-descriptions-item label="目的仓到仓时间">{{ logisticsDate(current.logistics_dates?.arrived_warehouse_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="heading"><h3>本次发货商品</h3><el-button v-if="canEdit" @click="addLine">添加 SKU</el-button></div>
        <div class="table-scroll"><el-table :data="form.lines" border>
          <el-table-column type="index" label="行" width="55"/><el-table-column label="商品图片" width="112"><template #default="{row}"><DocumentProductImageV2 :image-path="row.image_preview_url || ''" :alt="`${row.sku || ''} 商品图片`"/></template></el-table-column><el-table-column label="SKU / 商品" min-width="210"><template #default="{row}"><el-select v-if="canEdit && !row.id" v-model="row.sku_id" filterable placeholder="选择 SKU" @change="changeLineSku(row)"><el-option v-for="sku in skus" :key="sku.id" :label="`${sku.sku_code}${sku.legacy_sku_code ? ` · 旧 ${sku.legacy_sku_code}` : ''} · ${sku.product_name}`" :value="sku.id"/></el-select><DocumentSkuV2 v-if="row.sku_id" :sku="row.sku || row.sku_code" :legacy-sku-code="row.legacy_sku_code"/><small class="sub">{{ row.product_name }}</small></template></el-table-column>
          <el-table-column label="发货数量" width="140"><template #default="{row}"><el-input-number v-if="canEdit" v-model="row.quantity" :min="1" :precision="0" :controls="false"/><span v-else>{{ row.quantity }}</span></template></el-table-column>
          <el-table-column v-if="!supplier" label="单价" width="150"><template #default="{row}"><el-input-number v-if="canManage && canEdit" v-model="row.unit_price" :min="0" :precision="4" :controls="false"/><el-input-number v-else-if="canPriceEdit && current.status==='submitted'" v-model="row.unit_price" :min="0" :precision="4" :controls="false"/><span v-else>{{ row.unit_price == null ? '待采购补价' : row.unit_price }}</span></template></el-table-column>
          <el-table-column label="超量提示" min-width="140"><template #default="{row}"><el-tag v-if="row.exception_type==='additional'" type="warning">采购单外 SKU</el-tag><el-tag v-else-if="row.exception_type && row.exception_type!=='none' || Number(row.excess_quantity)>0" type="warning">超出采购 {{ row.excess_quantity || '' }} 件</el-tag><span v-else class="sub">正常</span></template></el-table-column>
          <el-table-column v-if="canEdit" label="操作" width="80"><template #default="{ $index }"><el-button link type="danger" @click="form.lines.splice($index,1)">移除</el-button></template></el-table-column>
        </el-table></div>
        <p class="sub">共 {{ totalQty({lines:form.lines}) }} 件。超出采购数量会提示，但不会阻止提交。</p>
        <el-form-item label="箱号文件（保存草稿后上传）"><input ref="fileInput" type="file" accept=".pdf,.xlsx,.csv,.png,.jpg,.jpeg,application/pdf" :disabled="busy || !current.id || current.status!=='draft' || !canEdit" @change="uploadFile"/><p class="sub">请上传包含本次全部箱号的文件；支持 PDF、Excel、CSV、PNG、JPG，最大 10MB。提交前至少上传一份附件。</p></el-form-item>
        <el-table :data="current.attachments || []" border empty-text="还没有箱号文件"><el-table-column prop="file_name" label="文件名" min-width="210"/><el-table-column label="大小" width="100"><template #default="{row}">{{ formatSize(row.file_size) }}</template></el-table-column><el-table-column prop="sha256" label="校验值" min-width="180"/><el-table-column label="操作" width="180"><template #default="{row}"><el-button link type="primary" @click="download(row)">下载</el-button><el-button v-if="canEdit" link type="danger" :disabled="busy" @click="removeAttachment(row)">移除</el-button></template></el-table-column></el-table>
        <el-alert v-if="formError" :title="formError" type="error" :closable="false" class="notice"/>
      </template>
      <template #footer><div class="actions"><el-button @click="open=false" :disabled="busy">关闭</el-button><el-button v-if="canEdit" @click="save" :loading="busy">保存草稿</el-button><el-button v-if="canPriceEdit && current?.status==='submitted'" @click="savePrices" :loading="busy">保存调价</el-button><el-button v-if="canEdit" type="success" :disabled="busy || !current.attachments?.length" @click="act('submit')">提交发货</el-button><el-button v-if="canEdit" type="danger" plain :disabled="busy" @click="act('cancel')">作废</el-button><el-button v-if="!supplier && canManage && current?.status==='submitted' && current.delivery_mode!=='factory_loading' && !current.collection_arrived" type="primary" plain :disabled="busy" @click="arrived">标记到仓</el-button></div></template>
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import CostSettlementLinkV2 from '../../components/supply-chain/CostSettlementLinkV2.vue';
import DocumentSkuV2 from '../../components/supply-chain/DocumentSkuV2.vue';
import DocumentProductImageV2 from '../../components/supply-chain/DocumentProductImageV2.vue';
import * as api from '../../api/supplyShipmentsV2';
import { useAuthStore } from '../../stores/auth';

const props = defineProps({ supplier: { type: Boolean, default: false } });
const route = useRoute();
const auth=useAuthStore();
const orders=ref([]), orderTotal=ref(0), orderOffset=ref(0), ordersLoadingMore=ref(false), shipments=ref([]), skus=ref([]), orderId=ref(route.query.order_id ? Number(route.query.order_id) : ''), status=ref(''), page=ref(1), limit=ref(20), total=ref(0), loading=ref(false), busy=ref(false), error=ref(''), open=ref(false), current=ref(null), formError=ref(''), fileInput=ref(null), savedPayload=ref('');
const form=reactive({shipment_date:'',delivery_mode:'collection_center',loading_address:'',notes:'',lines:[]});
const priceReason=ref('');
const selectedOrder=computed(()=>orders.value.find(o=>String(o.id)===String(orderId.value)));
const canManage=computed(()=>props.supplier || (!auth.authorizationStale && auth.hasPermission('supply.v2.manage')));
const canEdit=computed(()=>canManage.value && !!current.value && current.value.status==='draft' && current.value.editable!==false);
const canPriceEdit=computed(()=>!props.supplier && canManage.value && !!current.value && current.value.price_editable!==false);
const dirty=computed(()=>JSON.stringify(payload())!==savedPayload.value);
const pendingKeys=new Map();
function unwrap(r){if(!r?.success)throw new Error(r?.message||'请求失败');return r.data;}
function rowsOf(data){return Array.isArray(data)?data:(data?.results||data?.items||data?.rows||[]);}
async function loadOrderPage(reset=false){if(reset){orders.value=[];orderOffset.value=0;}ordersLoadingMore.value=true;try{const response=await api.fetchShipmentOrders(props.supplier,{limit:100,offset:orderOffset.value});orders.value.push(...rowsOf(unwrap(response)).filter(o=>o.status==='confirmed'&&!orders.value.some(old=>String(old.id)===String(o.id))));orderTotal.value=Number(response.count||0);orderOffset.value+=100;}catch(e){error.value=`采购订单加载失败：${e.message||'请求失败'}`;}finally{ordersLoadingMore.value=false;}}
async function loadMoreOrders(){if(!ordersLoadingMore.value&&orderOffset.value<orderTotal.value)await loadOrderPage();}
async function load(){loading.value=true;error.value='';let routeProblem='';try{const opt=await api.fetchShipmentOptions(props.supplier);skus.value=unwrap(opt)?.skus||[];await loadOrderPage(true);if(orderId.value&&!orders.value.some(o=>String(o.id)===String(orderId.value))){try{const detail=unwrap(await api.fetchShipmentOrder(orderId.value,props.supplier));if(detail.status==='confirmed')orders.value.unshift(detail);else if(route.query.order_id)routeProblem='链接中的采购订单尚未确认，发货单目前不可见。';}catch(e){if(route.query.order_id)routeProblem=`无法读取指定采购订单：${e.message||'请求失败'}`;}}await loadShipments();if(routeProblem)error.value=routeProblem;}catch(e){error.value=e.message||'加载失败';}finally{loading.value=false;}}
async function loadShipments(){loading.value=true;try{const response=await api.fetchShipments(props.supplier,{limit:limit.value,offset:(page.value-1)*limit.value,...(status.value?{status:status.value}:{}),...(orderId.value?{order_id:orderId.value}:{})});const data=unwrap(response);shipments.value=rowsOf(data);total.value=Number(response.count||0);}catch(e){error.value=e.message||'发货单加载失败';}finally{loading.value=false;}}
function onOrderChange(){page.value=1;loadShipments();}
watch(()=>route.query.order_id,(v)=>{if(v){orderId.value=Number(v);onOrderChange();}});
function statusText(s){return {draft:'草稿',submitted:'已提交',cancelled:'已作废'}[s]||s;}
function logisticsText(s){return {unmarked:'未标记',departed:'开船',arrived_port:'到港',arrived_warehouse:'到仓'}[s]||'未标记';}
function logisticsDate(value){return value?new Date(value).toLocaleString():'未记录';}
function totalQty(s){return (s.lines||[]).reduce((n,l)=>n+Number(l.quantity||0),0);}
function cleanLine(l){return { ...(l.id?{id:l.id}:{}),sku_id:l.sku_id, purchase_line_id:l.purchase_line_id??null,quantity:Number(l.quantity), ...(!props.supplier?{unit_price:l.unit_price==null||l.unit_price===''?null:Number(l.unit_price)}:{})};}
function payload(){return {shipment_date:form.shipment_date,delivery_mode:form.delivery_mode,...(form.delivery_mode==='factory_loading'?{loading_address:form.loading_address}:{}),notes:form.notes,lines:form.lines.map(cleanLine)};}
function editForm(s){current.value=s;Object.assign(form,{shipment_date:s.shipment_date||today(),delivery_mode:s.delivery_mode||'collection_center',loading_address:s.loading_address||'',notes:s.notes||'',lines:(s.lines||[]).map(l=>({...l,quantity:Number(l.quantity),unit_price:l.unit_price==null?null:Number(l.unit_price)}))});savedPayload.value=JSON.stringify(payload());formError.value='';}
function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function mutate(slot,data,execute){const fingerprint=JSON.stringify(data);let pending=pendingKeys.get(slot);if(!pending||pending.fingerprint!==fingerprint){pending={fingerprint,key:api.createIdempotencyKey()};pendingKeys.set(slot,pending);}return execute(pending.key).then(response=>{const result=unwrap(response);pendingKeys.delete(slot);return result;});}
function mergeSnapshot(data){if(!data)return;current.value={...current.value,...data};}
async function newShipment(){if(!canManage.value||busy.value||!selectedOrder.value)return;busy.value=true;try{const order=unwrap(await api.fetchShipmentOrder(selectedOrder.value.id,props.supplier));if(order.status!=='confirmed')throw new Error('只有已确认采购单可以新建发货单。');editForm({id:null,order_id:order.id,order_number:order.number,status:'draft',version:0,attachments:[],lines:(order.lines||[]).map(l=>({sku_id:l.sku_id,sku:l.sku,legacy_sku_code:l.legacy_sku_code||'',image_preview_url:l.product_details?.image_url?(l.image_preview_url||''):'',product_name:l.product_name||l.name,purchase_line_id:l.id,quantity:Number(l.quantity||1),unit_price:l.unit_price==null?null:Number(l.unit_price)}))});open.value=true;}catch(e){error.value=e.message||'读取采购订单失败';}finally{busy.value=false;}}
async function openShipment(row){busy.value=true;try{editForm(unwrap(await api.fetchShipment(row.id,props.supplier)));open.value=true;}catch(e){error.value=e.message||'读取发货单失败';}finally{busy.value=false;}}
function changeLineSku(row){const sources=(selectedOrder.value?.lines||[]).filter(l=>l.sku_id===row.sku_id);row.purchase_line_id=sources.length===1?sources[0].id:null;const sku=skus.value.find(s=>s.id===row.sku_id);row.sku=sku?.sku_code;row.legacy_sku_code=sku?.legacy_sku_code||'';row.image_preview_url=sku?.image_preview_url||'';row.product_name=sku?.product_name;row.unit_price=sources.length===1&&sources[0].unit_price!=null?Number(sources[0].unit_price):null;}
function addLine(){if(canEdit.value)form.lines.push({sku_id:null,purchase_line_id:null,quantity:1,unit_price:null});}
async function save(){if(!canEdit.value||busy.value)return false;formError.value='';if(!form.shipment_date||!form.lines.length||form.lines.some(l=>!l.sku_id||!Number.isInteger(Number(l.quantity))||Number(l.quantity)<1)){formError.value='请填写发货日期，并为每行选择 SKU 和大于 0 的整数数量。';return false;}busy.value=true;try{const data={...payload(),...(current.value.id?{expected_version:current.value.version}:{order_id:current.value.order_id})};const result=await mutate(`save-${current.value.id||'new'}`,data,key=>current.value.id?api.updateShipment(current.value.id,data,props.supplier,key):api.createShipment(data,props.supplier,key));editForm(result);ElMessage.success('发货草稿已保存。');await loadShipments();return true;}catch(e){formError.value=e.message||'保存失败，草稿内容已保留。';return false;}finally{busy.value=false;}}
async function savePrices(){if(!canPriceEdit.value||busy.value)return;if(form.lines.some(l=>l.unit_price==null||l.unit_price===''||!Number.isFinite(Number(l.unit_price))||Number(l.unit_price)<0)){formError.value='请为每行填写大于或等于 0 的有效单价。';return;}if(current.value.price_adjustment_requires_reason&&!priceReason.value.trim()){formError.value='已集货的发货单调价必须填写原因。';return;}busy.value=true;formError.value='';try{const lines=form.lines.map(l=>({id:l.id,unit_price:Number(l.unit_price)})),data={expected_version:current.value.version,lines,...(priceReason.value.trim()?{reason:priceReason.value.trim()}:{})};const result=await mutate(`prices-${current.value.id}`,data,key=>api.updateShipmentPrices(current.value.id,data,key));editForm(result);priceReason.value='';ElMessage.success('价格已保存。');await loadShipments();}catch(e){formError.value=e.message||'调价失败';}finally{busy.value=false;}}
function onCostUpdated(target){if(target&&current.value&&String(target.id)===String(current.value.id))current.value={...current.value,...target};}
async function act(action){if(!current.value||!canManage.value&&action==='cancel')return;if(action==='submit'&&dirty.value&&!await save())return;if(action==='submit'&&current.value.delivery_mode==='factory_loading'&&!String(current.value.loading_address||'').trim()){formError.value='货柜上门装载的发货单提交前必须填写装柜地址。';return;}try{await ElMessageBox.confirm(action==='submit'?'提交后供应商发货信息将进入采购协同。':'作废这张发货单？',action==='submit'?'提交发货':'作废发货单',{type:'warning'});}catch{return;}busy.value=true;try{const body={expected_version:current.value.version};const result=await mutate(`${action}-${current.value.id}`,body,key=>action==='submit'?api.submitShipment(current.value.id,body,props.supplier,key):api.cancelShipment(current.value.id,body,props.supplier,key));editForm(result);await loadShipments();ElMessage.success(action==='submit'?'发货单已提交。':'发货单已作废。');}catch(e){formError.value=e.message||'操作失败';}finally{busy.value=false;}}
async function arrived(){if(props.supplier||!canManage.value||busy.value)return;busy.value=true;try{const body={expected_version:current.value.version};editForm(await mutate(`arrival-${current.value.id}`,body,key=>api.markShipmentArrived(current.value.id,body,key)));await loadShipments();ElMessage.success('已标记到仓。');}catch(e){formError.value=e.message||'标记到仓失败';}finally{busy.value=false;}}
async function uploadFile(event){const file=event.target.files?.[0];event.target.value='';if(!file)return;if(file.size>10*1024*1024||! /\.(pdf|xlsx|csv|png|jpe?g)$/i.test(file.name)){formError.value='请选择 10MB 以内的 PDF、XLSX、CSV、PNG 或 JPG 文件。';return;}if(!canEdit.value)return;if(dirty.value&&!await save())return;if(!current.value?.id){formError.value='请先保存发货草稿，再上传箱号文件。';return;}busy.value=true;try{const version=current.value.version,result=await mutate(`upload-${current.value.id}-${file.name}`,{version,name:file.name,size:file.size,modified:file.lastModified},key=>api.uploadShipmentAttachment(current.value.id,file,version,props.supplier,key));mergeSnapshot(result);formError.value='';}catch(e){formError.value=e.message||'上传失败';}finally{busy.value=false;}}
async function removeAttachment(a){if(!canEdit.value)return;try{await ElMessageBox.confirm(`移除附件“${a.file_name}”？`,'移除附件',{type:'warning'});}catch{return;}busy.value=true;try{const body={expected_version:current.value.version};const result=await mutate(`remove-${current.value.id}-${a.id}`,body,key=>api.removeShipmentAttachment(current.value.id,a.id,body,props.supplier,key));mergeSnapshot(result);}catch(e){formError.value=e.message||'移除失败';}finally{busy.value=false;}}
async function download(a){const r=await api.downloadShipmentAttachment(current.value.id,a.id,a.file_name,props.supplier);if(!r?.success)formError.value=r?.message||'下载失败';}
function formatSize(n){return n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;}
function closeDrawer(done){if(!busy.value)done();}
defineExpose({savePrices,priceReason,current,form,formError});
onMounted(load);
</script>

<style scoped>
.notice{margin:0 0 16px}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0 18px}.filters :deep(.el-select){width:min(320px,100%)}.table-scroll{width:100%;overflow-x:auto}.pagination{margin-top:18px;overflow-x:auto}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px}.form-grid :deep(.el-date-editor){width:100%}.heading,.actions{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.heading{margin:18px 0 10px}.heading h3{margin:0;font-size:16px}.actions{justify-content:flex-end}.sub{display:block;color:#64748b;font-size:12px;margin-top:4px}.table-scroll :deep(.el-input-number),.table-scroll :deep(.el-select){width:100%}.table-scroll :deep(.el-table){min-width:680px}.pagination :deep(.el-pagination){min-width:500px}@media(max-width:680px){.form-grid{grid-template-columns:1fr}.actions{justify-content:flex-start}}
</style>
