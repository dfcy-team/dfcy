import ABCBadges from "./RecoveredABCBadges537.js";
import ABCStatus from "./RecoveredABCStatus537.js";
import { ElSelect, ElOption, ElInput, ElButton } from "element-plus";
import ProductImage from "../supply-chain/DocumentProductImageV2.vue";
import { h, ref, onMounted, onBeforeUnmount, watch } from "vue";
import request from "../../api/request.js";
import { useAuthStore } from "../../stores/auth.js";
import { cockpitActorKey } from "../../utils/cockpitDraft.js";
const url="/api/internal/commerce/inventory/category-query/";
const value=x=>x==null?"—":String(x);
const STYLES='\n.spu-stock-page{color:#25354b}.spu-stock-page h2{font-size:22px;margin:0 0 18px}\n.spu-stock-page>div:first-of-type{padding:14px;background:#fff;border:1px solid #dfe6ef;border-radius:8px}\n.spu-stock-page input:not(.el-input__inner):not(.el-select__input),.spu-stock-page select{height:34px;border:1px solid #d7dfe9;border-radius:5px;padding:0 10px;background:#fff;color:#34445c}\n.spu-stock-page table{min-width:850px}.spu-stock-page th{font-size:13px;color:#52627a;background:#f4f7fb;white-space:nowrap}\n.spu-stock-page td{font-size:13px;vertical-align:middle}.spu-stock-page td .document-product-image{width:64px}\n.spu-stock-page td .el-button{padding:5px 9px;height:30px}\n.spu-stock-page .stock-dialog{position:fixed;inset:0;z-index:10020;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,.4);padding:24px;box-sizing:border-box}\n.spu-stock-page .stock-dialog-card{width:min(820px,95vw);max-height:80vh;overflow:auto;background:white;border-radius:10px;padding:20px;box-shadow:0 12px 45px #0003}\n.spu-stock-page .stock-dialog-header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}\n.spu-stock-page .stock-dialog-header h3{margin:0;font-size:18px}.spu-stock-page .stock-dialog table{min-width:500px}\n';
const TREE_STYLES=".category-stock-layout{display:flex;gap:20px;margin-top:18px;align-items:flex-start}.category-stock-sidebar{width:235px;flex-shrink:0;background:#fff;border:1px solid #e1e7ef;border-radius:8px;padding:14px;box-sizing:border-box;max-height:75vh;overflow:auto;position:sticky;top:12px}.category-tree-item{display:block;flex:1;min-width:0;width:100%;text-align:left;border:0;background:transparent;color:#42536a;border-radius:5px;padding:8px 9px;cursor:pointer;font-size:13px;overflow-wrap:anywhere}.category-tree-item:hover{background:#f0f5fc}.category-tree-arrow{cursor:pointer;color:#93a3b8;width:20px;flex-shrink:0;text-align:center}.category-stock-sidebar details[open]>summary>.category-tree-arrow{transform:rotate(90deg)}@media(max-width:800px){.category-stock-layout{flex-direction:column}.category-stock-sidebar{width:100%;position:static;max-height:300px}}";
const border="padding:10px 12px;border-bottom:1px solid #e5eaf1;text-align:left";
export default {
 props:{kind:{default:"operations"},title:{type:String,default:""}},
 setup(props) {
  const auth=useAuthStore();
  const countries=ref([]), country=ref(""), warehouse=ref(""), search=ref(""), days=ref(30), stockedOnly=ref(false);
  const abcGrade=ref("");
  const warehouseOptions=ref([]);
  const categoryOptions=ref([]),selectedCategories=ref([]), categoryTerm=ref("");
  const data=ref(null), busy=ref(false), error=ref(""), expanded=ref({});
  const trail=ref([]), chosenSpu=ref(null), level=ref("spu"), page=ref(1);
  let seq=0,controller,detailSequence=0,detailController,skuEpoch=0,disposed=false;
  const skuRequests=new Map();
  const detail=ref(null),detailError=ref("");
  async function openDetail(row, type) {
   const token=++detailSequence;detailController?.abort();detailController=new AbortController();
   detail.value={title:type==="stores"?"店铺销售":"仓库库存",loading:true,rows:[],sku:row.code,type};
   detailError.value="";
   try {
    const result=await request({method:"get",url,params:{...applied.value,level:type,sku_id:row.id},signal:detailController.signal,timeout:30000});
    if(token!==detailSequence)return;
    if(!result?.success)throw Error(result?.message||"明细读取失败");
    detail.value={...detail.value,loading:false,rows:result.data?.results||[]};
   }catch(e){if(token===detailSequence){detailError.value=e.message;detail.value={...detail.value,loading:false};}}
  }
  const applied=ref(null);
  async function fetchData(params, signal=controller?.signal) {
   const response=await request({method:"get",url,params,signal,timeout:30000});
   if(!response?.success)throw Error(response?.message||"库存查询失败");
   return response.data;
  }
  async function loadCountries() {
   const token=++seq;controller?.abort();controller=new AbortController();
   try {const initial=await fetchData({});if(token!==seq||disposed)return;countries.value=initial.countries||[];categoryOptions.value=initial.categories||[];} catch(e){if(token===seq&&!disposed)error.value=e.message;}
  }
  onMounted(loadCountries);
  const stopAuthWatch=watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{
   reset();countries.value=[];country.value="";warehouseOptions.value=[];categoryOptions.value=[];selectedCategories.value=[];
   if(!auth.authorizationStale&&auth.currentUser)loadCountries();
  },{flush:"sync"});
  onBeforeUnmount(()=>{disposed=true;stopAuthWatch();reset();});
  let categoryBox;
  function closeCategoryOutside(event) {
   if(categoryBox&&!categoryBox.contains(event.target))categoryBox.open=false;
  }
  function categorySelection() {
   if(!selectedCategories.value.length)return [h("span",null,"选择商品类目")];
   return selectedCategories.value.map(id=>h("span",{key:id,style:"display:inline-flex;align-items:center;gap:5px;background:#edf4ff;color:#2863b9;border:1px solid #d7e6ff;border-radius:4px;padding:2px 5px;font-size:12px"},[
    h("span",null,categoryOptions.value.find(c=>c.id===id)?.name||String(id)),
    h("button",{type:"button","aria-label":"取消类目："+(categoryOptions.value.find(c=>c.id===id)?.name||id),style:"border:0;background:transparent;color:#6484ae;cursor:pointer;padding:0 2px",onClick:e=>{e.preventDefault();e.stopPropagation();selectedCategories.value=selectedCategories.value.filter(x=>x!==id);}},"×")
   ]));
  }
  function categoryTree(parentId) {
   const term=categoryTerm.value.trim();
   const matches=node=>node.name.includes(term)||categoryOptions.value.some(c=>c.parent_id===node.id&&matches(c));
   return categoryOptions.value.filter(c=>(c.parent_id||null)===parentId&&(!term||matches(c))).map(c=>{
    const children=categoryOptions.value.some(n=>n.parent_id===c.id);
    const check=h("label",{style:"display:inline-flex;align-items:center;gap:8px;padding:5px",onClick:e=>e.stopPropagation()},[
     h("input",{type:"checkbox","aria-label":"选择类目："+c.name,style:"height:16px;width:16px",checked:selectedCategories.value.includes(c.id),onChange:e=>{
      selectedCategories.value=e.target.checked?[...selectedCategories.value,c.id]:selectedCategories.value.filter(id=>id!==c.id);
     }}),c.name
    ]);
    return children?h("details",{key:c.id,open:term?true:undefined},[
     h("summary",{style:"cursor:pointer"},[check]),h("div",{style:"padding-left:20px"},categoryTree(c.id))
    ]):h("div",{key:c.id,style:"padding-left:16px"},[check]);
   });
  }
  function reset() {
   warehouse.value="";
   seq++;skuEpoch++;for(const pending of skuRequests.values())pending.controller.abort();skuRequests.clear();detailSequence++;detailController?.abort();detail.value=null;controller?.abort();busy.value=false;data.value=null;applied.value=null;trail.value=[];chosenSpu.value=null;expanded.value={};page.value=1;
   level.value="spu";error.value="";
  }
  function invalidateSkuRequests(){skuEpoch++;for(const pending of skuRequests.values())pending.controller.abort();skuRequests.clear();}
  async function load(next=1) {
   if(!applied.value)return;
   invalidateSkuRequests();
   const token=++seq;controller?.abort();controller=new AbortController();
   busy.value=true;error.value="";expanded.value={};
   try {
    const params={...applied.value,level:level.value,stocked_only:stockedOnly.value,offset:(next-1)*20};
    if(trail.value.length)params.category_id=trail.value.at(-1).id;
    if(chosenSpu.value)params.spu_id=chosenSpu.value.id;
    const result=await fetchData(params);
    if(token!==seq)return;
    data.value=result;warehouseOptions.value=result.warehouses||warehouseOptions.value;categoryOptions.value=result.categories||categoryOptions.value;page.value=next;
   }catch(e){if(token===seq)error.value=e.message;}
   finally{if(token===seq)busy.value=false;}
  }
  function query() {
   const selectedWarehouse=warehouse.value;reset();warehouse.value=selectedWarehouse;applied.value={abc_grade:abcGrade.value||undefined,country_id:Number(country.value),days:Number(days.value),search:search.value.trim(),category_ids:selectedCategories.value.join(",")||undefined,...(warehouse.value?{warehouse_id:Number(warehouse.value)}:{})};
   load();
  }
  function enter(row) {
   if(level.value==="category"){
    trail.value=[...trail.value,row];
    level.value=row.has_children?"category":"spu";
    load();
    }else if(level.value==="spu"){
    if(expanded.value[row.id]){skuRequests.get(row.id)?.controller.abort();skuRequests.delete(row.id);expanded.value={...expanded.value,[row.id]:null};return;}
    const token=skuEpoch,requestController=new AbortController();
    skuRequests.get(row.id)?.controller.abort();skuRequests.set(row.id,{controller:requestController,token});
    expanded.value={...expanded.value,[row.id]:{loading:true,results:[],count:0,page:1}};
    fetchData({...applied.value,level:"sku",spu_id:row.id,offset:0,stocked_only:stockedOnly.value},requestController.signal).then(result=>{
     if(!disposed&&token===skuEpoch&&skuRequests.get(row.id)?.controller===requestController)expanded.value={...expanded.value,[row.id]:{loading:false,results:result.results||[],count:result.count||0,page:1}};
    }).catch(e=>{if(!disposed&&token===skuEpoch&&skuRequests.get(row.id)?.controller===requestController){error.value=e.message;expanded.value={...expanded.value,[row.id]:null};}}).finally(()=>{if(skuRequests.get(row.id)?.controller===requestController)skuRequests.delete(row.id);});
   }
  }
  async function loadSkuPage(row,next){
   const current=expanded.value[row.id];if(!current||current.loading)return;
   const token=skuEpoch,requestController=new AbortController();skuRequests.get(row.id)?.controller.abort();skuRequests.set(row.id,{controller:requestController,token});
   expanded.value={...expanded.value,[row.id]:{...current,loading:true}};
   try{const result=await fetchData({...applied.value,level:"sku",spu_id:row.id,offset:(next-1)*20,stocked_only:stockedOnly.value},requestController.signal);if(token!==skuEpoch||disposed||skuRequests.get(row.id)?.controller!==requestController)return;expanded.value={...expanded.value,[row.id]:{loading:false,results:result.results||[],count:result.count||0,page:next}};}
   catch(e){if(token===skuEpoch&&!disposed&&skuRequests.get(row.id)?.controller===requestController){error.value=e.message;expanded.value={...expanded.value,[row.id]:current};}}
   finally{if(skuRequests.get(row.id)?.controller===requestController)skuRequests.delete(row.id);}
  }
  function root() {
   trail.value=[];chosenSpu.value=null;level.value="spu";selectedCategories.value=[];if(country.value)query();
  }
  function button(text,onClick,disabled=false) {
   return h(ElButton,{disabled,onClick},{default:()=>text});
  }
  function browseCategory(id) {
   selectedCategories.value=id==null?[]:[id];
   if(country.value)query();
  }
  function sidebarTree(parentId) {
   const term=categoryTerm.value.trim();
   const matches=c=>c.name.includes(term)||categoryOptions.value.some(n=>n.parent_id===c.id&&matches(n));
   return categoryOptions.value.filter(c=>(c.parent_id||null)===parentId&&(!term||matches(c))).map(c=>{
    const children=categoryOptions.value.some(n=>n.parent_id===c.id),active=selectedCategories.value.includes(c.id);
    const item=h("button",{type:"button",class:"category-tree-item",style:active?"background:#eaf1ff;color:#245de0;font-weight:600":"","aria-current":active?"true":undefined,onClick:e=>{e.preventDefault();e.stopPropagation();browseCategory(c.id);}},c.name);
    const multiCheck=props.kind==="category"?h("input",{type:"checkbox","aria-label":"筛选类目："+c.name,checked:selectedCategories.value.includes(c.id),onClick:e=>e.stopPropagation(),onChange:e=>{const set=new Set(selectedCategories.value);e.target.checked?set.add(c.id):set.delete(c.id);selectedCategories.value=[...set];if(country.value)query();}}):null;
    return children?h("details",{key:c.id,open:term?true:undefined},[
     h("summary",{style:"display:flex;align-items:center;list-style:none"},[
      h("span",{class:"category-tree-arrow","aria-label":"展开"+c.name,onClick:e=>{e.preventDefault();e.currentTarget.closest('details').open=!e.currentTarget.closest('details').open;}},"▸"),item
     ]),multiCheck,h("div",{style:"padding-left:15px"},sidebarTree(c.id))
    ]):h("div",{key:c.id,style:"padding-left:20px"},[multiCheck,item]);
   });
  }
  function table(rows,variant=false) {
   const unmapped=level.value==="unmapped";
   const columns=unmapped?
    [["source_sku","来源 SKU"],["warehouse__name","仓库"],["on_hand_qty","实物库存"],["available_qty","可售库存"]]:
    variant?[["abc","ABC"],["code","新 SKU"],["legacy","旧 SKU"],["specification","规格"],["available","可售库存"],["sales","近 "+(applied.value?.days||30)+" 天已采集销量"]]:
    [["abc","ABC"],["name",level.value==="category"?"分类":"商品／SPU"],["sku_count","规格数"],["available","可售库存"],["sales","近 "+(applied.value?.days||30)+" 天已采集销量"],["variant_status","规格分布"]];
   return h("table",{style:"width:100%;border-collapse:collapse;background:#fff"},[
    h("thead",null,[h("tr",{style:"background:#f4f7fb"},[...(!unmapped?[h("th",{style:border,scope:"col"},"商品图片")]:[]),...columns.map(([,label])=>h("th",{style:border,scope:"col"},label)),...(variant?[h("th",{style:border},"明细")]:[])])]),
    h("tbody",null,rows.flatMap((row,index)=>{
     const main=h("tr",{key:row.id??row.source_sku,style:{background:index%2?"#f8faff":"#fff"}},[...(!unmapped?[h("td",{style:border,width:80},[h(ProductImage,{imagePath:row.image_preview_url||"",alt:row.name||row.code||"商品图片"})])]:[]),...columns.map(([key])=>
      h("td",{style:border},[key==="abc"?h(ABCBadges,{row}):key==="name"&&!variant?
       [button((row.variants?.length?(expanded.value[row.id]?"▾ ":"▸ "):"")+value(row[key]),()=>enter(row),busy.value),level.value!=="category"?h("div",{style:"margin-top:6px;color:#64748b;white-space:nowrap"},"新 SPU "+value(row.code)+" · 旧 SPU "+value(row.legacy)):null]:value(row[key])])),...(variant?[h("td",{style:border},[
       button("仓库",()=>openDetail(row,"warehouses")),button("店铺销售",()=>openDetail(row,"stores")),
      ])]:[])]);
     if(variant||unmapped||!expanded.value[row.id])return [main];
     const skuState=expanded.value[row.id];
     return [main,h("tr",{key:"variants-"+row.id},[h("td",{colspan:columns.length+1,style:"padding:12px 24px;background:#eef4fb"},[
      skuState.loading?h("p",{role:"status"},"正在读取 SKU…"):table(skuState.results,true),
      skuState.count>20?h("nav",{style:"display:flex;gap:12px;align-items:center;margin-top:10px"},[
       button("上一页",()=>loadSkuPage(row,skuState.page-1),skuState.loading||skuState.page<=1),h("span",null,"第 "+skuState.page+" 页 · 共 "+skuState.count+" 项"),button("下一页",()=>loadSkuPage(row,skuState.page+1),skuState.loading||skuState.page*20>=skuState.count),
      ]):null,
     ])])];
    })),
   ]);
  }
  return ()=>h("section",{class:"spu-stock-page",style:"padding:16px 20px","aria-label":"整款库存"},[
   h("style",null,STYLES+TREE_STYLES),
   h("h2",null,props.title||(props.kind==="category"?"分类库存查询":props.kind==="warehouse"?"仓库整款库存":"库存经营")),
   h("div",{class:"inventory-query-filters",style:"display:flex;gap:10px;flex-wrap:wrap;align-items:center"},[
    h(ElSelect,{modelValue:country.value,placeholder:"选择国家","aria-label":"整款库存国家",filterable:true,style:"width:220px",onChange:id=>{country.value=id;warehouseOptions.value=[];reset();if(props.kind==="category"&&country.value)query();}}, {default:()=>countries.value.map(c=>h(ElOption,{key:c.id,value:String(c.id),label:c.name+" ("+c.country_code+")"}))}),
    ["warehouse","category"].includes(props.kind)?h(ElSelect,{modelValue:warehouse.value,placeholder:country.value?"全部仓库":"仓库（先选择国家）","aria-label":"整款库存仓库",clearable:true,filterable:true,disabled:!country.value||busy.value,style:"width:220px",onChange:id=>{warehouse.value=id||"";if(country.value)query();}},{default:()=>warehouseOptions.value.map(w=>h(ElOption,{key:w.id,value:String(w.id),label:w.name}))}):null,
    h(ElSelect,{modelValue:abcGrade.value,"aria-label":"库存 ABC 筛选",placeholder:"SKU ABC",clearable:true,style:"width:170px",onChange:value=>{abcGrade.value=value||"";if(country.value)query();}},{default:()=>[{value:"A",label:"A 类（含参考）"},{value:"B",label:"B 类（含参考）"},{value:"C",label:"C 类（含参考）"},{value:"new",label:"新品观察"},{value:"no_sales",label:"无净销售额"},{value:"unavailable",label:"未分类／参考"}].map(option=>h(ElOption,option))}),
    h(ElInput,{placeholder:"搜索名称 / 规格 / 新旧 SPU、SKU",modelValue:search.value,clearable:true,"aria-label":"商品搜索",style:"width:300px","onUpdate:modelValue":v=>search.value=v,onKeyup:e=>{if(e.key==="Enter"&&country.value&&!busy.value)query();}}),
    h(ElSelect,{modelValue:Number(days.value),"aria-label":"整款销量周期",style:"width:130px",onChange:v=>days.value=v},{default:()=>[7,15,30].map(d=>h(ElOption,{key:d,value:d,label:d+" 日销量"}))}),
    h("label",{style:"display:inline-flex;align-items:center;gap:5px"},[h("input",{type:"checkbox","aria-label":"仅显示有库存",checked:stockedOnly.value,onChange:e=>{stockedOnly.value=e.target.checked;if(country.value)query();}}),"仅显示有库存"]),
    props.kind!=="category"?h("details",{style:"position:relative;min-width:200px;max-width:420px",ref:el=>categoryBox=el,onVnodeMounted:()=>document.addEventListener("pointerdown",closeCategoryOutside),onVnodeBeforeUnmount:()=>document.removeEventListener("pointerdown",closeCategoryOutside),onKeydown:e=>{if(e.key==="Escape")categoryBox.open=false;}},[
      h("summary",{"aria-label":"商品类目多选",style:"cursor:pointer;padding:5px 9px;border:1px solid #d7dfe9;border-radius:5px;background:white;min-height:22px;display:flex;align-items:center;flex-wrap:wrap;gap:5px"},[...categorySelection(),h("span",{style:"margin-left:auto;color:#8ba0b8"},"⌄")]),
      h("div",{style:"position:absolute;top:38px;left:0;z-index:30;width:320px;background:white;border:1px solid #d7dfe9;border-radius:6px;padding:12px;box-shadow:0 4px 15px #0002"},[
        h("input",{placeholder:"搜索大类／二级／三级类目",value:categoryTerm.value,onInput:e=>categoryTerm.value=e.target.value}),
        h("div",{style:"max-height:320px;overflow:auto"},categoryTree(null)),
        !categoryOptions.value.length?h("p",null,"暂无可选类目"):null,
        button("清空已选",()=>selectedCategories.value=[]),
      ]),
    ]):null,
    h(ElButton,{type:"primary",loading:busy.value,disabled:!country.value,onClick:query},{default:()=>"查询"}),
    applied.value?button("未关联商品库存",()=>{level.value="unmapped";chosenSpu.value=null;load(1);},busy.value):null,
   ]),
   h(ABCStatus,{countryId:country.value}),
   h("div",{class:props.kind==="category"?"category-stock-layout":""},[
    props.kind==="category"?h("aside",{class:"category-stock-sidebar","aria-label":"库存分类树"},[
     h("h3",{style:"margin:0 0 12px;font-size:15px"},"商品分类"),
     h(ElInput,{placeholder:"搜索分类",clearable:true,style:"width:100%;box-sizing:border-box;margin-bottom:10px",modelValue:categoryTerm.value,"onUpdate:modelValue":v=>categoryTerm.value=v}),
     h("button",{type:"button",class:"category-tree-item",onClick:()=>browseCategory(null),style:!selectedCategories.value.length?"background:#eaf1ff;color:#245de0":""},"全部分类"),
     ...sidebarTree(null)
    ]):null,
    h("main",{style:"min-width:0;flex:1"},[
    props.kind==="category"?h("h3",{style:"font-size:16px;margin:0 0 10px"},(categoryOptions.value.find(c=>c.id===selectedCategories.value[0])?.name||"全部分类")+" · SPU 库存"):null,
    props.kind==="category"&&!country.value?h("p",{style:"color:#7a8ba0"},"请选择国家后查看该分类库存"):null,
   applied.value&&props.kind!=="category"?h("nav",{style:"margin:12px 0"},[
    button("全部"+(props.kind==="category"?"分类":"整款"),root,busy.value),
    ...trail.value.map((node,index)=>button(node.name,()=>{trail.value=trail.value.slice(0,index+1);level.value=node.has_children?"category":"spu";load();},busy.value)),
   ]):null,
   applied.value?h("p",{style:"color:#64748b;margin:10px 0"},"库存按各仓库最新完整批次展示，默认排除虚拟商品。销量为已采集成交，缺少记录显示 —。"):null,
   error.value?h("p",{role:"alert"},error.value):null,
   busy.value?h("p",{role:"status"},"正在读取整款库存…"):null,
   data.value?.unmapped_totals?.sku_count?h("p",null,"未关联商品库存："+value(data.value.unmapped_totals.available)+" 件，点击上方入口查看来源 SKU。"):null,
   data.value?.summary?h("p",null,"可售库存 "+value(data.value.summary.available)+" · 商品款数 "+value(data.value.summary.spu_count)+" · 规格数 "+value(data.value.summary.sku_count)):null,
   data.value?h("div",{style:"overflow:auto"},[table(data.value.results||[])]):null,
   detail.value?h("div",{class:"stock-dialog",onClick:event=>{
     if(event.target===event.currentTarget){detailSequence++;detail.value=null;}
   }},[h("section",{class:"stock-dialog-card",role:"dialog","aria-modal":"true","aria-label":detail.value.title},[
     h("div",{class:"stock-dialog-header"},[
       h("h3",null,detail.value.title+" · "+value(detail.value.sku)),
       button("关闭",()=>{detailSequence++;detail.value=null;}),
     ]),
     detailError.value?h("p",{role:"alert",style:"color:#c43535"},detailError.value):null,
     detail.value.loading?h("p",{role:"status"},"正在读取明细…"):null,
     !detail.value.loading&&detail.value.rows.length?h("table",null,[
       h("thead",null,[h("tr",null,(detail.value.type==="stores"?["店铺","平台","销量","销售额","币种"]:["仓库","可售库存"]).map(label=>h("th",{style:border},label)))]),
       h("tbody",null,detail.value.rows.map(row=>h("tr",null,
         (detail.value.type==="stores"?[row.sales_order__store__name,row.sales_order__store__platform__platform_type,row.units,row.amount,row.currency]:[row.name,row.available])
           .map(item=>h("td",{style:border},value(item)))))),
     ]):null,
     !detail.value.loading&&!detail.value.rows.length?h("p",null,"当前范围暂无明细"):null,
   ])]):null,
   data.value?h("nav",{style:"display:flex;gap:12px;align-items:center;margin-top:12px"},[
    button("上一页",()=>load(page.value-1),busy.value||page.value<=1),
    h("span",null,"第 "+page.value+" 页 · 共 "+data.value.count+" 项"),
    button("下一页",()=>load(page.value+1),busy.value||page.value*20>=data.value.count),
   ]):null,
    ]),
   ]),
  ]);
 }
};

