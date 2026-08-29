document.addEventListener("DOMContentLoaded", function () {
  var toggleBtn = document.getElementById("sidebarToggle");
  var sidebar = document.getElementById("appSidebar");
  var backdrop = document.getElementById("sidebarBackdrop");

  function closeSidebar() {
    sidebar.classList.remove("show");
    backdrop.classList.remove("show");
    toggleBtn.setAttribute("aria-expanded", "false");
  }

  function openSidebar() {
    sidebar.classList.add("show");
    backdrop.classList.add("show");
    toggleBtn.setAttribute("aria-expanded", "true");
  }

  if (toggleBtn && sidebar && backdrop) {
    toggleBtn.addEventListener("click", function () {
      var isOpen = sidebar.classList.contains("show");
      isOpen ? closeSidebar() : openSidebar();
    });
    backdrop.addEventListener("click", closeSidebar);
  }

  document.querySelectorAll("[data-auto-dismiss]").forEach(function (el) {
    setTimeout(function () {
      var alert = bootstrap.Alert.getOrCreateInstance(el);
      alert.close();
    }, 6000);
  });
});
