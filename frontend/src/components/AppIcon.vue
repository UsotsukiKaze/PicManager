<script setup lang="ts">
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  home: 'm3 10 9-7 9 7M5 9v11h5v-6h4v6h5V9',
  gallery: 'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm-2 13 5-5 4 4 3-3 6 6M15 7h.01',
  emoji: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM8 9h.01M16 9h.01M8 14c2 3 6 3 8 0',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4',
  settings: 'M4 7h16M4 17h16M8 4v6m8 4v6',
  groups: 'M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z',
  character: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2',
  tags: 'M20 13 11 22 2 13V3h10l9 9a1 1 0 0 1-1 1ZM7 8h.01',
  refresh: 'M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M18 18A8 8 0 0 1 4 12',
  search: 'M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6',
  edit: 'm16 3 5 5-12 12-6 1 1-6L16 3Zm-3 3 5 5',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  left: 'm14 6-6 6 6 6', right: 'm10 6 6 6-6 6',
  close: 'm6 6 12 12M6 18 18 6',
  collapse: 'M8 5 1 12l7 7M17 5l-7 7 7 7',
  expand: 'm7 5 7 7-7 7M16 5l7 7-7 7',
  logout: 'M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4M14 8l5 4-5 4M8 12h11',
  download: 'M12 3v12m-5-5 5 5 5-5M4 17v3h16v-3',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  check: 'm5 12 4 4L19 6',
};
</script>
<template><svg class="app-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.gallery"/></svg></template>
