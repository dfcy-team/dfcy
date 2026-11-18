// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createElementBlock, createElementVNode, createVNode, defineComponent, nextTick, openBlock, ref } from 'vue';
import { repairOutreachRenderBlocks } from '../scripts/repair-outreach-render-blocks.mjs';

const fixture = `
function renderPriority(){
 return n("section",null,[active.value?u(Tag,null,{default:()=>"Priority"}):n("p",null,"Empty")]);
}
function renderActivity(){
 return n("section",null,[u(Tag,null,{default:()=>"Refresh"}),n("p",null,active.value?"Latest request":"No requests")]);
}
let outreachLoadSeq=0;
return ()=>{r();return C("main",null,[renderPriority(),renderActivity(),n("aside",null,detail.value?"Task details":"Closed",1)]);};
`;

describe('outreach hotfix isolated render blocks', () => {
  it('keeps details reactive across activity updates and repeated open/close', async () => {
    const active = ref(false);
    const detail = ref(false);
    const Tag = defineComponent({ setup: (_, { slots }) => () => createElementVNode('span', null, slots.default?.()) });
    const build = new Function('r', 'C', 'n', 'u', 'Tag', 'active', 'detail', repairOutreachRenderBlocks(fixture));
    const errors = [];
    const wrapper = mount(defineComponent({ setup: () => build(openBlock, createElementBlock, createElementVNode, createVNode, Tag, active, detail) }), {
      global: { config: { errorHandler: error => errors.push(error) } },
    });
    try {
      for (const visible of [true, false, true]) {
        active.value = visible;
        await nextTick();
        expect(wrapper.text()).toContain(visible ? 'Latest request' : 'No requests');
        detail.value = visible;
        await nextTick();
        expect(wrapper.find('aside').text()).toBe(visible ? 'Task details' : 'Closed');
      }
      expect(errors).toEqual([]);
    } finally {
      wrapper.unmount();
    }
  });

  it('rejects unknown or already repaired assets without partial output', () => {
    expect(() => repairOutreachRenderBlocks('unknown')).toThrow('Missing renderer');
    expect(() => repairOutreachRenderBlocks(repairOutreachRenderBlocks(fixture))).toThrow('Unexpected renderer');
  });
});
