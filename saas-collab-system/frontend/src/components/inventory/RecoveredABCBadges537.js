import { h } from 'vue';
import InventoryAbcBadges from './InventoryAbcBadges.js';

// Retain the current composite policy and its auditable evidence in the restored panel.
export default {
  props: { row: { type: Object, default: () => ({}) } },
  setup(props) {
    return () => {
      const row = props.row;
      const isSpu = row.__spu || Boolean(row.variants) || Boolean(row.spu_id && !row.sku_id && !row.internal_sku);
      return h(InventoryAbcBadges, { row, entityType: isSpu ? 'spu' : 'sku' });
    };
  },
};
