<template>
 <div ref="root" class="finance-period-picker" aria-label="统计周期" @keydown.esc.stop.prevent="close">
  <label>统计周期<button ref="trigger" type="button" class="period-trigger" :disabled="disabled" :aria-expanded="opened" aria-haspopup="dialog" @click="open">{{ typeName(modelValue.period_type) }} · {{ periodText(modelValue) }}<span aria-hidden="true">⌄</span></button></label>
  <section v-if="opened" ref="panel" class="period-popover" role="dialog" aria-label="选择统计周期" tabindex="-1">
   <nav class="period-dimensions" aria-label="统计维度">
    <button v-for="item in types" :key="item[0]" type="button" :aria-pressed="pending.period_type===item[0]" @click="changeType(item[0])">{{ item[1] }}</button>
    <button v-if="pending.period_type==='month'" type="button" class="period-special" @click="pending.month='';pending.period=''">全部账期</button>
    <button v-else type="button" class="period-special" :aria-pressed="pending.period==='undated'" @click="pending.period='undated'">待归期</button>
   </nav>
   <div class="period-calendar">
    <header><button type="button" :aria-label="pending.period_type==='week'?'上个月':'上一年'" @click="move(-1)">‹</button><strong>{{ pending.period_type==='week'?monthTitle(browseMonth):browseMonth.slice(0,4)+'年' }}</strong><button type="button" :aria-label="pending.period_type==='week'?'下个月':'下一年'" @click="move(1)">›</button></header>
    <div v-if="pending.period_type==='month'" class="month-grid">
     <button v-for="month in yearMonths" :key="month" type="button" :data-month="month" :aria-pressed="pending.month===month" @click="select(month+'-01')">{{ Number(month.slice(5)) }}月</button>
    </div>
    <div v-else-if="pending.period_type==='half_month'" class="half-grid">
     <div v-for="month in yearMonths" :key="month"><strong>{{ Number(month.slice(5)) }}月</strong><button v-for="day in ['01','16']" :key="day" type="button" :data-half="month+'-'+day" :aria-pressed="pending.period===month+'-'+day" @click="select(month+'-'+day)">{{ day==='01'?'上半月':'下半月' }}<small>{{ day==='01'?'1—15日':'16—'+Number(periodRange('month',month).to.slice(8))+'日' }}</small></button></div>
    </div>
    <div v-else class="week-calendars">
     <div v-for="month in [browseMonth,shiftMonth(browseMonth,1)]" :key="month" class="week-calendar"><strong>{{ monthTitle(month) }}</strong><div class="week-days"><span v-for="day in ['一','二','三','四','五','六','日']" :key="day">{{ day }}</span><button v-for="day in calendarDays(month)" :key="day" type="button" :data-day="day" :aria-label="day+'，选择该自然周'" :aria-pressed="selectedDay(day)" :class="{outside:!day.startsWith(month),selected:selectedDay(day)}" @click="select(day)">{{ Number(day.slice(8)) }}</button></div></div>
    </div>
    <p class="period-guidance">{{ pending.period_type==='week'?'点击日期选择周一至周日的完整自然周，跨月不拆分。':'选择周期后点击应用，再点击页面查询。' }}</p>
   </div>
   <footer><div><strong>{{ selectedRange ? selectedRange.from+' — '+selectedRange.to : periodText(pending) }}</strong><small v-if="outsideCoverage">超出已接入日期范围，查询仅汇总已有数据。</small><small v-else>北京时间 · 应用后不立即计算</small></div><button type="button" @click="close">取消</button><button type="button" class="apply-period" :disabled="disabled" @click="apply">应用</button></footer>
  </section>
 </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { calendarDays, periodRange, periodText, shiftMonth } from './financePeriods';
