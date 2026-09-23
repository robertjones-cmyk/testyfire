<script setup lang="ts">
/**
 * An authenticated camera frame with an optional detection box.
 *
 * Alt text is descriptive, e.g. "Camera I-40 Rio Grande, 5:42 PM, possible
 * smoke detected in upper left, score 0.72" — and the same information is
 * repeated as visible text under the image, so the box is not the only carrier.
 */
import { computed } from 'vue'

const props = defineProps<{
  frameId: number | null
  cameraName: string
  capturedAt?: string | null
  score?: number | null
  bbox?: number[] | null
  viewChanged?: boolean | number
}>()

const src = computed(() => (props.frameId ? `/api/frames/${props.frameId}/image` : ''))

const timeText = computed(() =>
  props.capturedAt
    ? new Date(props.capturedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : 'time unknown',
)

/** Plain-language position of the detection box, for the alt text. */
const wherePhrase = computed(() => {
  if (!props.bbox || props.bbox.length < 4) return ''
  const [x, y, w, h] = props.bbox
  const centreX = x + w / 2
  const centreY = y + h / 2
  const horizontal = centreX < 0.34 ? 'left' : centreX > 0.66 ? 'right' : 'centre'
  const vertical = centreY < 0.34 ? 'upper' : centreY > 0.66 ? 'lower' : 'middle'
  return `${vertical} ${horizontal}`
})

const altText = computed(() => {
  const parts = [`Camera ${props.cameraName}`, timeText.value]
  if (props.viewChanged) {
    parts.push('camera view changed, no smoke assessment for this frame')
  } else if (props.score != null && props.bbox) {
    parts.push(`possible smoke detected in ${wherePhrase.value}, score ${props.score.toFixed(2)}`)
  } else if (props.score != null) {
    parts.push(`smoke score ${props.score.toFixed(2)}, no region marked`)
  } else {
    parts.push('no smoke assessment')
  }
  return parts.join(', ')
})

const boxStyle = computed(() => {
  if (!props.bbox || props.bbox.length < 4) return null
  const [x, y, w, h] = props.bbox
  return {
    left: `${x * 100}%`,
    top: `${y * 100}%`,
    width: `${w * 100}%`,
    height: `${h * 100}%`,
  }
})
</script>

<template>
  <figure class="frame">
    <div class="frame__media">
      <img v-if="src" :src="src" :alt="altText" class="frame__img" />
      <div v-else class="frame__empty">No frame captured yet</div>
      <div v-if="boxStyle && !viewChanged" class="frame__box" :style="boxStyle" aria-hidden="true" />
    </div>
    <figcaption class="frame__caption">{{ altText }}</figcaption>
  </figure>
</template>

<style scoped>
.frame { margin: 0; }
.frame__media {
  position: relative; border-radius: var(--radius-control); overflow: hidden;
  border: 1px solid var(--color-border); background: var(--color-surface-sunken);
}
.frame__img { display: block; width: 100%; height: auto; }
.frame__empty { padding: 40px 16px; text-align: center; color: var(--color-text-muted); font-size: 13px; }
.frame__box {
  position: absolute;
  border: 2px solid var(--color-brand);
  border-radius: 4px;
  box-shadow: 0 0 0 2px oklch(0% 0 0 / 35%);
}
.frame__caption { margin-top: 8px; font-size: 12px; color: var(--color-text-muted); }
</style>
