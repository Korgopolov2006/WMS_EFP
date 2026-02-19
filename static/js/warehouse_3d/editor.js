/**
 * Warehouse 3D Editor
 * Three.js based 3D warehouse visualization and editing
 */

(function() {
  'use strict';

  const config = window.WAREHOUSE_3D_CONFIG;
  if (!config) {
    console.error('WAREHOUSE_3D_CONFIG not found');
    return;
  }

  // State
  let scene, camera, renderer, controls;
  let raycaster, mouse;
  let floorMesh, wallsGroup;
  let selectedObject = null;
  let isEditMode = config.canEdit;
  let isLayoutMode = false; // Will be set by user action
  let actionHistory = []; // For undo (Ctrl+Z)
  let modalTarget = null; // Object for modal actions
  let isDraggingObject = false;
  let dragStartPos = new THREE.Vector3();
  let savePositionTimeout = null; // Debounce для сохранения позиции
  let wallsVisible = true;
  let wallsTransparent = false;
  let isPanning = false;
  let pendingObjectType = null; // Type of object to add at click position
  let lastClickPosition = null; // Store click position for object placement
  let controlMode = 'camera'; // 'camera' or 'object' - режим управления
  let isFullscreen = false; // Fullscreen mode
  
  // Update UI based on edit mode
  function updateUIForEditMode() {
    const hotkeysPanel = document.getElementById('hotkeys-panel');
    
    if (!config.canEdit || !isEditMode) {
      // Hide hotkeys panel in view mode
      if (hotkeysPanel) {
        hotkeysPanel.style.display = 'none';
      }
      // Disable all edit buttons
      document.querySelectorAll('.tool-btn, #btn-finish-layout, #btn-save-object, #btn-delete-object').forEach(btn => {
        if (btn) {
          btn.disabled = true;
          btn.style.opacity = '0.5';
          btn.style.pointerEvents = 'none';
        }
      });
    } else {
      // Show hotkeys panel in edit mode
      if (hotkeysPanel) {
        hotkeysPanel.style.display = 'block';
      }
      // Enable all edit buttons
      document.querySelectorAll('.tool-btn, #btn-finish-layout, #btn-save-object, #btn-delete-object').forEach(btn => {
        if (btn) {
          btn.disabled = false;
          btn.style.opacity = '1';
          btn.style.pointerEvents = 'auto';
        }
      });
    }
  }
  let floorPoints = [];
  let storageObjects = new Map();
  let isDragging = false;
  let dragOffset = { x: 0, z: 0 };

  // Grid settings
  const GRID_SIZE = 1.0;
  const GRID_DIVISIONS = 50;

  // Object type defaults
  const OBJECT_DEFAULTS = {
    RACK: { width: 2, depth: 1, height: 2.5, color: 0x4a90e2 },
    SHELF: { width: 1.5, depth: 0.8, height: 0.3, color: 0x7c5cff },
    CELL: { width: 0.5, depth: 0.5, height: 0.5, color: 0x2dd4bf },
    FLOOR: { width: 2, depth: 2, height: 0.1, color: 0x94a3b8 }
  };

  // Initialize
  function init() {
    console.log('[Warehouse3D] Initialization started');
    
    const container = document.getElementById('canvas-container');
    if (!container) {
      console.error('[Warehouse3D] Canvas container not found');
      setTimeout(init, 100);
      return;
    }
    
    console.log('[Warehouse3D] Container found:', container.clientWidth, 'x', container.clientHeight);

    // Check if Three.js is loaded
    if (typeof THREE === 'undefined') {
      console.error('[Warehouse3D] Three.js is not loaded');
      setTimeout(init, 100);
      return;
    }
    
    console.log('[Warehouse3D] Three.js loaded, version:', THREE.REVISION);

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0e27);
    console.log('[Warehouse3D] Scene created');

    // Camera (isometric)
    // Wait for container to have proper size
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    
    if (width === 0 || height === 0) {
      console.warn('[Warehouse3D] Container has zero size, retrying...');
      setTimeout(init, 100);
      return;
    }
    
    console.log('[Warehouse3D] Container size:', width, 'x', height);
    
    const aspect = width / height;
    camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 1000);
    setCameraView('iso');
    console.log('[Warehouse3D] Camera created');

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    
    // Ensure canvas has proper styling
    const canvas = renderer.domElement;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    canvas.style.position = 'absolute';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.zIndex = '1';
    
    // Clear any existing canvas
    const existingCanvas = container.querySelector('canvas');
    if (existingCanvas) {
      console.log('[Warehouse3D] Removing existing canvas');
      container.removeChild(existingCanvas);
    }
    
    container.appendChild(canvas);
    console.log('[Warehouse3D] Renderer created and added to DOM');
    console.log('[Warehouse3D] Canvas element:', canvas);
    console.log('[Warehouse3D] Canvas dimensions:', canvas.width, 'x', canvas.height);
    console.log('[Warehouse3D] Canvas style:', {
      width: canvas.style.width,
      height: canvas.style.height,
      display: canvas.style.display,
      position: canvas.style.position
    });

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(10, 20, 10);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    scene.add(directionalLight);

    // Raycaster for mouse picking
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Create floor
    createFloor();

    // Load existing layout
    if (config.layoutDefined && config.floorPoints.length > 0) {
      loadLayout(config.floorPoints);
    }

    // Load storage objects
    if (config.storageObjects) {
      config.storageObjects.forEach(obj => {
        createStorageObject(obj);
      });
    }

    // Controls (simple orbit)
    setupControls();

    // Event listeners
    setupEventListeners();
    
    // Setup modals
    setupModals();
    
    // Start render loop
    animate();
    console.log('[Warehouse3D] Render loop started');
    
    // Инициализация режимов
    // Если есть права на редактирование, начинаем в режиме редактирования
    if (config.canEdit) {
      isEditMode = true;
      // В режиме редактирования начинаем с режима объектов для удобства
      controlMode = 'object';
      if (controls) {
        controls.enabled = false;
      }
      console.log('[Warehouse3D] Initialized in edit mode, object control mode');
    } else {
      isEditMode = false;
      controlMode = 'camera';
      if (controls) {
        controls.enabled = true;
      }
      console.log('[Warehouse3D] Initialized in view mode, camera control mode');
    }
    
    // Update UI for edit mode
    updateUIForEditMode();
    
    // Update mode indicator
    const modeIndicator = document.getElementById('control-mode-indicator');
    if (modeIndicator) {
      modeIndicator.textContent = controlMode === 'camera' ? '🧭 Режим камеры' : '✋ Режим объектов';
    }
    
    // Логирование начального состояния кнопок
    setTimeout(() => {
      logButtonStates();
    }, 100);
    
    // Force initial render
    if (renderer && scene && camera) {
      console.log('[Warehouse3D] Scene children before render:', scene.children.length);
      renderer.render(scene, camera);
      console.log('[Warehouse3D] Initial render completed');
      
      // Verify canvas is visible
      const canvas = renderer.domElement;
      const rect = canvas.getBoundingClientRect();
      console.log('[Warehouse3D] Canvas bounding rect:', {
        width: rect.width,
        height: rect.height,
        top: rect.top,
        left: rect.left,
        visible: rect.width > 0 && rect.height > 0
      });
      
      // Check if canvas is actually in DOM
      const canvasInDOM = container.contains(canvas);
      console.log('[Warehouse3D] Canvas in DOM:', canvasInDOM);
    } else {
      console.error('[Warehouse3D] Cannot render - missing:', {
        renderer: !!renderer,
        scene: !!scene,
        camera: !!camera
      });
    }
    
    // Handle window resize
    setTimeout(() => {
      onWindowResize();
    }, 100);
    
    console.log('[Warehouse3D] Initialization complete');
  }

  function createFloor() {
    console.log('[Warehouse3D] Creating floor...');
    const floorGeometry = new THREE.PlaneGeometry(100, 100);
    const floorMaterial = new THREE.MeshStandardMaterial({
      color: 0x1a1f3a,
      roughness: 0.8,
      metalness: 0.2
    });
    floorMesh = new THREE.Mesh(floorGeometry, floorMaterial);
    floorMesh.rotation.x = -Math.PI / 2;
    floorMesh.receiveShadow = true;
    floorMesh.position.y = 0;
    scene.add(floorMesh);
    console.log('[Warehouse3D] Floor mesh added to scene');

    // Grid helper
    const gridHelper = new THREE.GridHelper(100, 100, 0x2a2f4a, 0x1a1f3a);
    gridHelper.position.y = 0.01; // Slightly above floor
    scene.add(gridHelper);
    console.log('[Warehouse3D] Grid helper added to scene');
    console.log('[Warehouse3D] Scene children count:', scene.children.length);
  }

  function setupControls() {
    console.log('[Warehouse3D] Setting up controls...');
    
    // Use OrbitControls for proper camera management
    // Check if OrbitControls is available (might be loaded as module or global)
    let OrbitControlsClass = null;
    if (typeof THREE !== 'undefined' && typeof THREE.OrbitControls !== 'undefined') {
      OrbitControlsClass = THREE.OrbitControls;
      console.log('[Warehouse3D] OrbitControls found in THREE.OrbitControls');
    } else if (typeof OrbitControls !== 'undefined') {
      OrbitControlsClass = OrbitControls;
      console.log('[Warehouse3D] OrbitControls found as global');
    }
    
    if (!OrbitControlsClass) {
      console.warn('[Warehouse3D] OrbitControls not loaded. Using basic controls.');
      // Fallback to basic controls
      setupBasicControls();
      return;
    }

    try {
      controls = new OrbitControlsClass(camera, renderer.domElement);
      console.log('[Warehouse3D] OrbitControls created successfully');
      
      // Configure OrbitControls
      controls.enableDamping = true;
      controls.dampingFactor = 0.05;
      controls.minDistance = 10;
      controls.maxDistance = 100;
      controls.maxPolarAngle = Math.PI * 0.45; // Limit vertical rotation
      controls.minPolarAngle = Math.PI * 0.1;
      
      // Pan is disabled by default, enabled only with Shift
      controls.enablePan = false;
      controls.panSpeed = 1.0;
      
      // Mouse buttons configuration
      if (THREE.MOUSE) {
        controls.mouseButtons = {
          LEFT: THREE.MOUSE.ROTATE,
          MIDDLE: THREE.MOUSE.DOLLY,
          RIGHT: THREE.MOUSE.PAN
        };
      }
      
      // Custom pan handler for Shift + ЛКМ (PAN)
      // PAN должен работать только в режиме камеры и только с Shift
      // Проверяем что методы существуют перед использованием
      if (controls.onMouseDown && typeof controls.onMouseDown === 'function') {
        const originalOnMouseDown = controls.onMouseDown.bind(controls);
        const originalOnMouseUp = controls.onMouseUp && typeof controls.onMouseUp === 'function' 
          ? controls.onMouseUp.bind(controls) 
          : null;
        
        controls.onMouseDown = function(event) {
          // Если Shift + ЛКМ в режиме камеры - включаем PAN
          if (event.button === 0 && event.shiftKey && controlMode === 'camera' && !isEditMode) {
            controls.enableRotate = false;
            controls.enablePan = true;
            controls.enableDamping = false; // Отключаем damping для более точного PAN
            originalOnMouseDown.call(this, event);
          } else if (!event.shiftKey || controlMode !== 'camera' || isEditMode) {
            // Обычное поведение без Shift
            controls.enableRotate = true;
            controls.enablePan = false;
            originalOnMouseDown.call(this, event);
          }
        };
        
        if (originalOnMouseUp) {
          controls.onMouseUp = function(event) {
            // После отпускания мыши возвращаем обычное состояние
            if (event.button === 0) {
              controls.enableRotate = true;
              controls.enablePan = false;
              controls.enableDamping = true;
            }
            originalOnMouseUp.call(this, event);
          };
        }
      }
      
      console.log('[Warehouse3D] OrbitControls configured');
    } catch (error) {
      console.error('[Warehouse3D] Error creating OrbitControls:', error);
      setupBasicControls();
    }
  }
  
  function setupBasicControls() {
    // Fallback basic controls if OrbitControls not available
    let isMouseDown = false;
    let mouseX = 0, mouseY = 0;
    const minDistance = 10;
    const maxDistance = 100;
    const zoomSpeed = 0.1;

    renderer.domElement.addEventListener('mousedown', (e) => {
      if (e.button === 0 && !isLayoutMode && controlMode === 'camera') {
        if (e.shiftKey) {
          isPanning = true;
        } else {
          isMouseDown = true;
          mouseX = e.clientX;
          mouseY = e.clientY;
        }
      }
    });

    renderer.domElement.addEventListener('mousemove', (e) => {
      if (isPanning && controlMode === 'camera') {
        const deltaX = (e.movementX || 0) * 0.01;
        const deltaY = (e.movementY || 0) * 0.01;
        camera.position.x -= deltaX;
        camera.position.z -= deltaY;
      } else if (isMouseDown && !isDragging && !isLayoutMode && controlMode === 'camera') {
        const deltaX = e.clientX - mouseX;
        const deltaY = e.clientY - mouseY;
        
        const spherical = new THREE.Spherical();
        spherical.setFromVector3(camera.position);
        spherical.theta -= deltaX * 0.005;
        spherical.phi += deltaY * 0.005;
        spherical.phi = Math.max(0.2, Math.min(Math.PI - 0.2, spherical.phi));

        const newPosition = new THREE.Vector3();
        newPosition.setFromSpherical(spherical);
        camera.position.copy(newPosition);
        camera.lookAt(0, 0, 0);

        mouseX = e.clientX;
        mouseY = e.clientY;
      }
    });

    renderer.domElement.addEventListener('mouseup', () => {
      isMouseDown = false;
      isPanning = false;
    });

    renderer.domElement.addEventListener('wheel', (e) => {
      if (controlMode === 'camera') {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 1 + zoomSpeed : 1 - zoomSpeed;
        const currentDistance = camera.position.length();
        const newDistance = currentDistance * delta;
        
        if (newDistance >= minDistance && newDistance <= maxDistance) {
          camera.position.multiplyScalar(delta);
        }
      }
    });
  }

  function setupEventListeners() {
    // Canvas click
    renderer.domElement.addEventListener('click', onCanvasClick);
    renderer.domElement.addEventListener('dblclick', onCanvasDoubleClick); // Двойной клик для удаления
    renderer.domElement.addEventListener('mousemove', onCanvasMouseMove);
    renderer.domElement.addEventListener('mousedown', onCanvasMouseDown);
    renderer.domElement.addEventListener('mouseup', onCanvasMouseUp);

    // Window resize
    window.addEventListener('resize', onWindowResize);

    // Tool buttons
    document.querySelectorAll('.tool-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        addStorageObject(type);
      });
    });

    // Mode toggle
    const modeToggle = document.getElementById('mode-toggle');
    if (modeToggle) {
      modeToggle.addEventListener('click', toggleMode);
    }

    // Finish layout
    const finishLayoutBtn = document.getElementById('btn-finish-layout');
    if (finishLayoutBtn) {
      finishLayoutBtn.addEventListener('click', finishLayout);
    }

    // Camera buttons
    document.querySelectorAll('[data-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        setCameraView(btn.dataset.view);
      });
    });

    // Object properties
    const saveBtn = document.getElementById('btn-save-object');
    const deleteBtn = document.getElementById('btn-delete-object');
    if (saveBtn) saveBtn.addEventListener('click', saveCurrentObject);
    if (deleteBtn) deleteBtn.addEventListener('click', deleteCurrentObject);

    // Warehouse selector
    const warehouseSelector = document.getElementById('warehouse-selector');
    if (warehouseSelector) {
      warehouseSelector.addEventListener('change', (e) => {
        if (e.target.value) {
          // Show loading state
          const container = document.getElementById('canvas-container');
          if (container) {
            container.style.opacity = '0.5';
            container.style.pointerEvents = 'none';
          }
          // Navigate to new warehouse
          window.location.href = e.target.value;
        }
      });
    }

    // Hotkeys
    document.addEventListener('keydown', onKeyDown);
    
    // Fullscreen button
    const fullscreenBtn = document.getElementById('btn-fullscreen');
    if (fullscreenBtn) {
      fullscreenBtn.addEventListener('click', toggleFullscreen);
    }
    
    // Clear layout button
    const clearLayoutBtn = document.getElementById('btn-clear-layout');
    const clearConfirmDiv = document.getElementById('clear-layout-confirm');
    const clearConfirmInput = document.getElementById('clear-confirm-input');
    const confirmClearBtn = document.getElementById('btn-confirm-clear');
    
    if (clearLayoutBtn && clearConfirmDiv && clearConfirmInput && confirmClearBtn) {
      clearLayoutBtn.addEventListener('click', () => {
        clearConfirmDiv.style.display = clearConfirmDiv.style.display === 'none' ? 'block' : 'none';
        clearConfirmInput.value = '';
        confirmClearBtn.disabled = true;
      });
      
      clearConfirmInput.addEventListener('input', (e) => {
        const confirmText = 'ОЧИСТИТЬ СКЛАД ПОЛНОСТЬЮ';
        confirmClearBtn.disabled = e.target.value !== confirmText;
      });
      
      confirmClearBtn.addEventListener('click', clearLayout);
    }
    
    // Wall controls
    const toggleWallsBtn = document.getElementById('btn-toggle-walls');
    const toggleWallsTransparentBtn = document.getElementById('btn-toggle-walls-transparent');
    
    if (toggleWallsBtn) {
      toggleWallsBtn.addEventListener('click', () => {
        wallsVisible = !wallsVisible;
        if (wallsGroup) {
          wallsGroup.visible = wallsVisible;
        }
        toggleWallsBtn.innerHTML = wallsVisible ? '<span>👁️ Скрыть стены</span>' : '<span>👁️ Показать стены</span>';
      });
    }
    
    if (toggleWallsTransparentBtn) {
      toggleWallsTransparentBtn.addEventListener('click', () => {
        wallsTransparent = !wallsTransparent;
        if (wallsGroup) {
          wallsGroup.children.forEach(wall => {
            if (wall.material) {
              wall.material.transparent = wallsTransparent;
              wall.material.opacity = wallsTransparent ? 0.3 : 1.0;
            }
          });
        }
        toggleWallsTransparentBtn.innerHTML = wallsTransparent ? '<span>🪟 Сделать непрозрачными</span>' : '<span>🪟 Сделать прозрачными</span>';
      });
    }
  }
  
  function setupModals() {
    const canvas = renderer.domElement;
    if (!canvas) return;
    
    // Right click handler - show modals
    // Убрано контекстное меню по требованию пользователя
    canvas.addEventListener('contextmenu', (e) => {
      e.preventDefault(); // Просто блокируем стандартное меню
    });
    
    // Modal close buttons
    document.querySelectorAll('.modal__close').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const modalName = btn.dataset.modal;
        hideModal(modalName);
      });
    });
    
    // Modal overlay click
    document.querySelectorAll('.modal__overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => {
        const modal = overlay.closest('.modal');
        if (modal) {
          hideModal(modal.id.replace('modal-', ''));
        }
      });
    });
    
    // Empty area modal actions
    const emptyModal = document.getElementById('modal-empty');
    if (emptyModal) {
      emptyModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.modal-btn');
        if (!btn) return;
        
        const action = btn.dataset.action;
        if (action === 'add-object') {
          hideModal('empty');
          showModal('add-object');
        } else if (action === 'start-layout') {
          hideModal('empty');
          startLayoutMode();
        } else if (action === 'cancel') {
          hideModal('empty');
        }
      });
    }
    
    // Add object modal actions
    const addObjectModal = document.getElementById('modal-add-object');
    if (addObjectModal) {
      addObjectModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.modal-btn');
        if (!btn) return;
        
        const action = btn.dataset.action;
        const type = btn.dataset.type;
        
      if (action === 'add' && type) {
        hideModal('add-object');
        // Set pending object type - will be created at next click position
        pendingObjectType = type;
        // Show hint
        const canvas = renderer.domElement;
        if (canvas) {
          canvas.style.cursor = 'crosshair';
          canvas.title = 'Кликните по полу, чтобы разместить объект';
        }
      } else if (action === 'cancel') {
        hideModal('add-object');
        pendingObjectType = null;
      }
      });
    }
    
    // Object actions modal
    const objectModal = document.getElementById('modal-object');
    if (objectModal) {
      objectModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.modal-btn');
        if (!btn) return;
        
        const action = btn.dataset.action;
        
        if (action === 'edit' && modalTarget) {
          hideModal('object');
          selectObject(modalTarget);
        } else if (action === 'properties' && modalTarget) {
          hideModal('object');
          selectObject(modalTarget);
        } else if (action === 'delete' && modalTarget) {
          hideModal('object');
          
          // Check for stock
          if (modalTarget && modalTarget.mesh && modalTarget.mesh.userData && modalTarget.mesh.userData.stocks && modalTarget.mesh.userData.stocks.length > 0) {
            const stockCount = modalTarget.mesh.userData.stockCount || 0;
            const totalQty = modalTarget.mesh.userData.totalQty || 0;
            alert(`Невозможно удалить объект: на нём находятся товары (${stockCount} позиций, всего ${totalQty} шт.)`);
            hideModal('object');
            return;
          }
          
          // Удаление без подтверждения (как указано в промпте)
          
          // Delete object
          if (!modalTarget || !modalTarget.id) {
            // Just remove from scene if not saved
            if (modalTarget && modalTarget.mesh) {
              scene.remove(modalTarget.mesh);
              storageObjects.delete(modalTarget.mesh.uuid);
            }
            deselectObject();
            hideModal('object');
            return;
          }
          
          // Delete from server
          const deleteUrl = config.urls.deleteObject.replace('999999', modalTarget.id);
          fetch(deleteUrl, {
            method: 'POST',
            headers: {
              'X-CSRFToken': getCsrfToken()
            }
          })
          .then(response => response.json())
          .then(data => {
            console.log('[Warehouse3D] Delete response:', data);
            if (data.success) {
              if (modalTarget && modalTarget.mesh) {
                scene.remove(modalTarget.mesh);
                console.log('[Warehouse3D] Object removed from scene');
              }
              if (modalTarget && modalTarget.id) {
                storageObjects.delete(modalTarget.id);
                console.log('[Warehouse3D] Object removed from storageObjects:', modalTarget.id);
              }
              deselectObject();
              hideModal('object');
              console.log('[Warehouse3D] Object deleted successfully');
            } else {
              console.error('[Warehouse3D] Delete failed:', data.error);
              alert('Ошибка удаления: ' + (data.error || 'Неизвестная ошибка'));
            }
          })
          .catch(error => {
            console.error('[Warehouse3D] Delete error:', error);
            alert('Ошибка при удалении объекта: ' + error.message);
          });
        } else if (action === 'cancel') {
          hideModal('object');
        }
      });
    }
    
    // Create warehouse modal
    const createWarehouseModal = document.getElementById('modal-create-warehouse');
    if (createWarehouseModal) {
      createWarehouseModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.modal-btn');
        if (!btn) return;
        
        const action = btn.dataset.action;
        
        if (action === 'create-warehouse') {
          createWarehouseBySize();
        } else if (action === 'cancel') {
          hideModal('create-warehouse');
        }
      });
    }
    
    // Start layout button
    const startLayoutBtn = document.getElementById('btn-start-layout');
    if (startLayoutBtn) {
      startLayoutBtn.addEventListener('click', () => {
        startLayoutMode();
      });
    }
    
    // Create by size button
    const createBySizeBtn = document.getElementById('btn-create-by-size');
    if (createBySizeBtn) {
      createBySizeBtn.addEventListener('click', () => {
        showModal('create-warehouse');
      });
    }
  }
  
  function showModal(modalName, obj = null) {
    const modal = document.getElementById(`modal-${modalName}`);
    if (!modal) return;
    
    modalTarget = obj;
    modal.style.display = 'flex';
    modal.classList.add('modal--active');
    
    // Prevent body scroll
    document.body.style.overflow = 'hidden';
  }
  
  function hideModal(modalName) {
    const modal = document.getElementById(`modal-${modalName}`);
    if (modal) {
      modal.style.display = 'none';
      modal.classList.remove('modal--active');
    }
    
    // Restore body scroll
    document.body.style.overflow = '';
    modalTarget = null;
  }
  
  function startLayoutMode() {
    if (!config.canEdit) return;
    isLayoutMode = true;
    const panel = document.getElementById('layout-mode-panel');
    if (panel) panel.style.display = 'block';
    const startBtn = document.getElementById('btn-start-layout');
    const createBtn = document.getElementById('btn-create-by-size');
    if (startBtn) startBtn.style.display = 'none';
    if (createBtn) createBtn.style.display = 'none';
  }
  
  function createWarehouseBySize() {
    const width = parseFloat(document.getElementById('warehouse-width').value) || 10;
    const length = parseFloat(document.getElementById('warehouse-length').value) || 10;
    const height = parseFloat(document.getElementById('warehouse-height').value) || 3;
    
    if (width < 1 || length < 1 || height < 2) {
      alert('Пожалуйста, введите корректные размеры (ширина и длина от 1м, высота от 2м)');
      return;
    }
    
    // Create rectangular floor points
    const halfWidth = width / 2;
    const halfLength = length / 2;
    const floorPoints = [
      [-halfWidth, -halfLength],
      [halfWidth, -halfLength],
      [halfWidth, halfLength],
      [-halfWidth, halfLength]
    ];
    
    // Save layout
    fetch(config.urls.saveLayout, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ floor_points: floorPoints })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        hideModal('create-warehouse');
        location.reload();
      } else {
        alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Ошибка при создании склада');
    });
  }
  
  function clearLayout() {
    if (!confirm('Вы уверены, что хотите полностью очистить разметку склада? Это действие нельзя отменить.')) {
      return;
    }
    
    fetch(config.urls.saveLayout, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ floor_points: [] })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        alert('Разметка склада очищена');
        isEditMode = false;
        location.reload();
      } else {
        alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Ошибка при очистке разметки');
    });
  }

  function onCanvasClick(event) {
    if (!isEditMode || !config.canEdit) return;

    updateMousePosition(event);
    raycaster.setFromCamera(mouse, camera);

    // Check if we need to place a new object (работает в любом режиме редактирования)
    if (pendingObjectType) {
      const intersects = raycaster.intersectObjects([floorMesh], false);
      if (intersects.length > 0) {
        const point = intersects[0].point;
        const x = Math.round(point.x / GRID_SIZE) * GRID_SIZE;
        const z = Math.round(point.z / GRID_SIZE) * GRID_SIZE;
        
        // Check if point is within warehouse bounds
        if (config.layoutDefined && floorPoints && floorPoints.length >= 3) {
          if (!isPointInPolygon(x, z, floorPoints)) {
            alert('Нельзя размещать объекты за пределами склада');
            return;
          }
        }
        
        // Create object at click position
        console.log('[Warehouse3D] Adding object at position:', x, z);
        addStorageObjectAtPosition(pendingObjectType, x, z);
        pendingObjectType = null;
        
        // Reset cursor
        const canvas = renderer.domElement;
        if (canvas) {
          canvas.style.cursor = 'default';
          canvas.title = '';
        }
        return;
      }
    }

    // Не добавляем объект, если кликнули по объекту (чтобы не создавать новый)
    if (event.target === renderer.domElement) {
      if (isLayoutMode) {
        handleLayoutClick();
      } else {
        handleObjectClick();
      }
    }
  }
  
  function addStorageObjectAtPosition(type, x, z) {
    if (!config.canEdit || !isEditMode) {
      alert('У вас нет прав на редактирование этого склада');
      return;
    }
    
    if (!config.layoutDefined) {
      alert('Сначала создайте разметку склада');
      return;
    }

    const defaults = OBJECT_DEFAULTS[type];
    if (!defaults) return;

    const obj = {
      id: null,
      type: type,
      code: '',
      name: '',
      position: { x: x, y: 0, z: z },
      size: { width: defaults.width, depth: defaults.depth, height: defaults.height },
      rotation: 0
    };

    const createdObj = createStorageObject(obj);
    selectObject(createdObj);
    
    // Устанавливаем режим объектов для перетаскивания
    if (isEditMode && config.canEdit) {
      controlMode = 'object';
      if (controls) {
        controls.enabled = false;
      }
      console.log('[Warehouse3D] Control mode set to object for new object');
    }
    
    // Включаем режим перетаскивания сразу после создания
    isDraggingObject = true;
    dragStartPos.copy(createdObj.mesh.position);
    console.log('[Warehouse3D] Object created, ready for drag:', createdObj.type);
    
    // Автоматически сохраняем новый объект на сервер
    if (createdObj && !createdObj.id) {
      console.log('[Warehouse3D] Auto-saving new object...');
      setTimeout(() => {
        saveCurrentObject();
      }, 100);
    }
  }

  function onCanvasMouseMove(event) {
    updateMousePosition(event);
    
    // Если перетаскиваем объект - обрабатываем перетаскивание
    if (isDraggingObject && selectedObject && isEditMode && config.canEdit) {
      if (controls) {
        controls.enabled = false;
      }
      handleObjectDrag();
      return;
    }
    
    // В режиме камеры - OrbitControls обрабатывает движение
    if (!isDraggingObject && !isDragging) {
      if (controls) {
        controls.enabled = (controlMode === 'camera');
      }
    }
  }

  function onCanvasMouseDown(event) {
    updateMousePosition(event);
    
    // В режиме редактирования разрешаем перетаскивание объектов
    if (isEditMode && config.canEdit && !isLayoutMode) {
      // Disable camera controls during object interaction
      if (controls) {
        controls.enabled = false;
      }
      
      raycaster.setFromCamera(mouse, camera);
      
      // Check if clicked on object first
      const objectMeshes = Array.from(storageObjects.values()).map(obj => obj.mesh).filter(m => m);
      const objectIntersects = raycaster.intersectObjects(objectMeshes, true);
      
      if (objectIntersects.length > 0) {
        const clickedMesh = objectIntersects[0].object;
        // Для Group нужно найти родительский объект
        let obj = null;
        for (const [key, storageObj] of storageObjects.entries()) {
          if (storageObj.mesh === clickedMesh) {
            obj = storageObj;
            break;
          }
          // Проверяем дочерние элементы для Group
          if (storageObj.mesh instanceof THREE.Group) {
            storageObj.mesh.traverse((child) => {
              if (child === clickedMesh) {
                obj = storageObj;
              }
            });
            if (obj) break;
          }
        }
        
        if (obj) {
          selectObject(obj);
          isDraggingObject = true;
          dragStartPos.copy(obj.mesh.position);
          controlMode = 'object'; // Устанавливаем режим объектов
          console.log('[Warehouse3D] Started dragging object:', obj.id, 'Type:', obj.type);
          return;
        }
      }

      // Check floor for dragging selected object
      const intersects = raycaster.intersectObjects([floorMesh], false);
      if (intersects.length > 0 && selectedObject) {
        isDraggingObject = true;
        dragStartPos.copy(selectedObject.mesh.position);
        controlMode = 'object'; // Устанавливаем режим объектов
        console.log('[Warehouse3D] Started dragging selected object from floor');
      }
    }
    
    // In camera mode, let OrbitControls handle it (except Shift + LKM for pan)
    if (!isEditMode && controlMode === 'camera' && event.shiftKey && event.button === 0) {
      if (controls) {
        controls.enableRotate = false;
        controls.enablePan = true;
      }
    }
  }

  function onCanvasMouseUp() {
    isDragging = false;
    isDraggingObject = false;
    isPanning = false;
    
    // Re-enable controls after drag
    if (controls && controlMode === 'camera') {
      controls.enabled = true;
      controls.enableRotate = true;
      controls.enablePan = false; // Pan only with Shift
    }
  }

  function updateMousePosition(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  }

  function handleLayoutClick() {
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects([floorMesh], false);
    
    if (intersects.length > 0) {
      const point = intersects[0].point;
      const x = Math.round(point.x / GRID_SIZE) * GRID_SIZE;
      const z = Math.round(point.z / GRID_SIZE) * GRID_SIZE;

      floorPoints.push([x, z]);
      updateLayoutPreview();
      
      const finishBtn = document.getElementById('btn-finish-layout');
      if (finishBtn && floorPoints.length >= 3) {
        finishBtn.disabled = false;
      }
    }
  }

  function handleObjectClick() {
    raycaster.setFromCamera(mouse, camera);
    
    // Check objects first - включая все типы объектов (SHELF, CELL, FLOOR, RACK)
    const objectMeshes = Array.from(storageObjects.values()).map(obj => obj.mesh).filter(m => m);
    console.log('[Warehouse3D] Checking click on', objectMeshes.length, 'objects');
    
    const objectIntersects = raycaster.intersectObjects(objectMeshes, true);
    console.log('[Warehouse3D] Found', objectIntersects.length, 'intersections');
    
    if (objectIntersects.length > 0) {
      const clickedMesh = objectIntersects[0].object;
      console.log('[Warehouse3D] Clicked mesh:', clickedMesh, 'Type:', clickedMesh.type);
      
      // Для Group нужно найти родительский объект
      let obj = null;
      for (const [key, storageObj] of storageObjects.entries()) {
        // Прямое совпадение
        if (storageObj.mesh === clickedMesh) {
          obj = storageObj;
          console.log('[Warehouse3D] Found direct match:', storageObj.type, storageObj.id);
          break;
        }
        // Проверяем дочерние элементы для Group (стеллажи)
        if (storageObj.mesh instanceof THREE.Group) {
          storageObj.mesh.traverse((child) => {
            if (child === clickedMesh) {
              obj = storageObj;
              console.log('[Warehouse3D] Found in Group:', storageObj.type, storageObj.id);
            }
          });
          if (obj) break;
        }
        // Проверяем дочерние элементы для обычных объектов (outline, indicator и т.д.)
        if (storageObj.mesh && storageObj.mesh.children) {
          for (const child of storageObj.mesh.children) {
            if (child === clickedMesh) {
              obj = storageObj;
              console.log('[Warehouse3D] Found in children:', storageObj.type, storageObj.id);
              break;
            }
          }
          if (obj) break;
        }
      }
      
      if (obj) {
        console.log('[Warehouse3D] Selecting object:', obj.type, obj.id);
        selectObject(obj);
        return;
      } else {
        console.log('[Warehouse3D] Object not found in storageObjects');
      }
    }

    // Deselect
    console.log('[Warehouse3D] Deselecting');
    deselectObject();
  }

  function onCanvasDoubleClick(event) {
    // Двойной клик по объекту для удаления
    if (!isEditMode || !config.canEdit) return;
    
    updateMousePosition(event);
    raycaster.setFromCamera(mouse, camera);
    
    const objectMeshes = Array.from(storageObjects.values()).map(obj => obj.mesh).filter(m => m);
    const objectIntersects = raycaster.intersectObjects(objectMeshes, true);
    
    if (objectIntersects.length > 0) {
      const clickedMesh = objectIntersects[0].object;
      let obj = null;
      for (const [key, storageObj] of storageObjects.entries()) {
        // Прямое совпадение
        if (storageObj.mesh === clickedMesh) {
          obj = storageObj;
          break;
        }
        // Проверяем дочерние элементы для Group (стеллажи)
        if (storageObj.mesh instanceof THREE.Group) {
          storageObj.mesh.traverse((child) => {
            if (child === clickedMesh) {
              obj = storageObj;
            }
          });
          if (obj) break;
        }
        // Проверяем дочерние элементы для обычных объектов
        if (storageObj.mesh && storageObj.mesh.children) {
          for (const child of storageObj.mesh.children) {
            if (child === clickedMesh) {
              obj = storageObj;
              break;
            }
          }
          if (obj) break;
        }
      }
      
      if (obj) {
        selectObject(obj);
        deleteCurrentObject();
      }
    }
  }

  function handleObjectDrag() {
    if (!selectedObject) return;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects([floorMesh], false);
    
    if (intersects.length > 0) {
      const point = intersects[0].point;
      
      // ОСОБОЕ ПРАВИЛО ДЛЯ ПОЛОК: прилипание к стенам
      if (selectedObject.type === 'SHELF') {
        handleShelfDrag(point);
        return;
      }
      
      // Обычное перетаскивание для всех остальных объектов
      // Snap to grid
      const x = Math.round(point.x / GRID_SIZE) * GRID_SIZE;
      const z = Math.round(point.z / GRID_SIZE) * GRID_SIZE;
      
      // Check if point is within warehouse bounds (if layout is defined)
      if (config.layoutDefined && floorPoints && floorPoints.length >= 3) {
        if (!isPointInPolygon(x, z, floorPoints)) {
          // Point is outside warehouse, don't move
          return;
        }
      }
      
      // Update position (keep Y)
      selectedObject.position.x = x;
      selectedObject.position.z = z;
      selectedObject.mesh.position.x = x;
      selectedObject.mesh.position.z = z;
      
      // Для Group (стеллажи) Y уже установлен правильно при создании
      // Для обычных объектов обновляем Y (кроме полок, у них своя логика)
      if (!(selectedObject.mesh instanceof THREE.Group) && selectedObject.type !== 'SHELF') {
        selectedObject.mesh.position.y = selectedObject.position.y + selectedObject.size.height / 2;
      }
      
      // Сохраняем позицию при перетаскивании (debounce для производительности)
      if (!savePositionTimeout && selectedObject && selectedObject.id) {
        savePositionTimeout = setTimeout(() => {
          if (selectedObject && selectedObject.id) {
            saveCurrentObject();
          }
          savePositionTimeout = null;
        }, 500);
      }
      
      // Highlight during drag
      if (selectedObject.mesh instanceof THREE.Group) {
        selectedObject.mesh.traverse((child) => {
          if (child instanceof THREE.Mesh && child.material) {
            child.material.emissive = new THREE.Color(0x666666);
            child.material.emissiveIntensity = 0.5;
          }
        });
      } else if (selectedObject.mesh && selectedObject.mesh.material) {
        selectedObject.mesh.material.emissive = new THREE.Color(0x666666);
        selectedObject.mesh.material.emissiveIntensity = 0.5;
      }
    }
  }
  
  function handleShelfDrag(point) {
    // Полка должна прилипать к ближайшей стене
    if (!config.layoutDefined || floorPoints.length < 3) {
      // Если нет разметки, обычное поведение
      const x = Math.round(point.x / GRID_SIZE) * GRID_SIZE;
      const z = Math.round(point.z / GRID_SIZE) * GRID_SIZE;
      selectedObject.position.x = x;
      selectedObject.position.z = z;
      selectedObject.mesh.position.x = x;
      selectedObject.mesh.position.z = z;
      selectedObject.mesh.position.y = selectedObject.position.y + selectedObject.size.height / 2;
      return;
    }
    
    // Находим ближайшую стену (сегмент контура склада)
    let nearestWall = null;
    let minDistance = Infinity;
    let nearestPoint = null;
    let wallNormal = null;
    
    for (let i = 0; i < floorPoints.length; i++) {
      const p1 = floorPoints[i];
      const p2 = floorPoints[(i + 1) % floorPoints.length];
      
      // Вычисляем ближайшую точку на сегменте стены
      const wallVec = { x: p2[0] - p1[0], z: p2[1] - p1[1] };
      const pointVec = { x: point.x - p1[0], z: point.z - p1[1] };
      const wallLength = Math.sqrt(wallVec.x * wallVec.x + wallVec.z * wallVec.z);
      
      if (wallLength === 0) continue;
      
      const t = Math.max(0, Math.min(1, (pointVec.x * wallVec.x + pointVec.z * wallVec.z) / (wallLength * wallLength)));
      const closestPoint = {
        x: p1[0] + t * wallVec.x,
        z: p1[1] + t * wallVec.z
      };
      
      const distance = Math.sqrt(
        Math.pow(point.x - closestPoint.x, 2) + 
        Math.pow(point.z - closestPoint.z, 2)
      );
      
      if (distance < minDistance) {
        minDistance = distance;
        nearestPoint = closestPoint;
        nearestWall = { p1, p2 };
        // Нормаль к стене (направлена внутрь склада)
        const normalX = -wallVec.z / wallLength;
        const normalZ = wallVec.x / wallLength;
        wallNormal = { x: normalX, z: normalZ };
      }
    }
    
    if (nearestPoint && nearestWall) {
      // Прижимаем полку к стене (немного отступаем внутрь)
      const offset = 0.1; // Небольшой отступ от стены
      const x = nearestPoint.x + wallNormal.x * offset;
      const z = nearestPoint.z + wallNormal.z * offset;
      
      // Высота (Y) может изменяться - используем текущую позицию мыши по Y
      // Но ограничиваем: не ниже пола, не выше стены
      const minY = selectedObject.size.height / 2; // Пол
      const maxY = 5.0; // Максимальная высота (можно настроить)
      let y = selectedObject.mesh.position.y;
      
      // Если перетаскиваем по вертикали, обновляем Y
      // (это можно определить по движению мыши, но для простоты оставляем текущий Y)
      y = Math.max(minY, Math.min(maxY, y));
      
      // Обновляем позицию
      selectedObject.position.x = x;
      selectedObject.position.z = z;
      selectedObject.position.y = y - selectedObject.size.height / 2;
      selectedObject.mesh.position.x = x;
      selectedObject.mesh.position.z = z;
      selectedObject.mesh.position.y = y;
      
      // Сохраняем позицию при перетаскивании (debounce)
      if (!savePositionTimeout) {
        savePositionTimeout = setTimeout(() => {
          if (selectedObject && selectedObject.id) {
            saveCurrentObject();
          }
          savePositionTimeout = null;
        }, 500);
      }
      
      // Поворачиваем полку лицом внутрь склада
      if (wallNormal) {
        const angle = Math.atan2(wallNormal.x, wallNormal.z);
        selectedObject.rotation = angle * (180 / Math.PI);
        selectedObject.mesh.rotation.y = angle;
      }
      
      // Highlight during drag
      if (selectedObject.mesh.material) {
        selectedObject.mesh.material.emissive = new THREE.Color(0x666666);
        selectedObject.mesh.material.emissiveIntensity = 0.5;
      }
    }
  }
  
  function isPointInPolygon(x, z, points) {
    // Simple point-in-polygon test
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const xi = points[i][0], zi = points[i][1];
      const xj = points[j][0], zj = points[j][1];
      
      const intersect = ((zi > z) !== (zj > z)) &&
        (x < (xj - xi) * (z - zi) / (zj - zi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function updateLayoutPreview() {
    // Remove old preview
    if (scene.getObjectByName('layoutPreview')) {
      scene.remove(scene.getObjectByName('layoutPreview'));
    }

    if (floorPoints.length < 2) return;

    const points = floorPoints.map(p => new THREE.Vector3(p[0], 0.01, p[1]));
    if (floorPoints.length >= 3) {
      points.push(points[0]); // Close the loop
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: 0x7c5cff, linewidth: 2 });
    const line = new THREE.Line(geometry, material);
    line.name = 'layoutPreview';
    scene.add(line);

    // Add point markers
    floorPoints.forEach(([x, z], i) => {
      const markerGeometry = new THREE.SphereGeometry(0.1, 8, 8);
      const markerMaterial = new THREE.MeshBasicMaterial({ color: 0x2dd4bf });
      const marker = new THREE.Mesh(markerGeometry, markerMaterial);
      marker.position.set(x, 0.05, z);
      marker.name = 'layoutPreview';
      scene.add(marker);
    });
  }

  function finishLayout() {
    if (floorPoints.length < 3) {
      alert('Недостаточно точек для создания контура');
      return;
    }

    // Save to server
    fetch(config.urls.saveLayout, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ floor_points: floorPoints })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        buildWalls();
        isLayoutMode = false;
        document.getElementById('btn-finish-layout').style.display = 'none';
        location.reload();
      } else {
        alert('Ошибка сохранения: ' + (data.error || 'Неизвестная ошибка'));
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Ошибка при сохранении геометрии склада');
    });
  }

  function loadLayout(points) {
    floorPoints = points;
    buildWalls();
  }

  function buildWalls() {
    if (floorPoints.length < 3) return;

    // Remove old walls
    if (wallsGroup) {
      scene.remove(wallsGroup);
    }

    wallsGroup = new THREE.Group();
    wallsGroup.name = 'walls';

    const wallHeight = 3;
    const wallThickness = 0.2;

    for (let i = 0; i < floorPoints.length; i++) {
      const [x1, z1] = floorPoints[i];
      const [x2, z2] = floorPoints[(i + 1) % floorPoints.length];

      const dx = x2 - x1;
      const dz = z2 - z1;
      const length = Math.sqrt(dx * dx + dz * dz);
      const angle = Math.atan2(dz, dx);

      const wallGeometry = new THREE.BoxGeometry(length, wallHeight, wallThickness);
      const wallMaterial = new THREE.MeshStandardMaterial({
        color: 0x3a3f5a,
        roughness: 0.7,
        metalness: 0.1
      });
      const wall = new THREE.Mesh(wallGeometry, wallMaterial);
      wall.position.set(
        (x1 + x2) / 2,
        wallHeight / 2,
        (z1 + z2) / 2
      );
      wall.rotation.y = angle;
      wall.castShadow = true;
      wall.receiveShadow = true;
      wallsGroup.add(wall);
    }

    scene.add(wallsGroup);

    // Update floor to match layout
    if (floorMesh) {
      const shape = new THREE.Shape();
      const firstPoint = floorPoints[0];
      shape.moveTo(firstPoint[0], firstPoint[1]);
      for (let i = 1; i < floorPoints.length; i++) {
        shape.lineTo(floorPoints[i][0], floorPoints[i][1]);
      }
      shape.lineTo(firstPoint[0], firstPoint[1]);

      const floorGeometry = new THREE.ShapeGeometry(shape);
      const floorMaterial = new THREE.MeshStandardMaterial({
        color: 0x1a1f3a,
        side: THREE.DoubleSide
      });
      const newFloor = new THREE.Mesh(floorGeometry, floorMaterial);
      newFloor.rotation.x = -Math.PI / 2;
      newFloor.receiveShadow = true;
      scene.remove(floorMesh);
      floorMesh = newFloor;
      scene.add(floorMesh);
    }
  }

  function isPointInsideWarehouse(x, z) {
    if (floorPoints.length < 3) return true; // No layout yet

    // Ray casting algorithm
    let inside = false;
    for (let i = 0, j = floorPoints.length - 1; i < floorPoints.length; j = i++) {
      const [xi, zi] = floorPoints[i];
      const [xj, zj] = floorPoints[j];
      if (((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi) + xi)) {
        inside = !inside;
      }
    }
    return inside;
  }

  function addStorageObject(type, createAtCursor = false) {
    if (!config.canEdit || !isEditMode) {
      alert('У вас нет прав на редактирование этого склада');
      return;
    }
    
    if (!config.layoutDefined) {
      alert('Сначала создайте разметку склада');
      return;
    }

    // Если createAtCursor = true (горячие клавиши), создаём объект сразу в центре экрана
    // (так как мы не знаем точную позицию курсора без события мыши)
    if (createAtCursor) {
      console.log('[Warehouse3D] HOTKEY_PRESS: Creating', type, 'at cursor position');
      
      // Используем центр экрана как позицию курсора
      mouse.x = 0;
      mouse.y = 0;
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects([floorMesh], false);
      
      if (intersects.length > 0) {
        const point = intersects[0].point;
        const x = Math.round(point.x / GRID_SIZE) * GRID_SIZE;
        const z = Math.round(point.z / GRID_SIZE) * GRID_SIZE;
        
        // Проверка границ склада
        if (config.layoutDefined && floorPoints && floorPoints.length >= 3) {
          if (!isPointInPolygon(x, z, floorPoints)) {
            console.log('[Warehouse3D] Point outside warehouse bounds:', x, z);
            alert('Нельзя размещать объекты за пределами склада');
            return;
          }
        }
        
        console.log('[Warehouse3D] Creating object at position:', x, z, 'Type:', type);
        addStorageObjectAtPosition(type, x, z);
        console.log('[Warehouse3D] OBJECT_CREATED');
        return;
      } else {
        console.log('[Warehouse3D] Raycast did not hit floor, creating at origin');
        // Если луч не пересекает пол, создаём в центре координат
        addStorageObjectAtPosition(type, 0, 0);
        console.log('[Warehouse3D] OBJECT_CREATED (at origin)');
        return;
      }
    }

    // Иначе (ПКМ через модальное окно) - устанавливаем pending type
    pendingObjectType = type;
    const canvas = renderer.domElement;
    if (canvas) {
      canvas.style.cursor = 'crosshair';
      canvas.title = 'Кликните по полу, чтобы разместить объект';
    }
  }

  function createStorageObject(objData) {
    const defaults = OBJECT_DEFAULTS[objData.type];
    let mesh;
    let group = null;
    
    // Материалы
    const woodMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x8B5A2B, 
      roughness: 0.6,
      metalness: 0.1
    });
    const metalMaterial = new THREE.MeshStandardMaterial({ 
      color: 0x333333, 
      roughness: 0.3, 
      metalness: 0.8 
    });
    
    // ОСОБАЯ ОБРАБОТКА ДЛЯ СТЕЛЛАЖЕЙ
    if (objData.type === 'RACK') {
      group = new THREE.Group();
      const width = objData.size.width;
      const depth = objData.size.depth;
      const height = objData.size.height;
      
      // Вертикальные стойки (4 угла)
      const postSize = 0.1;
      const postGeometry = new THREE.BoxGeometry(postSize, height, postSize);
      
      const positions = [
        [-width/2 + postSize/2, height/2, -depth/2 + postSize/2],
        [width/2 - postSize/2, height/2, -depth/2 + postSize/2],
        [-width/2 + postSize/2, height/2, depth/2 - postSize/2],
        [width/2 - postSize/2, height/2, depth/2 - postSize/2]
      ];
      
      positions.forEach(pos => {
        const post = new THREE.Mesh(postGeometry, metalMaterial);
        post.position.set(pos[0], pos[1], pos[2]);
        post.castShadow = true;
        post.receiveShadow = true;
        group.add(post);
      });
      
      // Горизонтальные полки (3 уровня)
      const shelfThickness = 0.05;
      const shelfGeometry = new THREE.BoxGeometry(width - postSize, shelfThickness, depth - postSize);
      const shelfLevels = [0.5, height/2, height - 0.5];
      
      shelfLevels.forEach(level => {
        const shelf = new THREE.Mesh(shelfGeometry, woodMaterial);
        shelf.position.set(0, level, 0);
        shelf.castShadow = true;
        shelf.receiveShadow = true;
        group.add(shelf);
      });
      
      // Задняя стенка (опционально)
      const backThickness = 0.05;
      const backGeometry = new THREE.BoxGeometry(width, height, backThickness);
      const back = new THREE.Mesh(backGeometry, woodMaterial);
      back.position.set(0, height/2, -depth/2 + backThickness/2);
      back.castShadow = true;
      back.receiveShadow = true;
      group.add(back);
      
      // Устанавливаем позицию и поворот группы
      group.position.set(
        objData.position.x || 0,
        objData.position.y !== undefined ? objData.position.y : 0,
        objData.position.z || 0
      );
      group.rotation.y = (objData.rotation || 0) * Math.PI / 180;
      
      mesh = group; // Используем group как mesh для совместимости
      
    } else if (objData.type === 'SHELF') {
      // ПОЛКИ: создаём как простой объект, но с поддержкой уровней
      const geometry = new THREE.BoxGeometry(
        objData.size.width,
        objData.size.height,
        objData.size.depth
      );
      const material = new THREE.MeshStandardMaterial({
        color: defaults.color,
        roughness: 0.6,
        metalness: 0.2
      });
      mesh = new THREE.Mesh(geometry, material);
      
      // Добавляем свойство level для полок (0, 1, 2)
      if (!objData.level) objData.level = 1; // По умолчанию уровень 1
      
      // Позиция полки зависит от уровня
      const levelHeights = [0.3, 1.0, 1.7]; // Высоты для уровней 0, 1, 2
      const currentLevel = objData.level !== undefined && objData.level !== null ? objData.level : 1;
      const yOffset = levelHeights[currentLevel] || levelHeights[1];
      
      // Для полок: если position.y задан из базы, используем его напрямую
      // Иначе вычисляем на основе уровня
      let finalY;
      if (objData.position.y !== undefined && objData.position.y !== null && objData.id) {
        // Загружаем из базы - используем сохранённую позицию
        finalY = objData.position.y;
      } else {
        // Новый объект или без позиции - вычисляем на основе уровня
        finalY = yOffset;
      }
      
      mesh.position.set(
        objData.position.x || 0,
        finalY,
        objData.position.z || 0
      );
      
      // Сохраняем уровень в объекте
      objData.level = currentLevel;
      // Обновляем position.y для сохранения
      objData.position.y = finalY - yOffset; // Сохраняем базовую позицию
      mesh.rotation.y = (objData.rotation || 0) * Math.PI / 180;
      
    } else {
      // Остальные объекты (ячейки, напольные зоны) - обычные кубы
      const geometry = new THREE.BoxGeometry(
        objData.size.width,
        objData.size.height,
        objData.size.depth
      );
      const material = new THREE.MeshStandardMaterial({
        color: defaults.color,
        roughness: 0.6,
        metalness: 0.3
      });
      mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(
        objData.position.x || 0,
        (objData.position.y !== undefined ? objData.position.y : 0) + objData.size.height / 2,
        objData.position.z || 0
      );
      mesh.rotation.y = (objData.rotation || 0) * Math.PI / 180;
    }
    
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    
    // Для стеллажей (Group) добавляем outline к группе
    if (objData.type === 'RACK' && group) {
      // Outline для стеллажа не нужен, он уже детализирован
    } else {
      // Add outline для остальных объектов
      const edges = new THREE.EdgesGeometry(mesh.geometry);
      const line = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 1 })
      );
      mesh.add(line);
    }

    // Add stock indicators if has stock
    const locationId = objData.storageLocationId;
    if (locationId && config.stocksByLocation && config.stocksByLocation[locationId]) {
      const stocks = config.stocksByLocation[locationId];
      const stockCount = stocks.length;
      const totalQty = stocks.reduce((sum, s) => sum + s.qty, 0);
      
      // Add small indicator box on top
      const indicatorGeometry = new THREE.BoxGeometry(0.3, 0.1, 0.3);
      const indicatorMaterial = new THREE.MeshBasicMaterial({ color: 0x2dd4bf });
      const indicator = new THREE.Mesh(indicatorGeometry, indicatorMaterial);
      indicator.position.set(0, objData.size.height / 2 + 0.1, 0);
      mesh.add(indicator);
      
      // Store stock info
      mesh.userData.stocks = stocks;
      mesh.userData.stockCount = stockCount;
      mesh.userData.totalQty = totalQty;
    }

    scene.add(mesh);

    const obj = {
      id: objData.id,
      type: objData.type,
      code: objData.code || '',
      name: objData.name || '',
      position: { ...objData.position },
      size: { ...objData.size },
      rotation: objData.rotation || 0,
      storageLocationId: locationId || null,
      mesh: mesh,
      level: objData.level || (objData.type === 'SHELF' ? 1 : null) // Уровень для полок
    };

    if (obj.id) {
      storageObjects.set(obj.id, obj);
      // Save to history for undo
      saveActionToHistory({ type: 'add', objectId: obj.id });
    } else {
      storageObjects.set(mesh.uuid, obj);
    }

    return obj;
  }
  
  function changeShelfLevel(shelfObj, delta) {
    if (!shelfObj || shelfObj.type !== 'SHELF') return;
    
    const currentLevel = shelfObj.level !== undefined ? shelfObj.level : 1;
    const newLevel = Math.max(0, Math.min(2, currentLevel + delta));
    
    if (newLevel === currentLevel) {
      console.log('[Warehouse3D] Level unchanged:', currentLevel);
      return; // Уровень не изменился
    }
    
    shelfObj.level = newLevel;
    
    // Обновляем позицию полки по уровню
    const levelHeights = [0.3, 1.0, 1.7]; // Высоты для уровней 0, 1, 2
    const yOffset = levelHeights[newLevel];
    
    // Сохраняем базовую позицию (X, Z) и обновляем только Y
    const baseY = shelfObj.position.y !== undefined ? shelfObj.position.y : 0;
    shelfObj.mesh.position.y = baseY + yOffset;
    shelfObj.position.y = baseY; // Сохраняем базовую позицию для сохранения в БД
    
    console.log('[Warehouse3D] Shelf level changed from', currentLevel, 'to', newLevel, 'Y:', shelfObj.mesh.position.y);
    
    // Сохраняем изменения на сервер
    saveCurrentObject();
  }

  function selectObject(obj) {
    deselectObject();
    selectedObject = obj;

    // Highlight (reset if was dragging)
    // Для Group (стеллажи) нужно обрабатывать все дочерние элементы
    if (obj.mesh instanceof THREE.Group) {
      obj.mesh.traverse((child) => {
        if (child instanceof THREE.Mesh && child.material) {
          child.material.emissive = new THREE.Color(0x444444);
          child.material.emissiveIntensity = 0.3;
        }
      });
    } else if (obj.mesh && obj.mesh.material) {
      obj.mesh.material.emissive = new THREE.Color(0x444444);
      obj.mesh.material.emissiveIntensity = 0.3;
    }

    // Show properties panel
    const propsPanel = document.getElementById('object-properties');
    if (propsPanel) {
      propsPanel.style.display = 'block';
      updateObjectProperties();
    }
  }

  function deselectObject() {
    if (selectedObject && selectedObject.mesh) {
      // Для Group (стеллажи) нужно обрабатывать все дочерние элементы
      if (selectedObject.mesh instanceof THREE.Group) {
        selectedObject.mesh.traverse((child) => {
          if (child instanceof THREE.Mesh && child.material) {
            child.material.emissive = new THREE.Color(0x000000);
            child.material.emissiveIntensity = 0;
          }
        });
      } else if (selectedObject.mesh.material) {
        selectedObject.mesh.material.emissive = new THREE.Color(0x000000);
        selectedObject.mesh.material.emissiveIntensity = 0;
      }
    }
    selectedObject = null;

    const propsPanel = document.getElementById('object-properties');
    if (propsPanel) {
      propsPanel.style.display = 'none';
    }
  }

  function updateObjectProperties() {
    if (!selectedObject) return;

    const codeInput = document.getElementById('obj-code');
    const nameInput = document.getElementById('obj-name');
    const widthInput = document.getElementById('obj-width');
    const depthInput = document.getElementById('obj-depth');
    const heightInput = document.getElementById('obj-height');
    const stockInfo = document.getElementById('object-stock-info');
    const stockList = document.getElementById('object-stock-list');

    if (codeInput) codeInput.value = selectedObject.code || '';
    if (nameInput) nameInput.value = selectedObject.name || '';
    if (widthInput) widthInput.value = selectedObject.size.width;
    if (depthInput) depthInput.value = selectedObject.size.depth;
    if (heightInput) heightInput.value = selectedObject.size.height;

    // Show stock info if available
    if (selectedObject.mesh.userData.stocks && selectedObject.mesh.userData.stocks.length > 0) {
      if (stockInfo) stockInfo.style.display = 'block';
      if (stockList) {
        const stocks = selectedObject.mesh.userData.stocks;
        stockList.innerHTML = stocks.map(s => 
          `<div>${s.product_sku} — ${s.product_name} (${s.qty} шт.)</div>`
        ).join('');
      }
    } else {
      if (stockInfo) stockInfo.style.display = 'none';
    }
  }

  function saveCurrentObject() {
    if (!selectedObject) return;

    const codeInput = document.getElementById('obj-code');
    const nameInput = document.getElementById('obj-name');
    const widthInput = document.getElementById('obj-width');
    const depthInput = document.getElementById('obj-depth');
    const heightInput = document.getElementById('obj-height');

    selectedObject.code = codeInput.value;
    selectedObject.name = nameInput.value;
    selectedObject.size.width = parseFloat(widthInput.value) || 1;
    selectedObject.size.depth = parseFloat(depthInput.value) || 1;
    selectedObject.size.height = parseFloat(heightInput.value) || 1;

    // Update mesh (только для не-Group объектов)
    if (!(selectedObject.mesh instanceof THREE.Group)) {
      const defaults = OBJECT_DEFAULTS[selectedObject.type];
      const newGeometry = new THREE.BoxGeometry(
        selectedObject.size.width,
        selectedObject.size.height,
        selectedObject.size.depth
      );
      if (selectedObject.mesh.geometry) {
        selectedObject.mesh.geometry.dispose();
      }
      selectedObject.mesh.geometry = newGeometry;
      selectedObject.mesh.position.y = selectedObject.position.y + selectedObject.size.height / 2;
    }

    // Save to server
    fetch(config.urls.saveObject, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({
        id: selectedObject.id,
        object_type: selectedObject.type,
        code: selectedObject.code,
        name: selectedObject.name,
        position_x: selectedObject.position.x,
        position_z: selectedObject.position.z,
        position_y: selectedObject.position.y,
        width: selectedObject.size.width,
        depth: selectedObject.size.depth,
        height: selectedObject.size.height,
        rotation_y: selectedObject.rotation,
        level: selectedObject.level || null // Сохраняем уровень для полок
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        console.log('[Warehouse3D] Object saved successfully:', data);
        if (data.id) {
          // Если объект был новым, обновляем его ID
          if (!selectedObject.id) {
            const oldKey = selectedObject.mesh ? selectedObject.mesh.uuid : null;
            selectedObject.id = data.id;
            if (oldKey) {
              storageObjects.delete(oldKey);
            }
            storageObjects.set(data.id, selectedObject);
            console.log('[Warehouse3D] Object ID assigned:', data.id);
          } else {
            // Обновляем существующий объект
            storageObjects.set(selectedObject.id, selectedObject);
            console.log('[Warehouse3D] Object updated:', selectedObject.id);
          }
        }
      } else {
        console.error('[Warehouse3D] Save error:', data.error);
        alert('Ошибка сохранения: ' + (data.error || 'Неизвестная ошибка'));
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Ошибка при сохранении объекта');
    });
  }

  function deleteCurrentObject() {
    if (!selectedObject) {
      console.log('[Warehouse3D] No object selected for deletion');
      return;
    }
    
    console.log('[Warehouse3D] Deleting object:', selectedObject.id, selectedObject.type);
    
    if (!selectedObject.id) {
      // Just remove from scene if not saved
      if (selectedObject.mesh) {
        scene.remove(selectedObject.mesh);
        storageObjects.delete(selectedObject.mesh.uuid);
        console.log('[Warehouse3D] Unsaved object removed from scene');
      }
      deselectObject();
      return;
    }

    // Check for stock
    if (selectedObject.mesh && selectedObject.mesh.userData && selectedObject.mesh.userData.stocks && selectedObject.mesh.userData.stocks.length > 0) {
      const stockCount = selectedObject.mesh.userData.stockCount || 0;
      const totalQty = selectedObject.mesh.userData.totalQty || 0;
      alert(`Невозможно удалить объект: на нём находятся товары (${stockCount} позиций, всего ${totalQty} шт.)`);
      return;
    }

    // Удаление без подтверждения - сразу удаляем
    const deleteUrl = config.urls.deleteObject.replace('999999', String(selectedObject.id));
    console.log('[Warehouse3D] Sending DELETE request to:', deleteUrl, 'Object ID:', selectedObject.id);
    
    fetch(deleteUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken()
      }
    })
    .then(response => {
      console.log('[Warehouse3D] Delete response status:', response.status);
      return response.json();
    })
    .then(data => {
      console.log('[Warehouse3D] Delete response data:', data);
      if (data.success) {
        if (selectedObject.mesh) {
          scene.remove(selectedObject.mesh);
          console.log('[Warehouse3D] Object removed from scene');
        }
        if (selectedObject.id) {
          storageObjects.delete(selectedObject.id);
          console.log('[Warehouse3D] Object removed from storageObjects');
        }
        deselectObject();
        console.log('[Warehouse3D] Object deleted successfully');
      } else {
        console.error('[Warehouse3D] Delete failed:', data.error);
        alert('Ошибка удаления: ' + (data.error || 'Неизвестная ошибка'));
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Ошибка при удалении объекта');
    });
  }

  function toggleMode() {
    if (!config.canEdit) return; // Can't toggle if no edit rights
    
    isEditMode = !isEditMode;
    const btn = document.getElementById('mode-toggle');
    if (btn) {
      btn.dataset.mode = isEditMode ? 'edit' : 'view';
      const textSpan = btn.querySelector('span:not(.btn__icon)');
      const iconSpan = btn.querySelector('.btn__icon');
      if (textSpan) textSpan.textContent = isEditMode ? 'Режим редактирования' : 'Режим просмотра';
      if (iconSpan) iconSpan.textContent = isEditMode ? '✏️' : '👁';
    }
    
    // При включении режима редактирования автоматически переключаемся в режим объектов
    if (isEditMode) {
      controlMode = 'object';
      if (controls) {
        controls.enabled = false;
      }
    } else {
      controlMode = 'camera';
      if (controls) {
        controls.enabled = true;
      }
    }
    
    // Обновляем индикатор режима
    const modeIndicator = document.getElementById('control-mode-indicator');
    if (modeIndicator) {
      modeIndicator.textContent = controlMode === 'camera' ? '🧭 Режим камеры' : '✋ Режим объектов';
    }
    
    deselectObject();
    hideModal('empty');
    hideModal('add-object');
    hideModal('object');
    hideModal('create-warehouse');
    updateUIForEditMode();
    
    // Логирование состояния кнопок
    logButtonStates();
  }
  
  function logButtonStates() {
    console.log('[Warehouse3D] === Button States ===');
    console.log('[Warehouse3D] Edit Mode:', isEditMode);
    console.log('[Warehouse3D] Control Mode:', controlMode);
    console.log('[Warehouse3D] Can Edit:', config.canEdit);
    
    // Проверяем кнопки инструментов
    const toolButtons = document.querySelectorAll('.tool-btn');
    console.log('[Warehouse3D] Tool buttons:', toolButtons.length);
    toolButtons.forEach((btn, index) => {
      const isDisabled = btn.disabled;
      const type = btn.dataset.type || 'unknown';
      console.log(`[Warehouse3D]   Tool button ${index + 1} (${type}): ${isDisabled ? 'DISABLED' : 'ENABLED'}`);
    });
    
    // Проверяем кнопки камеры
    const cameraButtons = document.querySelectorAll('[data-view]');
    console.log('[Warehouse3D] Camera buttons:', cameraButtons.length);
    cameraButtons.forEach((btn, index) => {
      const isDisabled = btn.disabled;
      const view = btn.dataset.view || 'unknown';
      console.log(`[Warehouse3D]   Camera button ${index + 1} (${view}): ${isDisabled ? 'DISABLED' : 'ENABLED'}`);
    });
    
    // Проверяем кнопку режима
    const modeToggle = document.getElementById('mode-toggle');
    if (modeToggle) {
      const isDisabled = modeToggle.disabled;
      console.log(`[Warehouse3D] Mode toggle: ${isDisabled ? 'DISABLED' : 'ENABLED'}`);
    }
    
    // Проверяем другие кнопки
    const finishLayoutBtn = document.getElementById('btn-finish-layout');
    if (finishLayoutBtn) {
      console.log(`[Warehouse3D] Finish layout button: ${finishLayoutBtn.disabled ? 'DISABLED' : 'ENABLED'}`);
    }
    
    const saveBtn = document.getElementById('btn-save-object');
    if (saveBtn) {
      console.log(`[Warehouse3D] Save object button: ${saveBtn.disabled ? 'DISABLED' : 'ENABLED'}`);
    }
    
    const deleteBtn = document.getElementById('btn-delete-object');
    if (deleteBtn) {
      console.log(`[Warehouse3D] Delete object button: ${deleteBtn.disabled ? 'DISABLED' : 'ENABLED'}`);
    }
    
    console.log('[Warehouse3D] ====================');
  }

  function setCameraView(view) {
    const distance = 30;
    
    switch(view) {
      case 'top':
        camera.position.set(0, distance, 0);
        camera.lookAt(0, 0, 0);
        break;
      case 'iso':
        camera.position.set(distance * 0.7, distance * 0.7, distance * 0.7);
        camera.lookAt(0, 0, 0);
        break;
      case 'reset':
        camera.position.set(distance * 0.7, distance * 0.7, distance * 0.7);
        camera.lookAt(0, 0, 0);
        break;
    }
  }

  function saveActionToHistory(action) {
    actionHistory.push(action);
    // Limit history size
    if (actionHistory.length > 50) {
      actionHistory.shift();
    }
  }

  function onKeyDown(event) {
    // Проверяем, не вводит ли пользователь текст в поле ввода
    const activeElement = document.activeElement;
    if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
      // Разрешаем только Escape и некоторые горячие клавиши даже в полях ввода
      if (event.key === 'Escape') {
        activeElement.blur();
      }
      return;
    }
    
    // Hotkeys only work in edit mode
    if (!isEditMode || !config.canEdit) {
      // Only camera controls work in view mode
      if (['1', '2', '3'].includes(event.key)) {
        switch(event.key) {
          case '1':
            setCameraView('top');
            break;
          case '2':
            setCameraView('iso');
            break;
          case '3':
            setCameraView('reset');
            break;
        }
      }
      return;
    }

    // Prevent default for hotkeys
    if (['r', 's', 'c', 'f', 'Delete', 'Escape', ' ', 'ArrowUp', 'ArrowDown'].includes(event.key) || 
        (event.ctrlKey && event.key.toLowerCase() === 'z')) {
      event.preventDefault();
    }

    switch(event.key.toLowerCase()) {
      case 'r':
        if (isEditMode && config.canEdit) {
          console.log('[Warehouse3D] HOTKEY_PRESS: R');
          addStorageObject('RACK', true); // true = create at cursor
        }
        break;
      case 's':
        if (isEditMode && config.canEdit) {
          console.log('[Warehouse3D] HOTKEY_PRESS: S');
          addStorageObject('SHELF', true);
        }
        break;
      case 'c':
        if (isEditMode && config.canEdit) {
          console.log('[Warehouse3D] HOTKEY_PRESS: C');
          addStorageObject('CELL', true);
        }
        break;
      case 'f':
        if (isEditMode && config.canEdit) {
          console.log('[Warehouse3D] HOTKEY_PRESS: F');
          addStorageObject('FLOOR', true);
        }
        break;
      case 'Delete':
        if (selectedObject) deleteCurrentObject();
        break;
      case 'Escape':
        deselectObject();
        hideModal('empty');
        hideModal('add-object');
        hideModal('object');
        hideModal('create-warehouse');
        break;
      case ' ':
        event.preventDefault();
        toggleControlMode();
        break;
      case 'ArrowUp':
        if (selectedObject && selectedObject.type === 'SHELF' && selectedObject.level !== undefined) {
          changeShelfLevel(selectedObject, 1); // Увеличить уровень
        }
        break;
      case 'ArrowDown':
        if (selectedObject && selectedObject.type === 'SHELF' && selectedObject.level !== undefined) {
          changeShelfLevel(selectedObject, -1); // Уменьшить уровень
        }
        break;
      case 'z':
        if (event.ctrlKey) {
          undoLastAction();
        }
        break;
      case '1':
        setCameraView('top');
        break;
      case '2':
        setCameraView('iso');
        break;
      case '3':
        setCameraView('reset');
        break;
    }
  }

  function onWindowResize() {
    const container = document.getElementById('canvas-container');
    if (!container || !camera || !renderer) {
      console.warn('[Warehouse3D] onWindowResize: missing container, camera, or renderer');
      return;
    }

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    
    if (width === 0 || height === 0) {
      console.warn('[Warehouse3D] onWindowResize: container has zero size');
      return;
    }
    
    console.log('[Warehouse3D] Resizing to:', width, 'x', height);
    
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    
    if (controls) {
      controls.update();
    }
  }

  function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      if (name === 'csrftoken') {
        return value;
      }
    }
    return '';
  }

  function animate() {
    requestAnimationFrame(animate);
    
    // Only render if everything is ready
    if (!renderer || !scene || !camera) {
      return;
    }
    
    // Update OrbitControls if enabled
    if (controls && controls.enabled) {
      controls.update();
    }
    
    renderer.render(scene, camera);
  }
  
  function toggleControlMode() {
    // Переключение режимов работает только в режиме редактирования
    if (!isEditMode || !config.canEdit) {
      console.log('[Warehouse3D] Cannot toggle control mode: not in edit mode');
      return;
    }
    
    controlMode = controlMode === 'camera' ? 'object' : 'camera';
    console.log('[Warehouse3D] Control mode switched to:', controlMode);
    
    // Update controls based on mode
    if (controls) {
      if (controlMode === 'camera') {
        controls.enabled = true;
        console.log('[Warehouse3D] Camera controls enabled');
      } else {
        controls.enabled = false;
        console.log('[Warehouse3D] Camera controls disabled (object mode)');
      }
    }
    
    // Deselect object when switching modes
    if (controlMode === 'camera') {
      deselectObject();
    }
    
    // Update UI indicator
    const modeIndicator = document.getElementById('control-mode-indicator');
    if (modeIndicator) {
      modeIndicator.textContent = controlMode === 'camera' ? '🧭 Режим камеры' : '✋ Режим объектов';
    }
    
    // Update button text if exists
    const controlModeBtn = document.getElementById('btn-control-mode');
    if (controlModeBtn) {
      const textSpan = controlModeBtn.querySelector('span:not(.btn__icon)');
      if (textSpan) {
        textSpan.textContent = controlMode === 'camera' ? 'Режим камеры' : 'Режим объектов';
      }
    }
    
    // Show notification
    const canvas = renderer.domElement;
    if (canvas) {
      canvas.title = controlMode === 'camera' 
        ? 'Режим камеры (Space - переключить)' 
        : 'Режим объектов (Space - переключить)';
    }
  }
  
  function toggleFullscreen() {
    const container = document.getElementById('canvas-container');
    if (!container) return;
    
    if (!isFullscreen) {
      if (container.requestFullscreen) {
        container.requestFullscreen();
      } else if (container.webkitRequestFullscreen) {
        container.webkitRequestFullscreen();
      } else if (container.msRequestFullscreen) {
        container.msRequestFullscreen();
      }
      isFullscreen = true;
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      } else if (document.msExitFullscreen) {
        document.msExitFullscreen();
      }
      isFullscreen = false;
    }
  }
  
  // Listen for fullscreen changes
  document.addEventListener('fullscreenchange', () => {
    isFullscreen = !!document.fullscreenElement;
    updateFullscreenButton();
  });
  document.addEventListener('webkitfullscreenchange', () => {
    isFullscreen = !!document.webkitFullscreenElement;
    updateFullscreenButton();
  });
  document.addEventListener('msfullscreenchange', () => {
    isFullscreen = !!document.msFullscreenElement;
    updateFullscreenButton();
  });
  
  function updateFullscreenButton() {
    const btn = document.getElementById('btn-fullscreen');
    if (btn) {
      const icon = btn.querySelector('.btn__icon');
      const text = btn.querySelector('span:not(.btn__icon)');
      if (icon) icon.textContent = isFullscreen ? '⤓' : '⤢';
      if (text) text.textContent = isFullscreen ? 'Выйти из полноэкранного режима' : 'Полноэкранный режим';
    }
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      // Wait a bit for Three.js to load
      setTimeout(init, 100);
    });
  } else {
    // Wait a bit for Three.js to load
    setTimeout(init, 100);
  }

})();
