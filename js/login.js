/* ═══════════════════════════════════════════════
 * login.js — 模拟登录（需求：登录功能）
 *
 * 职责：
 *  1. 程序启动时显示全屏登录遮罩（毛玻璃 + 柔和渐变，贴合视觉小说风格）。
 *  2. 模拟登录：不校验账号——任意用户名/密码点击登录都能进入主界面。
 *  3. 支持「回车快捷登录」：在用户名或密码输入框内按回车即触发登录。
 *  4. 登录成功：遮罩淡出，同时在主界面右上角显示当前登录用户的圆形小头像。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const Login = {
    // —— 模拟登录入口：不做真实校验，任何输入均可进入 ——
    login() {
      const overlay = $("login-overlay");
      // 触发淡出（opacity → 0）
      overlay.classList.add("logged-in");
      // 淡出结束后隐藏遮罩，避免仍拦截页面交互
      setTimeout(() => overlay.classList.add("hidden"), 360);

      // 显示右上角用户头像（默认图，圆形小尺寸）
      const avatar = $("user-avatar");
      if (avatar) avatar.classList.remove("hidden");

      // Render 是顶层 const（不挂到 window），不能用 window.Render（总为 undefined）
      if (typeof Render !== "undefined") Render.toast("登录成功，欢迎回来！");
    },

    bind() {
      const btn = $("btn-login");
      if (btn) btn.addEventListener("click", () => this.login());

      // 回车快捷登录：用户名 / 密码输入框内按回车都触发登录
      ["login-username", "login-password"].forEach((id) => {
        const el = $(id);
        if (!el) return;
        el.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            this.login();
          }
        });
      });
    },
  };

  window.Login = Login;

  document.addEventListener("DOMContentLoaded", () => Login.bind());
})();