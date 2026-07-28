// ForgeStore Capacitor Bridge
// Provides native mobile features when running inside Capacitor WebView.
// Falls back gracefully when running in a regular browser.

(function() {
  'use strict';

  const isCapacitor = () => {
    try {
      return window.Capacitor && window.Capacitor.isNativePlatform();
    } catch { return false; }
  };

  const platform = isCapacitor() ? window.Capacitor.getPlatform() : null;

  // ─── Push Notifications ───────────────────────────────────────
  async function requestPushPermission() {
    if (!isCapacitor()) return false;
    const { PushNotifications } = window.Capacitor.Plugins;
    const perm = await PushNotifications.requestPermissions();
    return perm.receive === 'granted';
  }

  async function registerForPushNotifications() {
    if (!isCapacitor()) return;
    const { PushNotifications } = window.Capacitor.Plugins;
    await PushNotifications.register();
  }

  function onPushReceived(callback) {
    if (!isCapacitor()) return;
    const { PushNotifications } = window.Capacitor.Plugins;
    PushNotifications.addListener('pushNotificationReceived', callback);
  }

  function onPushAction(callback) {
    if (!isCapacitor()) return;
    const { PushNotifications } = window.Capacitor.Plugins;
    PushNotifications.addListener('pushNotificationActionPerformed', callback);
  }

  // ─── Status Bar ───────────────────────────────────────────────
  async function setStatusBarStyle(style = 'DARK', color) {
    if (!isCapacitor()) return;
    const { StatusBar } = window.Capacitor.Plugins;
    await StatusBar.setStyle({ style });
    if (color) await StatusBar.setBackgroundColor({ color });
  }

  // ─── Haptics ──────────────────────────────────────────────────
  async function hapticLight() {
    if (!isCapacitor()) return;
    const { Haptics } = window.Capacitor.Plugins;
    await Haptics.impact({ style: 'LIGHT' });
  }

  async function hapticMedium() {
    if (!isCapacitor()) return;
    const { Haptics } = window.Capacitor.Plugins;
    await Haptics.impact({ style: 'MEDIUM' });
  }

  async function hapticNotification(type = 'SUCCESS') {
    if (!isCapacitor()) return;
    const { Haptics } = window.Capacitor.Plugins;
    await Haptics.notification({ type });
  }

  // ─── Keyboard ─────────────────────────────────────────────────
  async function hideKeyboard() {
    if (!isCapacitor()) return;
    const { Keyboard } = window.Capacitor.Plugins;
    await Keyboard.hide();
  }

  // ─── App Lifecycle ────────────────────────────────────────────
  function onAppActive(callback) {
    if (!isCapacitor()) return;
    const { App } = window.Capacitor.Plugins;
    App.addListener('appStateChange', ({ isActive }) => {
      if (isActive) callback();
    });
  }

  function onAppBackButton(callback) {
    if (!isCapacitor()) return;
    const { App } = window.Capacitor.Plugins;
    App.addListener('backButton', callback);
  }

  // ─── Device Info ──────────────────────────────────────────────
  async function getDeviceInfo() {
    if (!isCapacitor()) return { platform: 'web', isNative: false };
    const { Device } = window.Capacitor.Plugins;
    const info = await Device.getInfo();
    return { ...info, isNative: true };
  }

  // ─── Expose globally ──────────────────────────────────────────
  window.ForgeStore = {
    isCapacitor,
    platform,
    push: {
      requestPermission: requestPushPermission,
      register: registerForPushNotifications,
      onReceived: onPushReceived,
      onAction: onPushAction,
    },
    statusBar: {
      setStyle: setStatusBarStyle,
    },
    haptics: {
      light: hapticLight,
      medium: hapticMedium,
      notification: hapticNotification,
    },
    keyboard: {
      hide: hideKeyboard,
    },
    app: {
      onActive: onAppActive,
      onBackButton: onAppBackButton,
    },
    device: {
      getInfo: getDeviceInfo,
    },
  };

  // Auto-request push permission on app start
  if (isCapacitor()) {
    document.addEventListener('DOMContentLoaded', async () => {
      const granted = await requestPushPermission();
      if (granted) {
        await registerForPushNotifications();
      }
    });
  }

  console.log(`ForgeStore Bridge: ${platform || 'browser'} mode`);
})();
