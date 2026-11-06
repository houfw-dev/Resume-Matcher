/**
 * Helpers for locating elements by CSS-module *local* class name.
 *
 * CSS-module class tokens are hashed in builds
 * (`_base-module__6VxlCq__resume-item`), while tests render identity tokens
 * (`resume-item`) because CSS modules are stubbed in vitest. Plain selectors
 * (`.resume-item`) only match the latter, so DOM measurement walks class
 * tokens and accepts both the identity form and any token ending in
 * `__<localName>`.
 */

export function hasLocalClass(element: Element, localName: string): boolean {
  const suffix = `__${localName}`;
  for (const token of element.classList) {
    if (token === localName || token.endsWith(suffix)) return true;
  }
  return false;
}

/** All descendants (or the element itself) carrying the local class. */
export function queryLocalClass<T extends HTMLElement = HTMLElement>(
  root: ParentNode,
  localName: string
): T[] {
  const matches: T[] = [];
  root.querySelectorAll<T>('[class]').forEach((element) => {
    if (hasLocalClass(element, localName)) matches.push(element);
  });
  return matches;
}

/** First descendant carrying the local class, or null. */
export function findLocalClass<T extends HTMLElement = HTMLElement>(
  root: ParentNode,
  localName: string
): T | null {
  return queryLocalClass<T>(root, localName)[0] ?? null;
}

/** Nearest ancestor (the element included) carrying the local class. */
export function closestLocalClass<T extends HTMLElement = HTMLElement>(
  element: Element | null,
  localName: string
): T | null {
  let current: Element | null = element;
  while (current) {
    if (hasLocalClass(current, localName)) return current as T;
    current = current.parentElement;
  }
  return null;
}
