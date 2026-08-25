<template><IntegrationWorkspace mode="sync-jobs" :run-permission="runAction.permission" :mock-run-permission="mockRunAction.permission" /></template>
<script setup>
import IntegrationWorkspace from './IntegrationWorkspace.vue';

const runAction = { permission: 'integrations.run_live_readonly' };
const mockRunAction = { permission: 'integrations.run' };
</script>
