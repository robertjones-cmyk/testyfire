<script setup lang="ts">
/**
 * The Torch flame mark on an orange rounded-square tile.
 * TODO: replace this placeholder path with the real Torch asset when supplied.
 */
withDefaults(defineProps<{ size?: number }>(), { size: 48 })
</script>

<template>
  <span class="logo-tile" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size * 0.58" :height="size * 0.58" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 2c2.2 2.8 3.4 5.1 3.4 6.9 0 1.4-.7 2.4-1.7 2.9.4-1.4-.2-2.7-1.3-3.8-.5 2-1.6 2.9-2.7 4.2-1 1.2-1.5 2.4-1.5 3.7 0 2.7 2.2 4.8 5 4.8s5-2.2 5-5.1C18.2 11.5 15.3 7.7 12 2Z"
        fill="currentColor"
      />
    </svg>
  </span>
</template>
