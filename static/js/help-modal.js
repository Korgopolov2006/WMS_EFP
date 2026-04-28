/**
 * Универсальный компонент модального окна помощи
 */
(function() {
  'use strict';

  // Инициализация модального окна
  function initHelpModal() {
    const helpBtn = document.getElementById('help-btn');
    const helpModal = document.getElementById('help-modal');
    
    if (!helpBtn || !helpModal) {
      return;
    }

    const closeBtn = helpModal.querySelector('.help-modal__close');
    const modalContent = helpModal.querySelector('.help-modal__content');

    // Открытие модального окна
    helpBtn.addEventListener('click', function(e) {
      e.preventDefault();
      helpModal.classList.add('help-modal--active');
      document.body.style.overflow = 'hidden';
    });

    // Закрытие по крестику
    if (closeBtn) {
      closeBtn.addEventListener('click', function() {
        closeModal();
      });
    }

    // Закрытие по клику вне окна
    helpModal.addEventListener('click', function(e) {
      if (e.target === helpModal) {
        closeModal();
      }
    });

    // Закрытие по Escape
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && helpModal.classList.contains('help-modal--active')) {
        closeModal();
      }
    });

    // Предотвращение закрытия при клике на контент
    if (modalContent) {
      modalContent.addEventListener('click', function(e) {
        e.stopPropagation();
      });
    }

    function closeModal() {
      helpModal.classList.remove('help-modal--active');
      document.body.style.overflow = '';
    }
  }

  // Инициализация при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHelpModal);
  } else {
    initHelpModal();
  }
})();
