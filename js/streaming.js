/* ═══════════════════════════════════════════════
 * streaming.js — 播放器状态机（剧本逐句驱动的核心）
 *
 * 职责：
 *  1. 按「剧本节点」推进：line → 对话栏打字；question → 弹题、判题、讲评。
 *  2. 双向表情同步：每个节点渲染时同时更新说话者(talk_emo)与倾听者(listen_emo)。
 *  3. 每完成一个节点自动上报进度（主槽0）。
 *  4. 支持点击推进 / 自动播放 / 打字中途点击跳过。
 * ═══════════════════════════════════════════════ */

const Streaming = {
  _autoTimer: null,
  _questionStep: null,        // 当前弹题的 step 引用（「直接查看答案」用）

  /* —— 加载剧本并定位到指定进度 —— */
  async loadScript(scriptId, chapterIndex = 0, stepIndex = 0) {
    const data = await Api.getScript(scriptId);
    Modes.currentScript = data;
    Modes.scriptId = scriptId;
    Modes.chapterIndex = chapterIndex;
    Modes.stepIndex = stepIndex;
    Modes.resetRun();
    Render.hideQuestion();
    this._applyChapter(chapterIndex);
    document.body.classList.add("player-visible");
    this.playCurrent();
  },

  /* —— 进入某章节：切背景 + 章节条。
   * resetStep=true 时重置步进到 0（正常章节推进）；false 时保留
   * 已有 stepIndex（供「续播/读档」跳到章节中间）。*/
  _applyChapter(idx, resetStep = false) {
    const ch = Modes.currentScript.chapters[idx];
    if (!ch) return;
    Modes.chapterIndex = idx;
    if (resetStep) Modes.stepIndex = 0;
    Render.setBackground(ch.background);
    Render.setChapterBar(`${ch.title}`);
    Render.setChapterBarVisible(true);
  },

  /* —— 播放当前节点 —— */
  playCurrent() {
    const ch = Modes.currentScript.chapters[Modes.chapterIndex];
    if (!ch || !ch.steps.length) return this._finishScript();
    const step = ch.steps[Modes.stepIndex];
    if (!step) return this._nextChapterOrFinish();
    Modes.isPlaying = true;
    this._clearAutoTimer();

    if (step.type === "question") {
      this._playQuestion(step);
    } else {
      this._playLine(step);
    }
  },

  /* —— 普通台词节点 —— */
  _playLine(step) {
    this._syncEmotions(step);                  // 双向表情同步
    Render.el.dialogName().textContent = ROLE_NAME[step.speaker];
    Render.showDialogBox();

    // 记录对话历史（需求三：谁说的 + 内容 + 说话时表情头像）
    // 注意用 VNHistory：真实浏览器里 window.History 是内置 BOM 接口，会被覆盖失败
    if (window.VNHistory) VNHistory.addDialogue(step.speaker, step.text, step.talk_emo);

    Typing.start(Render.el.dialogText(), step.text, Modes.typingSpeed, {
      onDone: () => {
        this._onLineFinished(step);
      },
    });
  },

  /* —— 弹题节点 —— */
  _playQuestion(step) {
    Modes.pausedForQuestion = true;
    Modes.isPlaying = false;
    this._syncEmotions(step);
    this._questionStep = step;
    Render.hideDialogBox();

    // 每次渲染都重置「查看答案」按钮，避免上个问题残留
    Render.el.qPeek().classList.remove("hidden");
    Render.el.qSubmit().disabled = false;
    Render.el.qSubmit().textContent = "提交作答";

    Render.showQuestion({
      asker: ROLE_NAME[step.speaker] + " 的提问",
      text: step.text,
      choices: step.choices,
      quizType: step.quiz_type || "choice",
    });

    // 填空/简答：绑定输入区提交按钮
    Render.el.qSubmit().onclick = () => this._submitTextAnswer(step);

    // 绑定选项事件（每次渲染后重新绑定，避免旧监听）
    Render.el.qChoices().querySelectorAll(".q-choice").forEach((btn) => {
      btn.addEventListener("click", () => this._answer(step, Number(btn.dataset.index), btn));
    });
  },

  /* —— 直接查看答案：不依赖 AI 判题，判题卡死/超时也能看答案继续学 —— */
  peekAnswer() {
    const step = this._questionStep;
    if (!step) return;
    const quizType = step.quiz_type || "choice";

    let reveal;
    if (quizType === "choice") {
      reveal =
        step.choices && step.choices[step.answer] != null
          ? "正确答案：" + step.choices[step.answer]
          : "（本题未提供正确答案选项）";
    } else {
      reveal = this._buildReveal(step, quizType);
    }

    // 展示答案（纯前端逻辑，不经过 AI 接口）
    Render.revealAnswer(reveal);

    // 锁定所有作答控件，防止重复作答
    Render.el.qChoices().querySelectorAll(".q-choice").forEach((b) => (b.disabled = true));
    Render.el.qSubmit().disabled = true;
    Render.el.qPeek().classList.add("hidden");

    // 收尾：老师鼓励表情 + 出示「继续学习」按钮 + 记录进度
    Render.setSprite("teacher", "guli");
    Render.showSpeakerOnly("teacher");
    Render.el.qContinue().classList.remove("hidden");
    this._saveProgress(Modes.chapterIndex, Modes.stepIndex);
  },

  /* —— 判题（选择题：本地比较；填空/简答：交 AI 判题）—— */
  _answer(step, picked, btn) {
    const correct = picked === step.answer;
    const correctLabel = step.choices[step.answer];

    // 锁定选项，防止重复作答
    Render.el.qChoices().querySelectorAll(".q-choice").forEach((b) => (b.disabled = true));
    btn.classList.add(correct ? "q-choice-right" : "q-choice-wrong");

    this._finishAnswer(correct, step, correctLabel, undefined, step.choices[picked]);
  },

  /* —— 填空/简答题：读取输入框文本并交 AI 判题 —— */
  async _submitTextAnswer(step) {
    const text = Render.el.qInput().value.trim();
    if (!text) {
      Render.toast("请输入作答内容后再提交。");
      return;
    }
    const quizType = step.quiz_type || "choice";
    // 答错计数：填空题/简答题答错满 3 次自动出示正确答案并继续（需求）
    const maxTries = 3;
    this._attemptKey = `qtry_${Modes.scriptId}_${Modes.chapterIndex}_${Modes.stepIndex}`;

    // 已到 3 次上限：直接亮答案并收尾，不再判题
    if (quizType !== "choice" && Number(sessionStorage.getItem(this._attemptKey) || 0) >= maxTries) {
      const reveal = this._buildReveal(step, quizType);
      Render.revealAnswer(reveal);
      Render.el.qSubmit().disabled = true;
      Render.toast(`已答错 ${maxTries} 次，正确答案已出示。`);
      this._finishAnswer(false, step, reveal, "已答错 3 次，正确答案已展示，请继续学习。");
      return;
    }

    Render.el.qSubmit().disabled = true;   // 判题期间防重复提交
    Render.el.qSubmit().textContent = "判题中…";
    let result;
    try {
      result = await Api.verifyAnswer({
        script_id: Modes.scriptId,
        chapter_index: Modes.chapterIndex,
        step_index: Modes.stepIndex,
        quiz_type: quizType,
        quote: text,
      });
    } catch (err) {
      Render.el.qSubmit().disabled = false;
      Render.el.qSubmit().textContent = "提交作答";
      Render.toast(`判题失败：${err.message}`);
      return;
    }
    const correct = result.correct;
    const correctLabel =
      quizType === "fill"
        ? (step.answer_text || "")
        : "覆盖要点 70%-80% 即通过，具体请参看讲评";

    if (correct) {
      sessionStorage.removeItem(this._attemptKey);   // 答对清零
      Render.el.qSubmit().disabled = true;
      this._finishAnswer(true, step, correctLabel, result.explain, text);
      return;
    }

    // —— 答错（仅填空/简答有重试；选择题下方 _answer 已有锁定逻辑）——
    if (quizType === "choice") {
      this._finishAnswer(false, step, correctLabel, result.explain, text);
      return;
    }
    const attempts = Number(sessionStorage.getItem(this._attemptKey) || 0) + 1;
    sessionStorage.setItem(this._attemptKey, String(attempts));

    if (attempts >= maxTries) {
      // 第 3 次答错：亮出正确答案并继续
      const reveal = this._buildReveal(step, quizType);
      Render.revealAnswer(reveal);
      Render.el.qSubmit().disabled = true;
      Render.toast(`已答错 ${maxTries} 次，正确答案已出示。`);
      this._finishAnswer(false, step, reveal, "已答错 3 次，正确答案已展示，请继续学习。");
    } else {
      // 未达上限：允许重试，输入框保留已填内容，提示剩余次数
      Render.el.qSubmit().disabled = false;
      Render.el.qSubmit().textContent = "重新提交";
      Render.el.qInput().value = "";
      Render.revealAnswer("", "答错了，还剩 " + (maxTries - attempts) + " 次机会，请再试一次。");
      Render.toast(`答错了，还剩 ${maxTries - attempts} 次机会。`);
    }
  },

  /* —— 构建「正确答案」展示文本（答错满 3 次 / 直接亮答案用）——
   * 填空：显示 answer_text 参考答案；
   * 简答：把 reference_points 要点逐条列出，用户可对照。 */
  _buildReveal(step, quizType) {
    if (quizType === "fill") {
      return step.answer_text || "（未提供参考答案）";
    }
    const pts = step.reference_points || [];
    if (pts.length) {
      return "参考答案要点：\n" + pts.map((p, i) => `${i + 1}. ${p}`).join("\n");
    }
    return step.explain || "（未提供参考答案要点）";
  },

  /* —— 判题收尾：显示表情 + 讲评 —— */
  _finishAnswer(correct, step, correctLabel, explain, userAnswer = "") {
    const fbRole = "teacher";
    const fbEmo = correct ? "gaoxing" : "yansu";   // 需求4：答错 → 老师严肃
    Render.setSprite(fbRole, fbEmo);
    Render.showSpeakerOnly(fbRole);

    // 记录测验历史（需求三：题目 + 用户答案 + 正确答案 + 是否答对 + 解析）
    if (window.VNHistory) {
      VNHistory.addQuiz({
        question: step.text,
        userAnswer,
        correctAnswer: correctLabel || "",
        isCorrect: correct,
        explain: explain || step.explain || "",
      });
    }

    Render.showQuestionFeedback(correct, explain || step.explain || "（未提供讲评）", correctLabel);
    this._saveProgress(Modes.chapterIndex, Modes.stepIndex);
  },

  /* —— 台词完成：自动保存 + 自动播放调度 —— */
  _onLineFinished(step) {
    this._saveProgress(Modes.chapterIndex, Modes.stepIndex);
    if (Modes.autoPlay) {
      this._autoTimer = setTimeout(() => this.advance(), Modes.autoDelayMs);
    }
  },

  /* —— 下一步 —— */
  advance() {
    if (window.Lecture && Lecture.active) return;   // 讲师模式中禁止推进剧情
    if (Modes.pausedForQuestion) return;        // 弹题中禁止推进（用「继续」按钮）
    if (Typing.isTyping()) {
      Typing.skipToEnd();
      return;
    }
    const ch = Modes.currentScript.chapters[Modes.chapterIndex];
    if (!ch) return this._finishScript();

    Modes.stepIndex += 1;
    if (Modes.stepIndex >= ch.steps.length) {
      this._nextChapterOrFinish();
      return;
    }
    this.playCurrent();
  },

  /* —— 章节推进 —— */
  _nextChapterOrFinish() {
    const next = Modes.chapterIndex + 1;
    if (next < Modes.currentScript.chapters.length) {
      this._applyChapter(next, true);
      this.playCurrent();
    } else {
      this._finishScript();
    }
  },

  /* —— 播放结束 —— */
  _finishScript() {
    Modes.isPlaying = false;
    Render.showDialogBox();
    Render.el.dialogName().textContent = "— 学习完成 —";
    Render.el.dialogText().textContent = "恭喜你完成了本次学习！点击「返回主菜单」可保存进度并退出。";
    Render.el.dialogBox().classList.add("dialog-done");   // 结尾对话框样式提示
    Render.toast("本节学习已全部完成 🎉");
  },

  /* —— 单人轮播渲染：只显示当前说话者，切换表情；倾听者淡出（需求5）—— */
  _syncEmotions(step) {
    const talkKey = step.talk_emo || "jiangjie";
    Render.setSprite(step.speaker, talkKey);
    Render.showSpeakerOnly(step.speaker);
  },

  /* —— 自动保存（每节点完成触发）—— */
  async _saveProgress(chapterIndex, stepIndex) {
    if (!Modes.scriptId) return;
    try {
      await Api.saveProgress(Modes.scriptId, chapterIndex, stepIndex, 0);
    } catch {
      // 保存失败不影响播放体验，静默吞掉即可
    }
  },

  /* —— 从主按钮 读取/继续学习 恢复 —— */
  async resumeFromSlot(slot) {
    const slots = await Api.listSlots(Modes.scriptId);
    const hit = slots.slots.find((s) => s.slot === slot);
    const target = hit || { chapter_index: 0, step_index: 0 };
    await this.loadScript(Modes.scriptId, target.chapter_index, target.step_index);
  },

  /* —— 上一句（历史按钮占位，预留）—— */
  back() {
    Modes.chapterIndex = Modes.chapterIndex;    // 占位：历史功能开发中
  },

  _clearAutoTimer() {
    if (this._autoTimer) {
      clearTimeout(this._autoTimer);
      this._autoTimer = null;
    }
  },
};

/* 存读档相关由 app.js 调用 */