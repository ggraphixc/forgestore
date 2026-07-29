const { CapacitorConfig } = require('@capacitor/cli');

// Hybrid app: loads from your deployed server (Render, etc.)
// The native shell wraps your web app and adds native features.
const WEB_URL = process.env.CAPACITOR_WEB_URL || 'https://forgestore1.onrender.com';

const config = {
  appId: 'com.forgestore.app',
  appName: 'ForgeStore',
  webDir: 'capacitor-web',
  server: {
    androidScheme: 'https',
    url: WEB_URL,
    cleartext: false,
    allowNavigation: [new URL(WEB_URL).hostname],
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      backgroundColor: '#d97706',
      androidScaleType: 'CENTER_CROP',
      showSpinner: true,
      spinnerColor: '#ffffff',
      splashFullScreen: true,
      splashImmersive: true,
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#d97706',
      overlaysWebView: true,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    App: {},
  },
  ios: {
    scheme: 'ForgeStore',
    contentInset: 'automatic',
    backgroundColor: '#faf9f6',
    preferredContentMode: 'mobile',
  },
  android: {
    backgroundColor: '#faf9f6',
    allowMixedContent: true,
    captureInput: true,
    webContentsDebuggingEnabled: false,
  },
};

module.exports = config;
