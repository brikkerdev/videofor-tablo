const { createApp, ref, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

createApp({
  setup() {
    const mini    = ref(false);
    const devOpen = ref(true);
    const repOpen = ref(false);

    const BASE = window.location.origin;

    const topNav = [
      { icon:'vertical_split',   label:'Панель наблюдения',        href: BASE + '/monitoring' },
      { icon:'event',            label:'Журнал событий',           href: BASE + '/events' },
      { icon:'inventory_2',      label:'Архив',                    href: BASE + '/archive' },
      { icon:'display_settings', label:'Конструктор',              href: BASE + '/builder/configs' },
    ];
    const devNav = [
      { icon:'video_call',  label:'Камеры',                      href: BASE + '/cameras' },
      { icon:'speaker',     label:'Громкоговорители',            href: BASE + '/loudspeakers' },
      { icon:'devices',     label:'Исполнительные устройства',   href: BASE + '/executive-devices' },
      { icon:'place',       label:'Локации',                     href: BASE + '/locations' },
      { icon:'monitor',     label:'Информационные табло',        href: '#', active: true },
    ];
    const repNav = [
      { icon:'terminal',       label:'Журнал действий',    href: BASE + '/activity-log' },
      { icon:'terminal',       label:'Журнал изменений',   href: BASE + '/changes-log' },
      { icon:'switch_account', label:'Журнал авторизаций', href: BASE + '/login-attempt' },
      { icon:'event_note',     label:'Отчет по событиям',  href: BASE + '/events-report' },
    ];
    const bottomNav = [
      { icon:'domain',              label:'Подразделения', href: BASE + '/companies' },
      { icon:'person',              label:'Пользователи',  href: BASE + '/users' },
      { icon:'domain_verification', label:'Лицензии',      href: BASE + '/license' },
      { icon:'lan',                 label:'Диагностика',   href: BASE + '/diagnostics' },
      { icon:'code',                label:'О системе',     href: BASE + '/version' },
    ];

    const tab       = ref('overview');
    const cfg       = ref(null);
    const stateData = ref(null);
    const status    = ref(null);
    const saving    = ref(false);
    const pushing   = ref(false);
    const clearing  = ref(false);
    const adjustStep = ref(10);
    const cvs        = ref(null);

    const connDot = computed(() => {
      if (!status.value) return 'dot-grey';
      if (!status.value.reachable) return 'dot-err';
      if (!status.value.connected) return 'dot-warn';
      return 'dot-ok';
    });
    const connLabel = computed(() => {
      if (!status.value) return 'Проверка...';
      if (!status.value.reachable) return 'Нет связи со шлюзом';
      if (!status.value.connected) return 'Шлюз доступен, матрица не подключена';
      return 'Подключено';
    });
    const statusDetail = computed(() => status.value?.url || '');
    const lastPushLine = computed(() => {
      const lp = status.value?.last_push;
      if (!lp?.at) return '';
      return lp.ok
        ? `Последняя доставка: OK в ${lp.at}`
        : `Последняя доставка: ОШИБКА в ${lp.at} — ${lp.error}`;
    });
    const deviceLabel = computed(() => {
      const d = cfg.value?.device;
      return d ? `${d.width} × ${d.height} px` : '256 × 96 px';
    });

    const linesWithMeta = computed(() => {
      if (!cfg.value) return [];
      const byKey = {};
      (cfg.value.indicators || []).forEach(ind => { byKey[ind.key] = ind; });
      return (cfg.value.board.lines || []).map(ln => ({
        ...ln,
        display_name: byKey[ln.key]?.display_name || ln.key,
      }));
    });

    const loadConfig = async () => {
      try {
        const r = await fetch('/api/display/config');
        cfg.value = await r.json();
      } catch (e) { toast('err', 'Ошибка загрузки конфига: ' + e.message); }
    };

    const loadState = async () => {
      try {
        const r = await fetch('/api/state');
        stateData.value = await r.json();
      } catch { }
    };

    const loadStatus = async () => {
      try {
        const r = await fetch('/api/tablo/status');
        status.value = await r.json();
      } catch { }
    };

    const loadPreview = async () => {
      try {
        const r = await fetch('/api/display/preview');
        const p = await r.json();
        await nextTick();
        drawCanvas(p);
      } catch (e) { toast('err', 'Ошибка превью: ' + e.message); }
    };

    const save = async () => {
      if (!cfg.value) return;
      saving.value = true;
      try {
        const r = await fetch('/api/display/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cfg.value.board),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const data = await r.json();
        cfg.value.board = data.board;
        toast('ok', 'Настройки сохранены');
        if (tab.value === 'overview') await loadPreview();
      } catch (e) { toast('err', 'Ошибка сохранения: ' + e.message); }
      finally { saving.value = false; }
    };

    const pushNow = async () => {
      pushing.value = true;
      try {
        const r = await fetch('/api/display/push', { method: 'POST' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast('ok', 'Отправлено на табло');
        await loadStatus();
      } catch (e) { toast('err', 'Ошибка отправки: ' + e.message); }
      finally { pushing.value = false; }
    };

    const saveAndPush = async () => {
      await save();
      await pushNow();
    };

    const clearBoard = async () => {
      clearing.value = true;
      try {
        const r = await fetch('/api/display/clear', { method: 'POST' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast('ok', 'Экран очищен');
      } catch (e) { toast('err', 'Ошибка очистки: ' + e.message); }
      finally { clearing.value = false; }
    };

    const reconnect = async () => {
      try {
        await fetch('/api/tablo/reconnect', { method: 'POST' });
        await loadStatus();
        toast('ok', 'Команда переподключения отправлена');
      } catch (e) { toast('err', 'Ошибка переподключения: ' + e.message); }
    };

    const argbToHex = (argb) => {
      const m = /^0x[0-9a-f]{2}([0-9a-f]{6})$/i.exec(argb || '');
      return m ? '#' + m[1] : '#ffffff';
    };
    const hexToArgb = (hex, current) => {
      const am = /^0x([0-9a-f]{2})/i.exec(current || '');
      const alpha = am ? am[1] : 'ff';
      return '0x' + alpha + hex.replace('#', '').toLowerCase();
    };

    const adjust = async (key, delta) => {
      try {
        const r = await fetch('/api/state/adjust', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key, delta }),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const data = await r.json();
        if (stateData.value) {
          const ind = stateData.value.indicators.find(i => i.key === key);
          if (ind) ind.value = data.value;
        }
      } catch (e) { toast('err', 'Ошибка корректировки: ' + e.message); }
    };

    const setBrightness = async (val) => {
      try {
        await fetch('/api/tablo/brightness', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: val }),
        });
      } catch { }
    };

    const setThreshold = (i, field, val) => {
      const ln = cfg.value.board.lines[i];
      if (!ln.threshold) ln.threshold = { value: null, op: '>=', color: '0xffff0000', target: 'line' };
      if (field === 'value') {
        ln.threshold.value = val === '' ? null : Number(val);
      } else {
        ln.threshold[field] = val;
      }
      if (ln.threshold.value === null) ln.threshold = null;
    };

    function argbToCss(s) {
      const m = /^0x[0-9a-fA-F]{2}([0-9a-fA-F]{6})$/.exec(s || '');
      return m ? '#' + m[1] : '#ffffff';
    }

    function drawCanvas(p) {
      const c = cvs.value;
      if (!c) return;
      const ctx = c.getContext('2d');
      const dev = cfg.value?.device || {};
      const bw = dev.width  || 256;
      const bh = dev.height || 96;

      const nat = document.createElement('canvas');
      nat.width = bw; nat.height = bh;
      const nc = nat.getContext('2d');

      nc.fillStyle = '#080604';
      nc.fillRect(0, 0, bw, bh);

      (p.areas || []).forEach(a => {
        const x = +a.x, y = +a.y, w = +a.w, h = +a.h;
        nc.fillStyle = argbToCss(a.fontcolor);
        nc.font = `${Math.max(4, +a.fontsize)}px ${a.fontname || 'Arial'}`;
        nc.textBaseline = 'middle';
        nc.textAlign = 'center';
        nc.save();
        nc.beginPath(); nc.rect(x, y, w, h); nc.clip();
        nc.fillText(a.msg, x + w / 2, y + h / 2);
        nc.restore();
      });

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(nat, 0, 0, c.width, c.height);

      const sx = c.width / bw, sy = c.height / bh;
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      for (let xi = 0; xi < bw; xi++) ctx.fillRect(Math.round(xi * sx + sx - 1), 0, 1, c.height);
      for (let yi = 0; yi < bh; yi++) ctx.fillRect(0, Math.round(yi * sy + sy - 1), c.width, 1);
    }

    watch(tab, async (val) => {
      if (val === 'overview') {
        await nextTick();
        await loadPreview();
      }
    });

    const toasts = ref([]);
    let _tid = 0;
    const toast = (cls, msg, ms = 3500) => {
      const id = ++_tid;
      const icon = cls === 'ok' ? 'check_circle' : 'error';
      toasts.value.push({ id, cls, icon, msg });
      setTimeout(() => {
        const i = toasts.value.findIndex(t => t.id === id);
        if (i !== -1) toasts.value.splice(i, 1);
      }, ms);
    };

    let t1, t2;
    onMounted(async () => {
      await Promise.all([loadConfig(), loadState(), loadStatus()]);
      await loadPreview();
      t1 = setInterval(loadState,  10_000);
      t2 = setInterval(loadStatus, 10_000);
    });
    onUnmounted(() => { clearInterval(t1); clearInterval(t2); });

    return {
      mini, devOpen, repOpen,
      topNav, devNav, repNav, bottomNav,
      tab, cfg, stateData, status,
      saving, pushing, clearing, adjustStep, cvs,
      connDot, connLabel, statusDetail, lastPushLine, deviceLabel,
      linesWithMeta,
      loadConfig, loadState, loadStatus, loadPreview,
      save, pushNow, saveAndPush, clearBoard, reconnect,
      adjust, setBrightness,
      argbToHex, hexToArgb,
      setThreshold,
      toasts,
    };
  },
}).mount('#q-app');
