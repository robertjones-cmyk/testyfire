<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NConfigProvider, NDialogProvider, NDropdown, NMessageProvider, darkTheme,
} from 'naive-ui'
import AppSidebar from '@/components/AppSidebar.vue'
import IdleTimeoutWarning from '@/components/IdleTimeoutWarning.vue'
import LiveRegion from '@/components/LiveRegion.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import { buildThemeOverrides } from '@/theme/naiveOverrides'
import { useTheme } from '@/theme/useTheme'
import { useAuthStore } from '@/stores/auth'
import { useLiveStore } from '@/stores/live'
import { setUnauthorizedHandler } from '@/api'
import { useScrollableRegions } from '@/composables/useScrollableRegions'

const auth = useAuthStore()
const live = useLiveStore()
const route = useRoute()
const router = useRouter()
const { isDark, toggle: toggleTheme } = useTheme()

// Keep horizontally scrollable tables reachable by keyboard.
useScrollableRegions()

const themeOverrides = ref(buildThemeOverrides())
// Naive UI needs concrete colours, so rebuild them whenever the theme flips.
watch(isDark, () => {
  requestAnimationFrame(() => {
    themeOverrides.value = buildThemeOverrides()
  })
})

const isLogin = computed(() => route.name === 'login')

const userMenuOptions = computed(() => [
  { key: 'theme', label: isDark.value ? 'Switch to light theme' : 'Switch to dark theme' },
  { key: 'logout', label: 'Log out' },
])

async function onUserMenu(key: string) {
  if (key === 'theme') toggleTheme()
  if (key === 'logout') {
    await auth.logout()
    await router.push('/login')
  }
}

function recordActivity() {
  if (auth.isAuthenticated) auth.touch()
}

setUnauthorizedHandler(() => {
  auth.clear()
  live.stopPolling()
  if (route.name !== 'login') void router.push({ name: 'login' })
})

watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      void live.refreshAll(false)
      live.startPolling()
    } else {
      live.stopPolling()
    }
  },
  { immediate: true },
)

onMounted(() => {
  ;['click', 'keydown'].forEach((name) => window.addEventListener(name, recordActivity, { passive: true }))
})
onBeforeUnmount(() => {
  ;['click', 'keydown'].forEach((name) => window.removeEventListener(name, recordActivity))
  live.stopPolling()
})
</script>

<template>
  <NConfigProvider :theme="isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <a class="skip-link" href="#main-content">Skip to main content</a>

        <div v-if="isLogin" class="login-shell">
          <RouterView />
        </div>

        <div v-else class="shell">
          <AppSidebar :open-event-count="live.openEvents.length" />

          <div class="shell__body">
            <header class="topbar">
              <h1 class="topbar__title">{{ route.meta.title ?? 'Torch' }}</h1>
              <div class="topbar__right">
                <span class="topbar__updated">
                  <span v-if="live.paused">Live updates paused</span>
                  <span v-else-if="live.lastUpdated">
                    Updated {{ live.lastUpdated.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) }}
                  </span>
                </span>
                <NDropdown trigger="click" :options="userMenuOptions" @select="onUserMenu">
                  <NButton quaternary>
                    <template #icon><TorchIcon :name="isDark ? 'moon' : 'sun'" /></template>
                    {{ auth.email || 'Account' }}
                  </NButton>
                </NDropdown>
              </div>
            </header>

            <main id="main-content" class="main" tabindex="-1">
              <RouterView />
            </main>
          </div>
        </div>

        <IdleTimeoutWarning v-if="auth.isAuthenticated" />
        <LiveRegion
          :message="live.announcement"
          :politeness="live.announcementPoliteness"
          @consumed="live.clearAnnouncement()"
        />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style scoped>
.shell { display: flex; height: 100vh; overflow: hidden; }
.shell__body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.login-shell { min-height: 100vh; }

.topbar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px var(--space-page);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  flex: none;
}
.topbar__title { font-size: 18px; margin: 0; }
.topbar__right { display: flex; align-items: center; gap: 12px; }
.topbar__updated { font-size: 12px; color: var(--color-text-muted); font-weight: 600; }

.main { flex: 1; overflow: auto; padding: var(--space-page); }
.main:focus { outline: none; }

@media (max-width: 860px) {
  .shell { flex-direction: column; height: auto; overflow: visible; }
  .topbar { flex-wrap: wrap; }
}
</style>
