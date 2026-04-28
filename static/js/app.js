;(function () {
  var root = document.documentElement

  // ---------- Theme ----------
  var THEME_KEY = "wms-theme"

  function applyTheme(theme) {
    if (theme !== "light" && theme !== "dark") theme = "light"
    root.setAttribute("data-theme", theme)
    var btn = document.getElementById("theme-toggle")
    if (btn) btn.dataset.theme = theme
  }

  var storedTheme = null
  try { storedTheme = window.localStorage.getItem(THEME_KEY) } catch (e) {}

  var initialTheme = storedTheme
  if (!initialTheme && window.matchMedia) {
    initialTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  }
  applyTheme(initialTheme || "light")

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("#theme-toggle")
    if (!btn) return
    var current = root.getAttribute("data-theme") || "light"
    var next = current === "dark" ? "light" : "dark"
    try { window.localStorage.setItem(THEME_KEY, next) } catch (e) {}
    applyTheme(next)
  })

  // ---------- Sidebar collapse ----------
  var SB_KEY = "wms-sidebar"

  function applySidebar(state) {
    var shell = document.getElementById("app-shell")
    if (!shell) return
    if (state === "collapsed") shell.setAttribute("data-sidebar", "collapsed")
    else shell.removeAttribute("data-sidebar")
  }

  var storedSb = null
  try { storedSb = window.localStorage.getItem(SB_KEY) } catch (e) {}
  if (storedSb === "collapsed") applySidebar("collapsed")

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("#sidebar-collapse")
    if (!btn) return
    var shell = document.getElementById("app-shell")
    if (!shell) return
    var next = shell.getAttribute("data-sidebar") === "collapsed" ? "expanded" : "collapsed"
    applySidebar(next)
    try { window.localStorage.setItem(SB_KEY, next) } catch (e) {}
  })

  // ---------- Global shortcuts ----------
  document.addEventListener("keydown", function (e) {
    var isMod = e.ctrlKey || e.metaKey
    // Ctrl/Cmd + K — фокус глобального поиска
    if (isMod && (e.key === "k" || e.key === "K")) {
      var input = document.getElementById("topbar-search-input")
      if (input) { e.preventDefault(); input.focus(); input.select() }
      return
    }
    // Alt + S — открыть сканер
    if (e.altKey && (e.key === "s" || e.key === "S")) {
      var sc = document.getElementById("topbar-scanner")
      if (sc) { e.preventDefault(); sc.click() }
    }
  })

  // ---------- Data table density toggle ----------
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-density-set]")
    if (!btn) return
    var table = btn.closest(".data-table")
    if (!table) return
    var v = btn.getAttribute("data-density-set")
    table.setAttribute("data-density", v)
    var siblings = table.querySelectorAll("[data-density-set]")
    for (var i = 0; i < siblings.length; i++) {
      siblings[i].setAttribute("aria-pressed", siblings[i] === btn ? "true" : "false")
    }
    try { window.localStorage.setItem("wms-density", v) } catch (e) {}
  })

  // Apply persisted density on load
  document.addEventListener("DOMContentLoaded", function () {
    var v = null
    try { v = window.localStorage.getItem("wms-density") } catch (e) {}
    if (!v) return
    var tables = document.querySelectorAll(".data-table")
    for (var i = 0; i < tables.length; i++) {
      tables[i].setAttribute("data-density", v)
      var btns = tables[i].querySelectorAll("[data-density-set]")
      for (var j = 0; j < btns.length; j++) {
        btns[j].setAttribute("aria-pressed", btns[j].getAttribute("data-density-set") === v ? "true" : "false")
      }
    }
  })
})()
