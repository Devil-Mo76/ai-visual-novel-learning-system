/* ═══════════════════════════════════════════════
 * wrongbook.js — 错题本独立面板（含遗忘曲线复习规划）
 *
 * 职责：
 *  1. 播放器右侧「📕 错题本」悬浮按钮 → 弹窗列出「待复练」错题。
 *  2. 按遗忘曲线分两组：「今天该复习（due_now）」与「稍后复习」。
 *  3. 每题展示：题目 / 我的答案 / 正确答案 / 讲评 / 错误次数 / 下次复习日期。
 *  4. 「去复习」→ 进入「只看错题」复习模式（只播这些错题章节）。
 *  5. 「标记已练」→ 调 retest 接口，置 retested=true，并推进遗忘曲线阶段。
 *
 * 数据源：GET /api/scripts/{id}/wrong_questions?status=pending。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const WrongBook = {
    _scriptId: null,   // 当前错题本所属剧本（显式传入或取播放器当前剧本）

    /* —— 打开错题本面板：拉取待复练错题，按遗忘曲线分「今日/稍后」两组 ——
     * @param scriptId 可选：显式指定剧本；缺省用播放器当前剧本 */
    async open(scriptId) {
      this._scriptId = scriptId || (typeof Modes !== "undefined" && Modes.scriptId) || null;
      if (!this._scriptId) {
        Render.toast("请先选择一份资料（或进入学习）后再打开错题本。");
        return;
      }
      const desc = $("wrongbook-desc");
      const listEl = $("wrongbook-list");
      desc.textContent = "正在加载待复练错题…";
      listEl.innerHTML = "";
      $("wrongbook-modal").classList.remove("hidden");

      try {
        const wrongs = await Api.wrongQuestions(this._scriptId, "pending");
        if (!wrongs || !wrongs.length) {
          desc.textContent = "暂无待复练错题。先去作答，答错的题目会自动收进错题本。";
          return;
        }
        const today = wrongs.filter((w) => w.due_now);
        const later = wrongs.filter((w) => !w.due_now);
        const sortByWrong = (a, b) => (b.wrong_count || 1) - (a.wrong_count || 1);
        today.sort(sortByWrong);
        later.sort(sortByWrong);
        desc.textContent = `共 ${wrongs.length} 道待复练错题 · 今日该复习 ${today.length} 道（遗忘曲线）`;

        if (today.length) {
          listEl.appendChild(this._groupTitle(`🧠 今天该复习（${today.length}）`));
          today.forEach((w) => listEl.appendChild(this._buildItem(w)));
        }
        if (later.length) {
          listEl.appendChild(this._groupTitle(`📅 稍后复习（${later.length}）`));
          later.forEach((w) => listEl.appendChild(this._buildItem(w)));
        }
      } catch (err) {
        desc.textContent = `加载错题失败：${err.message}`;
      }
    },

    close() {
      $("wrongbook-modal").classList.add("hidden");
    },

    _groupTitle(text) {
      const div = document.createElement("div");
      div.className = "wrong-group";
      div.textContent = text;
      return div;
    },

    /* —— 渲染一条错题卡片（含遗忘曲线复习信息） —— */
    _buildItem(w) {
      const item = document.createElement("div");
      item.className = "wrong-item";
      const dueInfo = w.due_now
        ? '<span class="wrong-due-tag">今日复习</span>'
        : `<span class="wrong-next-due">下次复习：${w.next_due || "—"}</span>`;
      item.innerHTML =
        `<div class="wrong-q">${w.question_text || "（题目缺失）"}</div>` +
        `<div class="wrong-row"><span class="wrong-label">我的答案</span><span class="wrong-val wrong-bad">${w.your_answer || "（未作答）"}</span></div>` +
        `<div class="wrong-row"><span class="wrong-label">正确答案</span><span class="wrong-val wrong-good">${w.correct_answer || "（未提供）"}</span></div>` +
        (w.explain ? `<div class="wrong-explain">💡 ${w.explain}</div>` : "") +
        `<div class="wrong-meta">答错 ${w.wrong_count || 1} 次 · 第 ${w.chapter_index + 1} 章 · 已复练 ${w.review_count || 0} 次 ${dueInfo}</div>` +
        `<div class="wrong-actions">` +
        `<button class="btn-ghost wrong-go-review" title="进入只看错题模式复习这道题">去复习</button>` +
        `<button class="btn-ghost wrong-mark-done" title="标记为已练过，不再计入待复练">标记已练</button>` +
        `</div>`;

      // 「去复习」→ 进入只看错题模式并跳到这道题
      item.querySelector(".wrong-go-review").addEventListener("click", async () => {
        this.close();
        const sid = this._scriptId;
        if (Streaming.playOnlyWrong) {
          await Streaming.playOnlyWrong(sid);   // 资料库/播放器均可：加载剧本并进入只看错题
        } else if (Modes.onlyWrong) {
          await Streaming._loadWrongQuestions();
          Streaming._advanceToNextWrong(w.chapter_index, w.step_index - 1);
        } else {
          Modes.onlyWrong = true;
          await Streaming._loadWrongQuestions();
          Streaming._advanceToNextWrong(-1, -1);
        }
        // 若当前不在播放器（从资料库进入），切到播放器屏
        const playerEl = document.getElementById("screen-player");
        if (window.App && window.App.showScreen && playerEl && !playerEl.classList.contains("active")) {
          window.App.showScreen("screen-player");
        }
      });

      // 「标记已练」→ 调 retest 接口，置 retested=true，从列表移除
      item.querySelector(".wrong-mark-done").addEventListener("click", async () => {
        try {
          await Api.retestWrong(this._scriptId, w.chapter_index, w.step_index);
          Render.toast("已标记为已练过（历史报告仍保留）。");
          this.open(this._scriptId);   // 刷新列表
        } catch (err) {
          Render.toast(`标记失败：${err.message}`);
        }
      });

      return item;
    },

    /* —— 绑定界面事件 —— */
    bind() {
      const btn = $("btn-wrongbook-fab");
      if (btn) btn.addEventListener("click", () => this.open());
      $("btn-wrongbook-close").addEventListener("click", () => this.close());
    },
  };

  window.WrongBook = WrongBook;
  document.addEventListener("DOMContentLoaded", () => WrongBook.bind());
})();
