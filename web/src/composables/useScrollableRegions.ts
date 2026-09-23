/**
 * Make scrollable regions reachable by keyboard.
 *
 * Naive UI's data table puts its horizontal scroller in a plain `<div>`. When a
 * table is wider than its container — the Dashboard's per-camera metrics table
 * has ten columns — a mouse user can scroll to the rest, and a keyboard user
 * simply cannot reach it. axe flags this as `scrollable-region-focusable`
 * (WCAG 2.1.1 Keyboard), and it is a genuine loss of content, not a technicality.
 *
 * The standard remedy is to make the scroll container focusable so arrow keys
 * work. This watches the main region and applies it to any container that is
 * actually scrollable, re-checking when the DOM or the window changes.
 */
import { onBeforeUnmount, onMounted } from 'vue'

// Naive UI uses several different scroll containers depending on the table's
// state (an empty table renders `.n-virtual-list`, a populated one does not),
// so all of them are covered rather than just the one visible at the time.
const SELECTOR = [
  '.n-scrollbar-container',
  '.n-data-table-base-table-body',
  '.n-virtual-list',
].join(', ')

function patch(root: ParentNode) {
  root.querySelectorAll<HTMLElement>(SELECTOR).forEach((element) => {
    const scrolls =
      element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
    if (scrolls) {
      if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '0')
      if (!element.hasAttribute('role')) element.setAttribute('role', 'region')
      if (!element.hasAttribute('aria-label')) {
        element.setAttribute('aria-label', 'Scrollable table — use the arrow keys to scroll')
      }
    } else {
      // Not scrollable any more (window resized): do not leave a pointless stop
      // in the tab order.
      if (element.getAttribute('role') === 'region') {
        element.removeAttribute('tabindex')
        element.removeAttribute('role')
        element.removeAttribute('aria-label')
      }
    }
  })
}

export function useScrollableRegions() {
  let observer: MutationObserver | null = null
  let frame = 0

  const schedule = () => {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => patch(document))
  }

  onMounted(() => {
    schedule()
    observer = new MutationObserver(schedule)
    observer.observe(document.body, { childList: true, subtree: true })
    window.addEventListener('resize', schedule, { passive: true })
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    window.removeEventListener('resize', schedule)
    cancelAnimationFrame(frame)
  })
}
