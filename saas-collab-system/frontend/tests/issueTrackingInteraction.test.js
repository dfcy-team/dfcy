import {describe,it,expect,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import {dateFilters} from '../src/components/issueTracking/filters';
import TrackingFloat from '../src/components/issueTracking/TrackingFloat.vue';
vi.mock('vue-router',()=>({useRoute:()=>({path:'/test'})}));
vi.mock('../src/api/issueTracking',()=>({tracking:vi.fn().mockResolvedValue({rules:[{menu_key:'/test',enabled:true,scope:'both'}]})}));
vi.mock('../src/views/issueTracking/Index.vue',()=>({default:{template:'<p>跟踪抽屉内容</p>'}}));
function float(){return mount(TrackingFloat,{global:{stubs:{ElButton:{template:'<button><slot/></button>'},ElDrawer:{props:['modelValue'],template:'<aside v-if="modelValue"><slot/></aside>'}}}});}
describe('跟踪交互边界',()=>{
 it('结束日期含北京时间全天；显式历史查询不截断30天',()=>{const f=dateFilters(['2026-01-01','2026-01-31'],'closed');expect(f.created_before).toBe('2026-01-31T23:59:59.999999+08:00');expect(f.all_history).toBe('true');expect(f.closed_after).toBeUndefined();expect(dateFilters(null,'closed',true).all_history).toBe('true');});
 it('普通点击不capture并打开抽屉',async()=>{const w=float();await flushPromises();const box=w.get('.tracking-float'),capture=vi.fn();box.element.setPointerCapture=capture;await box.trigger('pointerdown',{clientX:10,clientY:10,pointerId:1});await box.trigger('pointerup');await w.get('button').trigger('click');expect(capture).not.toHaveBeenCalled();expect(w.text()).toContain('跟踪抽屉内容');w.unmount();});
 it('超过拖动阈值后capture，拖动结束不误开抽屉',async()=>{const w=float();await flushPromises();const box=w.get('.tracking-float'),capture=vi.fn();box.element.setPointerCapture=capture;await box.trigger('pointerdown',{clientX:10,clientY:10,pointerId:1});await box.trigger('pointermove',{clientX:30,clientY:30,pointerId:1});await box.trigger('pointerup');await w.get('button').trigger('click');expect(capture).toHaveBeenCalled();expect(w.find('aside').exists()).toBe(false);w.unmount();});
});
