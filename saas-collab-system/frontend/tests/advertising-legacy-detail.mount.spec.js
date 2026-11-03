import { shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
const state=vi.hoisted(()=>({query:{}}));
vi.mock('vue-router',()=>({useRoute:()=>state}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{user_type:'internal',permissions:['analytics.view']}})}));
import AdvertisingOverview from '../src/views/analytics/AdvertisingOverview.vue';
import ShopeeAdvertisingReport from '../src/components/ShopeeAdvertisingReport.vue';
const mountOptions={global:{stubs:{
 ElTabs:{name:'ElTabs',props:['modelValue'],template:'<div><slot /></div>'},
 ElTabPane:{name:'ElTabPane',props:['name','label'],template:'<section :data-tab="name"><slot /></section>'}
}}};
describe('legacy advertising detail drilldown',()=>{
 it('renders the filtered source component for legacy details URLs',()=>{
 state.query={view:'details',store_id:'12',date_from:'2026-10-01'};
 const w=shallowMount(AdvertisingOverview,mountOptions);expect(w.findComponent({name:'ElTabs'}).props('modelValue')).toBe('details');expect(w.findAllComponents(ShopeeAdvertisingReport).some(c=>c.props('performance')===true)).toBe(true);expect(state.query.store_id).toBe('12');w.unmount();
 });
 it('preserves the local default advertising workspace alongside the new marketing entries',()=>{
 state.query={};const w=shallowMount(AdvertisingOverview,mountOptions);expect(w.findComponent(ShopeeAdvertisingReport).exists()).toBe(true);expect(w.find('[data-tab="lazada"]').exists()).toBe(true);w.unmount();
 });
});
