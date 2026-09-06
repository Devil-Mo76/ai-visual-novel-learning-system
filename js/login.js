/* ═══════════════════════════════════════════════
 * login.js — 真实登录闭环（需求：多用户隔离）
 *
 * 职责：
 *  1. 启动时：若已有 token 则直接进入（跳过登录遮罩）；否则显示登录遮罩。
 *  2. 登录：POST /api/auth/login；若账号不存在（401）则自动注册同一账号密码再登录。
 *  3. 成功后把 access_token 存 localStorage（vn_token），用户名存 vn_user。
 *  4. 退出登录：清 token，重新显示登录遮罩。
 *  5. 注册 Api.onAuthExpired：token 失效时自动回到登录遮罩。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const Login = {
    /* —— 是否已登录（本地有 token）—— */
    isLoggedIn() {
      return !!localStorage.getItem("vn_token");
    },

    /* —— 尝试登录：账号不存在则自动注册同一账号密码 —— */
    async login() {
      const overlay = $("login-overlay");
      const username = ($("login-username").value || "").trim();
      const password = $("login-password").value;
      if (!username || !password) {
        Render.toast("请输入用户名和密码。");
        return;
      }
      try {
        let res;
        try {
          res = await Api.login(username, password);
        } catch (err) {
          // 账号不存在等登录失败 → 尝试注册并登录
          res = await Api.register(username, password);
        }
        localStorage.setItem("vn_token", res.access_token);
        localStorage.setItem("vn_user", res.user.username);

        overlay.classList.add("logged-in");
        setTimeout(() => overlay.classList.add("hidden"), 360);
        const avatar = $("user-avatar");
        if (avatar) avatar.classList.remove("hidden");
        this._showAvatar(true);
        Render.toast(`登录成功，欢迎 ${res.user.username}！`);
        // 登录后刷新当前屏数据（如资料库/设置），触发回调
        if (window.App && App.onLogin) App.onLogin();
      } catch (err) {
        Render.toast(`登录失败：${err.message}`);
      }
    },

    /* —— 头像显隐 / 用户菜单名称同步 —— */
    _showAvatar(show) {
      const avatar = $("user-avatar");
      if (avatar) avatar.classList.toggle("hidden", !show);
      this._syncUserName();
    },
    _syncUserName() {
      const nameEl = $("user-menu-name");
      if (nameEl) nameEl.textContent = localStorage.getItem("vn_user") || "未登录";
    },

    /* —— 打开/收起用户管理面板（头像点击）—— */
    toggleUserMenu() {
      const menu = $("user-menu");
      if (!menu) return;
      const willShow = menu.classList.contains("hidden");
      this._syncUserName();
      menu.classList.toggle("hidden", !willShow);
      if (willShow) {
        // 关闭其它可能覆盖它的界面逻辑见外层点击
      }
    },
    closeUserMenu() {
      const menu = $("user-menu");
      if (menu) menu.classList.add("hidden");
    },

    /* —— 退出登录：清 token，回登录遮罩，并复位本地会话防残留 —— */
    logout() {
      localStorage.removeItem("vn_token");
      localStorage.removeItem("vn_user");
      this._showAvatar(false);
      this.closeUserMenu();
      // 复位主页当前屏的选中/生成状态，避免看到上一账号残留
      if (window.App && App.resetSession) App.resetSession();
      const overlay = $("login-overlay");
      overlay.classList.remove("hidden");
      overlay.classList.remove("logged-in");
      Render.toast("已退出登录。");
    },

    bind() {
      // 登录包在 <form> 里以消除「密码不在表单内」提示；一律阻止原生提交，
      // 登录只由按钮点击 / 输入框回车触发，避免整页刷新或重复登录。
      const form = $("login-form");
      if (form) form.addEventListener("submit", (e) => e.preventDefault());

      const btn = $("btn-login");
      if (btn) btn.addEventListener("click", () => this.login());

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

      // 头像点击 → 弹出用户管理面板；退出登录按钮 → 退出
      const avatar = $("user-avatar");
      if (avatar) avatar.addEventListener("click", (e) => {
        e.stopPropagation();
        this.toggleUserMenu();
      });
      const logoutBtn = $("btn-user-logout");
      if (logoutBtn) logoutBtn.addEventListener("click", () => this.logout());
      // 点击其它区域收起用户面板
      document.addEventListener("click", () => this.closeUserMenu());

      // token 失效回调：自动回到登录遮罩
      Api.onAuthExpired = () => {
        const overlay = $("login-overlay");
        overlay.classList.remove("hidden");
        overlay.classList.remove("logged-in");
        this._showAvatar(false);
        this.closeUserMenu();
        Render.toast("登录已失效，请重新登录。");
      };
    },
  };

  window.Login = Login;

  document.addEventListener("DOMContentLoaded", () => {
    Login.bind();
    // 若已有 token，直接隐藏登录遮罩进入（已登录）
    if (Login.isLoggedIn()) {
      const overlay = $("login-overlay");
      overlay.classList.add("logged-in");
      setTimeout(() => overlay.classList.add("hidden"), 50);
      Login._showAvatar(true);
    }
  });
})();
