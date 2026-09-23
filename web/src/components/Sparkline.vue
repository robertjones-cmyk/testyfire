<script setup lang="ts">
/**
 * Small trend line with an accessible equivalent.
 *
 * The SVG itself is hidden from assistive tech; the same data is available as
 * a real <table> that any user can toggle open. That satisfies "bounding boxes
 * and sparklines have the same info in text".
 */
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    labels?: string[]
    label: string
    unit?: string
    width?: number
    height?: number
    threshold?: number
  }>(),
  { width: 140, height: 36, unit: '' },
)

const showTable = ref(false)
const tableId = `sparkline-table-${Math.random().toString(36).slice(2, 9)}`

const points = computed(() => {
  if (props.values.length < 2) return ''
  const min = Math.min(...props.values)
  const max = Math.max(...props.values)
  const span = max - min || 1
  return props.values
    .map((value, index) => {
      const x = (index / (props.values.length - 1)) * props.width
      const y = props.height - ((value - min) / span) * (props.height - 4) - 2
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const latest = computed(() => props.values.at(-1))
const summary = computed(() => {
  if (!props.values.length) return `${props.label}: no readings`
  const min = Math.min(...props.values).toFixed(1)
  const max = Math.max(...props.values).toFixed(1)
  return `${props.label}: latest ${latest.value?.toFixed(1)}${props.unit}, range ${min}–${max}${props.unit} over ${props.values.length} readings`
})
</script>

<template>
  <div class="sparkline">
    <div class="sparkline__head">
      <span class="sparkline__label">{{ label }}</span>
      <span class="sparkline__value">{{ latest?.toFixed(1) ?? '—' }}{{ unit }}</span>
    </div>

    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      aria-hidden="true"
      focusable="false"
      class="sparkline__svg"
    >
      <polyline v-if="points" :points="points" fill="none" stroke="currentColor" stroke-width="1.75"
        stroke-linejoin="round" stroke-linecap="round" />
    </svg>

    <!-- The text equivalent, always present for screen readers. -->
    <p class="visually-hidden">{{ summary }}</p>

    <button
      type="button"
      class="sparkline__toggle"
      :aria-expanded="showTable"
      :aria-controls="tableId"
      @click="showTable = !showTable"
    >
      {{ showTable ? 'Hide readings' : 'Show readings' }}
    </button>

    <table v-show="showTable" :id="tableId" class="sparkline__table">
      <caption class="visually-hidden">{{ label }} readings, oldest first</caption>
      <thead>
        <tr><th scope="col">Time</th><th scope="col">{{ label }}{{ unit ? ` (${unit})` : '' }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(value, index) in values" :key="index">
          <td>{{ labels?.[index] ?? `#${index + 1}` }}</td>
          <td>{{ value.toFixed(1) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.sparkline { color: var(--color-text-link); }
.sparkline__head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.sparkline__label { font-size: 12px; color: var(--color-text-muted); font-weight: 600; }
.sparkline__value { font-size: 15px; font-weight: 700; color: var(--color-text-strong); }
.sparkline__svg { display: block; width: 100%; height: auto; }
.sparkline__toggle {
  background: none; border: none; padding: 2px 0;
  color: var(--color-text-link); font: inherit; font-size: 12px; font-weight: 600;
  cursor: pointer; text-decoration: underline;
}
.sparkline__table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }
.sparkline__table th, .sparkline__table td {
  text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--color-divider);
  color: var(--color-text-body);
}
.sparkline__table th { color: var(--color-text-strong); }
</style>
