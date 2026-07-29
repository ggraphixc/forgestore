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

  // ─── API Helper ──────────────────────────────────────────────
  async function apiGet(path) {
    try {
      const resp = await fetch(path, { credentials: 'include' });
      if (!resp.ok) return null;
      return await resp.json();
    } catch { return null; }
  }

  // ─── 1. App Icon ──────────────────────────────────────────────
  async function getAppIcon() {
    return await apiGet('/api/app/icon');
  }

  // ─── 2. App Config (name, brand mark) ─────────────────────────
  async function getAppConfig() {
    return await apiGet('/api/app/config');
  }

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

  // ─── 4. Biometric Login (Face ID / Fingerprint) ────────────────
  async function biometricCheck() {
    if (!isCapacitor()) return { available: false, reason: 'not_native' };
    try {
      const { Biometric } = window.Capacitor.Plugins;
      const available = await Biometric.isAvailable();
      return available;
    } catch { return { available: false, reason: 'plugin_missing' }; }
  }

  async function biometricAuthenticate() {
    if (!isCapacitor()) return { success: false, reason: 'not_native' };
    try {
      const config = await apiGet('/api/app/config');
      const appName = (config && config.app_name) || 'the app';
      const { Biometric } = window.Capacitor.Plugins;
      const result = await Biometric.authenticate({
        reason: `Authenticate to access your ${appName} account`,
        title: 'Biometric Login',
        cancelTitle: 'Use Password',
      });
      return { success: result.authenticated, reason: result.authenticated ? 'success' : 'user_cancel' };
    } catch (e) {
      return { success: false, reason: e.message || 'auth_failed' };
    }
  }

  async function getBiometricSettings() {
    return await apiGet('/api/app/biometric');
  }

  // ─── 5. Offline-first Data Sync ────────────────────────────────
  const SYNC_CACHE_KEY = 'forgestore-sync-data';
  let _syncStatus = { syncing: false, lastSync: null, error: null };

  async function syncOfflineData() {
    _syncStatus = { syncing: true, lastSync: _syncStatus.lastSync, error: null };
    try {
      const data = await apiGet('/api/app/sync');
      if (data) {
        // Cache sync data in localStorage for offline access
        try {
          localStorage.setItem(SYNC_CACHE_KEY, JSON.stringify(data));
        } catch {}
        _syncStatus = { syncing: false, lastSync: data.synced_at, error: null };
        return { success: true, data };
      }
      _syncStatus = { syncing: false, lastSync: _syncStatus.lastSync, error: 'no_data' };
      return { success: false, data: null };
    } catch (e) {
      _syncStatus = { syncing: false, lastSync: _syncStatus.lastSync, error: e.message || 'network_error' };
      return { success: false, data: null };
    }
  }

  function getCachedSyncData() {
    try {
      const raw = localStorage.getItem(SYNC_CACHE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }

  function getSyncStatus() {
    return { ..._syncStatus };
  }

  // ─── 6. In-App Review Prompt ──────────────────────────────────
  const REVIEW_ORDER_THRESHOLD = 3;
  const REVIEW_STORAGE_KEY = 'forgestore-review-prompted';

  async function requestReview() {
    if (!isCapacitor()) return { presented: false, reason: 'not_native' };
    try {
      const { InAppReview } = window.Capacitor.Plugins;
      const result = await InAppReview.requestReview();
      return { presented: true, result };
    } catch { return { presented: false, reason: 'plugin_missing' }; }
  }

  function shouldPromptReview(deliveredOrderCount) {
    try {
      const prompted = JSON.parse(localStorage.getItem(REVIEW_STORAGE_KEY) || '{}');
      if (prompted.prompted) return false;
    } catch {}
    return deliveredOrderCount >= REVIEW_ORDER_THRESHOLD;
  }

  function markReviewPrompted() {
    try {
      localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify({ prompted: true, at: new Date().toISOString() }));
    } catch {}
  }

  async function checkAndPromptReview() {
    const config = await apiGet('/api/app/config');
    if (!config) return;
    const syncData = getCachedSyncData();
    if (!syncData || !syncData.recent_orders) return;
    const deliveredCount = syncData.recent_orders.filter(o => o.status === 'DELIVERED').length;
    if (shouldPromptReview(deliveredCount)) {
      const result = await requestReview();
      if (result.presented) markReviewPrompted();
      return result;
    }
    return { presented: false, reason: 'threshold_not_met' };
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
      getIcon: getAppIcon,
      getConfig: getAppConfig,
    },
    device: {
      getInfo: getDeviceInfo,
    },
    biometric: {
      check: biometricCheck,
      authenticate: biometricAuthenticate,
      getSettings: getBiometricSettings,
    },
    sync: {
      syncData: syncOfflineData,
      getCachedData: getCachedSyncData,
      getStatus: getSyncStatus,
    },
    review: {
      requestReview,
      checkAndPrompt: checkAndPromptReview,
      shouldPrompt: shouldPromptReview,
      markPrompted: markReviewPrompted,
    },
  };

  // Auto-request push permission on app start
  if (isCapacitor()) {
    document.addEventListener('DOMContentLoaded', async () => {
      const granted = await requestPushPermission();
      if (granted) {
        await registerForPushNotifications();
      }
      // Auto-sync data on app start
      await syncOfflineData();
    });
  }

  console.log(`ForgeStore Bridge: ${platform || 'browser'} mode`);
})();
