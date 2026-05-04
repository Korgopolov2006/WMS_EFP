/**
 * Warehouse 3D Features
 * Расширение editor.js: heatmap, fly-to SKU, KPI, mini-map, auto-walls,
 * picker FPS, snap-to-grid, undo/redo, слои, import/export layout,
 * heatmap движений, размещение товаров на полках.
 */
(function () {
  'use strict';

  function onReady(api) {
    const THREE = api.THREE;
    const cfg = window.WAREHOUSE_3D_CONFIG;
    if (!cfg) return;

    // ═══════════════════════════════════════════════════════════
    //  Общие утилиты
    // ═══════════════════════════════════════════════════════════
    function showToast(msg, type) {
      const el = document.getElementById('warehouse-3d-toast');
      if (!el) return;
      el.textContent = msg;
      el.className = 'warehouse-3d-toast' + (type === 'ok' ? ' warehouse-3d-toast--ok' : type === 'err' ? ' warehouse-3d-toast--err' : '');
      el.hidden = false;
      clearTimeout(el._t);
      el._t = setTimeout(() => { el.hidden = true; }, 2400);
    }

    function getCsrf() {
      const m = document.cookie.match(/csrftoken=([^;]+)/);
      return m ? m[1] : '';
    }

    function esc(value) {
      return String(value || '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[ch]));
    }

    function withObjectId(url, objectId) {
      return url.replace('999999', String(objectId));
    }

    function pctColor(pct) {
      // 0..0.5: green->yellow, 0.5..1: yellow->red
      const c = new THREE.Color();
      if (pct < 0.5) c.setHSL(0.33 - (pct * 2) * 0.16, 0.7, 0.45); // 120deg → 60deg
      else c.setHSL(0.16 - (pct - 0.5) * 0.32, 0.85, 0.5);          // 60deg → 0deg
      return c;
    }

    // ═══════════════════════════════════════════════════════════
    //  KPI-панель
    // ═══════════════════════════════════════════════════════════
    function renderKPI(kpi) {
      if (!kpi) return;
      const map = {
        total_objects: kpi.total_objects,
        with_stock: kpi.with_stock,
        empty: kpi.empty,
        total_qty: Math.round(kpi.total_qty),
        expired: kpi.expired,
        fill_pct_label: ((kpi.fill_pct || 0) * 100).toFixed(1) + '%',
      };
      Object.keys(map).forEach(k => {
        const el = document.querySelector(`[data-kpi="${k}"]`);
        if (el) el.textContent = map[k];
      });
      const meter = document.getElementById('kpi-fill-meter');
      if (meter) meter.style.width = ((kpi.fill_pct || 0) * 100).toFixed(1) + '%';
    }
    renderKPI(cfg.kpi);

    function refreshKPI() {
      fetch(cfg.urls.kpi, { credentials: 'same-origin' })
        .then(r => r.json())
        .then(d => {
          renderKPI(d.kpi);
          state.fillByObject = d.fill_by_object || {};
          if (state.heatmapEnabled) applyHeatmap();
        })
        .catch(() => {});
    }
    setInterval(refreshKPI, 30000); // авто-обновление каждые 30 с

    // ═══════════════════════════════════════════════════════════
    //  Внутреннее состояние модуля
    // ═══════════════════════════════════════════════════════════
    const state = {
      fillByObject: cfg.fillByObject || {},
      heatmapEnabled: false,
      movementHeatmapEnabled: false,
      movementHeatmap: {},
      productGroups: new Map(),       // objId -> THREE.Group (товары на полке)
      originalMaterials: new Map(),   // objId -> [{mesh, color}]
      undoStack: [],
      redoStack: [],
      flyTo: null,                     // активная анимация
      pickerActive: false,
      pickerControls: null,
      minimapVisible: true,
      minimapRenderer: null,
      minimapCamera: null,
      autoWallsBuilt: false,
      pickPathGroup: null,
      pickPathWaypoints: [],
      pickerRouteIndex: 0,
      liveEnabled: false,
      liveTimer: null,
      liveLastId: 0,
      liveAnimations: [],
    };

    // ═══════════════════════════════════════════════════════════
    //  1) Heatmap по заполненности
    // ═══════════════════════════════════════════════════════════
    function collectMaterialMeshes(objWrap) {
      const out = [];
      const root = objWrap.mesh;
      if (!root) return out;
      if (root instanceof THREE.Group) {
        root.traverse(child => {
          if (child instanceof THREE.Mesh && child.material && child.material.color) {
            out.push(child);
          }
        });
      } else if (root.material && root.material.color) {
        out.push(root);
      }
      return out;
    }

    function applyHeatmap() {
      api.storageObjects.forEach((wrap, key) => {
        const id = wrap.id;
        if (!id) return;
        const fill = state.fillByObject[id];
        const meshes = collectMaterialMeshes(wrap);
        if (!meshes.length) return;
        if (!state.originalMaterials.has(id)) {
          state.originalMaterials.set(id, meshes.map(m => ({ mesh: m, color: m.material.color.clone() })));
        }
        const pct = fill ? fill.pct : 0;
        const color = pctColor(pct);
        meshes.forEach(m => { m.material.color = color; });
      });
    }

    function clearHeatmap() {
      state.originalMaterials.forEach((entries) => {
        entries.forEach(e => { e.mesh.material.color.copy(e.color); });
      });
    }

    function bindHeatmapToggle() {
      const btn = document.getElementById('btn-toggle-heatmap');
      if (!btn) return;
      btn.addEventListener('click', () => {
        state.heatmapEnabled = !state.heatmapEnabled;
        btn.dataset.active = state.heatmapEnabled ? 'true' : 'false';
        btn.classList.toggle('is-active', state.heatmapEnabled);
        if (state.heatmapEnabled) {
          if (state.movementHeatmapEnabled) toggleMovementHeatmap(); // взаимоисключающие
          applyHeatmap();
          showToast('Heatmap заполненности включён', 'ok');
        } else {
          clearHeatmap();
          showToast('Heatmap выключен');
        }
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  2) Поиск SKU + fly-to
    // ═══════════════════════════════════════════════════════════
    function flyCameraTo(target, lookAt) {
      // плавная анимация камеры за ~600 мс
      const startPos = api.camera.position.clone();
      const startLook = new THREE.Vector3();
      api.camera.getWorldDirection(startLook).multiplyScalar(20).add(api.camera.position);
      const dur = 700;
      const t0 = performance.now();
      state.flyTo = function step() {
        const t = Math.min(1, (performance.now() - t0) / dur);
        const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        api.camera.position.lerpVectors(startPos, target, ease);
        const look = new THREE.Vector3().lerpVectors(startLook, lookAt, ease);
        api.camera.lookAt(look);
        if (api.controls) {
          api.controls.target.copy(lookAt);
          api.controls.update();
        }
        if (t < 1) requestAnimationFrame(step);
        else state.flyTo = null;
      };
      requestAnimationFrame(state.flyTo);
    }

    function highlightObject(objId) {
      const wrap = api.storageObjects.get(objId);
      if (!wrap) return;
      const meshes = collectMaterialMeshes(wrap);
      meshes.forEach(m => {
        const orig = m.material.emissive ? m.material.emissive.clone() : new THREE.Color(0x000000);
        if (m.material.emissive) {
          m.material.emissive.set(0xffaa00);
          m.material.emissiveIntensity = 0.8;
          setTimeout(() => {
            m.material.emissive.copy(orig);
            m.material.emissiveIntensity = 0;
          }, 2400);
        }
      });
    }

    function bindSearch() {
      const input = document.getElementById('sku-search');
      const results = document.getElementById('sku-search-results');
      if (!input || !results) return;
      let timer = null;

      const renderResults = (items) => {
        if (!items.length) {
          results.innerHTML = '<div class="sku-search-results__empty">Ничего не найдено</div>';
          results.hidden = false;
          return;
        }
        results.innerHTML = items.map((it, idx) => `
          <div class="sku-search-results__item" data-idx="${idx}">
            <strong>${it.product_sku}</strong> — ${it.product_name}
            <small>${it.location_code} · ${it.qty} шт. · объект #${it.object_code || it.object_id}</small>
          </div>
        `).join('');
        results.hidden = false;
        results.querySelectorAll('.sku-search-results__item').forEach(el => {
          el.addEventListener('click', () => {
            const it = items[parseInt(el.dataset.idx)];
            const target = new THREE.Vector3(it.position.x + 5, 6, it.position.z + 5);
            const lookAt = new THREE.Vector3(it.position.x, it.position.y || 1, it.position.z);
            flyCameraTo(target, lookAt);
            highlightObject(it.object_id);
            results.hidden = true;
          });
        });
      };

      input.addEventListener('input', () => {
        clearTimeout(timer);
        const q = input.value.trim();
        if (q.length < 2) { results.hidden = true; return; }
        timer = setTimeout(() => {
          fetch(cfg.urls.locate + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
            .then(r => r.json())
            .then(d => renderResults(d.results || []))
            .catch(() => { results.hidden = true; });
        }, 250);
      });
      document.addEventListener('click', (e) => {
        if (!results.contains(e.target) && e.target !== input) results.hidden = true;
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  3) Auto-walls по контуру floor_points
    //     (editor.js уже строит стены, но позволим перестроить)
    // ═══════════════════════════════════════════════════════════
    function bindWallsRebuild() {
      const btn = document.getElementById('btn-rebuild-walls');
      if (!btn) return;
      btn.addEventListener('click', () => {
        api.buildWalls && api.buildWalls();
        showToast('Стены перестроены по контуру', 'ok');
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  4) Mini-map (top-down)
    // ═══════════════════════════════════════════════════════════
    function setupMinimap() {
      const container = document.getElementById('minimap');
      if (!container) return;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(220, 220);
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      container.appendChild(renderer.domElement);

      // Орто-камера сверху вниз
      const size = 30;
      const camera = new THREE.OrthographicCamera(-size, size, size, -size, 0.1, 200);
      camera.position.set(0, 80, 0);
      camera.lookAt(0, 0, 0);
      camera.up.set(0, 0, -1);

      // Маркер положения главной камеры
      const markerGeom = new THREE.ConeGeometry(1.2, 2.4, 4);
      const markerMat = new THREE.MeshBasicMaterial({ color: 0xff5722 });
      const marker = new THREE.Mesh(markerGeom, markerMat);
      marker.rotation.x = Math.PI;
      api.scene.add(marker);
      marker.visible = false; // отображаем только в мини-карте через слой

      state.minimapRenderer = renderer;
      state.minimapCamera = camera;
      state.minimapMarker = marker;

      // Регистрируем on-after-render
      api._hooks.onAfterRender.push(() => {
        if (!state.minimapVisible) return;
        // Ставим маркер на позицию камеры
        const cam = api.camera;
        marker.position.set(cam.position.x, 1, cam.position.z);
        const lookDir = new THREE.Vector3();
        cam.getWorldDirection(lookDir);
        marker.rotation.y = Math.atan2(lookDir.x, lookDir.z) + Math.PI;
        marker.visible = true;
        renderer.render(api.scene, camera);
        marker.visible = false;
      });

      // Клик по мини-карте — переместить главную камеру в эту точку
      renderer.domElement.addEventListener('click', (e) => {
        const rect = renderer.domElement.getBoundingClientRect();
        const nx = (e.clientX - rect.left) / rect.width;
        const ny = (e.clientY - rect.top) / rect.height;
        const worldX = (nx - 0.5) * 2 * size;
        const worldZ = (ny - 0.5) * 2 * size;
        const target = new THREE.Vector3(worldX + 10, 12, worldZ + 10);
        const lookAt = new THREE.Vector3(worldX, 0, worldZ);
        flyCameraTo(target, lookAt);
      });

      const btn = document.getElementById('btn-toggle-minimap');
      if (btn) {
        btn.addEventListener('click', () => {
          state.minimapVisible = !state.minimapVisible;
          container.classList.toggle('is-hidden', !state.minimapVisible);
          btn.dataset.active = state.minimapVisible ? 'true' : 'false';
          btn.querySelector('span').textContent = state.minimapVisible ? 'Скрыть мини-карту' : 'Показать мини-карту';
        });
      }
    }

    // ═══════════════════════════════════════════════════════════
    //  5) Picker mode (FPS)
    // ═══════════════════════════════════════════════════════════
    function setupPickerMode() {
      const btn = document.getElementById('btn-toggle-picker');
      if (!btn) return;
      const canvas = api.renderer.domElement;
      const container = document.getElementById('canvas-container');
      const crosshair = document.createElement('div');
      crosshair.className = 'w3d-picker-crosshair';
      crosshair.hidden = true;
      crosshair.innerHTML = '<span></span>';
      const pickerHud = document.createElement('div');
      pickerHud.className = 'w3d-picker-hud';
      pickerHud.hidden = true;
      pickerHud.innerHTML = `
        <strong>Режим осмотра</strong>
        <span>WASD — движение · клик по центру — действия · E — повторить выбор · Esc — выйти</span>
        <span class="w3d-picker-hud__route" data-picker-route hidden></span>
      `;
      const pickerRouteHint = pickerHud.querySelector('[data-picker-route]');
      const pickerPanel = document.createElement('div');
      pickerPanel.className = 'w3d-picker-action-panel';
      pickerPanel.hidden = true;
      container.appendChild(crosshair);
      container.appendChild(pickerHud);
      container.appendChild(pickerPanel);

      // Параметры реального человека:
      const EYE_HEIGHT = 1.7;     // м — рост глаз
      const WALK_SPEED = 0.08;    // м/тик ~ 4.8 м/с
      const RUN_MULT   = 1.9;     // Shift = бег
      const BOB_AMP    = 0.04;    // амплитуда head-bob
      const BOB_FREQ   = 0.16;    // скорость head-bob
      const PERSON_R   = 0.35;    // «радиус» игрока для коллизий со стеллажами

      const move = { fwd: false, back: false, left: false, right: false, run: false };
      const euler = new THREE.Euler(0, 0, 0, 'YXZ');
      const PI_2 = Math.PI / 2;
      let bobPhase = 0;
      let savedCamPos = null;
      let savedCamQuat = null;
      let pickerUiOpen = false;
      let lastSelection = null;

      function distanceToSegment2D(x, z, ax, az, bx, bz) {
        const dx = bx - ax;
        const dz = bz - az;
        const lenSq = dx * dx + dz * dz;
        if (!lenSq) return Math.hypot(x - ax, z - az);
        const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / lenSq));
        return Math.hypot(x - (ax + t * dx), z - (az + t * dz));
      }

      function isInsideWarehouse(x, z) {
        const points = api.floorPoints || [];
        if (points.length < 3) return true;
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
          const [xi, zi] = points[i];
          const [xj, zj] = points[j];
          if (((zi > z) !== (zj > z)) && (x < ((xj - xi) * (z - zi)) / (zj - zi) + xi)) {
            inside = !inside;
          }
        }
        return inside;
      }

      function hasWallClearance(x, z) {
        const points = api.floorPoints || [];
        if (points.length < 3) return true;
        for (let i = 0; i < points.length; i++) {
          const [ax, az] = points[i];
          const [bx, bz] = points[(i + 1) % points.length];
          if (distanceToSegment2D(x, z, ax, az, bx, bz) < PERSON_R) return false;
        }
        return true;
      }

      function warehouseCenter() {
        const points = api.floorPoints || [];
        if (points.length < 3) return { x: 0, z: 0 };
        const sum = points.reduce((acc, point) => ({ x: acc.x + point[0], z: acc.z + point[1] }), { x: 0, z: 0 });
        return { x: sum.x / points.length, z: sum.z / points.length };
      }

      function onKeyDown(e) {
        if (!state.pickerActive) return;
        if (pickerUiOpen) {
          if (e.code === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            closePickerPanel(true);
          }
          return;
        }
        // В picker mode запрещены ВСЕ горячие клавиши, кроме движения и Esc
        e.stopPropagation();
        if (e.code === 'Escape') { e.preventDefault(); stopPicker(); return; }
        if (e.code === 'KeyE' && lastSelection) { e.preventDefault(); showPickerActions(lastSelection); return; }
        if (e.code === 'KeyW' || e.code === 'ArrowUp')    { move.fwd = true; e.preventDefault(); }
        if (e.code === 'KeyS' || e.code === 'ArrowDown')  { move.back = true; e.preventDefault(); }
        if (e.code === 'KeyA' || e.code === 'ArrowLeft')  { move.left = true; e.preventDefault(); }
        if (e.code === 'KeyD' || e.code === 'ArrowRight') { move.right = true; e.preventDefault(); }
        if (e.code === 'ShiftLeft' || e.code === 'ShiftRight') move.run = true;
        // Все остальные клавиши — съедаются (preventDefault не нужен, но stopPropagation выше блокирует editor.js)
      }
      function onKeyUp(e) {
        if (!state.pickerActive) return;
        e.stopPropagation();
        if (e.code === 'KeyW' || e.code === 'ArrowUp')    move.fwd = false;
        if (e.code === 'KeyS' || e.code === 'ArrowDown')  move.back = false;
        if (e.code === 'KeyA' || e.code === 'ArrowLeft')  move.left = false;
        if (e.code === 'KeyD' || e.code === 'ArrowRight') move.right = false;
        if (e.code === 'ShiftLeft' || e.code === 'ShiftRight') move.run = false;
      }
      function onMouseMove(e) {
        if (!state.pickerActive || pickerUiOpen) return;
        if (canvas.requestPointerLock && document.pointerLockElement !== canvas) return;
        const dx = e.movementX || 0;
        const dy = e.movementY || 0;
        euler.setFromQuaternion(api.camera.quaternion);
        euler.y -= dx * 0.0025;
        euler.x -= dy * 0.0025;
        euler.x = Math.max(-PI_2 + 0.05, Math.min(PI_2 - 0.05, euler.x));
        api.camera.quaternion.setFromEuler(euler);
      }
      function onPointerLockChange() {
        const isLocked = document.pointerLockElement === canvas;
        container.classList.toggle('is-pointer-locked', isLocked && state.pickerActive && !pickerUiOpen);
        if (!isLocked && state.pickerActive && !pickerUiOpen) {
          stopPicker();
        }
      }

      function requestPickerLookLock() {
        if (!canvas.requestPointerLock) return;
        try {
          const request = canvas.requestPointerLock();
          if (request && typeof request.catch === 'function') {
            request.catch(() => {
              container.classList.remove('is-pointer-locked');
              showToast('Кликните по области склада, чтобы вернуть управление взглядом', 'err');
            });
          }
        } catch (err) {
          container.classList.remove('is-pointer-locked');
          showToast('Не удалось захватить мышь для режима осмотра', 'err');
        }
      }

      /** Проверка: можно ли встать в (x, z) — не упираемся ли в стеллаж/полку. */
      function canStandAt(x, z) {
        if (!isInsideWarehouse(x, z) || !hasWallClearance(x, z)) return false;
        for (const [, wrap] of api.storageObjects.entries()) {
          if (!wrap || !wrap.mesh || !wrap.size) continue;
          // Только препятствия на уровне глаз/тела
          const ymin = wrap.mesh.position.y - wrap.size.height / 2;
          const ymax = wrap.mesh.position.y + wrap.size.height / 2;
          if (ymax < 0.3 || ymin > EYE_HEIGHT) continue;
          const ox = wrap.mesh.position.x;
          const oz = wrap.mesh.position.z;
          const halfW = wrap.size.width / 2 + PERSON_R;
          const halfD = wrap.size.depth / 2 + PERSON_R;
          if (Math.abs(x - ox) < halfW && Math.abs(z - oz) < halfD) {
            return false; // коллизия
          }
        }
        return true;
      }

      function findSafeSpawnPoint() {
        const gate = (cfg.gate && typeof cfg.gate.x === 'number') ? cfg.gate : null;
        const center = warehouseCenter();
        const candidates = [
          center,
          gate,
          gate ? { x: (gate.x + center.x) / 2, z: (gate.z + center.z) / 2 } : null,
          { x: center.x + 1, z: center.z },
          { x: center.x - 1, z: center.z },
          { x: center.x, z: center.z + 1 },
          { x: center.x, z: center.z - 1 },
        ].filter(Boolean);

        for (const point of candidates) {
          if (canStandAt(point.x, point.z)) return point;
        }

        for (let radius = 0.5; radius <= 8; radius += 0.5) {
          for (let step = 0; step < 24; step++) {
            const angle = (Math.PI * 2 * step) / 24;
            const point = {
              x: center.x + Math.cos(angle) * radius,
              z: center.z + Math.sin(angle) * radius,
            };
            if (canStandAt(point.x, point.z)) return point;
          }
        }
        return center;
      }

      function findProductFromHit(object) {
        let current = object;
        while (current) {
          if (current.userData && current.userData.product) {
            return { product: current.userData.product, box: current };
          }
          current = current.parent;
        }
        return null;
      }

      function findWrapFromHit(object) {
        for (const [, wrap] of api.storageObjects.entries()) {
          if (!wrap || !wrap.mesh) continue;
          let found = wrap.mesh === object;
          if (!found && wrap.mesh.traverse) {
            wrap.mesh.traverse(child => { if (child === object) found = true; });
          }
          if (found) return wrap;
        }
        return null;
      }

      function resetPickerMovement() {
        move.fwd = move.back = move.left = move.right = move.run = false;
      }

      function pausePickerForUi() {
        pickerUiOpen = true;
        state.pickerUiOpen = true;
        resetPickerMovement();
        container.classList.add('is-picker-paused');
        container.classList.remove('is-pointer-locked');
        crosshair.classList.add('is-muted');
        pickerHud.hidden = true;
        if (document.pointerLockElement === canvas && document.exitPointerLock) {
          document.exitPointerLock();
        }
      }

      function closePickerPanel(resumeLook) {
        pickerPanel.hidden = true;
        pickerPanel.innerHTML = '';
        pickerUiOpen = false;
        state.pickerUiOpen = false;
        container.classList.remove('is-picker-paused');
        container.classList.remove('is-pointer-locked');
        crosshair.classList.remove('is-muted');
        pickerHud.hidden = !state.pickerActive;
        if (resumeLook && state.pickerActive) {
          requestPickerLookLock();
        }
      }

      function routeTargetLabel(target, index) {
        if (!target) return `Точка ${index + 1}`;
        return target.product_sku || target.object_code || target.location_code || `Точка ${target.step || index + 1}`;
      }

      function updatePickerRouteHud() {
        if (!pickerRouteHint) return;
        const path = state.pickPathWaypoints || [];
        if (!state.pickerActive || !path.length) {
          pickerRouteHint.hidden = true;
          pickerRouteHint.textContent = '';
          return;
        }

        state.pickerRouteIndex = Math.max(0, Math.min(state.pickerRouteIndex || 0, path.length - 1));
        let target = path[state.pickerRouteIndex];
        if (!target || typeof target.x !== 'number' || typeof target.z !== 'number') {
          pickerRouteHint.hidden = true;
          return;
        }

        let distance = Math.hypot(target.x - api.camera.position.x, target.z - api.camera.position.z);
        if (distance < 1.2 && state.pickerRouteIndex < path.length - 1) {
          state.pickerRouteIndex += 1;
          target = path[state.pickerRouteIndex];
          distance = Math.hypot(target.x - api.camera.position.x, target.z - api.camera.position.z);
        }

        pickerRouteHint.hidden = false;
        pickerRouteHint.textContent = `Маршрут: ${routeTargetLabel(target, state.pickerRouteIndex)} · ${distance.toFixed(1)} м`;
      }

      function productToStock(product) {
        if (!product) return null;
        return {
          stock_id: product.stock_id,
          product_sku: product.product_sku,
          product_name: product.product_name,
          qty_available: product.originalQty || product.qty || 0,
          batch_no: product.batch_no || '',
          expiry_date: product.expiry_date || null,
        };
      }

      function openObjectStocksFromPicker(wrap) {
        showObjectCard(wrap);
        const card = document.getElementById('object-focus-card');
        const list = card ? card.querySelector('[data-card-stock-list]') : null;
        loadObjectStocks(wrap, list);
      }

      function showPickerActions(selection) {
        if (!selection || !selection.wrap) return;
        lastSelection = selection;
        const wrap = selection.wrap;
        const product = selection.product || null;
        pausePickerForUi();
        highlightObject(wrap.id);
        if (api.selectObject && cfg.canEdit) api.selectObject(wrap);

        const fill = state.fillByObject[wrap.id] || {};
        const pct = Math.round((fill.pct || 0) * 100);
        const productLine = product
          ? `<div class="w3d-picker-action-panel__product">
              <strong>${esc(product.product_sku || 'Товар')}</strong>
              <span>${esc(product.product_name || '')}</span>
              <small>${product.originalQty || product.qty || 0} шт.${product.batch_no ? ' · партия ' + esc(product.batch_no) : ''}${productHitLevel(selection) ? ' · этаж ' + productHitLevel(selection) : ''}</small>
            </div>`
          : '';
        const stock = productToStock(product);

        pickerPanel.hidden = false;
        pickerPanel.innerHTML = `
          <div class="w3d-picker-action-panel__header">
            <div>
              <div class="w3d-picker-action-panel__eyebrow">${product ? 'Товар в 3D-складе' : 'Объект склада'}</div>
              <h3>${esc(wrap.code || wrap.name || ('#' + wrap.id))}</h3>
            </div>
            <button type="button" class="w3d-picker-action-panel__close" data-picker-close aria-label="Закрыть">×</button>
          </div>
          ${productLine}
          <div class="w3d-picker-action-panel__meta">
            <span>${esc(wrap.type)}</span>
            <span>${esc(locationLabel(wrap.storageLocationId))}</span>
            <span>${pct}% заполнено</span>
          </div>
          <div class="w3d-picker-action-panel__actions">
            <button type="button" class="btn btn--primary btn--small" data-picker-resume>Вернуться к осмотру</button>
            <button type="button" class="btn btn--ghost btn--small" data-picker-card>Карточка</button>
            ${wrap.id ? '<button type="button" class="btn btn--ghost btn--small" data-picker-stocks>Товары</button>' : ''}
            ${wrap.id ? `<a class="btn btn--ghost btn--small" href="${withObjectId(cfg.urls.objectQr, wrap.id)}" target="_blank">QR объекта</a>` : ''}
            ${cfg.canEdit ? '<button type="button" class="btn btn--ghost btn--small" data-picker-select>Выбрать в панели</button>' : ''}
            ${cfg.canEdit && stock && stock.stock_id ? '<button type="button" class="btn btn--ghost btn--small" data-picker-stock-action>Действие с товаром</button>' : ''}
          </div>
          <div class="w3d-picker-action-panel__hint">Ты остаёшься в picker mode: панель можно закрыть и сразу продолжить движение по складу.</div>
        `;

        pickerPanel.querySelector('[data-picker-close]').addEventListener('click', () => closePickerPanel(true));
        pickerPanel.querySelector('[data-picker-resume]').addEventListener('click', () => closePickerPanel(true));
        pickerPanel.querySelector('[data-picker-card]').addEventListener('click', () => showObjectCard(wrap));
        const stocksBtn = pickerPanel.querySelector('[data-picker-stocks]');
        if (stocksBtn) stocksBtn.addEventListener('click', () => openObjectStocksFromPicker(wrap));
        const selectBtn = pickerPanel.querySelector('[data-picker-select]');
        if (selectBtn) selectBtn.addEventListener('click', () => {
          if (api.selectObject) api.selectObject(wrap);
          showToast('Объект выбран в панели редактирования', 'ok');
        });
        const stockBtn = pickerPanel.querySelector('[data-picker-stock-action]');
        if (stockBtn) stockBtn.addEventListener('click', () => openStockDialog(wrap, stock));
      }

      function productHitLevel(selection) {
        return selection && selection.box && selection.box.userData ? selection.box.userData.rackLevel : '';
      }

      function pickerSelectCenter() {
        if (!state.pickerActive || pickerUiOpen) return;
        if (canvas.requestPointerLock && document.pointerLockElement !== canvas) {
          requestPickerLookLock();
          return;
        }
        const candidates = [];
        state.productGroups.forEach(group => candidates.push(group));
        api.storageObjects.forEach(wrap => { if (wrap && wrap.mesh) candidates.push(wrap.mesh); });

        api.raycaster.setFromCamera(new THREE.Vector2(0, 0), api.camera);
        const hits = api.raycaster.intersectObjects(candidates, true);
        if (!hits.length) {
          showToast('В центре прицела нет объекта', 'err');
          return;
        }

        const productHit = hits.map(hit => findProductFromHit(hit.object)).find(Boolean);
        if (productHit) {
          const product = productHit.product;
          const parentId = productHit.box.userData.parentObjectId;
          const wrap = api.storageObjects.get(parentId) || api.storageObjects.get(Number(parentId)) || api.storageObjects.get(String(parentId));
          if (wrap) showPickerActions({ type: 'product', product, box: productHit.box, wrap });
          return;
        }

        const wrap = hits.map(hit => findWrapFromHit(hit.object)).find(Boolean);
        if (!wrap) return;
        showPickerActions({ type: 'object', wrap });
      }

      function tick() {
        if (!state.pickerActive) return;
        const dir = new THREE.Vector3();
        api.camera.getWorldDirection(dir);
        dir.y = 0;
        if (dir.lengthSq() > 0) dir.normalize();
        const right = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0)).normalize();
        const speed = WALK_SPEED * (move.run ? RUN_MULT : 1);

        let nx = api.camera.position.x;
        let nz = api.camera.position.z;
        let moving = false;
        if (move.fwd)   { nx += dir.x * speed;   nz += dir.z * speed;   moving = true; }
        if (move.back)  { nx -= dir.x * speed;   nz -= dir.z * speed;   moving = true; }
        if (move.right) { nx += right.x * speed; nz += right.z * speed; moving = true; }
        if (move.left)  { nx -= right.x * speed; nz -= right.z * speed; moving = true; }

        // Скользим вдоль стеллажей: проверяем X и Z отдельно
        if (moving) {
          if (canStandAt(nx, api.camera.position.z)) api.camera.position.x = nx;
          if (canStandAt(api.camera.position.x, nz)) api.camera.position.z = nz;
          bobPhase += BOB_FREQ * (move.run ? 1.5 : 1);
        } else {
          // Возвращаем head в нейтральное положение
          bobPhase *= 0.85;
        }

        // Жёсткая фиксация Y: глаза человека = 1.7 + лёгкое покачивание при ходьбе
        const bob = Math.sin(bobPhase) * BOB_AMP * (moving ? 1 : 0);
        api.camera.position.y = EYE_HEIGHT + bob;
        updatePickerRouteHud();

        requestAnimationFrame(tick);
      }

      function startPicker() {
        state.pickerActive = true;
        // Сохраняем текущее положение камеры, чтобы при выходе вернуться
        savedCamPos = api.camera.position.clone();
        savedCamQuat = api.camera.quaternion.clone();

        if (api.controls) api.controls.enabled = false;
        container.classList.add('is-picker');
        container.classList.remove('is-picker-paused');
        container.classList.remove('is-pointer-locked');
        crosshair.hidden = false;
        pickerHud.hidden = false;
        requestPickerLookLock();

        const spawn = findSafeSpawnPoint();
        api.camera.position.set(spawn.x, EYE_HEIGHT, spawn.z);
        const center = warehouseCenter();
        const lookTarget = new THREE.Vector3(center.x, EYE_HEIGHT, center.z);
        api.camera.lookAt(lookTarget);
        // Сбрасываем euler из текущей ориентации
        euler.setFromQuaternion(api.camera.quaternion);
        updatePickerRouteHud();

        // capture: keys ловим в фазе capture, чтобы blocking сработал ДО editor.js
        document.addEventListener('keydown', onKeyDown, true);
        document.addEventListener('keyup', onKeyUp, true);
        document.addEventListener('mousemove', onMouseMove);
        canvas.addEventListener('click', pickerSelectCenter);
        document.addEventListener('pointerlockchange', onPointerLockChange);
        btn.dataset.active = 'true';
        btn.classList.add('is-active');
        // Глобальный флаг — editor.js будет игнорировать hotkeys
        window.WAREHOUSE_3D.isPickerActive = true;
        showToast('Режим осмотра: клик по объекту откроет действия без выхода из picker mode', 'ok');
        requestAnimationFrame(tick);
      }
      function stopPicker() {
        state.pickerActive = false;
        window.WAREHOUSE_3D.isPickerActive = false;
        pickerUiOpen = false;
        state.pickerUiOpen = false;
        document.exitPointerLock && document.exitPointerLock();
        if (api.controls) api.controls.enabled = true;
        container.classList.remove('is-picker');
        container.classList.remove('is-picker-paused');
        container.classList.remove('is-pointer-locked');
        crosshair.hidden = true;
        pickerHud.hidden = true;
        updatePickerRouteHud();
        pickerPanel.hidden = true;
        pickerPanel.innerHTML = '';
        const focusCard = document.getElementById('object-focus-card');
        if (focusCard) focusCard.classList.remove('object-focus-card--picker');
        document.removeEventListener('keydown', onKeyDown, true);
        document.removeEventListener('keyup', onKeyUp, true);
        document.removeEventListener('mousemove', onMouseMove);
        canvas.removeEventListener('click', pickerSelectCenter);
        document.removeEventListener('pointerlockchange', onPointerLockChange);
        btn.dataset.active = 'false';
        btn.classList.remove('is-active');
        // Сбросить состояние клавиш чтобы не «зажалось»
        resetPickerMovement();
        // Восстанавливаем камеру или ставим в изометрию
        if (savedCamPos && savedCamQuat) {
          api.camera.position.copy(savedCamPos);
          api.camera.quaternion.copy(savedCamQuat);
          if (api.controls) api.controls.update && api.controls.update();
        } else if (api.setCameraView) {
          api.setCameraView('iso');
        }
      }

      btn.addEventListener('click', () => {
        if (state.pickerActive) stopPicker(); else startPicker();
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  6) Snap-to-grid + Undo/Redo
    // ═══════════════════════════════════════════════════════════
    function pushUndo(action) {
      state.undoStack.push(action);
      if (state.undoStack.length > 50) state.undoStack.shift();
      state.redoStack.length = 0;
    }
    window.WAREHOUSE_3D.pushUndo = pushUndo;
    window.WAREHOUSE_3D.snapEnabled = function () {
      const t = document.getElementById('snap-toggle');
      return t ? t.checked : true;
    };

    function applyAction(act, reverse) {
      if (act.type === 'move') {
        const wrap = api.storageObjects.get(act.objectId);
        if (!wrap || !wrap.mesh) return;
        const target = reverse ? act.before : act.after;
        wrap.mesh.position.x = target.x;
        wrap.mesh.position.z = target.z;
        wrap.position.x = target.x;
        wrap.position.z = target.z;
      }
    }
    function bindUndoRedo() {
      const undoBtn = document.getElementById('btn-undo');
      const redoBtn = document.getElementById('btn-redo');
      const doUndo = () => {
        const a = state.undoStack.pop();
        if (!a) return showToast('Нечего отменять');
        applyAction(a, true);
        state.redoStack.push(a);
        showToast('Отменено');
      };
      const doRedo = () => {
        const a = state.redoStack.pop();
        if (!a) return showToast('Нечего повторить');
        applyAction(a, false);
        state.undoStack.push(a);
        showToast('Повторено');
      };
      if (undoBtn) undoBtn.addEventListener('click', doUndo);
      if (redoBtn) redoBtn.addEventListener('click', doRedo);
      document.addEventListener('keydown', (e) => {
        const tag = (document.activeElement && document.activeElement.tagName) || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (e.ctrlKey && e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
        else if (e.ctrlKey && e.key.toLowerCase() === 'y') { e.preventDefault(); doRedo(); }
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  7) Слои/группы видимости
    // ═══════════════════════════════════════════════════════════
    function applyLayerVisibility() {
      const checks = document.querySelectorAll('.layer-toggle input[data-layer]');
      const visible = {};
      checks.forEach(c => { visible[c.dataset.layer] = c.checked; });
      api.storageObjects.forEach(wrap => {
        if (!wrap.mesh) return;
        wrap.mesh.visible = visible[wrap.type] !== false;
      });
      // Товары на полках
      const showProducts = visible.PRODUCTS !== false;
      state.productGroups.forEach(g => { g.visible = showProducts; });
    }
    function bindLayerToggles() {
      document.querySelectorAll('.layer-toggle input[data-layer]').forEach(c => {
        c.addEventListener('change', applyLayerVisibility);
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  8) Импорт/экспорт layout JSON
    // ═══════════════════════════════════════════════════════════
    function bindImport() {
      const btn = document.getElementById('btn-import-layout');
      const input = document.getElementById('import-file-input');
      if (!btn || !input) return;
      btn.addEventListener('click', () => input.click());
      input.addEventListener('change', () => {
        const file = input.files && input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          let payload;
          try { payload = JSON.parse(reader.result); }
          catch { return showToast('Файл повреждён: некорректный JSON', 'err'); }
          const replace = confirm('Заменить существующие объекты импортируемыми?\nOK — заменить, Отмена — добавить сверху.');
          payload.replace_objects = replace;
          fetch(cfg.urls.importLayout, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
            body: JSON.stringify(payload),
          }).then(r => r.json()).then(d => {
            if (d.success) {
              showToast(d.message || 'Импорт выполнен', 'ok');
              setTimeout(() => location.reload(), 800);
            } else {
              showToast(d.error || 'Ошибка импорта', 'err');
            }
          }).catch(() => showToast('Сетевая ошибка', 'err'));
        };
        reader.readAsText(file);
        input.value = '';
      });
    }

    // ═══════════════════════════════════════════════════════════
    //  9) Heatmap движений
    // ═══════════════════════════════════════════════════════════
    function applyMovementHeatmap() {
      api.storageObjects.forEach(wrap => {
        const id = wrap.id;
        if (!id) return;
        const v = state.movementHeatmap[id] || 0;
        const meshes = collectMaterialMeshes(wrap);
        if (!meshes.length) return;
        if (!state.originalMaterials.has(id)) {
          state.originalMaterials.set(id, meshes.map(m => ({ mesh: m, color: m.material.color.clone() })));
        }
        const color = pctColor(v);
        meshes.forEach(m => { m.material.color = color; });
      });
    }
    function toggleMovementHeatmap() {
      const btn = document.getElementById('btn-toggle-movement-heatmap');
      state.movementHeatmapEnabled = !state.movementHeatmapEnabled;
      if (btn) {
        btn.dataset.active = state.movementHeatmapEnabled ? 'true' : 'false';
        btn.classList.toggle('is-active', state.movementHeatmapEnabled);
      }
      if (state.movementHeatmapEnabled) {
        if (state.heatmapEnabled) {
          state.heatmapEnabled = false;
          const fb = document.getElementById('btn-toggle-heatmap');
          if (fb) { fb.dataset.active = 'false'; fb.classList.remove('is-active'); }
        }
        fetch(cfg.urls.movementHeatmap + '?days=30', { credentials: 'same-origin' })
          .then(r => r.json())
          .then(d => {
            state.movementHeatmap = d.by_object || {};
            applyMovementHeatmap();
            showToast(`Heatmap движений за ${d.days} дн. (${d.max_count} операций max)`, 'ok');
          })
          .catch(() => showToast('Не удалось получить heatmap', 'err'));
      } else {
        clearHeatmap();
        showToast('Heatmap движений выключен');
      }
    }
    function bindMovementHeatmap() {
      const btn = document.getElementById('btn-toggle-movement-heatmap');
      if (btn) btn.addEventListener('click', toggleMovementHeatmap);
    }

    // ═══════════════════════════════════════════════════════════
    //  10) Размещение товаров на полках стеллажа
    //  Товары добавляются как children объекта (parent-child).
    //  При drag объекта они едут вместе с ним автоматически.
    // ═══════════════════════════════════════════════════════════

    // Палитра для коробок (картонные оттенки + акцент бренда)
    const BOX_PALETTE = [
      { side: 0xc99767, top: 0xaa7b50, tape: 0xe9d2a5 },
      { side: 0xb8845f, top: 0x916445, tape: 0xe4c795 },
      { side: 0xd0a16f, top: 0xb17a4c, tape: 0xf2ddb0 },
      { side: 0xaa8765, top: 0x87684d, tape: 0xdfc596 },
      { side: 0xc08c6b, top: 0x9b6e54, tape: 0xebd2a0 },
      { side: 0xbfa07a, top: 0x96785b, tape: 0xf0d9aa },
    ];

    function hashString(value) {
      let hash = 0;
      const text = String(value || '');
      for (let i = 0; i < text.length; i++) {
        hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
      }
      return Math.abs(hash);
    }

    function cssHex(hex) {
      return '#' + Number(hex).toString(16).padStart(6, '0');
    }

    function shade(hex, amount) {
      const r = Math.max(0, Math.min(255, ((hex >> 16) & 255) + amount));
      const g = Math.max(0, Math.min(255, ((hex >> 8) & 255) + amount));
      const b = Math.max(0, Math.min(255, (hex & 255) + amount));
      return (r << 16) | (g << 8) | b;
    }

    function stockStatus(stock) {
      if (!stock || !stock.expiry_date) return { color: 0x2dd4bf, label: 'OK' };
      const today = new Date();
      const expiry = new Date(stock.expiry_date + 'T00:00:00');
      const days = Math.ceil((expiry - today) / 86400000);
      if (days < 0) return { color: 0xdc2626, label: 'EXP' };
      if (days <= 30) return { color: 0xeab308, label: 'SOON' };
      return { color: 0x2dd4bf, label: 'OK' };
    }

    function drawCardboardNoise(ctx, width, height, seed) {
      let x = seed || 1;
      const next = () => {
        x = (x * 1664525 + 1013904223) >>> 0;
        return x / 4294967296;
      };
      for (let i = 0; i < 520; i++) {
        const alpha = 0.025 + next() * 0.07;
        const tone = next() > 0.5 ? 255 : 45;
        ctx.fillStyle = `rgba(${tone},${tone},${tone},${alpha})`;
        ctx.fillRect(next() * width, next() * height, 1 + next() * 2.5, 1 + next() * 2.5);
      }
    }

    function drawBarcode(ctx, x, y, width, height, seed) {
      let cursor = x;
      let hash = seed || 7;
      ctx.fillStyle = '#111827';
      while (cursor < x + width) {
        hash = (hash * 1103515245 + 12345) & 0x7fffffff;
        const bar = 1 + (hash % 4);
        const gap = 1 + ((hash >> 3) % 3);
        ctx.fillRect(cursor, y, bar, height);
        cursor += bar + gap;
      }
    }

    function makeBoxTexture(stock, colors, face, status, seed) {
      const canvas = document.createElement('canvas');
      const w = 512, h = 512;
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext('2d');

      const base = face === 'top' ? colors.top : colors.side;
      const grad = ctx.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, cssHex(shade(base, 24)));
      grad.addColorStop(0.52, cssHex(base));
      grad.addColorStop(1, cssHex(shade(base, -28)));
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);

      drawCardboardNoise(ctx, w, h, seed);

      ctx.strokeStyle = 'rgba(45, 31, 20, .20)';
      ctx.lineWidth = 5;
      ctx.strokeRect(7, 7, w - 14, h - 14);

      ctx.strokeStyle = 'rgba(60, 38, 22, .22)';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(w * 0.5, 10);
      ctx.lineTo(w * 0.5, h - 10);
      ctx.stroke();

      ctx.fillStyle = cssHex(colors.tape);
      ctx.globalAlpha = 0.62;
      if (face === 'top') {
        ctx.fillRect(w * 0.42, 0, w * 0.16, h);
        ctx.fillRect(0, h * 0.45, w, h * 0.10);
      } else {
        ctx.fillRect(0, h * 0.44, w, h * 0.12);
      }
      ctx.globalAlpha = 1;

      if (face === 'front') {
        const sku = stock.product_sku || '';
        const name = stock.product_name || '';
        ctx.fillStyle = 'rgba(255,255,255,.92)';
        ctx.strokeStyle = 'rgba(17,24,39,.22)';
        ctx.lineWidth = 3;
        ctx.fillRect(70, 72, 372, 206);
        ctx.strokeRect(70, 72, 372, 206);

        ctx.fillStyle = cssHex(status.color);
        ctx.fillRect(70, 72, 372, 28);

        ctx.fillStyle = '#111827';
        ctx.font = '700 42px ui-monospace, Menlo, Consolas, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(sku.slice(0, 14), w / 2, 145);

        ctx.fillStyle = 'rgba(17,24,39,.68)';
        ctx.font = '22px system-ui, sans-serif';
        ctx.fillText(name.slice(0, 24), w / 2, 190);

        drawBarcode(ctx, 116, 218, 280, 42, seed + 13);

        ctx.fillStyle = 'rgba(17,24,39,.68)';
        ctx.font = '18px ui-monospace, Menlo, Consolas, monospace';
        const unitLabel = stock.visualTotal > 1 ? ` ${stock.visualIndex}/${stock.visualTotal}` : '';
        ctx.fillText(((stock.batch_no || 'BATCH') + unitLabel).slice(0, 20), w / 2, 324);

        ctx.fillStyle = cssHex(status.color);
        ctx.fillRect(350, 306, 92, 34);
        ctx.fillStyle = '#fff';
        ctx.font = '700 18px system-ui, sans-serif';
        ctx.fillText(status.label, 396, 323);
      }

      const texture = new THREE.CanvasTexture(canvas);
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.needsUpdate = true;
      return texture;
    }

    /** Создаёт одну реалистичную коробку с надписью SKU на лицевой грани. */
    function makeProductBox(width, height, depth, stock, paletteIdx, seed) {
      const colors = BOX_PALETTE[paletteIdx % BOX_PALETTE.length];
      const status = stockStatus(stock);
      const sideMat = new THREE.MeshStandardMaterial({
        map: makeBoxTexture(stock, colors, 'side', status, seed + 1),
        roughness: 0.92,
        metalness: 0.02,
      });
      const sideAltMat = new THREE.MeshStandardMaterial({
        map: makeBoxTexture(stock, colors, 'side-alt', status, seed + 2),
        roughness: 0.92,
        metalness: 0.02,
      });
      const topMat = new THREE.MeshStandardMaterial({
        map: makeBoxTexture(stock, colors, 'top', status, seed + 3),
        roughness: 0.95,
        metalness: 0.02,
      });
      const faceMat = new THREE.MeshStandardMaterial({
        map: makeBoxTexture(stock, colors, 'front', status, seed + 4),
        roughness: 0.88,
        metalness: 0.02,
      });
      // Порядок граней BoxGeometry: +X, -X, +Y, -Y, +Z, -Z
      // Делаем «лицевую» (+Z) — с этикеткой, верх и низ — top, остальные — side
      const materials = [sideMat, sideAltMat, topMat, topMat, faceMat, sideMat];
      const geom = new THREE.BoxGeometry(width, height, depth);
      const box = new THREE.Mesh(geom, materials);
      box.castShadow = true;
      box.receiveShadow = true;

      const tapeMaterial = new THREE.MeshStandardMaterial({
        color: colors.tape,
        roughness: 0.82,
        metalness: 0.01,
        transparent: true,
        opacity: 0.72,
      });
      const topTape = new THREE.Mesh(
        new THREE.BoxGeometry(width * 0.18, 0.012, depth * 1.03),
        tapeMaterial,
      );
      topTape.position.y = height / 2 + 0.008;
      box.add(topTape);

      const frontTape = new THREE.Mesh(
        new THREE.BoxGeometry(width * 0.16, height * 0.96, 0.012),
        tapeMaterial,
      );
      frontTape.position.z = depth / 2 + 0.008;
      box.add(frontTape);

      const tagMaterial = new THREE.MeshBasicMaterial({ color: status.color });
      const tag = new THREE.Mesh(new THREE.BoxGeometry(width * 0.22, height * 0.10, 0.014), tagMaterial);
      tag.position.set(width * 0.28, height * 0.30, depth / 2 + 0.018);
      box.add(tag);

      // Тонкие ребра, чтобы коробка была видна как объёмный объект
      const edges = new THREE.EdgesGeometry(geom);
      const lineMat = new THREE.LineBasicMaterial({ color: 0x22160d, transparent: true, opacity: 0.42 });
      const line = new THREE.LineSegments(edges, lineMat);
      box.add(line);
      return box;
    }

    function expandStockUnits(stocks, maxUnits) {
      const units = [];
      for (const stock of stocks) {
        const qty = Math.max(0, Number(stock.qty || 0));
        const wholeUnits = Math.floor(qty);
        const unitCount = Math.max(1, wholeUnits);
        for (let i = 0; i < unitCount && units.length < maxUnits; i++) {
          units.push({
            ...stock,
            qty: 1,
            visualIndex: i + 1,
            visualTotal: unitCount,
            originalQty: qty,
          });
        }
        if (units.length >= maxUnits) break;
      }
      return units;
    }

    function getRackStorageLevels(height) {
      const rawLevels = [0.5, height / 2, Math.max(0.5, height - 0.5)];
      const uniqueLevels = [];
      rawLevels.forEach((level) => {
        const clampedLevel = Math.max(0.12, Math.min(height - 0.08, level));
        if (!uniqueLevels.some((existing) => Math.abs(existing - clampedLevel) < 0.08)) {
          uniqueLevels.push(clampedLevel);
        }
      });

      return uniqueLevels.map((deckY, index) => ({
        deckY,
        boxBaseY: deckY + 0.055,
        level: index + 1,
      }));
    }

    function addRackLevelMarkers(group, width, depth, storageLevels) {
      const levelColors = [0x38bdf8, 0x22c55e, 0xf59e0b, 0xa78bfa];
      storageLevels.forEach((storageLevel, index) => {
        const marker = new THREE.Mesh(
          new THREE.BoxGeometry(width * 0.88, 0.026, 0.035),
          new THREE.MeshBasicMaterial({
            color: levelColors[index % levelColors.length],
            transparent: true,
            opacity: 0.72,
          }),
        );
        marker.position.set(0, storageLevel.deckY + 0.045, depth / 2 + 0.03);
        marker.userData.kind = 'rack-level-marker';
        group.add(marker);
      });
    }

    /**
     * Рендерит товары на одном объекте (или для всех, если objId опущен).
     * Товары становятся children объекта → drag двигает их вместе.
     */
    function placeProductsOnShelves(targetObjId) {
      const stocksByLoc = cfg.stocksByLocation || {};

      const handleOne = (wrap) => {
        const objId = wrap.id;
        if (!objId) return;
        const locId = wrap.storageLocationId;
        if (!locId) return;

        // Снимем старую группу, если была (важно при пересборке)
        if (state.productGroups.has(objId)) {
          const old = state.productGroups.get(objId);
          if (old.parent) old.parent.remove(old);
          state.productGroups.delete(objId);
        }

        const stocks = stocksByLoc[locId];
        if (!stocks || !stocks.length) return;

        const W = wrap.size.width;
        const D = wrap.size.depth;
        const H = wrap.size.height;
        const isRack = wrap.type === 'RACK';

        // Кладём коробки в локальную группу — её вешаем как child объекта
        const group = new THREE.Group();
        group.userData.kind = 'products';

        // Уровни хранения в локальной системе объекта.
        // RACK в editor.js — это группа с нулём у пола: полки стоят на 0.5, H/2, H-0.5.
        // Обычные объекты — Mesh с центром в середине, поэтому товар кладём на верхнюю грань.
        const storageLevels = isRack
          ? getRackStorageLevels(H)
          : [{ deckY: H / 2, boxBaseY: H / 2 + 0.02, level: 1 }];
        if (isRack) addRackLevelMarkers(group, W, D, storageLevels);

        // Кол-во колонок зависит от ширины объекта
        const cols = Math.max(2, Math.min(8, Math.floor(W / 0.35)));
        // Кол-во рядов по глубине: 1 для тонких, 2 для глубоких
        const rows = D >= 0.7 ? 2 : 1;
        const slotsPerLevel = cols * rows;
        const maxVisualUnits = Math.max(1, slotsPerLevel * storageLevels.length);
        const productUnits = expandStockUnits(stocks, maxVisualUnits);

        let placed = 0;
        for (let lvl = 0; lvl < storageLevels.length && placed < productUnits.length; lvl++) {
          const storageLevel = storageLevels[lvl];
          for (let r = 0; r < rows && placed < productUnits.length; r++) {
            for (let c = 0; c < cols && placed < productUnits.length; c++) {
              const s = productUnits[placed];
              const seed = hashString(`${s.product_sku || ''}:${s.batch_no || ''}:${storageLevel.level}:${s.visualIndex || placed}:${placed}`);
              const qtyFactor = Math.min(1.0, 0.6 + Math.log10((s.qty || 1) + 1) * 0.2);
              // Размер коробки
              const slotW = (W * 0.92) / cols;
              const slotD = (D * 0.85) / rows;
              const widthJitter = 0.84 + (seed % 17) / 100;
              const depthJitter = 0.82 + ((seed >> 4) % 19) / 100;
              const bw = slotW * widthJitter;
              const bd = slotD * depthJitter;
              const bh = Math.min(
                isRack ? Math.max(0.22, (H / storageLevels.length) * 0.42) : 0.35,
                0.18 + qtyFactor * (0.24 + ((seed >> 8) % 7) / 100),
              );

              const box = makeProductBox(bw, bh, bd, s, placed, seed);
              // Локальные координаты (относительно центра объекта)
              const jitterX = (((seed >> 2) % 101) / 100 - 0.5) * slotW * 0.14;
              const jitterZ = (((seed >> 6) % 101) / 100 - 0.5) * slotD * 0.12;
              const localX = -W / 2 + slotW * (c + 0.5) + W * 0.04 + jitterX;
              const localZ = -D / 2 + slotD * (r + 0.5) + D * 0.075 + jitterZ;
              const localY = storageLevel.boxBaseY + bh / 2;

              box.position.set(localX, localY, localZ);
              box.rotation.y = (((seed >> 10) % 9) - 4) * Math.PI / 720;
              box.rotation.x = (((seed >> 14) % 5) - 2) * Math.PI / 1800;
              box.userData.product = s;
              box.userData.parentObjectId = objId;
              box.userData.rackLevel = storageLevel.level;
              group.add(box);
              placed++;
            }
          }
        }

        // Привязываем к мешу объекта (parent-child)
        wrap.mesh.add(group);
        state.productGroups.set(objId, group);
      };

      if (targetObjId) {
        const wrap = api.storageObjects.get(targetObjId);
        if (wrap) handleOne(wrap);
        return;
      }
      api.storageObjects.forEach(handleOne);
    }
    // Экспортируем, чтобы editor.js мог вызывать после save_object
    window.WAREHOUSE_3D.refreshProductsOnObject = placeProductsOnShelves;

    // ═══════════════════════════════════════════════════════════
    //  Hover-tooltip над товарами (показывает SKU + qty)
    // ═══════════════════════════════════════════════════════════
    function setupProductHover() {
      const canvas = api.renderer.domElement;
      const tip = document.createElement('div');
      tip.style.cssText = 'position:absolute;pointer-events:none;background:rgba(0,0,0,.8);color:#fff;padding:6px 10px;border-radius:6px;font-size:12px;z-index:20;display:none;';
      const container = document.getElementById('canvas-container');
      container.appendChild(tip);

      canvas.addEventListener('mousemove', (e) => {
        if (state.pickerActive) { tip.style.display = 'none'; return; }
        const rect = canvas.getBoundingClientRect();
        const mouse = new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          -((e.clientY - rect.top) / rect.height) * 2 + 1
        );
        api.raycaster.setFromCamera(mouse, api.camera);
        const candidates = [];
        state.productGroups.forEach(g => g.children.forEach(c => { if (c.isMesh && c.userData.product) candidates.push(c); }));
        const hits = api.raycaster.intersectObjects(candidates, false);
        if (hits.length) {
          const h = hits[0].object;
          const p = h.userData.product;
          if (p) {
            const rackLevel = h.userData.rackLevel ? ` · этаж ${h.userData.rackLevel}` : '';
            tip.innerHTML = `<strong>${p.product_sku}</strong> — ${p.product_name}<br>${p.qty} шт.${rackLevel}${p.batch_no ? ' · ' + p.batch_no : ''}${p.expiry_date ? ' · ⏳ ' + p.expiry_date : ''}`;
            tip.style.left = (e.clientX - rect.left + 12) + 'px';
            tip.style.top = (e.clientY - rect.top + 12) + 'px';
            tip.style.display = 'block';
            return;
          }
        }
        tip.style.display = 'none';
      });
      canvas.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    }

    // ═══════════════════════════════════════════════════════════
    //  Help-overlay (горячие клавиши, ?/h)
    // ═══════════════════════════════════════════════════════════
    function setupHelp() {
      const overlay = document.createElement('div');
      overlay.className = 'w3d-help-overlay';
      overlay.hidden = true;
      overlay.innerHTML = `
        <div class="w3d-help-card">
          <div class="w3d-help-card__header">
            <h3>Горячие клавиши 3D-склада</h3>
            <button type="button" class="w3d-help-card__close" aria-label="Закрыть">×</button>
          </div>
          <div class="w3d-help-card__grid">
            <div class="w3d-help-section">
              <h4>Размещение объектов (режим редактирования)</h4>
              <div><kbd>R</kbd> Стеллаж</div>
              <div><kbd>S</kbd> Полка</div>
              <div><kbd>C</kbd> Ячейка</div>
              <div><kbd>F</kbd> Напольное место</div>
              <div><kbd>Del</kbd> Удалить выбранный</div>
              <div><kbd>↑</kbd> / <kbd>↓</kbd> Уровень полки</div>
              <div><kbd>Esc</kbd> Снять выделение / закрыть</div>
              <div><kbd>Space</kbd> Камера ↔ объекты</div>
            </div>
            <div class="w3d-help-section">
              <h4>Камера</h4>
              <div><kbd>1</kbd> Сверху</div>
              <div><kbd>2</kbd> Изометрия</div>
              <div><kbd>3</kbd> Сброс</div>
              <div><kbd>P</kbd> Picker (FPS), <kbd>ЛКМ</kbd> выбрать</div>
              <div><kbd>M</kbd> Мини-карта</div>
            </div>
            <div class="w3d-help-section">
              <h4>Layout</h4>
              <div><kbd>Backspace</kbd> Убрать последнюю точку разметки</div>
              <div><kbd>Enter</kbd> Завершить разметку</div>
              <div><kbd>Ctrl</kbd>+<kbd>Z</kbd> Отменить</div>
              <div><kbd>Ctrl</kbd>+<kbd>Y</kbd> Повторить</div>
              <div><kbd>G</kbd> Snap-to-grid вкл/выкл</div>
            </div>
            <div class="w3d-help-section">
              <h4>Прочее</h4>
              <div><kbd>T</kbd> Сменить тему</div>
              <div><kbd>?</kbd> / <kbd>H</kbd> Эта справка</div>
            </div>
          </div>
          <div class="w3d-help-card__footer">
            <small>Подсказка: горячие клавиши не работают, когда курсор находится в поле ввода.</small>
          </div>
        </div>`;
      document.body.appendChild(overlay);

      const close = () => { overlay.hidden = true; };
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('.w3d-help-card__close').addEventListener('click', close);

      window.WAREHOUSE_3D.toggleHelp = () => { overlay.hidden = !overlay.hidden; };
      window.WAREHOUSE_3D.closeHelp = close;
    }

    // ═══════════════════════════════════════════════════════════
    //  Тема: синхронизация со <html data-theme>
    // ═══════════════════════════════════════════════════════════
    function applySceneTheme() {
      const theme = document.documentElement.getAttribute('data-theme') || 'light';
      const isDark = theme === 'dark';
      // Цвета сцены / пола / сетки / стен
      const bg = isDark ? 0x0a0e27 : 0xf2f4f8;
      const floor = isDark ? 0x1a1f3a : 0xeef0f5;
      const grid = isDark ? 0x2a2f4a : 0xc5cad8;
      const grid2 = isDark ? 0x1a1f3a : 0xd8dde8;
      const ambient = isDark ? 0.6 : 0.75;
      const dirIntensity = isDark ? 0.8 : 1.05;

      api.scene.background = new THREE.Color(bg);

      // Пол
      api.scene.traverse(obj => {
        if (obj.isMesh && obj.geometry && obj.geometry.type === 'PlaneGeometry'
            && obj.rotation.x < -1) { // повёрнут на -PI/2 → это пол
          obj.material.color.setHex(floor);
        }
        if (obj.isMesh && obj.geometry && obj.geometry.type === 'ShapeGeometry') {
          obj.material.color.setHex(floor);
        }
        if (obj.isLight && obj.isAmbientLight) obj.intensity = ambient;
        if (obj.isLight && obj.isDirectionalLight) obj.intensity = dirIntensity;
        // GridHelper
        if (obj.type === 'GridHelper') {
          if (obj.material && Array.isArray(obj.material)) {
            obj.material[0].color.setHex(grid);
            obj.material[1].color.setHex(grid2);
          } else if (obj.material && obj.material.color) {
            obj.material.color.setHex(grid);
          }
        }
      });
    }
    function setupTheme() {
      window.WAREHOUSE_3D.toggleTheme = () => {
        const btn = document.getElementById('theme-toggle');
        if (btn) btn.click();
        else {
          const cur = document.documentElement.getAttribute('data-theme') || 'light';
          const next = cur === 'dark' ? 'light' : 'dark';
          document.documentElement.setAttribute('data-theme', next);
          try { localStorage.setItem('wms-theme', next); } catch (_) {}
          applySceneTheme();
        }
      };
      // Реагируем на изменения <html data-theme>
      const mo = new MutationObserver(() => applySceneTheme());
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
      // первое применение
      applySceneTheme();
    }

    // ═══════════════════════════════════════════════════════════
    //  Публичные undo/redo (используются hotkey-ами Ctrl+Z/Y)
    // ═══════════════════════════════════════════════════════════
    function setupPublicUndoRedo() {
      window.WAREHOUSE_3D.undo = () => {
        const btn = document.getElementById('btn-undo');
        if (btn) btn.click();
      };
      window.WAREHOUSE_3D.redo = () => {
        const btn = document.getElementById('btn-redo');
        if (btn) btn.click();
      };
    }

    // ═══════════════════════════════════════════════════════════
    //  Оживление готовых панелей: bulk, audit, pickpath, live, stocks
    // ═══════════════════════════════════════════════════════════
    function bindDialogCloseButtons() {
      document.querySelectorAll('[data-close]').forEach(btn => {
        btn.addEventListener('click', () => {
          const dialog = document.getElementById(btn.dataset.close);
          if (dialog && typeof dialog.close === 'function') dialog.close();
        });
      });
    }

    function bindBulkGenerate() {
      const openBtn = document.getElementById('btn-bulk-generate');
      const dialog = document.getElementById('bulk-gen-dialog');
      const submitBtn = document.getElementById('btn-bulk-gen-submit');
      if (!openBtn || !dialog || !submitBtn) return;
      openBtn.addEventListener('click', () => dialog.showModal());
      submitBtn.addEventListener('click', () => {
        const payload = {
          object_type: document.getElementById('bulk-gen-type').value,
          code_prefix: document.getElementById('bulk-gen-prefix').value.trim(),
          count: parseInt(document.getElementById('bulk-gen-count').value || '1', 10),
          step: parseFloat(document.getElementById('bulk-gen-step').value || '2.5'),
          start_x: parseFloat(document.getElementById('bulk-gen-x').value || '0'),
          start_z: parseFloat(document.getElementById('bulk-gen-z').value || '0'),
          direction: document.getElementById('bulk-gen-direction').value,
          width: parseFloat(document.getElementById('bulk-gen-w').value || '2'),
          depth: parseFloat(document.getElementById('bulk-gen-d').value || '1'),
          height: parseFloat(document.getElementById('bulk-gen-h').value || '2.5'),
        };
        fetch(cfg.urls.bulkGenerate, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
          body: JSON.stringify(payload),
        }).then(r => r.json()).then(d => {
          if (!d.success) return showToast(d.error || 'Не удалось создать ряд', 'err');
          showToast(d.message || 'Ряд объектов создан', 'ok');
          dialog.close();
          setTimeout(() => location.reload(), 700);
        }).catch(() => showToast('Сетевая ошибка при создании ряда', 'err'));
      });
    }

    function bindAuditTimeline() {
      const box = document.getElementById('audit-timeline');
      const refreshBtn = document.getElementById('btn-refresh-audit');
      if (!box || !cfg.urls.audit) return;

      const render = (items) => {
        if (!items.length) {
          box.innerHTML = '<p class="tool-section__desc tool-section__desc--compact">Пока нет изменений.</p>';
          return;
        }
        box.innerHTML = items.map(item => {
          const rollback = item.rollbackable
            ? `<button type="button" class="btn btn--ghost btn--small" data-rollback="${item.id}">Откатить</button>`
            : '';
          const date = item.timestamp ? new Date(item.timestamp).toLocaleString() : '';
          return `
            <div class="audit-timeline__item">
              <div class="audit-timeline__main">
                <strong>${esc(item.action_label || item.action)}</strong>
                <span>${esc(item.resource_str || ('#' + item.resource_id))}</span>
              </div>
              <div class="audit-timeline__meta">${esc(item.user)} · ${esc(date)}</div>
              ${rollback}
            </div>`;
        }).join('');
        box.querySelectorAll('[data-rollback]').forEach(btn => {
          btn.addEventListener('click', () => {
            if (!confirm('Откатить это изменение layout?')) return;
            fetch(withObjectId(cfg.urls.auditRollback, btn.dataset.rollback), {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'X-CSRFToken': getCsrf() },
            }).then(r => r.json()).then(d => {
              if (!d.success) return showToast(d.error || 'Откат не выполнен', 'err');
              showToast(d.message || 'Изменение откачено', 'ok');
              setTimeout(() => location.reload(), 700);
            }).catch(() => showToast('Сетевая ошибка при откате', 'err'));
          });
        });
      };

      const load = () => {
        fetch(cfg.urls.audit + '?limit=12', { credentials: 'same-origin' })
          .then(r => r.json())
          .then(d => render(d.items || []))
          .catch(() => { box.innerHTML = '<p class="tool-section__desc tool-section__desc--compact">Не удалось загрузить журнал.</p>'; });
      };
      if (refreshBtn) refreshBtn.addEventListener('click', load);
      load();
    }

    function clearPickPath() {
      if (state.pickPathGroup) {
        api.scene.remove(state.pickPathGroup);
        state.pickPathGroup = null;
      }
      state.pickPathWaypoints = [];
      state.pickerRouteIndex = 0;
    }

    function drawPickPath(data) {
      clearPickPath();
      state.pickPathWaypoints = (data.path || []).filter(p => typeof p.x === 'number' && typeof p.z === 'number');
      state.pickerRouteIndex = 0;
      const points = [];
      if (data.gate) points.push(new THREE.Vector3(data.gate.x, 0.08, data.gate.z));
      (data.path || []).forEach(p => points.push(new THREE.Vector3(p.x, 0.08, p.z)));
      if (data.gate && points.length > 1) points.push(new THREE.Vector3(data.gate.x, 0.08, data.gate.z));
      if (points.length < 2) return;

      const group = new THREE.Group();
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: 0xffb020, linewidth: 3 })
      );
      group.add(line);
      points.forEach((p, idx) => {
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(idx === 0 || idx === points.length - 1 ? 0.22 : 0.16, 16, 12),
          new THREE.MeshBasicMaterial({ color: idx === 0 || idx === points.length - 1 ? 0x16a34a : 0xffb020 })
        );
        marker.position.copy(p);
        group.add(marker);
      });
      state.pickPathGroup = group;
      api.scene.add(group);
    }

    function bindPickPath() {
      const input = document.getElementById('pickpath-skus');
      const buildBtn = document.getElementById('btn-pickpath-build');
      const clearBtn = document.getElementById('btn-pickpath-clear');
      const result = document.getElementById('pickpath-result');
      if (!input || !buildBtn || !clearBtn || !result) return;

      buildBtn.addEventListener('click', () => {
        const skus = input.value.trim();
        if (!skus) return showToast('Введите SKU для маршрута');
        fetch(cfg.urls.pickPath + '?skus=' + encodeURIComponent(skus), { credentials: 'same-origin' })
          .then(r => r.json())
          .then(d => {
            drawPickPath(d);
            const rows = (d.path || []).map(p => `<div>${p.step}. <strong>${esc(p.product_sku)}</strong> → ${esc(p.object_code || p.object_id)} <small>${esc(p.location_code)} · ${p.qty_available} шт.</small></div>`).join('');
            const missing = (d.missing || []).length ? `<div class="pickpath-result__missing">Не найдено: ${esc(d.missing.join(', '))}</div>` : '';
            const pickerHint = (d.path || []).length ? '<div class="pickpath-result__picker">В picker mode подсказка снизу будет вести к следующей позиции маршрута.</div>' : '';
            result.innerHTML = `<div class="pickpath-result__distance">Маршрут: ${d.total_distance || 0} м</div>${rows || '<div>Нет точек маршрута.</div>'}${pickerHint}${missing}`;
            result.hidden = false;
            showToast('Маршрут построен', 'ok');
          }).catch(() => showToast('Не удалось построить маршрут', 'err'));
      });
      clearBtn.addEventListener('click', () => {
        clearPickPath();
        result.hidden = true;
        input.value = '';
      });
    }

    function addLiveAnimation(item) {
      const from = item.from || cfg.gate || { x: 0, z: 0 };
      const to = item.to || cfg.gate || { x: 0, z: 0 };
      const box = new THREE.Mesh(
        new THREE.BoxGeometry(0.45, 0.35, 0.45),
        new THREE.MeshStandardMaterial({ color: 0xffd166, roughness: 0.7 })
      );
      box.position.set(from.x, 0.45, from.z);
      api.scene.add(box);
      state.liveAnimations.push({
        mesh: box,
        from: new THREE.Vector3(from.x, 0.45, from.z),
        to: new THREE.Vector3(to.x, 0.45, to.z),
        start: performance.now(),
        duration: 1200,
      });
    }

    function bindLiveMovements() {
      const btn = document.getElementById('btn-toggle-live');
      const feed = document.getElementById('live-feed');
      if (!btn || !feed) return;

      const tick = () => {
        fetch(cfg.urls.recentMovements + '?since=' + state.liveLastId, { credentials: 'same-origin' })
          .then(r => r.json())
          .then(d => {
            state.liveLastId = d.last_id || state.liveLastId;
            (d.items || []).forEach(item => {
              addLiveAnimation(item);
              const row = document.createElement('div');
              row.className = 'live-feed__item';
              row.innerHTML = `<strong>${esc(item.type_label || item.type)}</strong> ${esc(item.product_sku)} · ${item.quantity} шт.`;
              feed.prepend(row);
              while (feed.children.length > 8) feed.lastChild.remove();
            });
          }).catch(() => showToast('Live-режим: ошибка обновления', 'err'));
      };

      btn.addEventListener('click', () => {
        state.liveEnabled = !state.liveEnabled;
        btn.dataset.active = state.liveEnabled ? 'true' : 'false';
        btn.classList.toggle('is-active', state.liveEnabled);
        btn.querySelector('span').textContent = state.liveEnabled ? '■ Выключить live-режим' : '▶ Включить live-режим';
        if (state.liveEnabled) {
          tick();
          state.liveTimer = setInterval(tick, 5000);
          showToast('Live-режим включён', 'ok');
        } else {
          clearInterval(state.liveTimer);
          state.liveTimer = null;
          showToast('Live-режим выключен');
        }
      });

      api._hooks.onAfterRender.push(() => {
        const now = performance.now();
        state.liveAnimations = state.liveAnimations.filter(anim => {
          const t = Math.min(1, (now - anim.start) / anim.duration);
          anim.mesh.position.lerpVectors(anim.from, anim.to, t);
          if (t >= 1) {
            api.scene.remove(anim.mesh);
            return false;
          }
          return true;
        });
      });
    }

    function locationLabel(locationId) {
      const loc = (cfg.storageLocations || []).find(x => String(x.id) === String(locationId));
      return loc ? `${loc.label}${loc.name ? ' — ' + loc.name : ''}` : 'Не привязано';
    }

    function showObjectCard(wrap) {
      const card = document.getElementById('object-focus-card');
      if (!card || !wrap) return;
      const fill = state.fillByObject[wrap.id] || {};
      const pct = Math.round((fill.pct || 0) * 100);
      card.hidden = false;
      card.classList.toggle('object-focus-card--picker', Boolean(state.pickerActive));
      card.innerHTML = `
        <button type="button" class="object-focus-card__close" data-card-close aria-label="Закрыть">×</button>
        <div class="object-focus-card__eyebrow">${esc(wrap.type)} · ${esc(locationLabel(wrap.storageLocationId))}</div>
        <h3>${esc(wrap.code || ('#' + (wrap.id || 'новый объект')))}</h3>
        <p>${esc(wrap.name || 'Без названия')}</p>
        <div class="object-focus-card__stats">
          <span>${pct}% заполнено</span>
          <span>${fill.qty || 0} шт.</span>
          <span>${fill.products || 0} SKU</span>
        </div>
        <div class="object-focus-card__actions">
          ${wrap.id ? `<a class="btn btn--ghost btn--small" href="${withObjectId(cfg.urls.objectQr, wrap.id)}" target="_blank">QR</a>` : ''}
          ${wrap.id ? '<button type="button" class="btn btn--ghost btn--small" data-card-stocks>Товары</button>' : ''}
        </div>
        <div class="object-focus-card__stocks" data-card-stock-list hidden></div>
      `;
      card.querySelector('[data-card-close]').addEventListener('click', () => {
        card.hidden = true;
        card.classList.remove('object-focus-card--picker');
      });
      const stocksBtn = card.querySelector('[data-card-stocks]');
      if (stocksBtn) {
        stocksBtn.addEventListener('click', () => loadObjectStocks(wrap, card.querySelector('[data-card-stock-list]')));
      }
    }

    function focusObject(wrap, openCard) {
      if (!wrap || !wrap.mesh) return;
      const targetPos = wrap.mesh.position.clone();
      const target = new THREE.Vector3(targetPos.x + 5, Math.max(5, targetPos.y + 4), targetPos.z + 6);
      flyCameraTo(target, new THREE.Vector3(targetPos.x, targetPos.y, targetPos.z));
      highlightObject(wrap.id);
      if (api.selectObject && cfg.canEdit) api.selectObject(wrap);
      if (openCard) showObjectCard(wrap);
    }

    function loadObjectStocks(wrap, container) {
      if (!wrap || !wrap.id || !container) return;
      container.hidden = false;
      container.innerHTML = '<div class="object-focus-card__empty">Загрузка товаров…</div>';
      fetch(withObjectId(cfg.urls.objectStocks, wrap.id), { credentials: 'same-origin' })
        .then(r => r.json())
        .then(d => {
          const items = d.items || [];
          if (!items.length) {
            container.innerHTML = '<div class="object-focus-card__empty">На объекте нет товаров.</div>';
            return;
          }
          container.innerHTML = items.map(stock => `
            <div class="object-focus-card__stock">
              <div><strong>${esc(stock.product_sku)}</strong><small>${esc(stock.product_name)} · ${stock.qty_available} шт.</small></div>
              ${cfg.canEdit ? `<button type="button" class="btn btn--ghost btn--small" data-stock-id="${stock.stock_id}">Действие</button>` : ''}
            </div>
          `).join('');
          container.querySelectorAll('[data-stock-id]').forEach(btn => {
            const stock = items.find(x => String(x.stock_id) === String(btn.dataset.stockId));
            btn.addEventListener('click', () => openStockDialog(wrap, stock));
          });
        }).catch(() => { container.innerHTML = '<div class="object-focus-card__empty">Не удалось загрузить товары.</div>'; });
    }

    function openStockDialog(wrap, stock) {
      const dialog = document.getElementById('stock-edit-dialog');
      if (!dialog || !wrap || !stock) return;
      const info = document.getElementById('stock-edit-info');
      const action = document.getElementById('stock-edit-action');
      const targetWrap = document.getElementById('stock-edit-target-wrap');
      const target = document.getElementById('stock-edit-target');
      const qty = document.getElementById('stock-edit-qty');
      const reason = document.getElementById('stock-edit-reason');
      const comment = document.getElementById('stock-edit-comment');
      const submit = document.getElementById('btn-stock-edit-submit');

      info.textContent = `${stock.product_sku} — ${stock.product_name}. Доступно: ${stock.qty_available} шт.`;
      qty.value = stock.qty_available;
      reason.value = '';
      comment.value = '';
      target.innerHTML = '';
      api.storageObjects.forEach(candidate => {
        if (!candidate.id || candidate.id === wrap.id || !candidate.storageLocationId) return;
        const option = document.createElement('option');
        option.value = candidate.id;
        option.textContent = `${candidate.code || '#' + candidate.id} · ${locationLabel(candidate.storageLocationId)}`;
        target.appendChild(option);
      });

      const updateTarget = () => {
        targetWrap.style.display = action.value === 'transfer' ? 'block' : 'none';
      };
      action.onchange = updateTarget;
      updateTarget();

      submit.onclick = () => {
        const payload = {
          action: action.value,
          stock_id: stock.stock_id,
          qty: parseFloat(qty.value || '0'),
          target_object_id: target.value || null,
          reason: reason.value,
          comment: comment.value,
        };
        fetch(withObjectId(cfg.urls.stockAction, wrap.id), {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
          body: JSON.stringify(payload),
        }).then(r => r.json()).then(d => {
          if (!d.success) return showToast(d.error || 'Действие не выполнено', 'err');
          showToast(d.message || 'Остаток обновлён', 'ok');
          dialog.close();
          setTimeout(() => location.reload(), 800);
        }).catch(() => showToast('Сетевая ошибка при операции с товаром', 'err'));
      };

      dialog.showModal();
    }

    function findObjectFromCanvasEvent(event) {
      const rect = api.renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
      );
      api.raycaster.setFromCamera(mouse, api.camera);
      const meshes = Array.from(api.storageObjects.values()).map(obj => obj.mesh).filter(Boolean);
      const hits = api.raycaster.intersectObjects(meshes, true);
      if (!hits.length) return null;
      const hit = hits[0].object;
      for (const [, wrap] of api.storageObjects.entries()) {
        let found = wrap.mesh === hit;
        if (!found && wrap.mesh && wrap.mesh.traverse) {
          wrap.mesh.traverse(child => { if (child === hit) found = true; });
        }
        if (found) return wrap;
      }
      return null;
    }

    function bindObjectCardAndFocus() {
      document.addEventListener('warehouse3d:object-selected', e => {
        applyLayerVisibility();
        showObjectCard(e.detail);
      });
      document.addEventListener('warehouse3d:object-deselected', () => {
        const card = document.getElementById('object-focus-card');
        if (card) card.hidden = true;
      });

      api.renderer.domElement.addEventListener('click', (event) => {
        if (cfg.canEdit) return;
        const wrap = findObjectFromCanvasEvent(event);
        if (wrap) showObjectCard(wrap);
      });

      if (cfg.focusObjectId) {
        setTimeout(() => {
          const wrap = api.storageObjects.get(Number(cfg.focusObjectId)) || api.storageObjects.get(String(cfg.focusObjectId));
          if (wrap) focusObject(wrap, true);
        }, 350);
      }
      window.WAREHOUSE_3D.focusObject = (objectId) => {
        const wrap = api.storageObjects.get(Number(objectId)) || api.storageObjects.get(String(objectId));
        focusObject(wrap, true);
      };
    }

    // ═══════════════════════════════════════════════════════════
    //  Инициализация
    // ═══════════════════════════════════════════════════════════
    bindHeatmapToggle();
    bindMovementHeatmap();
    bindSearch();
    bindWallsRebuild();
    setupMinimap();
    setupPickerMode();
    bindUndoRedo();
    bindLayerToggles();
    bindImport();
    bindDialogCloseButtons();
    bindBulkGenerate();
    bindAuditTimeline();
    bindPickPath();
    bindLiveMovements();
    placeProductsOnShelves();
    setupProductHover();
    setupHelp();
    setupTheme();
    setupPublicUndoRedo();
    bindObjectCardAndFocus();

    console.log('[Warehouse3D Features] All 10 improvements + theme/help initialized');
  }

  // Ждём готовности editor.js
  if (window.WAREHOUSE_3D) {
    onReady(window.WAREHOUSE_3D);
  } else {
    document.addEventListener('warehouse3d:ready', (e) => onReady(e.detail));
  }
})();
