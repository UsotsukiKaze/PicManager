import { createApp } from 'vue';
import { VueQueryPlugin } from '@tanstack/vue-query';
import App from './App.vue';
import { router } from './router';
import { pinia, queryClient } from './state/client';
import './styles/app.css';

window.__PICMANAGER_MODERN__ = true;
createApp(App).use(pinia).use(VueQueryPlugin, { queryClient }).use(router).mount('#app');
