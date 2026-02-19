/**
 * Компонент для проверки деталей через EFP Parts
 */
(function() {
  'use strict';

  function initEFPChecker() {
    const form = document.getElementById('receiving-line-form');
    if (!form) {
      return;
    }

    const oemInput = document.getElementById('efp-oem-input');
    const checkBtn = document.getElementById('efp-check-btn');

    if (!oemInput || !checkBtn) {
      return;
    }

    // Обработчик кнопки проверки
    checkBtn.addEventListener('click', function() {
      const oemCode = oemInput.value.trim();
      if (!oemCode) {
        alert('Введите OEM код для проверки');
        return;
      }
      checkPartOnEFP(oemCode);
    });

    // Создаём модальное окно для результатов
    createEFPModal();
  }

  function createEFPModal() {
    const modal = document.createElement('div');
    modal.id = 'efp-modal';
    modal.className = 'help-modal';
    modal.innerHTML = `
      <div class="help-modal__content" style="max-width: 800px;">
        <div class="help-modal__header">
          <h2 class="help-modal__title">Результаты поиска на EFP Parts</h2>
          <button class="help-modal__close" aria-label="Закрыть">&times;</button>
        </div>
        <div class="help-modal__body" id="efp-results">
          <div style="text-align:center;padding:40px;">
            <div class="hint">Загрузка...</div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    // Обработчики закрытия
    const closeBtn = modal.querySelector('.help-modal__close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeEFPModal);
    }
    modal.addEventListener('click', function(e) {
      if (e.target === modal) {
        closeEFPModal();
      }
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && modal.classList.contains('help-modal--active')) {
        closeEFPModal();
      }
    });
  }

  function checkPartOnEFP(oemCode) {
    const modal = document.getElementById('efp-modal');
    const resultsContainer = document.getElementById('efp-results');
    
    if (!modal || !resultsContainer) {
      return;
    }

    // Показываем модальное окно
    modal.classList.add('help-modal--active');
    document.body.style.overflow = 'hidden';
    
    // Показываем загрузку
    resultsContainer.innerHTML = '<div style="text-align:center;padding:40px;"><div class="hint">Поиск детали на EFP Parts...</div></div>';

    // Делаем запрос
    fetch(`/efp/search/?oem=${encodeURIComponent(oemCode)}`)
      .then(response => response.json())
      .then(data => {
        if (data.success && data.results && data.results.length > 0) {
          displayEFPResults(data.results, oemCode);
        } else {
          resultsContainer.innerHTML = `
            <div style="text-align:center;padding:40px;">
              <div class="hint" style="color:rgba(255,80,120,.9);">${data.error || 'Деталь не найдена'}</div>
              <button class="btn btn--ghost" style="margin-top:20px;" onclick="document.getElementById('efp-modal').classList.remove('help-modal--active'); document.body.style.overflow='';">Закрыть</button>
            </div>
          `;
        }
      })
      .catch(error => {
        console.error('EFP search error:', error);
        resultsContainer.innerHTML = `
          <div style="text-align:center;padding:40px;">
            <div class="hint" style="color:rgba(255,80,120,.9);">Ошибка подключения к EFP Parts</div>
            <button class="btn btn--ghost" style="margin-top:20px;" onclick="document.getElementById('efp-modal').classList.remove('help-modal--active'); document.body.style.overflow='';">Закрыть</button>
          </div>
        `;
      });
  }

  function displayEFPResults(results, oemCode) {
    const resultsContainer = document.getElementById('efp-results');
    if (!resultsContainer) {
      return;
    }

    let html = '<div class="grid grid--2" style="gap:16px;margin-top:20px;">';
    
    results.forEach((result, index) => {
      html += `
        <div class="card card--glass" style="padding:16px;">
          ${result.photo_url ? `<img src="${result.photo_url}" style="width:100%;max-width:200px;height:auto;border-radius:8px;margin-bottom:12px;" alt="${result.name || ''}" onerror="this.style.display='none';">` : ''}
          <h3 style="font-size:16px;font-weight:600;margin-bottom:8px;">${result.name || 'Без названия'}</h3>
          ${result.brand ? `<div class="hint" style="margin-bottom:4px;"><strong>Бренд:</strong> ${result.brand}</div>` : ''}
          ${result.price ? `<div class="hint" style="margin-bottom:4px;"><strong>Цена:</strong> ${result.price}</div>` : ''}
          ${result.availability ? `<div class="hint" style="margin-bottom:4px;"><strong>Наличие:</strong> ${result.availability}</div>` : ''}
          ${result.detail_url ? `<a href="${result.detail_url}" target="_blank" class="hint" style="display:block;margin-bottom:12px;">Открыть на EFP Parts →</a>` : ''}
          <button class="btn btn--primary btn--block" onclick="selectEFPPart(${index})">Выбрать эту деталь</button>
        </div>
      `;
    });
    
    html += '</div>';
    html += '<button class="btn btn--ghost" style="margin-top:20px;" onclick="closeEFPModal()">Отмена</button>';
    
    resultsContainer.innerHTML = html;
    
    // Сохраняем результаты в глобальную переменную для использования в selectEFPPart
    window.efpResults = results;
    window.efpOemCode = oemCode;
  }

  window.selectEFPPart = function(index) {
    const results = window.efpResults;
    const oemCode = window.efpOemCode;
    
    if (!results || !results[index]) {
      return;
    }

    const part = results[index];
    
    // Заполняем форму приёмки
    const form = document.getElementById('receiving-line-form');
    if (!form) {
      return;
    }

    // Заполняем OEM (если есть поле)
    const oemInput = form.querySelector('[name*="oem"], [id*="oem"], #id_oem_check');
    if (oemInput && oemCode) {
      oemInput.value = oemCode;
    }

    // Ищем поле товара и пытаемся найти товар по OEM
    const productField = document.getElementById('id_product');
    if (productField && oemCode) {
      // Можно попробовать найти товар в базе по OEM
      // Пока просто оставляем поле пустым, пользователь выберет вручную
    }

    // Закрываем модальное окно
    closeEFPModal();
    
    // Показываем сообщение
    alert(`Деталь "${part.name || 'выбрана'}" выбрана. Заполните остальные поля формы.`);
  };

  window.closeEFPModal = function() {
    const modal = document.getElementById('efp-modal');
    if (modal) {
      modal.classList.remove('help-modal--active');
      document.body.style.overflow = '';
    }
  };

  // Инициализация при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEFPChecker);
  } else {
    initEFPChecker();
  }
})();
