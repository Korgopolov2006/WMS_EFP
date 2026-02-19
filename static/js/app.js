;(function () {
  var key = "wms-theme"
  var root = document.documentElement

  function applyTheme(theme) {
    if (theme !== "light" && theme !== "dark") theme = "dark"
    root.setAttribute("data-theme", theme)
    var btn = document.getElementById("theme-toggle")
    if (btn) {
      btn.dataset.theme = theme
      btn.textContent = theme === "dark" ? "Тёмная" : "Светлая"
    }
  }

  var stored = null
  try {
    stored = window.localStorage.getItem(key)
  } catch (e) {}

  var initial = stored
  if (!initial && window.matchMedia) {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) initial = "light"
  }
  applyTheme(initial || "dark")

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("#theme-toggle")
    if (!btn) return
    var current = root.getAttribute("data-theme") || "dark"
    var next = current === "dark" ? "light" : "dark"
    try {
      window.localStorage.setItem(key, next)
    } catch (e) {}
    applyTheme(next)
  })
})()

