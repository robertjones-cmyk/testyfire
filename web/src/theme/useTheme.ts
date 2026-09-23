/**
 * Theme switching: light/dark on <html data-theme>, stored in localStorage
 * under `app-theme`, defaulting to the OS setting.
 */
import { ref, computed } from 'vue'

export type ThemeName = 'light' | 'dark'
const STORAGE_KEY = 'app-theme'

function systemTheme(): ThemeName {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStored(): ThemeName | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

const current = ref<ThemeName>(readStored() ?? systemTheme())
/** True while the user has not chosen explicitly — we keep following the OS. */
const followingSystem = ref(readStored() === null)

export function useTheme() {
  function apply(next: ThemeName) {
    current.value = next
    document.documentElement.setAttribute('data-theme', next)
  }

  function setTheme(next: ThemeName) {
    followingSystem.value = false
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* private browsing — the choice just will not persist */
    }
    apply(next)
  }

  function toggle() {
    setTheme(current.value === 'dark' ? 'light' : 'dark')
  }

  function init() {
    apply(current.value)
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
      if (followingSystem.value) apply(event.matches ? 'dark' : 'light')
    })
  }

  return {
    theme: computed(() => current.value),
    isDark: computed(() => current.value === 'dark'),
    setTheme,
    toggle,
    init,
  }
}
