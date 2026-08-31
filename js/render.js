/* ═══════════════════════════════════════════════
 * render.js — 画面渲染层
 * 职责：切背景、换立绘表情、写对话栏、渲染弹题与存档列表。
 * 只做「按数据渲染」，判断逻辑全部在 streaming.js。
 * ═══════════════════════════════════════════════ */

const Render = {
  // DOM 句柄缓存
  el: {
    bg: () => document.getElementById("bg-layer"),
    teacher: () => document.getElementById("sprite-teacher"),
    student: () => document.getElementById("sprite-student"),
    chapterBar: () => document.getElementById("chapter-bar"),
    dialogBox: () => document.getElementById("dialog-box"),
    dialogName: () => document.getElementById("dialog-name"),
    dialogText: () => document.getElementById("dialog-text"),
    questionBox: () => document.getElementById("question-box"),
    qAsker: () => document.getElementById("q-asker"),
    qText: () => document.getElementById("q-text"),
    qChoices: () => document.getElementById("q-choices"),
    qInputArea: () => document.getElementById("q-input-area"),
    qInput: () => document.getElementById("q-input"),
    qSubmit: () => document.getElementById("q-submit"),
    qFeedback: () => document.getElementById("q-feedback"),
    qContinue: () => document.getElementById("q-continue"),
    qPeek: () => document.getElementById("q-peek-answer"),
    slotModal: () => document.getElementById("modal-slots"),
    slotGrid: () => document.getElementById("slot-grid"),
  },

  /* —— 背景 —— */
  setBackground(key) {
    const img = BG_MAP[key] || BG_FALLBACK;
    const bg = this.el.bg();
    bg.style.backgroundImage = `url("${encodeURI(img)}")`;
  },

  /* —— 立绘：设置角色表情 —— */
  setSprite(role, emo) {
    const map = EMO_MAP[role];
    const fallback = map[Object.keys(map)[0]];
    const img = map[emo] || fallback;           // 未知标签 → 角色默认表情
    const el = role === "teacher" ? this.el.teacher() : this.el.student();
    this.crossfade(el, img);
    return img;
  },

  /* —— 讲师立绘（一对一辅导模式，单独占屏）—— */
  setLecturerSprite(emo) {
    const src = LECTURER_EMO_MAP[emo] || LECTURER_EMO_MAP.jiangjie;   // 未知标签回退默认讲解
    const el = document.getElementById("sprite-lecturer");
    if (!el) return;
    if (el.dataset.src === src) return;
    el.dataset.src = src;
    el.style.backgroundImage = `url("${encodeURI(src)}")`;
  },
  showLecturer(emo) {
    this.setLecturerSprite(emo);
    const el = document.getElementById("sprite-lecturer");
    if (el) {
      el.classList.add("sprite-on");
      el.classList.remove("sprite-off");
    }
    // 隐藏讲述者/提问者立绘（讲师模式单人占屏）
    this.el.teacher().classList.add("sprite-off");
    this.el.teacher().classList.remove("sprite-on");
    this.el.student().classList.add("sprite-off");
    this.el.student().classList.remove("sprite-on");
  },
  // 关闭讲师后恢复「讲述者/提问者」立绘（需求2）。
  // 优先按当前剧情步骤的说话者恢复；无上下文时默认恢复讲师（teacher）。
  hideLecturer() {
    const el = document.getElementById("sprite-lecturer");
    if (el) {
      el.classList.add("sprite-off");
      el.classList.remove("sprite-on");
    }
    // 依据当前播放步骤，把立绘还给当下的说话者
    let speaker = "teacher";
    // Modes 是顶层 const（不挂到 window），不能再用 window.Modes（总为 undefined），须直接取模块级全局
    if (typeof Modes !== "undefined" && Modes.currentScript) {
      const ch = Modes.currentScript.chapters[Modes.chapterIndex];
      const step = ch && ch.steps[Modes.stepIndex];
      if (step && step.speaker) speaker = step.speaker;
    }
    this.showSpeakerOnly(speaker);
    this.setSprite(speaker, "jiangjie");
  },

  /* —— 单人轮播：只显示当前说话者，另一侧淡出（需求5）—— */
  showSpeakerOnly(speaker) {
    const teacherEl = this.el.teacher();
    const studentEl = this.el.student();
    if (speaker === "teacher") {
      teacherEl.classList.add("sprite-on");
      teacherEl.classList.remove("sprite-off");
      studentEl.classList.add("sprite-off");
      studentEl.classList.remove("sprite-on");
    } else {
      studentEl.classList.add("sprite-on");
      studentEl.classList.remove("sprite-off");
      teacherEl.classList.add("sprite-off");
      teacherEl.classList.remove("sprite-on");
    }
  },

  /** 切换立绘 src，带淡入淡出 */
  crossfade(el, src) {
    const encoded = encodeURI(src);
    if (el.dataset.src === encoded) return;   // 同一表情不重复切换
    el.dataset.src = encoded;
    el.style.opacity = 0;
    const imgEl = new Image();
    imgEl.onload = () => {
      el.style.backgroundImage = `url("${encoded}")`;
      el.style.opacity = 1;
    };
    imgEl.onerror = () => {
      // 图片缺失时保持空白，不阻断剧情
      el.style.backgroundImage = "";
      el.style.opacity = 1;
    };
    imgEl.src = encoded;
  },

  /* —— 对话栏 —— */
  showDialogBox() {
    this.el.dialogBox().classList.remove("dialog-hidden");
  },
  hideDialogBox() {
    this.el.dialogBox().classList.add("dialog-hidden");
  },

  setChapterBar(label) {
    this.el.chapterBar().textContent = label;
  },
  setChapterBarVisible(v) {
    this.el.chapterBar().style.opacity = v ? 1 : 0;
  },

  /* —— 弹题框：支持选择/填空/简答三种题型 —— */
  showQuestion({ asker, text, choices, quizType }) {
    const box = this.el.questionBox();
    this.el.qAsker().textContent = asker;
    this.el.qText().textContent = text;

    const wrap = this.el.qChoices();
    const inputArea = this.el.qInputArea();
    const input = this.el.qInput();

    wrap.innerHTML = "";
    // 选择题：渲染选项按钮
    if (quizType === "choice") {
      inputArea.classList.add("hidden");
      (choices || []).forEach((choice, i) => {
        const btn = document.createElement("button");
        btn.className = "q-choice";
        btn.dataset.index = String(i);
        btn.textContent = choice;
        wrap.appendChild(btn);
      });
    } else {
      // 填空/简答：显示文本输入区
      wrap.innerHTML = "";
      inputArea.classList.remove("hidden");
      input.value = "";
      input.placeholder =
        quizType === "fill" ? "请填写你的答案…" : "请用你自己的话复述要点（覆盖 70%-80% 即通过）…";
    }

    this.el.qFeedback().classList.add("hidden");
    this.el.qFeedback().textContent = "";
    this.el.qContinue().classList.add("hidden");
    // 「深入学习」按钮跟随弹题框展示（用讲师深入讲解这道题）
    document.getElementById("q-deep-dive").classList.remove("hidden");
    box.classList.remove("hidden");
  },

  /** 弹题反馈：正确显「✓」，错误显「✗」并给出讲评 */
  showQuestionFeedback(correct, explain, correctChoice) {
    const fb = this.el.qFeedback();
    fb.classList.remove("hidden");
    const head = correct ? "🎉 回答正确！" : "❌ 回答错误";
    fb.innerHTML =
      `<div class="q-fb-head ${correct ? "fb-ok" : "fb-bad"}">${head}` +
      (correct ? "" : `（正确答案：${correctChoice}）`) + `</div>` +
      `<div class="q-fb-explain">${explain}</div>`;
    this.el.qContinue().classList.remove("hidden");
  },

  hideQuestion() {
    this.el.questionBox().classList.add("hidden");
    this.el.qPeek().classList.add("hidden");   // 收起弹出框时一并隐藏「查看答案」
    document.getElementById("q-deep-dive").classList.add("hidden");   // 深度学习按钮随之隐藏
  },

  /** 填空/简答：亮出正确答案或剩余次数提示（需求：答错满 3 次出示答案）*/
  revealAnswer(answerText = "", hint = "") {
    const fb = this.el.qFeedback();
    fb.classList.remove("hidden");
    if (answerText) {
      fb.innerHTML =
        `<div class="q-fb-head fb-answer">💡 正确答案</div>` +
        `<div class="q-fb-explain">${answerText}</div>`;
    } else {
      fb.innerHTML = `<div class="q-fb-explain q-fb-hint">${hint}</div>`;
    }
  },

  /* —— 存档列表 —— */
  showSlots(slots, scriptId, onPick) {
    const grid = this.el.slotGrid();
    grid.innerHTML = "";
    for (let i = 0; i <= 9; i++) {
      const cell = document.createElement("div");
      cell.className = "slot-cell";
      const hit = slots.find((s) => s.slot === i);
      if (hit) {
        cell.innerHTML =
          `<div class="slot-name">${i === 0 ? "⭐ 自动存档" : `手动存档 ${i}`}</div>` +
          `<div class="slot-info">章节 ${hit.chapter_index + 1} · 步 ${hit.step_index + 1}</div>` +
          `<div class="slot-time">${hit.updated_at}</div>`;
        cell.dataset.slot = String(i);
        cell.addEventListener("click", () => onPick(i));
        cell.classList.add("slot-occupied");
      } else {
        cell.innerHTML = `<div class="slot-name">${i === 0 ? "⭐ 自动存档" : `手动存档 ${i}`}</div><div class="slot-empty">空</div>`;
        cell.dataset.slot = String(i);
        cell.addEventListener("click", () => onPick(i));   // 空槽也能存
        cell.classList.add("slot-empty");
      }
      grid.appendChild(cell);
    }
    this.el.slotModal().classList.remove("hidden");
  },
  hideSlots() {
    this.el.slotModal().classList.add("hidden");
  },

  toast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.remove("hidden");
    toast.classList.add("show");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  },
};