const props=defineProps({modelValue:{type:Object,required:true},coverage:{type:Object,default:()=>({})},disabled:Boolean});
const emit=defineEmits(['update:modelValue']);
const types=[['month','月度'],['half_month','半月'],['week','周度']];
const typeName=value=>types.find(item=>item[0]===value)?.[1]||'月度';
const root=ref(null),panel=ref(null),trigger=ref(null),opened=ref(false),browseMonth=ref('');
const pending=reactive({period_type:'month',month:'',period:''});
const today=()=>new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
const monthTitle=month=>month.slice(0,4)+'年'+Number(month.slice(5))+'月';
const yearMonths=computed(()=>Array.from({length:12},(_,i)=>browseMonth.value.slice(0,4)+'-'+String(i+1).padStart(2,'0')));
const selectedRange=computed(()=>!pending.month||pending.period==='undated'||pending.period_type!=='month'&&!pending.period?null:periodRange(pending.period_type,pending.period_type==='month'?pending.month:pending.period));
const outsideCoverage=computed(()=>{const range=selectedRange.value;return !!(range&&((props.coverage.from&&range.from<props.coverage.from)||(props.coverage.to&&range.to>props.coverage.to)));});
function anchorDate(){if(pending.period&&pending.period!=='undated')return pending.period;const month=pending.month||browseMonth.value;const end=[periodRange('month',month).to,today(),props.coverage.to].filter(Boolean).sort()[0];return end>=month+'-01'?end:month+'-01';}
function select(day){const range=periodRange(pending.period_type,day);pending.month=range.from.slice(0,7);pending.period=pending.period_type==='month'?'':range.from;}
function changeType(type){const day=anchorDate();pending.period_type=type;select(day);}
function selectedDay(day){return pending.period&&pending.period!=='undated'&&periodRange('week',day).from===pending.period;}
async function open(){if(props.disabled)return;Object.assign(pending,props.modelValue);browseMonth.value=pending.month||today().slice(0,7);opened.value=true;await nextTick();panel.value?.focus();}
function close(){opened.value=false;trigger.value?.focus();}
function apply(){if(props.disabled)return;emit('update:modelValue',{...pending});close();}
function move(step){browseMonth.value=shiftMonth(browseMonth.value,step*(pending.period_type==='week'?1:12));}
function outside(event){if(opened.value&&!root.value?.contains(event.target))opened.value=false;}
watch(()=>props.disabled,value=>{if(value)opened.value=false;});
onMounted(()=>document.addEventListener('pointerdown',outside));
onBeforeUnmount(()=>document.removeEventListener('pointerdown',outside));
</script>

<style scoped>
.finance-period-picker{position:relative;display:flex;align-items:end;gap:16px;flex:1.8;min-width:260px}.finance-period-picker>label{display:grid;gap:6px;flex:1}button{font:inherit;color:#29466e;background:#fff;border:1px solid #c6d3e5;border-radius:4px;cursor:pointer;padding:8px 12px}button:disabled{opacity:.55;cursor:default}button:focus-visible{outline:2px solid #255ff2;outline-offset:2px}.period-trigger{display:flex;align-items:center;justify-content:space-between;gap:14px;white-space:nowrap;min-height:36px;text-align:left}.period-popover{position:absolute;top:calc(100% + 8px);left:0;z-index:30;width:650px;max-width:calc(100vw - 32px);display:grid;grid-template-columns:100px 1fr;background:#fff;border:1px solid #c6d3e5;border-radius:6px;box-shadow:0 8px 28px #25375324;overflow:hidden;outline:none}.period-dimensions{display:flex;flex-direction:column;border-right:1px solid #dce5f3;padding:12px 8px;gap:6px}.period-dimensions button{white-space:nowrap;border:0;text-align:left;border-radius:4px}.period-dimensions button[aria-pressed=true]{background:#edf3ff;color:#174cce;font-weight:600}.period-special{margin-top:auto;font-size:12px}.period-calendar{padding:12px 16px}.period-calendar header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.period-calendar header button{border:0;font-size:20px;padding:2px 12px}.month-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.month-grid button{padding:15px 8px}.month-grid button[aria-pressed=true],.half-grid button[aria-pressed=true]{border-color:#255ff2;background:#edf3ff;color:#174cce}.half-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px 14px}.half-grid>div{display:grid;grid-template-columns:1fr 1fr;gap:4px}.half-grid strong{grid-column:1/-1;font-size:12px}.half-grid button{padding:5px 2px;font-size:12px}.half-grid small{display:block;font-size:10px;margin-top:2px}.week-calendars{display:grid;grid-template-columns:1fr 1fr;gap:20px}.week-calendar>strong{display:block;text-align:center;margin:0 0 12px;font-size:13px}.week-days{display:grid;grid-template-columns:repeat(7,1fr);gap:3px 0;text-align:center}.week-days span{font-size:12px;color:#526176;margin-bottom:5px}.week-days button{border:0;border-radius:0;padding:7px 0;font-size:12px}.week-days .outside{color:#748398}.week-days .selected{background:#e8efff;color:#174cce}.week-days button:hover{box-shadow:inset 0 0 0 1px #255ff2}.period-guidance{font-size:11px;color:#526176;margin:12px 0 0;line-height:1.6}.period-popover footer{grid-column:1/-1;border-top:1px solid #dce5f3;padding:10px 12px;display:flex;align-items:center;gap:8px}.period-popover footer>div{flex:1;min-width:0}.period-popover footer strong{font-size:12px;font-weight:500}.period-popover footer small{display:block;font-size:11px;color:#526176;margin-top:3px}.period-popover .apply-period{background:#255ff2;border-color:#255ff2;color:#fff}@media(max-width:900px){.period-popover{position:fixed;top:120px;left:16px;max-height:calc(100dvh - 140px);overflow:auto}}@media(max-width:600px){.finance-period-picker{min-width:0;flex-basis:100%}.period-popover{grid-template-columns:76px 1fr}.period-calendar{padding:10px}.week-calendars{grid-template-columns:1fr}.week-calendar:nth-child(2){display:none}.half-grid{grid-template-columns:repeat(2,1fr)}}
</style>
