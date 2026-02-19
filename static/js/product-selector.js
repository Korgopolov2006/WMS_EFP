/**
 * Компонент для удобного выбора товаров при приёмке
 */
(function() {
  'use strict';

  function initProductSelector() {
    const productField = document.getElementById('id_product');
    if (!productField) {
      return;
    }

    // Создаём контейнер для поиска
    const searchContainer = document.createElement('div');
    searchContainer.className = 'product-selector';
    searchContainer.style.marginTop = '8px';

    // Поле поиска
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'form__input';
    searchInput.placeholder = 'Поиск по артикулу, OEM, названию, бренду...';
    searchInput.style.marginBottom = '8px';

    // Контейнер для результатов
    const resultsContainer = document.createElement('div');
    resultsContainer.className = 'product-selector__results';
    resultsContainer.style.display = 'none';
    resultsContainer.style.maxHeight = '400px';
    resultsContainer.style.overflowY = 'auto';
    resultsContainer.style.borderRadius = '12px';
    resultsContainer.style.border = '1px solid var(--stroke)';
    resultsContainer.style.background = 'var(--glass)';
    resultsContainer.style.backdropFilter = 'blur(8px)';

    searchContainer.appendChild(searchInput);
    searchContainer.appendChild(resultsContainer);
    productField.parentNode.insertBefore(searchContainer, productField.nextSibling);

    let searchTimeout;
    let selectedProduct = null;

    // Поиск товаров
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimeout);
      const query = this.value.trim();

      if (query.length < 2) {
        resultsContainer.style.display = 'none';
        return;
      }

      searchTimeout = setTimeout(() => {
        searchProducts(query, resultsContainer, productField, function(product) {
          selectedProduct = product;
          productField.value = product.id;
          searchInput.value = `${product.internal_sku} - ${product.name}`;
          resultsContainer.style.display = 'none';
          
          // Показываем информацию о товаре
          showProductInfo(product);
        });
      }, 300);
    });

    // Закрытие при клике вне
    document.addEventListener('click', function(e) {
      if (!searchContainer.contains(e.target) && e.target !== productField) {
        resultsContainer.style.display = 'none';
      }
    });
  }

  function searchProducts(query, container, productField, onSelect) {
    // AJAX запрос для поиска товаров
    fetch(`/api/v1/products/search/?q=${encodeURIComponent(query)}`)
      .then(response => response.json())
      .then(data => {
        container.innerHTML = '';
        container.style.display = 'block';

        if (data.results && data.results.length > 0) {
          data.results.forEach(product => {
            const item = createProductItem(product, onSelect);
            container.appendChild(item);
          });
        } else {
          container.innerHTML = '<div style="padding:12px;text-align:center;color:var(--muted);">Товары не найдены</div>';
        }
      })
      .catch(error => {
        console.error('Product search error:', error);
        container.innerHTML = '<div style="padding:12px;text-align:center;color:rgba(255,80,120,.9);">Ошибка поиска</div>';
      });
  }

  function createProductItem(product, onSelect) {
    const item = document.createElement('div');
    item.className = 'product-selector__item';
    item.style.padding = '12px';
    item.style.borderBottom = '1px solid var(--stroke)';
    item.style.cursor = 'pointer';
    item.style.transition = 'background 0.2s ease';

    item.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
        <div style="flex:1;">
          <div style="font-weight:600;margin-bottom:4px;">${product.name || 'Без названия'}</div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:4px;">
            ${product.internal_sku || ''} ${product.oem_number ? '· OEM ' + product.oem_number : ''}
          </div>
          ${product.brand ? `<div style="font-size:12px;color:var(--muted);">Бренд: ${product.brand}</div>` : ''}
          ${product.category ? `<div style="font-size:12px;color:var(--muted);">Категория: ${product.category}</div>` : ''}
        </div>
        ${product.photo ? `<img src="${product.photo}" style="width:60px;height:60px;object-fit:cover;border-radius:8px;" alt="${product.name}">` : ''}
      </div>
    `;

    item.addEventListener('mouseenter', function() {
      this.style.background = 'rgba(255,255,255,0.08)';
    });

    item.addEventListener('mouseleave', function() {
      this.style.background = '';
    });

    item.addEventListener('click', function() {
      onSelect(product);
    });

    return item;
  }

  function showProductInfo(product) {
    // Создаём или обновляем блок с информацией о товаре
    let infoBlock = document.getElementById('product-info-block');
    if (!infoBlock) {
      infoBlock = document.createElement('div');
      infoBlock.id = 'product-info-block';
      infoBlock.className = 'card card--glass';
      infoBlock.style.marginTop = '12px';
      infoBlock.style.padding = '12px';
      document.querySelector('.product-selector').parentNode.appendChild(infoBlock);
    }

    infoBlock.innerHTML = `
      <div style="display:flex;gap:12px;">
        ${product.photo ? `<img src="${product.photo}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;" alt="${product.name}">` : ''}
        <div style="flex:1;">
          <div style="font-weight:600;margin-bottom:4px;">${product.name || 'Без названия'}</div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:8px;">
            ${product.internal_sku || ''} ${product.oem_number ? '· OEM ' + product.oem_number : ''}
          </div>
          ${product.brand ? `<div style="font-size:12px;margin-bottom:4px;"><strong>Бренд:</strong> ${product.brand}</div>` : ''}
          ${product.category ? `<div style="font-size:12px;margin-bottom:4px;"><strong>Категория:</strong> ${product.category}</div>` : ''}
          ${product.packaging_type ? `<div style="font-size:12px;margin-bottom:4px;"><strong>Упаковка:</strong> ${product.packaging_type}</div>` : ''}
          ${product.weight_kg ? `<div style="font-size:12px;"><strong>Вес:</strong> ${product.weight_kg} кг</div>` : ''}
        </div>
      </div>
    `;
  }

  // Инициализация при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initProductSelector);
  } else {
    initProductSelector();
  }
})();
