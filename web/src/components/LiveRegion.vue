<script setup lang="ts">
/**
 * Screen-reader announcements for new events.
 *
 * `polite` for Possible smoke / Warning, `assertive` only for Verified /
 * Critical. Frame refreshes are never announced. The message is cleared after
 * a moment so an identical next message is still spoken.
 */
import { ref, watch } from 'vue'

const props = defineProps<{ message: string; politeness: 'polite' | 'assertive' }>()
const emit = defineEmits<{ (event: 'consumed'): void }>()

const politeText = ref('')
const assertiveText = ref('')

watch(
  () => props.message,
  (message) => {
    if (!message) return
    if (props.politeness === 'assertive') {
      assertiveText.value = message
    } else {
      politeText.value = message
    }
    window.setTimeout(() => {
      politeText.value = ''
      assertiveText.value = ''
      emit('consumed')
    }, 4000)
  },
)
</script>

<template>
  <div>
    <div class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">{{ politeText }}</div>
    <div class="visually-hidden" role="alert" aria-live="assertive" aria-atomic="true">{{ assertiveText }}</div>
  </div>
</template>
