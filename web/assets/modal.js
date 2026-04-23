/*
 * Modal
 *
 * Pico.css - https://picocss.com
 * Copyright 2019-2023 - Licensed under MIT
 */

// Config
const isOpenClass = "modal-is-open";
const openingClass = "modal-is-opening";
const closingClass = "modal-is-closing";
const animationDuration = 400; // ms
let visibleModal = null;

// Função para abrir o modal
function openModalHandler(modal) {
  console.log("Modal is being opened."); 
  
  if (isScrollbarVisible()) {
    document.documentElement.style.setProperty(
      "--scrollbar-width",
      `${getScrollbarWidth()}px`
    );
  }
  
  document.documentElement.classList.add(isOpenClass, openingClass);
  
  setTimeout(() => {
    visibleModal = modal;
    document.documentElement.classList.remove(openingClass);
  }, animationDuration);
  
  modal.setAttribute("open", true);
  modal.style.display = "block"; // Também exibe o modal
}

// Função para fechar o modal
function closeModalHandler(modal) {
  visibleModal = null;
  
  document.documentElement.classList.add(closingClass);
  
  setTimeout(() => {
      document.documentElement.classList.remove(closingClass, isOpenClass);
      document.documentElement.style.removeProperty("--scrollbar-width");
      modal.removeAttribute("open");
      modal.style.display = "none"; // Também esconde o modal
  }, animationDuration);
}

// Fechar modal ao clicar fora
document.addEventListener("click", (event) => {
  if (visibleModal != null) {
      const modalContent = visibleModal.querySelector(".modal-content");
      const isClickInside = modalContent.contains(event.target);
      if (!isClickInside) {
          closeModalHandler(visibleModal);
      }
  }
});

// Fechar modal com o botão "X"
document.querySelector('.close').addEventListener('click', function() {
  closeModalHandler(document.getElementById('infoModal'));
});


// Fechar modal com tecla Esc
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && visibleModal != null) {
    closeModalHandler(visibleModal);
  }
});

// Largura da barra de rolagem
const getScrollbarWidth = () => {
  const outer = document.createElement("div");
  outer.style.visibility = "hidden";
  outer.style.overflow = "scroll"; 
  outer.style.msOverflowStyle = "scrollbar"; 
  document.body.appendChild(outer);

  const inner = document.createElement("div");
  outer.appendChild(inner);

  const scrollbarWidth = outer.offsetWidth - inner.offsetWidth;

  outer.parentNode.removeChild(outer);

  return scrollbarWidth;
};

const isScrollbarVisible = () => {
  return document.body.scrollHeight > screen.height;
};

