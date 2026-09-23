<script setup lang="ts">
/** Left navigation, using Torch's words: Map, Events, Sensors, Cameras, Dashboard, Settings. */
import { ref } from 'vue'
import { NSelect } from 'naive-ui'
import LogoTile from './LogoTile.vue'
import TorchIcon from './TorchIcon.vue'
import type { IconName } from '@/icons'

defineProps<{ openEventCount: number }>()

const links: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: 'Map', icon: 'map' },
  { to: '/events', label: 'Events', icon: 'fire-02' },
  { to: '/sensors', label: 'Sensors', icon: 'sensor-color' },
  { to: '/cameras', label: 'Cameras', icon: 'camera-01' },
  { to: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
  { to: '/settings', label: 'Settings', icon: 'settings-02' },
]

// Site grouping picker, mirroring the Torch app's "All assets / Folders".
const scope = ref('all')
const scopeOptions = [
  { label: 'All assets', value: 'all' },
  { label: 'Rio Grande Bosque', value: 'bosque' },
]
</script>

<template>
  <nav class="sidebar" aria-label="Main">
    <div class="sidebar__brand">
      <LogoTile :size="40" />
      <div>
        <div class="sidebar__title">Torch</div>
        <div class="sidebar__subtitle">Camera Fusion</div>
      </div>
    </div>

    <div class="sidebar__scope">
      <label class="sidebar__scope-label" for="asset-scope">Assets</label>
      <NSelect id="asset-scope" v-model:value="scope" :options="scopeOptions" size="medium" />
    </div>

    <ul class="sidebar__list">
      <li v-for="link in links" :key="link.to">
        <RouterLink :to="link.to" class="sidebar__link" active-class="sidebar__link--active"
          :aria-current="$route.path === link.to ? 'page' : undefined">
          <TorchIcon :name="link.icon" :size="18" />
          <span>{{ link.label }}</span>
          <span v-if="link.to === '/events' && openEventCount > 0" class="sidebar__badge">
            {{ openEventCount }}
            <span class="visually-hidden">open events</span>
          </span>
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  flex: none;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}
.sidebar__brand { display: flex; align-items: center; gap: 12px; }
.sidebar__title { font-weight: 700; font-size: 16px; color: var(--color-text-strong); line-height: 1.2; }
.sidebar__subtitle { font-size: 12px; color: var(--color-text-muted); }
.sidebar__scope-label {
  display: block; font-size: 12px; font-weight: 700;
  color: var(--color-text-muted); margin-bottom: 6px;
}
.sidebar__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.sidebar__link {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-control);
  color: var(--color-text-body);
  text-decoration: none;
  font-weight: 600;
  position: relative;
  min-height: 44px;
}
.sidebar__link:hover { background: var(--color-surface-sunken); text-decoration: none; }
.sidebar__link--active { background: var(--color-surface-sunken); color: var(--color-text-strong); }
/* Orange is an accent: the active indicator, not a flood of colour. */
.sidebar__link--active::before {
  content: ''; position: absolute; left: 0; top: 8px; bottom: 8px;
  width: 3px; border-radius: 3px; background: var(--color-brand);
}
.sidebar__badge {
  margin-left: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  color: var(--color-text-body);
  border-radius: var(--radius-pill);
  font-size: 11px; font-weight: 700;
  padding: 1px 8px;
}
@media (max-width: 860px) {
  .sidebar { width: 100%; border-right: none; border-bottom: 1px solid var(--color-border); }
  .sidebar__list { flex-direction: row; flex-wrap: wrap; }
}
</style>
