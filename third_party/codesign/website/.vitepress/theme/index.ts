import DefaultTheme from 'vitepress/theme';
import DemoVideo from './DemoVideo.vue';
import Layout from './Layout.vue';
import SmartDownload from './SmartDownload.vue';
import './style.css';

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }: { app: import('vue').App }) {
    app.component('SmartDownload', SmartDownload);
    app.component('DemoVideo', DemoVideo);
  },
};
