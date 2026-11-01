export function assertProductionMode(command, env) {
  if (command === 'build' && env.VITE_USE_MOCK !== 'false') {
    throw new Error('生产构建必须明确设置 VITE_USE_MOCK=false；演示预览请使用 npm run dev。');
  }
}
