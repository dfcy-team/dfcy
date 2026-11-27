import { createVNode, ref, watch } from 'vue';

const cache = new WeakMap();
export function pagedTable(table) {
  if (cache.has(table)) return cache.get(table);
  const view = {
    inheritAttrs: false,
    props: { data: { type: Array, required: true } },
    setup(props, { attrs, slots }) {
      const page = ref(1);
      watch(() => props.data, () => { page.value = 1; }, { flush: 'sync' });
      return () => {
        const size = 50;
        const pages = Math.max(1, Math.ceil(props.data.length / size));
        const pos = (page.value - 1) * size;
        return createVNode('div', null, [
          createVNode(table, { ...attrs, data: props.data.slice(pos, pos + size) }, slots),
          pages > 1 && createVNode('nav', { 'aria-label': '明细分页' }, [
            createVNode('button', { type: 'button', disabled: page.value <= 1, onClick: () => page.value-- }, '上一页'),
            ' ' + page.value + ' / ' + pages + '（共 ' + props.data.length + ' 条） ',
            createVNode('button', { type: 'button', disabled: page.value >= pages, onClick: () => page.value++ }, '下一页'),
          ]),
        ]);
      };
    },
  };
  cache.set(table, view);
  return view;
}
