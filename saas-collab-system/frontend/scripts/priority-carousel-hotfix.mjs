export function installPriorityCarousel(source, assetPath) {
  if (!/^\/assets\/PriorityTaskCarousel-[a-f0-9]+\.js$/.test(assetPath)) throw new Error('Invalid carousel asset');
  if (source.includes('import PriorityTaskCarousel')) throw new Error('Carousel already installed');
  const start = source.indexOf('function renderPriority(){');
  const end = source.indexOf('function renderActivity(){', start);
  if (start < 0 || end < 0) throw new Error('Unknown outreach renderer');
  const render = 'function renderPriority(){return u(PriorityTaskCarousel,{groups:priorityTasks.value,loading:activityLoading.value,error:activityError.value||priorityLoadError.value});}\n';
  return `import PriorityTaskCarousel from ${JSON.stringify(assetPath)};\n` + source.slice(0, start) + render + source.slice(end);
}
