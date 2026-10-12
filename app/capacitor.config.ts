import type { CapacitorConfig } from '@capacitor/cli';

// LIVE (default): the app opens the GitHub Pages site, so every push to main
// reaches the phones without rebuilding the app - same as the web app today.
// BUNDLED: `LB_BUNDLED=1 npm run sync` packs the files into the app instead
// (works with no signal at start-up, but needs a rebuild for every change).
const bundled = !!process.env.LB_BUNDLED;

const config: CapacitorConfig = {
  appId: 'com.linzee7000.lukezbunz',
  appName: 'Lukez Bunz',
  webDir: 'www',
  ...(bundled ? {} : { server: { url: 'https://linzee7000.github.io/lukez-bunz/' } }),
  android: {
    // Background GPS plugin: stops location updates halting after 5 min in the background.
    useLegacyBridge: true,
  },
};

export default config;
