const { createApp, ref, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

createApp({
  setup() {
    const UI_KEY    = 'tablo.editor.ui';
    const DRAFT_KEY = 'tablo.editor.draft';
    const LS = {
      get(key) {
        try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : null; }
        catch { return null; }
      },
      set(key, val) {
        try { localStorage.setItem(key, JSON.stringify(val)); } catch {}
      },
      remove(key) {
        try { localStorage.removeItem(key); } catch {}
      },
    };
    const savedUI = LS.get(UI_KEY) || {};

    /* ── sidebar ── */
    const mini    = ref(savedUI.mini    ?? false);
    const devOpen = ref(savedUI.devOpen ?? true);
    const repOpen = ref(savedUI.repOpen ?? false);

    const BASE = window.location.origin;

    const topNav = [
      { icon:'vertical_split',   label:'Панель наблюдения',        href: BASE + '/monitoring' },
      { icon:'event',             label:'Журнал событий',           href: BASE + '/events' },
      { icon:'inventory_2',       label:'Архив',                    href: BASE + '/archive' },
      { icon:'display_settings',  label:'Конструктор',              href: BASE + '/builder/configs' },
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

    /* ── state ── */
    const tab        = ref(savedUI.tab ?? 'overview');
    const cfg        = ref(null);
    const stateData  = ref(null);
    const status     = ref(null);
    const pushLog       = ref([]);
    const pushLogFilter = ref('');
    const pushLogPage   = ref(1);
    const pushLogPerPage = 20;
    const _TRIGGER_LABELS = {
      event:   'Событие',
      push:    'Вручную',
      config:  'Настройки',
      adjust:  'Коррекция',
      clock:   'Таймер',
      reload:  'Перезагрузка',
      startup: 'Запуск',
    };
    const triggerLabel = (t) => _TRIGGER_LABELS[t] || t || '—';
    const filteredPushLog = computed(() =>
      pushLogFilter.value ? pushLog.value.filter(e => e.trigger === pushLogFilter.value) : pushLog.value
    );
    const pushLogTotalPages = computed(() => Math.max(1, Math.ceil(filteredPushLog.value.length / pushLogPerPage)));
    const pagedPushLog = computed(() => {
      const p = pushLogPage.value;
      return filteredPushLog.value.slice((p - 1) * pushLogPerPage, p * pushLogPerPage);
    });
    const saving     = ref(false);
    const pushing    = ref(false);
    const clearing   = ref(false);
    const adjustStep = ref(savedUI.adjustStep ?? 10);
    const cvs        = ref(null);
    const hasDraft   = ref(false);
    let   baseline   = null;

    const dragIndex     = ref(null);
    const dragOverIndex = ref(null);
    const modalIndex    = ref(null);
    const eventModalOpen = ref(false);
    const catalog        = ref(null);
    const savingEvent    = ref(false);
    const createForm     = ref(null);
    const editForm       = ref(null);
    const bindForm       = ref(null);
    const confirmState   = ref(null);
    const connForm       = ref(null);
    const savingConn     = ref(false);

    /* ── computed: status ── */
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
    const statusDetail  = computed(() => status.value?.url || '');
    const lastPushLine  = computed(() => {
      const lp = status.value?.last_push;
      if (!lp?.at) return '';
      return lp.ok
        ? `Последняя доставка: OK в ${lp.at}`
        : `Последняя доставка: ОШИБКА в ${lp.at} - ${lp.error}`;
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

    const modalLine = computed(() => {
      if (modalIndex.value === null) return {};
      return linesWithMeta.value[modalIndex.value] || {};
    });

    /* ── drag & drop ── */
    const onDragStart = (i, e) => {
      dragIndex.value = i;
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        const card = e.target.closest('.line-card');
        if (card) e.dataTransfer.setDragImage(card, 20, 20);
      }
    };
    const onDragOver = (i) => { dragOverIndex.value = i; };
    const onDragEnd  = () => { dragIndex.value = null; dragOverIndex.value = null; };
    const onDrop = (i) => {
      const from = dragIndex.value;
      dragIndex.value = null;
      dragOverIndex.value = null;
      if (from === null || from === i || !cfg.value) return;
      const lines = cfg.value.board.lines;
      const [moved] = lines.splice(from, 1);
      lines.splice(i, 0, moved);
    };

    /* ── line modal ── */
    const openLineModal  = (i) => { modalIndex.value = i; };
    const closeLineModal = () => { modalIndex.value = null; };

    /* ── confirm dialog ── */
    const askConfirm = (opts) => new Promise((resolve) => {
      confirmState.value = {
        title: opts.title || 'Подтверждение',
        message: opts.message || '',
        confirmLabel: opts.confirmLabel || 'Подтвердить',
        danger: opts.danger !== false,
        resolve,
      };
    });
    const _confirmResolve = (val) => {
      const st = confirmState.value;
      confirmState.value = null;
      if (st) st.resolve(val);
    };
    const confirmYes = () => _confirmResolve(true);
    const confirmNo  = () => _confirmResolve(false);

    /* ── indicator constructor ── */
    const slugify  = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    const opLabel  = (op) => ({ inc: '+', dec: '−', set: '=' }[op] || op);
    const indStatus = (ind) => (ind.enabled && ind.line_enabled) ? 'displayed' : 'hidden';

    const triggersByIndicator = computed(() => {
      const map = {};
      for (const ev of (catalog.value?.events || []))
        for (const m of ev.mappings)
          (map[m.indicator_key] = map[m.indicator_key] || []).push(
            { event_type: ev.event_type, op: m.op, checkpoint: m.checkpoint });
      return map;
    });
    const unmappedRequests = computed(() =>
      (catalog.value?.events || []).filter(e => e.status === 'unhandled'));
    const eventTypeList = computed(() =>
      (catalog.value?.events || []).map(e => e.event_type));

    const loadCatalog = async () => {
      try {
        const r = await fetch('/api/event-catalog');
        catalog.value = await r.json();
      } catch (e) { toast('err', 'Ошибка каталога: ' + e.message); }
    };
    const openEventModal = async () => {
      eventModalOpen.value = true;
      catalog.value = null;
      createForm.value = null;
      bindForm.value = null;
      await loadCatalog();
    };
    const closeEventModal = () => {
      eventModalOpen.value = false;
      createForm.value = null;
      bindForm.value = null;
    };

    const refreshAll = async () => {
      await loadCatalog();
      await loadConfig();
      await loadState();
      if (tab.value === 'overview') await loadPreview();
    };

    const _post = async (url, body) => {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        let msg = 'HTTP ' + r.status;
        try { msg = (await r.json()).message || msg; } catch {}
        throw new Error(msg);
      }
    };

    const openCreate = (ev) => {
      createForm.value = {
        display_name: ev ? ev.event_type : '',
        key: ev ? slugify(ev.event_type) : '',
        kind: 'daily',
        event_type: ev ? ev.event_type : '',
        checkpoint: ev ? (ev.checkpoint || '') : '',
        op: 'inc',
      };
      bindForm.value = null;
      editForm.value = null;
    };
    const submitCreate = async () => {
      const f = createForm.value;
      if (!f) return;
      savingEvent.value = true;
      try {
        const body = { key: f.key, display_name: f.display_name, kind: f.kind };
        if (f.event_type) body.rule = { event_type: f.event_type, checkpoint: f.checkpoint || null, op: f.op };
        await _post('/api/indicators', body);
        toast('ok', 'Показатель создан');
        createForm.value = null;
        await refreshAll();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
      finally { savingEvent.value = false; }
    };

    const openEdit = (ind) => {
      editForm.value = {
        key: ind.key,
        display_name: ind.display_name,
        kind: ind.kind,
        sort_order: ind.sort_order,
        enabled: ind.enabled,
      };
      createForm.value = null;
      bindForm.value = null;
    };
    const submitEdit = async () => {
      const f = editForm.value;
      if (!f || !f.display_name) { toast('err', 'Укажите название'); return; }
      savingEvent.value = true;
      try {
        const r = await fetch('/api/indicators/' + encodeURIComponent(f.key), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            display_name: f.display_name,
            kind: f.kind,
            sort_order: Number(f.sort_order),
            enabled: f.enabled,
          }),
        });
        if (!r.ok) {
          let msg = 'HTTP ' + r.status;
          try { msg = (await r.json()).message || msg; } catch {}
          throw new Error(msg);
        }
        toast('ok', 'Показатель изменён');
        editForm.value = null;
        await refreshAll();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
      finally { savingEvent.value = false; }
    };

    const openTrigger = (ind) => {
      bindForm.value = { indicator_key: ind.key, indicator_locked: true,
                         event_type: '', event_locked: false, checkpoint: '', op: 'inc' };
      createForm.value = null;
      editForm.value = null;
    };
    const openBind = (ev) => {
      bindForm.value = { indicator_key: catalog.value?.indicators[0]?.key || '', indicator_locked: false,
                         event_type: ev.event_type, event_locked: true, checkpoint: ev.checkpoint || '', op: 'inc' };
      createForm.value = null;
      editForm.value = null;
    };
    const submitBind = async () => {
      const f = bindForm.value;
      if (!f || !f.event_type || !f.indicator_key) { toast('err', 'Укажите показатель и тип запроса'); return; }
      savingEvent.value = true;
      try {
        await _post('/api/event-rules', { event_type: f.event_type, checkpoint: f.checkpoint || null,
                                          indicator_key: f.indicator_key, op: f.op });
        toast('ok', 'Запрос привязан');
        bindForm.value = null;
        await refreshAll();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
      finally { savingEvent.value = false; }
    };

    const detachRule = async (event_type, indicator_key) => {
      try {
        const url = '/api/event-rules?event_type=' + encodeURIComponent(event_type) +
                    '&indicator_key=' + encodeURIComponent(indicator_key);
        const r = await fetch(url, { method: 'DELETE' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast('ok', 'Правило отвязано');
        await refreshAll();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
    };

    const deleteIndicator = async (key, name) => {
      const ok = await askConfirm({
        title: 'Удалить показатель',
        message: 'Показатель «' + name + '» будет удалён вместе с его правилами и историей значений. Действие необратимо.',
        confirmLabel: 'Удалить',
        danger: true,
      });
      if (!ok) return;
      try {
        const r = await fetch('/api/indicators/' + encodeURIComponent(key), { method: 'DELETE' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast('ok', 'Показатель удалён');
        await refreshAll();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
    };

    const dismissEvent = async (event_type) => {
      try {
        const r = await fetch('/api/event-catalog/' + encodeURIComponent(event_type), { method: 'DELETE' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        await loadCatalog();
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
    };

    const onKeydown = (e) => {
      if (e.key !== 'Escape') return;
      if (confirmState.value) confirmNo();
      else if (modalIndex.value !== null) closeLineModal();
      else if (eventModalOpen.value) closeEventModal();
    };

    /* ── API ── */
    const loadConfig = async () => {
      try {
        const r = await fetch('/api/display/config');
        cfg.value = await r.json();
        baseline = JSON.stringify(cfg.value.board);
        const draft = LS.get(DRAFT_KEY);
        if (draft && JSON.stringify(draft) !== baseline) {
          cfg.value.board = draft;
          hasDraft.value = true;
          toast('ok', 'Восстановлен черновик несохранённых правок');
        } else {
          LS.remove(DRAFT_KEY);
          hasDraft.value = false;
        }
      } catch (e) { toast('err', 'Ошибка загрузки конфига: ' + e.message); }
    };

    const discardDraft = () => {
      if (!cfg.value || baseline === null) return;
      cfg.value.board = JSON.parse(baseline);
      LS.remove(DRAFT_KEY);
      hasDraft.value = false;
      toast('ok', 'Черновик сброшен');
    };

    const loadState = async () => {
      try {
        const r = await fetch('/api/state');
        stateData.value = await r.json();
      } catch { /* silent */ }
    };

    const loadStatus = async () => {
      try {
        const r = await fetch('/api/tablo/status');
        status.value = await r.json();
      } catch { /* silent */ }
    };

    const loadPushLog = async () => {
      try {
        const r = await fetch('/api/tablo/push-log');
        pushLog.value = await r.json();
      } catch { /* silent */ }
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
        baseline = JSON.stringify(data.board);
        LS.remove(DRAFT_KEY);
        hasDraft.value = false;
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

    const saveAndPush = async () => { await save(); await pushNow(); };

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

    const openConnForm = async () => {
      try {
        const r = await fetch('/api/tablo/connection');
        connForm.value = await r.json();
      } catch (e) { toast('err', 'Ошибка загрузки настроек: ' + e.message); }
    };

    const saveConn = async () => {
      if (!connForm.value) return;
      savingConn.value = true;
      try {
        const r = await fetch('/api/tablo/connection', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(connForm.value),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast('ok', 'Настройки сохранены, переподключение...');
        connForm.value = null;
        setTimeout(() => loadStatus(), 2000);
      } catch (e) { toast('err', 'Ошибка: ' + e.message); }
      finally { savingConn.value = false; }
    };

    /* ── color helpers ── */
    const argbToHex = (argb) => {
      const m = /^0x[0-9a-f]{2}([0-9a-f]{6})$/i.exec(argb || '');
      return m ? '#' + m[1] : '#ffffff';
    };
    const hexToArgb = (hex, current) => {
      const am = /^0x([0-9a-f]{2})/i.exec(current || '');
      const alpha = am ? am[1] : 'ff';
      return '0x' + alpha + hex.replace('#', '').toLowerCase();
    };

    /* ── manual adjust ── */
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
      } catch { /* silent */ }
    };

    /* ── threshold helper ── */
    const setThreshold = (i, field, val) => {
      const ln = cfg.value.board.lines[i];
      if (!ln.threshold) ln.threshold = { value: null, op: '>=', color: '0xffff0000', target: 'line', duration_seconds: 0 };
      if (field === 'value') {
        ln.threshold.value = val === '' ? null : Number(val);
      } else {
        ln.threshold[field] = val;
      }
      if (ln.threshold.value === null) ln.threshold = null;
    };

    /* ── canvas drawing ── */
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
        const align = a.align || 'left';
        let tx;
        if (align === 'right')       { nc.textAlign = 'right';  tx = x + w; }
        else if (align === 'center') { nc.textAlign = 'center'; tx = x + w / 2; }
        else                         { nc.textAlign = 'left';   tx = x; }
        nc.save();
        nc.beginPath(); nc.rect(x, y, w, h); nc.clip();
        nc.fillText(a.msg, tx, y + h / 2);
        nc.restore();
      });

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(nat, 0, 0, c.width, c.height);

      const sx = c.width / bw, sy = c.height / bh;
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      for (let xi = 0; xi < bw; xi++) ctx.fillRect(Math.round(xi * sx + sx - 1), 0, 1, c.height);
      for (let yi = 0; yi < bh; yi++) ctx.fillRect(0, Math.round(yi * sy + sy - 1), c.width, 1);
    }

    /* ── watchers ── */
    watch(tab, async (val) => {
      if (val === 'overview') {
        await nextTick();
        await loadPreview();
      }
      if (val === 'connection') {
        await loadPushLog();
      }
    });

    watch(pushLogFilter, () => { pushLogPage.value = 1; });

    watch([mini, devOpen, repOpen, tab, adjustStep], () => {
      LS.set(UI_KEY, {
        mini: mini.value,
        devOpen: devOpen.value,
        repOpen: repOpen.value,
        tab: tab.value,
        adjustStep: adjustStep.value,
      });
    });

    watch(() => cfg.value && cfg.value.board, (board) => {
      if (!board || baseline === null) return;
      if (JSON.stringify(board) === baseline) {
        LS.remove(DRAFT_KEY);
        hasDraft.value = false;
      } else {
        LS.set(DRAFT_KEY, board);
        hasDraft.value = true;
      }
    }, { deep: true });

    /* ── toasts ── */
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

    /* ── lifecycle ── */
    let t1, t2, t3;
    onMounted(async () => {
      window.addEventListener('keydown', onKeydown);
      await Promise.all([loadConfig(), loadState(), loadStatus()]);
      await loadPreview();
      t1 = setInterval(loadState,  10_000);
      t2 = setInterval(loadStatus, 10_000);
      t3 = setInterval(async () => {
        if (tab.value === 'overview') await loadPreview();
      }, 10_000);
    });
    onUnmounted(() => {
      clearInterval(t1); clearInterval(t2); clearInterval(t3);
      window.removeEventListener('keydown', onKeydown);
    });

    return {
      mini, devOpen, repOpen,
      topNav, devNav, repNav, bottomNav,
      tab, cfg, stateData, status, pushLog, pushLogFilter, filteredPushLog,
      pushLogPage, pushLogPerPage, pushLogTotalPages, pagedPushLog, triggerLabel,
      saving, pushing, clearing, adjustStep, cvs,
      hasDraft, discardDraft,
      dragIndex, dragOverIndex, modalIndex, modalLine,
      onDragStart, onDragOver, onDragEnd, onDrop,
      openLineModal, closeLineModal,
      eventModalOpen, catalog, savingEvent, createForm, editForm, bindForm,
      confirmState, confirmYes, confirmNo,
      opLabel, indStatus, triggersByIndicator, unmappedRequests, eventTypeList,
      openEventModal, closeEventModal, loadCatalog,
      openCreate, submitCreate, openEdit, submitEdit, openTrigger, openBind, submitBind,
      detachRule, deleteIndicator, dismissEvent,
      connDot, connLabel, statusDetail, lastPushLine, deviceLabel,
      connForm, savingConn, openConnForm, saveConn,
      linesWithMeta,
      loadConfig, loadState, loadStatus, loadPreview, loadPushLog,
      save, pushNow, saveAndPush, clearBoard, reconnect,
      adjust, setBrightness,
      argbToHex, hexToArgb,
      setThreshold,
      toasts,
    };
  },
}).mount('#q-app');
