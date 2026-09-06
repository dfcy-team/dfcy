<template>
  <section class="journey" aria-labelledby="governance-pilot-journey-title">
    <div class="journey__heading">
      <div>
        <h2 id="governance-pilot-journey-title">生产推进轨道</h2>
        <p>固定环境：<strong>受控试点</strong>。每一步都以服务端真实证据和当前权限为准。</p>
      </div>
      <p class="journey__boundary">生产影响边界：验证阶段可能产生真实负载；部署、恢复和回滚会改变生产状态，必须在详情上下文内确认。</p>
    </div>

    <ol class="journey__steps">
      <li v-for="(step, index) in steps" :key="step.label" :class="stepClass(index)">
        <button
          v-if="canOpen(step)"
          type="button"
          class="journey__step-button"
          :aria-current="index === activeStep ? 'step' : undefined"
          :aria-label="`${step.label}：${step.description}`"
          @click="open(step.path)"
        >
          <span class="journey__step-index" aria-hidden="true">{{ index < activeStep ? '✓' : index + 1 }}</span>
          <span class="journey__step-copy">
            <strong>{{ step.label }}</strong>
            <small>{{ step.description }}</small>
          </span>
        </button>
        <span v-else class="journey__step-button journey__step-button--disabled" aria-disabled="true" tabindex="-1">
          <span class="journey__step-index" aria-hidden="true">{{ index + 1 }}</span>
          <span class="journey__step-copy">
            <strong>{{ step.label }}</strong>
            <small>当前账号无查看权限</small>
          </span>
        </span>
      </li>
    </ol>

    <nav class="journey__centers" aria-label="治理与试点中心">
      <span class="journey__centers-label">工作中心</span>
      <template v-for="center in centers" :key="center.path">
        <button v-if="canOpen(center)" type="button" class="journey__center-link" @click="open(center.path)">{{ center.label }}</button>
        <span v-else class="journey__center-link journey__center-link--disabled" aria-disabled="true" tabindex="-1">{{ center.label }}（无权限）</span>
      </template>
    </nav>
  </section>
</template>

<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const props = defineProps({
  activeStep: { type: Number, default: 0 }
});

const router = useRouter();
const auth = useAuthStore();

const governancePermissions = ['governance.api.view', 'governance.assistants.view'];
const validationPermissions = ['pilot.security_review.view', 'pilot.verification.view', 'pilot.performance.view'];
const releasePermissions = ['pilot.release.view', 'pilot.recovery.view'];
const operationsPermissions = ['pilot.control.view', 'pilot.topology.view', 'pilot.capacity.view'];

const steps = [
  { label: '登记', description: '登记治理对象', path: '/governance', permissions: governancePermissions },
  { label: '验证', description: '形成受控证据', path: '/pilot/validation', permissions: validationPermissions },
  { label: '准入', description: '完成准入决策', path: '/pilot/releases', permissions: releasePermissions },
  { label: '部署', description: '执行受控发布', path: '/pilot/releases', permissions: releasePermissions },
  { label: '观察', description: '读取实时作业', path: '/pilot/control-room', permissions: operationsPermissions },
  { label: '恢复/回滚', description: '在详情内处置', path: '/pilot/releases', permissions: releasePermissions }
];

const centers = [
  { label: '治理中心', path: '/governance', permissions: governancePermissions },
  { label: '验证中心', path: '/pilot/validation', permissions: validationPermissions },
  { label: '发布中心', path: '/pilot/releases', permissions: releasePermissions },
  { label: '运维控制台', path: '/pilot/control-room', permissions: operationsPermissions }
];

function canOpen(item) {
  return auth.isInternal && (auth.isSuperuser || item.permissions.some((permission) => auth.hasPermission(permission)));
}

function open(path) {
  router.push(path);
}

function stepClass(index) {
  return {
    'journey__step': true,
    'journey__step--active': index === props.activeStep,
    'journey__step--complete': index < props.activeStep
  };
}
</script>

<style scoped>
.journey {
  margin-bottom: 20px;
  padding: 18px 20px 16px;
  border: 1px solid #dbe3ec;
  background: #fff;
}

.journey__heading {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e7edf4;
}

.journey h2 {
  margin: 0;
  color: #172033;
  font-size: 16px;
  line-height: 1.4;
}

.journey p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.journey__boundary {
  max-width: 470px;
  margin: 0 !important;
  color: #8a5a00 !important;
}

.journey__steps {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 18px 0 16px;
  list-style: none;
}

.journey__step {
  position: relative;
  min-width: 0;
}

.journey__step::after {
  content: '';
  position: absolute;
  top: 15px;
  left: 50%;
  width: 100%;
  height: 1px;
  background: #cbd5e1;
  z-index: 0;
}

.journey__step--complete::after {
  background: #16a34a;
}

.journey__step:last-child::after {
  display: none;
}

.journey__step-button {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  min-height: 74px;
  padding: 0 5px;
  border: 0;
  background: transparent;
  color: #172033;
  font: inherit;
  text-align: center;
  cursor: pointer;
}

.journey__step-button:focus-visible,
.journey__center-link:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 3px;
}

.journey__step-button--disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.journey__step-index {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid #94a3b8;
  border-radius: 50%;
  background: #fff;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
}

.journey__step--active .journey__step-index {
  border-color: #2563eb;
  background: #2563eb;
  color: #fff;
}

.journey__step--complete .journey__step-index {
  border-color: #16a34a;
  background: #16a34a;
  color: #fff;
}

.journey__step-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 8px;
}

.journey__step-copy strong {
  font-size: 13px;
  font-weight: 650;
}

.journey__step-copy small {
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.journey__centers {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding-top: 13px;
  border-top: 1px solid #e7edf4;
  font-size: 13px;
}

.journey__centers-label {
  color: #64748b;
}

.journey__center-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1d4ed8;
  font: inherit;
  cursor: pointer;
}

.journey__center-link--disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .journey__heading {
    flex-direction: column;
    gap: 6px;
  }

  .journey__boundary {
    max-width: none;
  }

  .journey__steps {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    row-gap: 18px;
  }

  .journey__step:nth-child(3)::after,
  .journey__step:nth-child(6)::after {
    display: none;
  }
}

@media (max-width: 720px) {
  .journey {
    padding: 16px;
  }

  .journey__steps {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 14px 0;
  }

  .journey__step {
    min-height: 51px;
  }

  .journey__step::after {
    top: 30px;
    left: 14px;
    width: 1px;
    height: calc(100% - 4px);
  }

  .journey__step:last-child::after {
    display: none;
  }

  .journey__step:nth-child(3)::after {
    display: block;
  }

  .journey__step:nth-child(6)::after {
    display: none;
  }

  .journey__step-button {
    flex-direction: row;
    align-items: center;
    min-height: 51px;
    padding: 0;
    text-align: left;
  }

  .journey__step-copy {
    margin: 0 0 0 10px;
  }
}
</style>
