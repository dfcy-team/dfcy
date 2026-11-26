import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import IssueForm from '../src/components/issueTracking/IssueForm.vue';
import { tracking } from '../src/api/issueTracking';
vi.mock('../src/api/issueTracking',()=>({tracking:vi.fn()}));
const input={props:['modelValue'],template:'<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>'};
const slot={template:'<div><slot/></div>'};
const candidates={users:[{id:1,username:'handler',department_ids:[2]}],departments:[{id:2,name:'部门'}],rules:[]};
function form(){return mount(IssueForm,{props:{candidates},global:{stubs:{ScreenshotEditor:true,ElForm:{template:'<form @submit.prevent="$emit(\'submit\',$event)"><slot/></form>'},ElFormItem:slot,ElInput:input,ElSelect:input,ElOption:true,ElDatePicker:input,ElAlert:{props:['title'],template:'<p role="alert">{{title}}</p>'},ElButton:{template:'<button type="submit"><slot/></button>'}}}});}
beforeEach(()=>vi.clearAllMocks());
describe('事项发起表单',()=>{
 it('缺少必填字段不写入后端',async()=>{const w=form();await w.find('form').trigger('submit');expect(tracking).not.toHaveBeenCalled();expect(w.text()).toContain('请填写标题');w.unmount();});
 it('发起成功后传递服务端事项',async()=>{tracking.mockResolvedValue({id:7});const w=form();Object.assign(w.vm.form,{title:'跟踪',assignee:1,department:2,due_at:'2026-12-01T00:00:00Z'});await w.find('form').trigger('submit');await flushPromises();expect(tracking).toHaveBeenCalledWith('issues/','post',expect.objectContaining({title:'跟踪'}));expect(w.emitted('created')[0][0]).toEqual({id:7});w.unmount();});
 it('接口失败保留表单且不报告成功',async()=>{tracking.mockRejectedValue(new Error('权限不足'));const w=form();Object.assign(w.vm.form,{title:'跟踪',assignee:1,department:2,due_at:'2026-12-01T00:00:00Z'});await w.find('form').trigger('submit');await flushPromises();expect(w.text()).toContain('权限不足');expect(w.emitted('created')).toBeUndefined();w.unmount();});
});
