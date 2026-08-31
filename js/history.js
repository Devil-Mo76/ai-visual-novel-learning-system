/* ═══════════════════════════════════════════════
 * history.js — 历史记录（需求三：对话历史 + 测验历史）
 *
 * 职责：
 *  1. 记录当前学习会话中已播放的对话（谁说的 + 内容 + 角色头像小图）。
 *  2. 记录已作答的测验（题目 + 用户答案 + 正确答案 + 是否答对 + 解析）。
 *  3. 用 localStorage 持久化——刷新页面后历史不丢失。
 *  4. 「历史记录」面板：选项卡切换 对话历史 / 测验历史，列表形式展示。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const STORAGE_KEY = "vn_history_v1";

  const History = {
    // —— 数据模型 ——
    dialogues: [],   // { role, name, text, avatar }
    quizzes: [],     // { question, userAnswer, correctAnswer, isCorrect, explain }

    /* —— 头像小图：按角色与其说话时的表情，从 EMO_MAP 取立绘做小圆头像 —— */
    avatarFor(role, emo) {
      // 历史记录专用的角色头像：统一从 images/历史记录头像/ 目录取固定小头像，
      // 按说话角色一一对应（讲述者/提问者/讲师），不再使用播放时的表情立绘。
      const AVATAR_BY_ROLE = {
        teacher: "images/历史记录头像/讲述者头像.png",
        student: "images/历史记录头像/提问者头像.png",
        lecturer: "images/历史记录头像/讲师头像.png",
      };
      return AVATAR_BY_ROLE[role] || "images/历史记录头像/用户头像.png";
    },

    /* —— 记录一条对话：谁说的 + 内容 + 说话时的角色表情头像 —— */
    addDialogue(role, text, emo = "") {
      const name =
        (role === "teacher" && ROLE_NAME && ROLE_NAME.teacher) ||
        (role === "student" && ROLE_NAME && ROLE_NAME.student) ||
        "讲师";
      this.dialogues.push({
        role,
        name,
        text: String(text || ""),
        avatar: this.avatarFor(role, emo),
        time: Date.now(),
      });
      this._save();
    },

    /* —— 记录一次测验作答 —— */
    addQuiz({ question, userAnswer, correctAnswer, isCorrect, explain }) {
      this.quizzes.push({
        question: String(question || ""),
        userAnswer: String(userAnswer || "（未作答）"),
        correctAnswer: String(correctAnswer || ""),
        isCorrect: Boolean(isCorrect),
        explain: String(explain || ""),
        time: Date.now(),
      });
      this._save();
    },

    /* —— localStorage 持久化 —— */
    _save() {
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ dialogues: this.dialogues, quizzes: this.quizzes })
        );
      } catch {
        // 存储失败（如隐私模式）不阻断功能
      }
    },

    /* —— 载入已持久化的历史 —— */
    load() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const data = JSON.parse(raw);
        this.dialogues = Array.isArray(data.dialogues) ? data.dialogues : [];
        this.quizzes = Array.isArray(data.quizzes) ? data.quizzes : [];
      } catch {
        this.dialogues = [];
        this.quizzes = [];
      }
    },

    /* —— 打开历史面板 —— */
    open() {
      this.load();                       // 确保展示持久化数据
      this._switchTab("dialogue");
      $("history-modal").classList.remove("hidden");
    },

    close() {
      $("history-modal").classList.add("hidden");
    },

    /* —— 选项卡切换 —— */
    _switchTab(tab) {
      document.querySelectorAll("#history-modal .htab-btn").forEach((b) =>
        b.classList.toggle("active", b.dataset.tab === tab)
      );
      const pane = tab === "dialogue" ? $("history-dialogue") : $("history-quiz");
      // 两条列表在 CSS 里默认隐藏，只有一个显示
      const showId = tab === "dialogue" ? "history-dialogue" : "history-quiz";
      $("history-dialogue").classList.toggle("hidden", showId !== "history-dialogue");
      $("history-quiz").classList.toggle("hidden", showId !== "history-quiz");

      if (tab === "dialogue") this._renderDialogue();
      else this._renderQuiz();
    },

    /* —— 渲染对话历史列表 —— */
    _renderDialogue() {
      const box = $("history-dialogue");
      box.innerHTML = "";
      if (!this.dialogues.length) {
        box.innerHTML = '<div class="hist-empty">暂无对话记录。</div>';
        return;
      }
      this.dialogues.forEach((d) => {
        const item = document.createElement("div");
        item.className = "hist-dialogue-item";
        item.innerHTML =
          `<img class="hist-avatar" src="${d.avatar}" alt="${d.name}" />` +
          `<div class="hist-body">` +
          `<div class="hist-name">${d.name}</div>` +
          `<div class="hist-text">${d.text}</div>` +
          `</div>`;
        box.appendChild(item);
      });
    },

    /* —— 渲染测验历史列表 —— */
    _renderQuiz() {
      const box = $("history-quiz");
      box.innerHTML = "";
      if (!this.quizzes.length) {
        box.innerHTML = '<div class="hist-empty">暂无测验记录。</div>';
        return;
      }
      this.quizzes.forEach((q) => {
        const item = document.createElement("div");
        item.className = "hist-quiz-item" + (q.isCorrect ? " quiz-ok" : " quiz-bad");
        item.innerHTML =
          `<div class="hist-q-question">${q.question}</div>` +
          `<div class="hist-q-row"><span class="hist-q-label">你的答案</span><span class="hist-q-val">${q.userAnswer}</span></div>` +
          `<div class="hist-q-row"><span class="hist-q-label">正确答案</span><span class="hist-q-val">${q.correctAnswer}</span></div>` +
          `<div class="hist-q-status">${q.isCorrect ? "✅ 答对" : "❌ 答错"}</div>` +
          `<div class="hist-q-explain">${q.explain}</div>`;
        box.appendChild(item);
      });
    },

    /* —— 绑定界面事件 —— */
    bind() {
      $("btn-history") && $("btn-history").addEventListener("click", () => this.open());
      $("btn-history-close") && $("btn-history-close").addEventListener("click", () => this.close());
      document.querySelectorAll("#history-modal .htab-btn").forEach((btn) => {
        btn.addEventListener("click", () => this._switchTab(btn.dataset.tab));
      });
    },
  };

  // 注意：不能挂到 window.History —— 那是浏览器内置的 History 接口（BOM），
  // 不可被覆盖，赋值会静默失败；下游引用 window.History.addDialogue 会在
  // 真实浏览器里报 "History.addDialogue is not a function"，导致「进入学习」加载剧本失败。
  // 因此挂到自定义名 VNHistory，streaming.js 里同步引用。
  window.VNHistory = History;
  document.addEventListener("DOMContentLoaded", () => History.bind());
})();