/**
 * Shared presentation helpers for product category trees and list rows.
 *
 * Categories are returned as a flat list by the product dictionary API.  The
 * product master and SKU detail pages intentionally use the same display
 * label and L2 colour mapping so that moving between the two lists does not
 * change how a category is understood.
 */

export function categoryDisplayName(category) {
  return `${category?.code || ''} ${category?.name || ''}`.trim();
}

function categoryReferenceId(value) {
  if (value && typeof value === 'object') return value.id ?? value.pk ?? value.value ?? null;
  return value;
}

function categoryParentId(category) {
  return categoryReferenceId(category?.parent ?? category?.parent_id);
}

export function buildCategoryTree(categories = []) {
  const map = new Map(
    categories
      .filter((item) => item && categoryReferenceId(item.id) !== null && categoryReferenceId(item.id) !== undefined)
      .map((item) => [String(categoryReferenceId(item.id)), { ...item, displayName: categoryDisplayName(item), children: [] }])
  );
  const roots = [];
  for (const node of map.values()) {
    const parentId = categoryParentId(node);
    const parent = parentId === null || parentId === undefined || parentId === ''
      ? null
      : map.get(String(parentId));
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sort = (items) => {
    items.sort((left, right) => String(left.code || '').localeCompare(String(right.code || ''), undefined, { numeric: true }));
    items.forEach((item) => sort(item.children));
    return items;
  };
  return sort(roots);
}

function categoryById(categories) {
  return new Map(
    (categories || [])
      .filter((item) => item && categoryReferenceId(item.id) !== null && categoryReferenceId(item.id) !== undefined)
      .map((item) => [String(categoryReferenceId(item.id)), item])
  );
}

/**
 * Merge the FoundationSettings L2 colour collection into the category
 * dictionary used by product tables.  The settings endpoint is deliberately
 * separate from category CRUD, so a product page must not assume that the
 * regular category response carries the latest colour (or even every L2
 * node when that response is paginated).
 */
export function mergeCategoryBackgroundColors(categories = [], backgroundCategories = []) {
  const merged = new Map();
  for (const item of categories || []) {
    const id = categoryReferenceId(item?.id);
    if (id !== null && id !== undefined && id !== '') merged.set(String(id), { ...item });
  }
  for (const item of backgroundCategories || []) {
    const id = categoryReferenceId(item?.id);
    if (id === null || id === undefined || id === '') continue;
    const key = String(id);
    const existing = merged.get(key);
    const background = String(item?.row_background_color ?? '').trim();
    if (existing) {
      merged.set(key, {
        ...existing,
        ...(item?.parent !== undefined && existing.parent === undefined ? { parent: item.parent } : {}),
        ...(item?.parent_id !== undefined && existing.parent_id === undefined ? { parent_id: item.parent_id } : {}),
        ...(item?.level !== undefined && existing.level === undefined ? { level: item.level } : {}),
        ...(item?.code !== undefined && existing.code === undefined ? { code: item.code } : {}),
        ...(item?.name !== undefined && existing.name === undefined ? { name: item.name } : {}),
        // The settings endpoint is authoritative, including an empty value
        // when an operator restores the category's default colour.
        row_background_color: background,
      });
    } else {
      merged.set(key, {
        ...item,
        level: Number(item?.level || 2),
        parent: item?.parent ?? item?.parent_id ?? null,
        parent_id: item?.parent_id ?? item?.parent ?? null,
        row_background_color: background,
      });
    }
  }
  return Array.from(merged.values());
}

function l2Category(row, categories = []) {
  const map = categoryById(categories);
  const directReference = row?.category_l2_id
    ?? row?.category_l2_node
    ?? row?.category_node
    ?? row?.category_node_id
    ?? row?.category_id;
  const directId = categoryReferenceId(directReference);
  let category = directId === null || directId === undefined || directId === '' ? null : map.get(String(directId));

  // Detail responses from older clients sometimes include the category object
  // itself while the current dictionary request is still in flight.
  if (!category && directReference && typeof directReference === 'object') category = directReference;
  if (!category && row?.category_l2 && typeof row.category_l2 === 'object') category = row.category_l2;

  // Some list payloads only include a category name/path.  Prefer the
  // explicit L2 fields when present and otherwise resolve the leaf through
  // its parent chain.
  if (!category && row?.category_l2_code) {
    const codeCandidates = (categories || []).filter(
      (item) => Number(item.level) === 2 && String(item.code) === String(row.category_l2_code),
    );
    if (codeCandidates.length === 1) {
      category = codeCandidates[0];
    } else if (codeCandidates.length > 1 && row?.category_l2_name) {
      const nameCandidates = codeCandidates.filter(
        (item) => String(item.name) === String(row.category_l2_name),
      );
      if (nameCandidates.length === 1) category = nameCandidates[0];
    }
  }
  if (!category && row?.category_l2_name) {
    const nameCandidates = (categories || []).filter(
      (item) => Number(item.level) === 2 && String(item.name) === String(row.category_l2_name),
    );
    if (nameCandidates.length === 1) {
      category = nameCandidates[0];
    } else if (nameCandidates.length > 1 && row?.category_l2_code) {
      const codeCandidates = nameCandidates.filter(
        (item) => String(item.code) === String(row.category_l2_code),
      );
      if (codeCandidates.length === 1) category = codeCandidates[0];
    }
  }
  const visited = new Set();
  while (category && Number(category.level) > 2 && categoryParentId(category) !== null && categoryParentId(category) !== undefined) {
    const id = String(categoryReferenceId(category.id));
    if (visited.has(id)) break;
    visited.add(id);
    const parentObject = category.parent && typeof category.parent === 'object' ? category.parent : null;
    // Prefer the freshly fetched flat dictionary over an embedded parent
    // object, which may carry a stale background colour from the list payload.
    category = map.get(String(categoryParentId(category))) || parentObject || category;
  }
  if (category && Number(category.level) === 2) return category;

  const fallback = row?.category_l2_name || row?.category_l2_code || row?.category_name || row?.category || '';
  return fallback ? { id: fallback, code: fallback, name: fallback, level: 2 } : null;
}

function stableHash(value) {
  let hash = 0;
  for (const character of String(value || '')) hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
  return Math.abs(hash);
}

const DEFAULT_CATEGORY_BACKGROUNDS = ['#f0f9ff', '#f5f3ff', '#f0fdf4', '#fff1f2', '#f0fdfa'];

export function defaultCategoryBackgroundColor(category) {
  if (!category) return '';
  if (/床上用品/.test(`${category.name || ''}${category.code || ''}`)) return '#fff4e6';
  return DEFAULT_CATEGORY_BACKGROUNDS[stableHash(category.id || category.code || category.name) % DEFAULT_CATEGORY_BACKGROUNDS.length];
}

export function categoryBackgroundColor(row, categories = []) {
  const category = l2Category(row, categories);
  return category?.row_background_color || defaultCategoryBackgroundColor(category);
}

/** Return an Element Plus row class for a product's second-level category. */
export function categoryRowClass(row, categories = []) {
  const category = l2Category(row, categories);
  if (!category) return '';
  if (category.row_background_color) return 'product-category-custom';
  if (/床上用品/.test(`${category.name || ''}${category.code || ''}`)) return 'product-category-tone-warm';
  return `product-category-tone-${stableHash(category.id || category.code || category.name) % 5}`;
}

export function categoryRowStyle(row, categories = []) {
  const category = l2Category(row, categories);
  if (!category?.row_background_color) return {};
  return { '--product-category-row-background': category.row_background_color };
}
