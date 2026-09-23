<script setup lang="ts">
/** Cameras screen — a card grid grouped by feed, with feed badge and health dot. */
import { computed } from 'vue'
import { NEmpty } from 'naive-ui'
import CameraDrawer from '@/components/CameraDrawer.vue'
import HealthDot from '@/components/HealthDot.vue'
import TorchIcon from '@/components/TorchIcon.vue'
import { ref } from 'vue'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
const openCameraKey = ref<string | null>(null)

/**
 * Groups include feeds that returned NO cameras.
 *
 * Without this, a feed that is failing outright simply vanishes from this
 * screen, which is the exact case an operator most needs to see — a broken
 * feed looks identical to a feed nobody configured.
 */
const groups = computed(() => {
  const byFeed = live.camerasByFeed
  const feedIds = new Set([...Object.keys(byFeed), ...Object.keys(live.feeds)])
  return [...feedIds]
    .map((feedId) => ({
      feedId,
      cameras: byFeed[feedId] ?? [],
      health: live.feeds[feedId] ?? null,
    }))
    // A disabled feed with no cameras is not news; a failing one is.
    .filter((group) => group.cameras.length > 0 || group.health?.enabled)
    .sort((a, b) => a.feedId.localeCompare(b.feedId))
})

function frameTime(ts?: string | null) {
  return ts ? new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : 'never'
}
</script>

<template>
  <div class="stack">
    <NEmpty v-if="!groups.length" description="No cameras yet. Check Settings › Feeds for feed errors." />

    <section v-for="group in groups" :key="group.feedId" class="card" :aria-labelledby="`feed-${group.feedId}`">
      <header class="feed-head">
        <h2 :id="`feed-${group.feedId}`" class="feed-head__title">
          <span class="feed-badge">{{ group.health?.type ?? 'feed' }}</span>
          {{ group.feedId }}
        </h2>
        <HealthDot :ok="group.health ? group.health.reachable : null" />
        <span class="feed-head__meta">
          {{ group.cameras.length }} camera(s) · last success {{ frameTime(group.health?.last_success) }}
          <template v-if="group.health?.error_count"> · {{ group.health.error_count }} error(s)</template>
        </span>
      </header>

      <p v-if="group.health?.last_error" class="feed-error" role="status">
        <TorchIcon name="alert-triangle" :size="14" />
        {{ group.health.last_error }}
      </p>

      <p v-if="!group.cameras.length" class="feed-empty">
        This feed returned no cameras. Check the error above, then run
        <code>python -m feeds test {{ group.feedId }}</code> to diagnose it.
      </p>

      <ul v-else class="grid">
        <li v-for="camera in group.cameras" :key="camera.key">
          <button type="button" class="camera-card" @click="openCameraKey = camera.key">
            <span class="camera-card__thumb">
              <img
                v-if="camera.latest_frame"
                :src="`/api/frames/${camera.latest_frame.id}/image`"
                :alt="`Latest frame from ${camera.name}, ${frameTime(camera.latest_frame.ts)}`"
              />
              <span v-else class="camera-card__empty">No frame yet</span>
            </span>
            <span class="camera-card__body">
              <span class="camera-card__name">
                <TorchIcon name="camera-01" :size="15" />
                {{ camera.name }}
              </span>
              <span class="camera-card__meta">
                Last frame {{ frameTime(camera.latest_frame?.ts) }}
                <template v-if="camera.latest_frame?.score != null">
                  · score {{ camera.latest_frame.score.toFixed(2) }}
                </template>
              </span>
              <span class="camera-card__meta">
                View changes today: <strong>{{ camera.view_changes_today }}</strong>
                <template v-if="camera.is_ptz"> · PTZ</template>
              </span>
              <span v-if="camera.latest_frame?.view_changed" class="camera-card__flag">
                <TorchIcon name="alert-triangle" :size="13" /> View changed
              </span>
            </span>
          </button>
        </li>
      </ul>
    </section>

    <CameraDrawer :camera-key="openCameraKey" @close="openCameraKey = null" />
  </div>
</template>

<style scoped>
.feed-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }
.feed-head__title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 16px; }
.feed-head__meta { font-size: 12px; color: var(--color-text-muted); font-weight: 600; }
.feed-badge {
  background: var(--color-surface-sunken); border: 1px solid var(--color-border-strong);
  color: var(--color-text-body); border-radius: var(--radius-tag);
  font-size: 11px; font-weight: 700; padding: 2px 8px; text-transform: uppercase;
}
.feed-empty {
  font-size: 13px; color: var(--color-text-muted); margin: 12px 0 0;
}
.feed-error {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--color-warning-text); font-weight: 600;
  background: var(--color-surface-sunken); border-radius: var(--radius-control);
  padding: 8px 10px; margin: 8px 0 0;
}
.grid {
  list-style: none; margin: 16px 0 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px;
}
.camera-card {
  width: 100%; text-align: left; cursor: pointer; font: inherit;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-card); overflow: hidden; padding: 0;
  display: flex; flex-direction: column; color: var(--color-text-body);
}
.camera-card:hover { border-color: var(--color-border-strong); }
.camera-card__thumb {
  display: block; aspect-ratio: 16 / 9; background: var(--color-surface-sunken);
  display: grid; place-items: center; overflow: hidden;
}
.camera-card__thumb img { width: 100%; height: 100%; object-fit: cover; }
.camera-card__empty { font-size: 12px; color: var(--color-text-muted); }
.camera-card__body { padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.camera-card__name {
  display: flex; align-items: center; gap: 6px;
  font-weight: 700; color: var(--color-text-strong); font-size: 13px;
}
.camera-card__meta { font-size: 12px; color: var(--color-text-muted); }
.camera-card__flag {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; font-weight: 700; color: var(--color-warning-text);
}
</style>
