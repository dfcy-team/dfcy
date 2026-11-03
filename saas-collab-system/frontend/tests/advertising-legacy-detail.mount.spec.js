import { shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
const state=vi.hoisted(()=>({query:{}}));
vi.mock('vue-router',()=>({useRoute:()=>state}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{user_type:'internal',permissions:['analytics.view']}})}));
import AdvertisingOverview from '../src/views/analytics/AdvertisingOverview.vue';
import ShopeeAdvertisingReport from '../src/components/ShopeeAdvertisingReport.vue';
describe('legacy advertising detail drilldown',()=>{
 it('renders the filtered source component for legacy details URLs',()=>{
 state.query={view:'details',store_id:'12',date_from:'2026-10-01'};
 const w=shallowMount(AdvertisingOverview);expect(w.findComponent(ShopeeAdvertisingReport).exists()).toBe(true);expect(w.findComponent(ShopeeAdvertisingReport).props('performance')).toBe(true);expect(state.query.store_id).toBe('12');w.unmount();
 });
 it('keeps the default advertising page in composite analysis mode',()=>{
 state.query={};const w=shallowMount(AdvertisingOverview);expect(w.findComponent(ShopeeAdvertisingReport).exists()).toBe(false);w.unmount();
 });
});
