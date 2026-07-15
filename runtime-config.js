(function () {
  const defaults = {
    mode: 'local',
    apiBase: '/api',
    allowLocalFallback: false
  };
  window.DONGBO_CONFIG = Object.assign(defaults, window.DONGBO_CONFIG || {});
})();
