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

export function buildCategoryTree(categories = []) {
  const map = new Map(
    categories.map((item) => [String(item.id), { ...item, displayName: categoryDisplayName(item), children: [] }])
  );
  const roots = [];
  for (const node of map.values()) {
    const parent = node.parent === null || node.parent === undefined || node.parent === ''
      ? null
      : map.get(String(node.parent));
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
  return new Map((categories || []).map((item) => [String(item.id), item]));
}

function l2Category(row, categories = []) {
  const map = categoryById(categories);
  const directId = row?.category_l2_id ?? row?.category_l2_node ?? row?.category_node ?? row?.category_node_id ?? row?.category_id;
  let category = directId === null || directId === undefined || directId === '' ? null : map.get(String(directId));

  // Some list payloads only include a category name/path.  Prefer the
  // explicit L2 fields when present and otherwise resolve the leaf through
  // its parent chain.
  if (!category && row?.category_l2_code) {
    category = (categories || []).find((item) => String(item.code) === String(row.category_l2_code)) || null;
  }
  if (!category && row?.category_l2_name) {
    category = (categories || []).find((item) => String(item.name) === String(row.category_l2_name) && Number(item.level) === 2) || null;
  }
  const visited = new Set();
  while (category && Number(category.level) > 2 && category.parent !== null && category.parent !== undefined) {
    const id = String(category.id);
    if (visited.has(id)) break;
    visited.add(id);
    category = map.get(String(category.parent)) || category;
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
