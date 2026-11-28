import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { effectScope, nextTick, reactive, ref } from 'vue';
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), state: null }));
vi.mock('../src/api/influencers', () => ({ fetchDuplicateSampleRecords: (...args) => mocks.fetch(...args) }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => mocks.state }));
import { useDuplicateSampleWarning } from '../src/composables/useDuplicateSampleWarning';
let scopes;
const drain = async () => { await nextTick(); await Promise.resolve(); await nextTick(); };
const success = (number, status='pending') => ({ success:true, data:{records:[{fulfillment_no:number,status,secret:'not-for-output'}]} });
function start(active, id) { const scope=effectScope();scopes.push(scope);return scope.run(()=>useDuplicateSampleWarning(active,id)); }
beforeEach(()=>{scopes=[];mocks.fetch.mockReset();mocks.state=reactive({currentUser:{id:1,tenant_id:1},authorizationStale:false});});
afterEach(()=>scopes.forEach(s=>s.stop()));

describe('optional duplicate warning lifecycle',()=>{
 it('queries only an active create dialog, retains max three safe rows and supports all five states',async()=>{
   const active=ref(false),id=ref(4);const warning=start(active,id);expect(mocks.fetch).not.toHaveBeenCalled();
   mocks.fetch.mockResolvedValue({success:true,data:{records:['pending','shipped','delivered','overdue','blacklisted'].map((status,i)=>({fulfillment_no:`S${i}`,status,secret:'omit'}))}});
   active.value=true;await drain();expect(mocks.fetch).toHaveBeenCalledTimes(1);expect(warning.records.value).toHaveLength(3);
   expect(warning.warning.value).toContain('已签收');expect(JSON.stringify(warning.records.value)).not.toContain('secret');
   mocks.fetch.mockResolvedValue(success('Late','overdue'));id.value=5;await drain();expect(warning.warning.value).toContain('已逾期');
   mocks.fetch.mockResolvedValue(success('Blocked','blacklisted'));id.value=6;await drain();expect(warning.warning.value).toContain('已拉黑');
 });
 it('ignores reversed responses after a different creator is selected',async()=>{
   let oldResolve,newResolve;mocks.fetch.mockImplementationOnce(()=>new Promise(r=>oldResolve=r)).mockImplementationOnce(()=>new Promise(r=>newResolve=r));
   const active=ref(true),id=ref(1);const warning=start(active,id);id.value=2;await drain();
   newResolve(success('NEW'));await drain();oldResolve(success('OLD'));await drain();
   expect(warning.records.value.map(r=>r.fulfillment_no)).toEqual(['NEW']);
 });
 it('clears and aborts when hidden, and discards a result from a refreshed same-ID actor',async()=>{
   let firstResolve;mocks.fetch.mockImplementationOnce(()=>new Promise(r=>firstResolve=r)).mockResolvedValue(success('CURRENT'));
   const active=ref(true),id=ref(1);const warning=start(active,id);const firstSignal=mocks.fetch.mock.calls[0][1].signal;
   mocks.state.currentUser={id:1,tenant_id:1};await drain();firstResolve(success('OLD_ACTOR'));await drain();
   expect(firstSignal.aborted).toBe(true);expect(warning.records.value[0].fulfillment_no).toBe('CURRENT');
   active.value=false;await drain();expect(warning.records.value).toEqual([]);
 });
 it('never blocks creation on denied or failed reads and clears stale authorization',async()=>{
   mocks.fetch.mockRejectedValue(new Error('denied'));const active=ref(true),id=ref(1);const warning=start(active,id);await drain();
   expect(warning.warning.value).toBe('');expect(Object.keys(warning).sort()).toEqual(['records','warning']);
   mocks.fetch.mockResolvedValue(success('OK'));id.value=2;await drain();expect(warning.records.value).toHaveLength(1);
   mocks.state.authorizationStale=true;await drain();expect(warning.records.value).toEqual([]);
 });
});
