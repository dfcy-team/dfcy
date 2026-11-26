<template><div v-if="rule?.enabled && (rule.scope!=='record'||context.record_id) && (rule.scope!=='page'||!context.record_id)" class="tracking-float" :style="{right:`${right}px`,bottom:`${bottom}px`}" @pointerdown="start" @pointerup="stop" @pointermove="move" @pointercancel="cancel" @lostpointercapture="stop"><el-button type="primary" round @click="!dragged&&(open=true)">{{collapsed?'跟踪':'事件跟踪'}}<span @click.stop="collapsed=!collapsed"> {{collapsed?'+':'−'}}</span></el-button></div><el-drawer v-model="open" title="当前页面跟踪" size="min(1000px, 96vw)"><Index v-if="open" :key="route.path" :context="context"/></el-drawer></template>
<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { useRoute } from 'vue-router';
import { tracking } from '../../api/issueTracking';
import Index from '../../views/issueTracking/Index.vue';
const route=useRoute(),open=ref(false),collapsed=ref(false),right=ref(24),bottom=ref(32),rules=ref([]);let origin=null,dragged=false;
const rule=computed(()=>rules.value.find(r=>r.menu_key===context.value.menu_key));
const record=ref(null);const context=computed(()=>{const match=route.path.match(/^\/workflow\/(approvals|exceptions)\/(\d+)$/);return {menu_key:match?`/workflow/${match[1]}`:route.path,page_path:route.path,...(match?{record_type:match[1]==='approvals'?'approval':'exception',record_id:match[2]}:record.value||{})};});
function receive(e){record.value=e.detail;}onMounted(()=>window.addEventListener('issue-tracking-context',receive));onBeforeUnmount(()=>window.removeEventListener('issue-tracking-context',receive));
watch(()=>route.path,async()=>{open.value=false;record.value=null;try{rules.value=(await tracking('candidates/')).rules||[];}catch{rules.value=[];}},{immediate:true});
function start(e){origin={x:e.clientX,y:e.clientY,right:right.value,bottom:bottom.value};dragged=false;}
function move(e){if(!origin)return;const dx=e.clientX-origin.x,dy=e.clientY-origin.y;if(!dragged && Math.abs(dx)+Math.abs(dy)>5){dragged=true;e.currentTarget.setPointerCapture?.(e.pointerId);}if(!dragged)return;right.value=Math.max(0,Math.min(innerWidth-110,origin.right-dx));bottom.value=Math.max(0,Math.min(innerHeight-45,origin.bottom-dy));}
function stop(){origin=null;}
function cancel(){origin=null;dragged=true;}
</script><style scoped>.tracking-float{position:fixed;z-index:1999;touch-action:none;cursor:move}.tracking-float span{padding-left:12px}</style>
