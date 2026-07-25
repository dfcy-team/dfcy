"use strict";

Component({
  properties: {
    state: {
      type: String,
      value: "empty"
    },
    title: {
      type: String,
      value: ""
    },
    description: {
      type: String,
      value: ""
    },
    actionText: {
      type: String,
      value: ""
    }
  },
  methods: {
    handleAction() {
      this.triggerEvent("action");
    }
  }
});
