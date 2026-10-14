import { createApp } from 'vue';
import { VueQueryPlugin } from '@tanstack/vue-query';
import App from './App.vue';
import { router } from './router';
import { pinia, queryClient } from './state/client';
import './styles/app.css';
import { useAppearance } from './state/appearance';

window.__PICMANAGER_MODERN__ = true;
useAppearance(pinia);
createApp(App).use(pinia).use(VueQueryPlugin, { queryClient }).use(router).mount('#app');
