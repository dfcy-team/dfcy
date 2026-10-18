import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { fetchApiFile } from '../api/request';

const MAX_ACTIVE_IMAGE_REQUESTS = 4;
const imageQueue = [];
let activeImageRequests = 0;

function drainImageQueue() {
  while (activeImageRequests < MAX_ACTIVE_IMAGE_REQUESTS && imageQueue.length) {
    const job = imageQueue.shift();
    if (job.cancelled) continue;
    activeImageRequests += 1;
    let execution;
    try { execution = job.run(); }
    catch { execution = undefined; }
    Promise.resolve(execution)
      .catch(() => {})
      .finally(() => {
        activeImageRequests -= 1;
        drainImageQueue();
      });
  }
}

function enqueueImageRequest(run) {
  const job = { run, cancelled: false };
  imageQueue.push(job);
  drainImageQueue();
  return () => { job.cancelled = true; };
}

export function useLazyApiImage(element, path, enabled = () => true) {
  const imageUrl = ref('');
  const loading = ref(false);
  let sequence = 0;
  let mounted = false;
  let observer;
  let cancelQueuedRequest;
  let visible = false;

  function release() {
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
    imageUrl.value = '';
  }

  function requestCurrentImage(current, imagePath) {
    if (current !== sequence) return;
    cancelQueuedRequest?.();
    cancelQueuedRequest = enqueueImageRequest(async () => {
      if (current !== sequence) return;
      try {
        const result = await fetchApiFile(imagePath);
        if (current === sequence && result?.success) imageUrl.value = URL.createObjectURL(result.blob);
      } catch {
        // Keep the existing unavailable-image placeholder on request failures.
      } finally {
        if (current === sequence) loading.value = false;
      }
    });
  }

  function observeCurrentImage(current, imagePath) {
    const target = element.value?.$el || element.value;
    if (!imagePath || !enabled()) return;
    if (typeof IntersectionObserver === 'undefined' || !target) {
      requestCurrentImage(current, imagePath);
      return;
    }
    observer?.disconnect();
    observer = new IntersectionObserver(entries => {
      if (current !== sequence) return;
      if (entries.some(entry => entry.isIntersecting || entry.intersectionRatio > 0)) {
        visible = true;
        observer?.disconnect();
        observer = undefined;
        requestCurrentImage(current, imagePath);
      }
    }, { rootMargin: '150px' });
    observer.observe(target);
  }

  function resetImage() {
    const current = ++sequence;
    const wasVisible = visible;
    observer?.disconnect();
    observer = undefined;
    cancelQueuedRequest?.();
    cancelQueuedRequest = undefined;
    release();
    visible = false;

    const imagePath = path();
    if (!imagePath || !enabled()) {
      loading.value = false;
      return;
    }
    loading.value = true;
    if (mounted) {
      if (wasVisible) requestCurrentImage(current, imagePath);
      else observeCurrentImage(current, imagePath);
    }
  }

  watch([path, enabled], resetImage, { immediate: true, flush: 'sync' });
  onMounted(() => {
    mounted = true;
    const imagePath = path();
    if (imagePath && enabled()) observeCurrentImage(sequence, imagePath);
  });
  onBeforeUnmount(() => {
    mounted = false;
    sequence += 1;
    observer?.disconnect();
    observer = undefined;
    cancelQueuedRequest?.();
    release();
  });

  return { imageUrl, loading };
}
