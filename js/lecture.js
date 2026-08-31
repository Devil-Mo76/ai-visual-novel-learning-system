/* ═══════════════════════════════════════════════
 * lecture.js — 讲师一对一辅导模式（需求：用户召唤的专属讲师）
 *
 * 职责：
 *  1. 通过「讲师」悬浮按钮 / 弹题「深入学习」按钮进入讲师模式。
 *  2. 进入后：双人立绘淡出，讲师立绘单独占屏，弹题框变身「一对一辅导面板」。
 *  3. 用户输入问题 → POST /api/lecture/chat（SSE 流式）→
 *     后端逐段返回 {talk_emo, text}，前端实时换讲师立绘 + 追加气泡。
 *  4. 会话记忆由后端按 script_id 维护（多轮连贯）。
 *  5. 「返回学习」→ 清会话、恢复双人立绘、回到弹题框续播。
 *
 * 讲师表情：英文标签（jiangjie/kaixin/sikao/yansutixing/shengqi）
 * → LECTURER_EMO_MAP（config.js）映射到 images/讲师/ 中文立绘。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const Lecture = {
    active: false,          // 当前是否处于讲师模式

    /* —— 记忆入口上下文（进入时由调用方传入）——
     * enterFrom: "fab"（主界面悬浮按钮） | "question"（弹题深入学习按钮）
     * context  : 当前上下文文字（章节标题 / 题目 / 讲评），后端据此定位疑难。 */
    enterFrom: null,
    context: "",

    /* —— 进入讲师模式 —— */
    enter(enterFrom, context = "") {
      this.enterFrom = enterFrom;
      this.context = context || "";

      // 1. 暂停双人播放（讲师接管画面）
      // Modes 是顶层 const（不挂到 window），不能用 window.Modes（总为 undefined）
      if (typeof Modes !== "undefined") {
        Modes.isPlaying = false;
      }
      window.Typing && Typing.cancel();
      window.Streaming && Streaming._clearAutoTimer && Streaming._clearAutoTimer();

      // 2. 收起弹题框（会话区已移至底部对话栏内，不再复甩弹题框面板）
      const box = $("question-box");
      box.classList.add("hidden");
      box.classList.remove("lecture-mode");

      // 3. 底部对话栏变身讲师辅导栏：复用 #dialog-box，
      //    与讲述者/提问者共用同一条对话栏
      const db = $("dialog-box");
      db.classList.remove("dialog-hidden");
      db.classList.add("lecture-mode");

      // 4. 切到讲师立绘（单人占屏），隐藏双人
      Render.showLecturer("kaixin");  // 讲师进场：欢迎表情

      // 5. 会话区就绪
      const session = $("lecture-session");
      session.classList.remove("hidden");
      $("lecture-chat").innerHTML =
        '<div class="lec-empty">🎓 讲师已就位。你可以针对当前难点自由提问，我会一对一为你讲透。</div>';
      $("lecture-input").value = "";
      $("lecture-input").focus();

      this.active = true;
    },

    /* —— 提一个问题并流式接收讲师回答 —— */
    async ask() {
      if (!this.active) return;
      const input = $("lecture-input");
      const q = input.value.trim();
      if (!q) {
        Render.toast("请先输入你想深入了解的问题。");
        return;
      }
      if (!Modes.scriptId) {
        Render.toast("尚未进入学习，请先开始学习。");
        return;
      }

      // 追加用户气泡
      const chatBox = $("lecture-chat");
      const userBubble = document.createElement("div");
      userBubble.className = "lec-user";
      userBubble.textContent = q;
      chatBox.appendChild(userBubble);
      chatBox.scrollTop = chatBox.scrollHeight;

      // 讲师气泡（流式填充）
      const tutorBubble = document.createElement("div");
      tutorBubble.className = "lec-tutor";
      chatBox.appendChild(tutorBubble);
      let full = "";

      const sendBtn = $("btn-lecture-send");
      sendBtn.disabled = true;
      sendBtn.textContent = "讲师讲解中…";
      input.disabled = true;

      try {
        await Api.lectureChat(
          Modes.scriptId,
          q,
          this.context,
          (seg) => {
            // 逐段：先换讲师表情，再追加文本
            if (seg.talk_emo) Render.showLecturer(seg.talk_emo);
            tutorBubble.textContent = (full += seg.text);
            chatBox.scrollTop = chatBox.scrollHeight;
          }
        );
      } catch (err) {
        tutorBubble.textContent = `（讲师应答失败：${err.message}）`;
        Render.toast(`讲师应答失败：${err.message}`);
      } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = "提问";
        input.disabled = false;
        input.focus();
      }
    },

    /* —— 退出讲师模式，返回双人学习 —— */
    async end() {
      if (!this.active) return;
      this.active = false;

      // 通知后端清会话记忆（失败不影响收尾）
      if (Modes.scriptId) {
        try {
          await Api.lectureEnd(Modes.scriptId);
        } catch {}
      }

      // 收起讲师辅导栏：摘掉底部对话栏的 lecture-mode，恢复普通台词显示；
      // 隐藏会话区、隐藏讲师立绘，并恢复讲述者/提问者立绘（需求2）
      const db = $("dialog-box");
      db.classList.remove("lecture-mode");
      db.classList.remove("dialog-hidden");
      $("lecture-session").classList.add("hidden");
      Render.hideLecturer();   // hideLecturer 现在会恢复双人立绘

      // 回到弹题框：重新展示弹题（原题上下文）
      // 注意：必须用 Streaming._playQuestion 而不是 Render.showQuestion——
      // showQuestion 只重渲染 DOM，选项/提交/继续的点击监听是在
      // _playQuestion 里绑定的；用它重放才能恢复完整交互。
      if (this.enterFrom === "question" && Modes.currentScript) {
        const ch = Modes.currentScript.chapters[Modes.chapterIndex];
        const step = ch && ch.steps[Modes.stepIndex];
        if (step && step.type === "question") {
          Streaming._playQuestion(step);
          return;  // 弹题重新展示，用户可继续作答或再次深入学习
        }
      }

      // 兜底：非弹题入口 / 上下文丢失 → 恢复对话栏续播
      $("question-box").classList.add("hidden");   // 弹题框不再需要（回到纯对话场景）
      Render.showDialogBox();
      // Streaming 是顶层 const（不挂到 window），不能用 window.Streaming（总为 undefined）
      if (typeof Streaming !== "undefined" && Modes.currentScript) {
        Streaming.playCurrent && Streaming.playCurrent();
      }
    },

    /* —— 静默复位：离开播放器（返回主菜单等）时调用，不触发网络请求 —— */
    resetSilently() {
      this.active = false;
      this.enterFrom = null;
      this.context = "";
      const db = $("dialog-box");
      if (db) {
        db.classList.remove("lecture-mode");
        db.classList.remove("dialog-hidden");
      }
      const session = $("lecture-session");
      if (session) session.classList.add("hidden");
      Render.hideLecturer();
    },

    /* —— 绑定界面事件 —— */
    bind() {
      $("btn-lecture-fab").addEventListener("click", () => {
        // 主界面右侧悬浮键：携带当前章节上下文进入讲师
        const ctx = Modes.currentScript && Modes.currentScript.chapters[Modes.chapterIndex]
          ? "当前章节：" + (Modes.currentScript.chapters[Modes.chapterIndex].title || "")
          : "";
        Lecture.enter("fab", ctx);
      });

      // 弹题「深入学习」：带当前题目 + 讲评进讲师
      $("q-deep-dive").addEventListener("click", () => {
        const step = window.Streaming && Streaming._questionStep;
        const ctxParts = [];
        if (Modes.currentScript && Modes.currentScript.chapters[Modes.chapterIndex]) {
          ctxParts.push("当前章节：" + Modes.currentScript.chapters[Modes.chapterIndex].title);
        }
        if (step) {
          ctxParts.push("当前题目：" + step.text);
          if (step.explain) ctxParts.push("讲评：" + step.explain);
        }
        Lecture.enter("question", ctxParts.join("\n"));
      });

      $("btn-lecture-send").addEventListener("click", () => Lecture.ask());
      $("lecture-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          Lecture.ask();
        }
      });
      // 顶部「✕ 关闭」按钮同样结束辅导（此前漏绑，导致退出键无法使用）
      $("btn-lecture-close-top").addEventListener("click", () => Lecture.end());
      $("btn-lecture-close").addEventListener("click", () => Lecture.end());
    },
  };

  window.Lecture = Lecture;
})();