export function createSuccessfulAsyncCache(loader, isSuccess = (value) => Boolean(value)) {
  const results = new Map();
  const pending = new Map();

  return {
    async get(key, ...args) {
      if (results.has(key)) return results.get(key);
      if (!pending.has(key)) {
        pending.set(
          key,
          Promise.resolve()
            .then(() => loader(...args))
            .then((result) => {
              if (isSuccess(result)) results.set(key, result);
              return result;
            })
            .finally(() => pending.delete(key)),
        );
      }
      return pending.get(key);
    },
  };
}

export function createRequestSequence() {
  let current = 0;
  return {
    begin() {
      const sequence = ++current;
      return { isCurrent: () => sequence === current };
    },
  };
}
