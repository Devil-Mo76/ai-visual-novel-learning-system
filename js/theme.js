/* ═══════════════════════════════════════════════
 * theme.js — 白天 / 黑夜主题切换
 *   - 根元素 <html data-theme="dark|light">
 *   - 记忆到 localStorage["vn_theme"]
 *   - 两个入口按钮：主菜单左下角 #btn-theme-menu、游戏内左下角 #btn-theme-player
 * ═══════════════════════════════════════════════ */
(() => {
  "use strict";

  const KEY = "vn_theme";
  const ROOT = document.documentElement;

  function current() {
    return ROOT.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  /* 按钮内容：当前暗黑 → 显示"☀ 白天"（点了变白天）；当前白天 → 显示"🌙 黑夜" */
  function paintButtons() {
    const light = current() === "light";
    const emoji = light ? "🌙" : "☀️";
    const label = light ? "黑夜" : "白天";
    const mark = light ? "night" : "day";
    document.querySelectorAll(".theme-toggle-btn").forEach((btn) => {
      btn.dataset.mode = mark;
      btn.innerHTML = `<span class="tt-emoji">${emoji}</span><span class="tt-label">${label}</span>`;
    });
  }

  function setTheme(t) {
    ROOT.setAttribute("data-theme", t);
    try { localStorage.setItem(KEY, t); } catch (e) {}
    paintButtons();
  }

  function toggle() {
    setTheme(current() === "dark" ? "light" : "dark");
  }

  function bind() {
    document.querySelectorAll(".theme-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", toggle);
    });
    paintButtons();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
