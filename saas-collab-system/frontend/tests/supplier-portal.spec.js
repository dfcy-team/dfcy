import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { supplierRedirect } from '../src/utils/supplierPortal';
import { readAuthSession, writeAuthSession, updateAccessToken, clearAuthSession } from '../src/utils/authSession';
const api = vi.hoisted(() => ({ supplierLogin:vi.fn(), getCurrentUser:vi.fn(), login:vi.fn() }));
vi.mock('../src/api/auth', () => api);
vi.mock('../src/api/request', () => ({useMock:false}));
import { useAuthStore } from '../src/stores/auth';

describe('supplier portal identity and order return link', () => {
  beforeEach(()=>{sessionStorage.clear();setActivePinia(createPinia());vi.clearAllMocks();});
  it('keeps the supplier channel when renewing access',()=>{
    writeAuthSession({access:'A',refresh:'R',channel:'supplier_web'});updateAccessToken('B');
    expect(readAuthSession()).toEqual({access:'B',refresh:'R',channel:'supplier_web'});
    clearAuthSession();expect(readAuthSession()).toBeNull();
  });
  it('only returns to supplier order/shipments routes after login',()=>{
    expect(supplierRedirect('/supplier/orders/8')).toBe('/supplier/orders/8');
    expect(supplierRedirect('/supplier/shipments?order_id=8')).toBe('/supplier/shipments?order_id=8');
    for(const target of ['//evil.test','/supply-chain/purchase-orders','/supplier/login','/supplier/orders/../login','/supplier/orders\\evil']){
      expect(supplierRedirect(target)).toBe('/supplier/orders');
    }
  });
  it('logs in using supplier identity without provisioning internal permissions',async()=>{
    api.supplierLogin.mockResolvedValue({success:true,data:{access:'A',refresh:'R'}});
    api.getCurrentUser.mockResolvedValue({success:true,data:{id:3,user_type:'external',supplier_id:8,permissions:[]}});
    const auth=useAuthStore();const r=await auth.loginSupplier({username:'supplier',password:'test'});
    expect(r.success).toBe(true);expect(readAuthSession().channel).toBe('supplier_web');
    expect(auth.isInternal).toBe(false);expect(auth.hasPermission('supply.v2.manage')).toBe(false);
    expect(api.login).not.toHaveBeenCalled();
  });
  it('rejects failed supplier binding and clears old authentication',async()=>{
    writeAuthSession({access:'A',refresh:'R',channel:'supplier_web'});
    api.supplierLogin.mockResolvedValue({success:false,message:'binding invalid'});
    const auth=useAuthStore();expect((await auth.loginSupplier({})).success).toBe(false);
    expect(readAuthSession()).toBeNull();expect(auth.isAuthenticated).toBe(false);
  });
});
