import { h } from 'vue';
import InventoryAbcStatus from './InventoryAbcStatus.vue';

// Preserve the current authorization, cancellation and composite-policy behavior.
export default {
  props: { countryId: [Number, String] },
  setup(props) {
    return () => h(InventoryAbcStatus, { countryId: props.countryId });
  },
};
