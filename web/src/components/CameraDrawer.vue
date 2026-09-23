<script setup lang="ts">
/** Camera detail: latest snapshot, last 10 frames, smoke score, view-change status. */
import { computed, ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NSpin } from 'naive-ui'
import FrameImage from './FrameImage.vue'
import TorchIcon from './TorchIcon.vue'
import { api } from '@/api'

const props = defineProps<{ cameraKey: string | null }>()
const emit = defineEmits<{ (event: 'close'): void }>()

interface FrameRow {
  id: number; ts: string; score: number | null; view_changed: number
  bbox: string | null; inference_ms: number | null; cost_usd: number | null
}
interface CameraDetail {
  key: string; name: string; feed_id: string; lat: number | null; lon: number | null
  heading: number | null; fov: number | null; is_ptz: number; heading_known: boolean
  view_changes_today: number
  latest_frame: FrameRow | null
  recent_frames: FrameRow[]
}

const detail = ref<CameraDetail | null>(null)
const loading = ref(false)
const selectedFrameId = ref<number | null>(null)

const show = computed(() => props.cameraKey !== null)

watch(
  () => props.cameraKey,
  async (key) => {
    detail.value = null
    selectedFrameId.value = null
    if (!key) return
    loading.value = true
    try {
      detail.value = await api.get<CameraDetail>(`/api/cameras/${encodeURIComponent(key)}`)
      selectedFrameId.value = detail.value.latest_frame?.id ?? null
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const selectedFrame = computed<FrameRow | null>(() => {
  if (!detail.value) return null
  return (
    detail.value.recent_frames.find((frame) => frame.id === selectedFrameId.value) ??
    detail.value.latest_frame
  )
})

function parseBbox(raw: string | null): number[] | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

function timeLabel(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}
</script>

<template>
  <NDrawer
    :show="show"
    :width="460"
    placement="right"
    :trap-focus="true"
    :block-scroll="true"
    :auto-focus="true"
    @update:show="(value: boolean) => !value && emit('close')"
  >
    <NDrawerContent :title="detail?.name ?? 'Camera'" closable>
      <NSpin :show="loading">
        <div v-if="detail" class="stack">
          <FrameImage
            :frame-id="selectedFrame?.id ?? null"
            :camera-name="detail.name"
            :captured-at="selectedFrame?.ts"
            :score="selectedFrame?.score ?? null"
            :bbox="parseBbox(selectedFrame?.bbox ?? null)"
            :view-changed="selectedFrame?.view_changed"
          />

          <section aria-labelledby="camera-status-heading">
            <h3 id="camera-status-heading">Status</h3>
            <dl class="facts">
              <div class="facts__row">
                <dt>Smoke score</dt>
                <dd>{{ selectedFrame?.score != null ? selectedFrame.score.toFixed(2) : 'not scored' }}</dd>
              </div>
              <div class="facts__row">
                <dt>View</dt>
                <dd>
                  <span v-if="selectedFrame?.view_changed" class="warn">
                    <TorchIcon name="alert-triangle" :size="14" />
                    View changed — smoke alerts suppressed for this frame
                  </span>
                  <span v-else>Matches reference view</span>
                </dd>
              </div>
              <div class="facts__row">
                <dt>View changes today</dt>
                <dd>{{ detail.view_changes_today }}</dd>
              </div>
              <div class="facts__row">
                <dt>Type</dt>
                <dd>{{ detail.is_ptz ? 'PTZ (operator can move it)' : 'Fixed' }}</dd>
              </div>
              <div class="facts__row">
                <dt>Coverage</dt>
                <dd>
                  <template v-if="detail.heading_known">
                    Heading {{ detail.heading }}°, field of view {{ detail.fov ?? 60 }}° (from config, not surveyed)
                  </template>
                  <template v-else>Heading unknown — shown on the map as a 360° radius</template>
                </dd>
              </div>
              <div class="facts__row">
                <dt>Feed</dt>
                <dd>{{ detail.feed_id }}</dd>
              </div>
            </dl>
          </section>

          <section aria-labelledby="camera-strip-heading">
            <h3 id="camera-strip-heading">Last {{ detail.recent_frames.length }} frames</h3>
            <ul class="strip">
              <li v-for="frame in detail.recent_frames" :key="frame.id">
                <button
                  type="button"
                  class="strip__item"
                  :class="{ 'strip__item--active': frame.id === selectedFrame?.id }"
                  :aria-pressed="frame.id === selectedFrame?.id"
                  @click="selectedFrameId = frame.id"
                >
                  <img :src="`/api/frames/${frame.id}/image`" alt="" class="strip__thumb" />
                  <span class="strip__meta">
                    {{ timeLabel(frame.ts) }}
                    <span v-if="frame.view_changed" class="strip__flag">moved</span>
                    <span v-else-if="frame.score != null">{{ frame.score.toFixed(2) }}</span>
                  </span>
                </button>
              </li>
            </ul>
          </section>
        </div>
      </NSpin>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.facts { margin: 0; }
.facts__row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--color-divider); }
.facts__row dt { flex: 0 0 140px; color: var(--color-text-muted); font-size: 13px; margin: 0; }
.facts__row dd { margin: 0; font-size: 13px; color: var(--color-text-body); }
.warn { display: inline-flex; align-items: center; gap: 6px; color: var(--color-warning-text); font-weight: 700; }
.strip { list-style: none; margin: 0; padding: 0; display: flex; gap: 8px; overflow-x: auto; }
.strip__item {
  border: 1px solid var(--color-border); background: var(--color-surface);
  border-radius: var(--radius-control); padding: 4px; cursor: pointer;
  display: flex; flex-direction: column; gap: 4px; min-width: 96px;
}
.strip__item--active { border-color: var(--color-brand); border-width: 2px; padding: 3px; }
.strip__thumb { width: 88px; height: 50px; object-fit: cover; border-radius: 4px; display: block; }
.strip__meta { font-size: 11px; color: var(--color-text-muted); font-weight: 600; }
.strip__flag { color: var(--color-warning-text); }
</style>
