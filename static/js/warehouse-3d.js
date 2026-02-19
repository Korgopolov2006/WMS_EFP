import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

(function() {
  'use strict';

  const container = document.getElementById('warehouse-3d-canvas');
  if (!container) return;

  const warehouseId = window.WAREHOUSE_ID;
  const accessLevel = window.ACCESS_LEVEL || 'VIEW';
  const canEdit = accessLevel === 'EDIT' || accessLevel === 'ADMIN';

  if (!warehouseId) {
    console.error('Warehouse ID not provided');
    return;
  }

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.minDistance = 5;
  controls.maxDistance = 50;

  camera.position.set(20, 15, 20);
  camera.lookAt(0, 0, 0);

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);

  const directionalLight = new THREE.DirectionalLight(0xffffff, 0.4);
  directionalLight.position.set(10, 10, 5);
  scene.add(directionalLight);

  let floor = null;
  let gridHelper = null;
  let warehouseData = null;

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  let selectedObject = null;
  const objectsMap = new Map();

  const apiBaseUrl = window.location.origin;
  const warehouseDataUrl = apiBaseUrl + `/catalog/api/warehouses/${warehouseId}/data/`;
  const warehouseObjectCreateUrl = apiBaseUrl + `/catalog/api/warehouses/${warehouseId}/objects/`;
  const warehouseObjectDeleteUrl = apiBaseUrl + `/catalog/api/warehouses/${warehouseId}/objects/`;

  function getCsrfToken() {
    const tokenEl = document.querySelector('[name=csrfmiddlewaretoken]');
    return tokenEl ? tokenEl.value : '';
  }

  function createObject(objData) {
    const geometry = new THREE.BoxGeometry(objData.width, objData.height, objData.depth);
    const material = new THREE.MeshStandardMaterial({
      color: objData.color,
      roughness: 0.7,
      metalness: 0.2,
      transparent: true,
      opacity: 0.85,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(objData.x, objData.y + objData.height / 2, objData.z);
    mesh.userData = { id: objData.id, code: objData.code, type: objData.type };

    const edges = new THREE.EdgesGeometry(geometry);
    const line = new THREE.LineSegments(
      edges,
      new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0.3, transparent: true })
    );
    mesh.add(line);

    scene.add(mesh);
    objectsMap.set(objData.id, mesh);

    return mesh;
  }

  function highlightObject(mesh, highlight) {
    if (!mesh) return;
    if (highlight) {
      mesh.material.emissive.setHex(0x444444);
      mesh.material.opacity = 1.0;
    } else {
      mesh.material.emissive.setHex(0x000000);
      mesh.material.opacity = 0.85;
    }
  }

  function loadWarehouseData() {
    fetch(warehouseDataUrl)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
      })
      .then(data => {
        warehouseData = data;

        if (data.warehouse) {
          const wh = data.warehouse;
          const floorGeometry = new THREE.PlaneGeometry(wh.width, wh.length);
          const floorMaterial = new THREE.MeshStandardMaterial({
            color: 0x1e293b,
            roughness: 0.8,
            metalness: 0.1,
          });
          floor = new THREE.Mesh(floorGeometry, floorMaterial);
          floor.rotation.x = -Math.PI / 2;
          floor.position.y = 0;
          scene.add(floor);

          gridHelper = new THREE.GridHelper(wh.length, wh.length, 0x3b82f6, 0x1e293b);
          gridHelper.position.y = 0.01;
          scene.add(gridHelper);
        }

        if (data.objects && data.objects.length > 0) {
          data.objects.forEach(obj => {
            createObject(obj);
          });
        }
      })
      .catch(err => {
        console.error('Failed to load warehouse data:', err);
        alert('Ошибка загрузки данных склада: ' + err.message);
      });
  }

  function addObject(type, code, x, y, z) {
    if (!canEdit) {
      alert('У вас нет прав на редактирование этого склада');
      return;
    }

    const typeToZoneCode = {
      'cell': 'CELL',
      'shelf': 'SHELF',
      'floor': 'FLOOR',
    };

    const payload = {
      type: typeToZoneCode[type] || 'CELL',
      code: code,
      x: x,
      y: y,
      z: z,
      aisle: Math.floor(x / 2) || 1,
      rack: Math.floor(y / 1.5) || 1,
      shelf: Math.floor(z / 0.5) || 1,
    };

    fetch(warehouseObjectCreateUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify(payload),
    })
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          alert('Ошибка: ' + data.error);
          return;
        }
        location.reload();
      })
      .catch(err => console.error('Failed to add object:', err));
  }

  function deleteObject(id) {
    if (!canEdit) {
      alert('У вас нет прав на редактирование этого склада');
      return;
    }

    if (!confirm('Удалить объект?')) return;

    fetch(warehouseObjectDeleteUrl + id + '/', {
      method: 'DELETE',
      headers: {
        'X-CSRFToken': getCsrfToken(),
      },
    })
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          alert('Ошибка: ' + data.error);
          return;
        }
        const mesh = objectsMap.get(id);
        if (mesh) {
          scene.remove(mesh);
          objectsMap.delete(id);
        }
      })
      .catch(err => console.error('Failed to delete object:', err));
  }

  if (canEdit) {
    container.addEventListener('click', (event) => {
      mouse.x = (event.clientX / container.clientWidth) * 2 - 1;
      mouse.y = -(event.clientY / container.clientHeight) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(Array.from(objectsMap.values()));

      if (selectedObject) {
        highlightObject(selectedObject, false);
        selectedObject = null;
      }

      if (intersects.length > 0) {
        const obj = intersects[0].object;
        selectedObject = obj;
        highlightObject(obj, true);
        deleteObject(obj.userData.id);
      }
    });
  }

  const addBtn = document.getElementById('add-object-btn');
  if (addBtn && canEdit) {
    addBtn.addEventListener('click', () => {
      const type = document.getElementById('add-object-type').value;
      const code = document.getElementById('add-object-code').value.trim();
      if (!code) {
        alert('Введите код');
        return;
      }
      const x = Math.random() * 20 - 10;
      const y = 0.5;
      const z = Math.random() * 20 - 10;
      addObject(type, code, x, y, z);
    });
  }

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  function handleResize() {
    const width = container.clientWidth;
    const height = container.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  window.addEventListener('resize', handleResize);

  loadWarehouseData();
  animate();
})();
