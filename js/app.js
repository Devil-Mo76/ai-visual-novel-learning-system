/* ═══════════════════════════════════════════════
 * app.js — 入口与全局事件绑定
 *
 * 职责：
 *  1. 屏幕切换（主菜单 / 开始学习 / 设置 / 播放器）。
 *  2. 上传、生成剧本、设置读写与连接测试。
 *  3. 播放器控制（保存 / 读取 / 自动 / 隐藏对话栏 / 返回）。
 *  4. 弹题「继续」按钮恢复播放。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  /* ────────── 屏幕切换 ────────── */
  const SCREENS = ["screen-menu", "screen-library", "screen-settings", "screen-player"];

  function showScreen(name) {
    SCREENS.forEach((s) => {
      document.getElementById(s).classList.toggle("active", s === name);
    });
    document.body.classList.toggle("player-visible", name === "screen-player");
    if (name !== "screen-player") {
      // 离开播放器时取消自动播放
      Modes.resetRun();
      Typing.cancel();
      Streaming._clearAutoTimer && Streaming._clearAutoTimer();
      // 正在讲师辅导中离开播放器 → 静默复位（不触发网络请求）
      window.Lecture && Lecture.active && Lecture.resetSilently();
    }
  }

  /* ────────── 主菜单「读取存档」弹窗（标注资料名）────────── */
  async function openArchiveModal() {
    const listEl = $("archive-list");
    listEl.innerHTML = "";
    try {
      const list = await Api.listArchive();
      if (!list || !list.length) {
        listEl.innerHTML = `<div class="archive-empty">暂无存档。请先「开始学习」导入资料并学习后，会自动生成存档。</div>`;
        return;
      }
      list.forEach((a) => {
        const item = document.createElement("div");
        item.className = "archive-item";
        item.innerHTML =
          `<div class="archive-doc">📄 ${a.document_title || "（未命名资料）"}</div>` +
          `<div class="archive-meta">${a.slot === 0 ? "⭐ 自动存档" : `手动存档 ${a.slot}`} · 第 ${a.chapter_index + 1} 章 · ${formatDateTimeShort(a.updated_at)}</div>` +
          `<button class="archive-del" data-script="${a.script_id}" data-slot="${a.slot}" title="删除该存档">✕</button>`;
        // 整行点击 → 读档
        item.addEventListener("click", async () => {
          $("modal-archive").classList.add("hidden");
          try {
            await Streaming.loadScript(a.script_id, a.chapter_index, a.step_index);
            showScreen("screen-player");
          } catch (err) {
            Render.toast(`加载存档失败：${err.message}`);
          }
        });
        // 删除按钮：单独处理，阻止冒泡到「读档」；删完刷新列表（需求2）
        item.querySelector(".archive-del").addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!confirm(`确认删除「${a.document_title || "未命名资料"}」的${a.slot === 0 ? "自动存档" : `手动存档 ${a.slot}`}？`)) return;
          try {
            await Api.deleteProgress(a.script_id, a.slot);
            Render.toast("存档已删除");
            listEl.innerHTML = "";
            openArchiveModal();
          } catch (err) {
            Render.toast(`删除失败：${err.message}`);
          }
        });
        listEl.appendChild(item);
      });
    } catch (err) {
      listEl.innerHTML = `<div class="archive-empty">读取存档失败：${err.message}</div>`;
    }
    $("modal-archive").classList.remove("hidden");
  }

  function formatDateTimeShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  /* ────────── 主菜单 ────────── */
  function bindMenu() {
    document.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.nav;
        if (target === "menu") showScreen("screen-menu");
        if (target === "library") openLibrary();
        if (target === "settings") openSettings();
      });
    });

    // 继续学习：读最近进度直接进播放
    $("btn-menu-continue").addEventListener("click", continueLearning);

    // 读取存档：打开全档列表（标注资料名）
    $("btn-menu-load").addEventListener("click", openArchiveModal);

    // 退出
    $("btn-menu-exit").addEventListener("click", () => {
      Render.toast("已退出应用。浏览器无法由代码强制关闭标签页，请手动关闭。");
    });
  }

  async function continueLearning() {
    const statusEl = $("menu-status");
    statusEl.textContent = "正在读取上次进度…";
    try {
      const latest = await Api.latestProgress();
      if (!latest.exists) {
        statusEl.textContent = "暂无学习记录，请先「开始学习」。";
        return;
      }
      await Streaming.loadScript(latest.script_id, latest.chapter_index, latest.step_index);
      showScreen("screen-player");
    } catch (err) {
      statusEl.textContent = `读取失败：${err.message}`;
    }
  }

  /* ────────── 开始学习 / 资料库 ────────── */
  let selectedDocId = null;
  let lastScriptId = null;

  async function openLibrary() {
    showScreen("screen-library");
    await refreshDocList();
  }

  async function refreshDocList() {
    const list = $("doc-list");
    list.innerHTML = "";
    try {
      const docs = await Api.listDocuments();
      if (!docs.length) {
        list.innerHTML = `<li class="doc-item doc-empty">暂无学习资料，请先上传。</li>`;
        return;
      }
      docs.forEach((d) => {
        const li = document.createElement("li");
        li.className = "doc-item" + (d.id === selectedDocId ? " doc-selected" : "");
        li.dataset.id = d.id;
        li.innerHTML =
          `<div class="doc-main" data-id="${d.id}">` +
          `<div class="doc-info">` +
          `<div class="doc-name">${d.title}</div>` +
          `<div class="doc-meta">${d.filename} · ${formatDate(d.created_at)}</div>` +
          `<div class="doc-preview">${d.content_preview || ""}</div>` +
          `</div>` +
          `<div class="doc-btns">` +
          (d.has_script
            ? `<button class="doc-enter" data-enter="${d.id}" data-script="${d.latest_script_id}" title="直接进入学习">▶ 进入学习</button>`
            : "") +
          `<button class="doc-del" data-del="${d.id}" title="删除该资料">✕</button>` +
          `</div>` +
          `</div>`;
        // 点击卡片主体 → 选中（并启用生成按钮）
        li.querySelector(".doc-main").addEventListener("click", () => {
          selectedDocId = d.id;
          $("btn-generate").disabled = false;
          refreshDocList();
        });
        // 「进入学习」→ 直接加载最近剧本并进播放器
        const enterBtn = li.querySelector(".doc-enter");
        if (enterBtn) {
          enterBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const scriptId = Number(enterBtn.dataset.script);
            try {
              await Streaming.loadScript(scriptId, 0, 0);
              showScreen("screen-player");
              Render.toast("已进入学习");
            } catch (err) {
              Render.toast(`加载剧本失败：${err.message}`);
            }
          });
        }
        // 点击删除按钮 → 删除（阻止冒泡到选中）
        li.querySelector(".doc-del").addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!confirm(`确认删除学习资料「${d.title}」？其剧本与进度将一并删除。`)) return;
          try {
            await Api.deleteDocument(d.id);
            if (selectedDocId === d.id) {
              selectedDocId = null;
              $("btn-generate").disabled = true;
            }
            Render.toast("已删除该资料");
            await refreshDocList();
          } catch (err) {
            Render.toast(`删除失败：${err.message}`);
          }
        });
        list.appendChild(li);
      });
    } catch (err) {
      list.innerHTML = `<li class="doc-item doc-empty">加载失败：${err.message}</li>`;
    }
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function bindLibrary() {
    // 上传：点按钮或拖拽到 drop 区
    async function doUpload(file) {
      const statusEl = $("upload-status");
      if (!file) {
        statusEl.textContent = "请先选择要上传的文件。";
        return;
      }
      statusEl.textContent = "正在上传并解析…";
      try {
        const doc = await Api.uploadDocument(file);
        selectedDocId = doc.id;
        statusEl.textContent = `解析成功：${file.name}（已选中，可直接生成剧本）`;
        $("file-input").value = "";
        await refreshDocList();
        $("btn-generate").disabled = false;
      } catch (err) {
        statusEl.textContent = `上传失败：${err.message}`;
      }
    }

    $("btn-upload").addEventListener("click", () => {
      const file = $("file-input").files[0];
      doUpload(file);
    });

    // 点击 drop 区 → 打开文件选择
    const dropArea = $("drop-area");
    dropArea.addEventListener("click", () => $("file-input").click());
    $("file-input").addEventListener("change", () => doUpload($("file-input").files[0]));
    // 拖拽上传
    ["dragenter", "dragover"].forEach((evt) =>
      dropArea.addEventListener(evt, (e) => {
        e.preventDefault();
        dropArea.classList.add("drag-hover");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dropArea.addEventListener(evt, (e) => {
        e.preventDefault();
        dropArea.classList.remove("drag-hover");
      })
    );
    dropArea.addEventListener("drop", (e) => {
      const file = e.dataTransfer.files[0];
      if (file) doUpload(file);
    });

    // 基于选中资料生成剧本（章节数取自下拉框）
    $("btn-generate").addEventListener("click", async () => {
      if (!selectedDocId) {
        $("gen-status").textContent = "请先在列表中选择一份资料。";
        return;
      }
      const chapterCount = Number($("chapter-count").value) || 3;
      const learningGoal = $("learning-goal").value.trim();
      // 需求3：读取弹题类型勾选（选择题/填空题/简答题）
      const quizTypes = [];
      if ($("qtype-choice") && $("qtype-choice").checked) quizTypes.push("choice");
      if ($("qtype-fill") && $("qtype-fill").checked) quizTypes.push("fill");
      if ($("qtype-short") && $("qtype-short").checked) quizTypes.push("short");
      if (!quizTypes.length) quizTypes.push("choice");  // 至少保留选择题作兜底
      const statusEl = $("gen-status");
      statusEl.textContent = `正在生成教学剧本（${chapterCount} 章，题型：${quizTypes.join("/")}，可能需数十秒）…`;
      statusEl.classList.add("spin");
      try {
        const out = await Api.generateScript(selectedDocId, chapterCount, learningGoal, quizTypes);
        lastScriptId = out.script_id;
        statusEl.textContent = `剧本生成成功：${out.script.title}`;
        // 需求1：生成完成后不直接进入学习，弹出提示框让用户选择
        showGenerateDoneModal(out.script_id, out.script.title);
      } catch (err) {
        statusEl.textContent = `生成失败：${err.message}`;
      } finally {
        statusEl.classList.remove("spin");
      }
    });
  }

  /* ────────── 生成完成提示框（需求1）────────── */
  function showGenerateDoneModal(scriptId, title) {
    $("modal-done-desc").textContent = `教学剧本已生成完毕：《${title}》\n现在进入学习，还是稍后再学？`;
    const modal = $("modal-done");
    modal.classList.remove("hidden");

    // 进入学习按钮
    $("btn-done-enter").onclick = async () => {
      modal.classList.add("hidden");
      try {
        await Streaming.loadScript(scriptId, 0, 0);
        showScreen("screen-player");
      } catch (err) {
        Render.toast(`进入学习失败：${err.message}`);
      }
    };
    // 下次再学：直接关闭弹窗留在当前页
    $("btn-done-later").onclick = () => {
      modal.classList.add("hidden");
      Render.toast("剧本已保存，可稍后从「现有学习资料」进入");
    };
  }

  /* ────────── 设置 ────────── */
  let settingsReturnTo = "menu";   // 设置屏返回去向（menu 或 player）

  async function openSettings(returnTo = "menu") {
    settingsReturnTo = returnTo;
    showScreen("screen-settings");
    try {
      const s = await Api.getSettings();
      $("set-api-base").value = s.api_base;
      $("set-model").value = s.model;
      $("key-hint").textContent = s.api_key_set
        ? `密钥已配置：${s.key_masked}（留空保存则保持不变）`
        : "密钥仅保存在后端数据库，不会回传到浏览器。";
      $("set-api-key").value = "";
    } catch (err) {
      $("settings-status").textContent = `读取设置失败：${err.message}`;
    }
  }

  function bindSettings() {
    $("btn-test").addEventListener("click", async () => {
      const statusEl = $("settings-status");
      statusEl.textContent = "正在测试连接…";
      try {
        const result = await Api.testSettings({
          api_base: $("set-api-base").value,
          api_key: $("set-api-key").value,
          model: $("set-model").value,
        });
        statusEl.style.color = result.success ? "#2e7d32" : "#c62828";
        statusEl.textContent = result.message;
      } catch (err) {
        statusEl.style.color = "#c62828";
        statusEl.textContent = `测试失败：${err.message}`;
      }
    });

    $("btn-save-settings").addEventListener("click", async () => {
      const statusEl = $("settings-status");
      statusEl.textContent = "正在保存…";
      try {
        const s = await Api.saveSettings({
          api_base: $("set-api-base").value,
          api_key: $("set-api-key").value,
          model: $("set-model").value,
        });
        statusEl.style.color = "#2e7d32";
        statusEl.textContent = `保存成功：${s.api_key_set ? "Key 已配置" : "Key 未配置"}`;
        $("key-hint").textContent = s.api_key_set
          ? `密钥已配置：${s.key_masked}`
          : "密钥仅保存在后端数据库，不会回传到浏览器。";
      } catch (err) {
        statusEl.style.color = "#c62828";
        statusEl.textContent = `保存失败：${err.message}`;
      }
    });

    // —— 需求2：全局字体大小调节 ——
    // 注意：applyFontSize 内部直接 $() 取元素，不依赖外部 const 变量，
    // 避免 const 处于 TDZ（暂时性死区）导致调用时 ReferenceError，
    // 从而中断绑定链（bindPlayer 等后续绑定将永远不会执行）。
    function applyFontSize() {
      const saved = localStorage.getItem("baseFontSize");
      const px = saved ? Number(saved) : 16;
      $("font-size").value = px;
      $("font-size-val").textContent = px + "px";
      document.documentElement.style.setProperty("--base-font", px + "px");
      $("font-preview").style.fontSize = "calc(" + px + "px + 2px)";
    }
    applyFontSize();   // 载入已保存的字号（此时才调用，声明在前）
    const fontRange = $("font-size");
    const fontVal = $("font-size-val");
    fontRange.addEventListener("input", () => {
      const px = Number(fontRange.value);
      fontVal.textContent = px + "px";                       // 实时数值反馈
      document.documentElement.style.setProperty("--base-font", px + "px");  // 实时预览
      $("font-preview").style.fontSize = "calc(" + px + "px + 2px)";
    });
    $("btn-font-apply").addEventListener("click", () => {    // 应用：持久化字号
      const px = Number(fontRange.value);
      localStorage.setItem("baseFontSize", String(px));
      Render.toast(`字体已应用为 ${px}px`);
    });
    $("btn-font-default").addEventListener("click", () => {  // 默认：恢复 16px
      localStorage.removeItem("baseFontSize");
      applyFontSize();
      Render.toast("已恢复默认字体 16px");
    });
  }

  /* ────────── 播放器控制 ────────── */
  function bindPlayer() {
    const player = $("screen-player");

    // 点击画面推进（排除按钮、弹题框、各种弹窗）
    player.addEventListener("click", (e) => {
      if (e.target.closest(".control-bar")) return;   // 点控制栏不算推进
      if (e.target.closest("#question-box")) return;  // 弹题期间不推进
      if (e.target.closest("#login-overlay")) return; // 登录遮罩不推进（先登录）
      if (e.target.closest(".modal")) return;         // 其它弹窗（历史/存档/弹窗）不推进
      Streaming.advance();
    });

    // 键盘推进（需求二）：空格 = 下一句。焦点在输入框内时不推进（正常输入空格）
    document.addEventListener("keydown", (e) => {
      if (e.key !== " ") return;
      // 输入框内敲空格 → 正常输入，不推进对话
      const t = document.activeElement && document.activeElement.tagName;
      if (t === "INPUT" || t === "TEXTAREA") return;
      e.preventDefault();   // 阻止页面滚动
      // 登录遮罩 / 弹题 / 各类弹窗打开时不推进
      // （login-overlay 为可选登录模块，未加载时跳过，保证空格键正常推进）
      const loginEl = $("login-overlay");
      if (loginEl && !loginEl.classList.contains("hidden")) return;
      if (!$("question-box").classList.contains("hidden")) return;
      if (document.querySelector(".modal:not(.hidden)")) return;  // 有任意弹窗打开则跳过
      Streaming.advance();
    });

    // 保存（打开存档选择槽位）
    $("btn-save").addEventListener("click", () => openSlotModal("save"));
    // 读取（打开存档选择槽位）
    $("btn-load").addEventListener("click", () => openSlotModal("load"));

    // 主菜单「读取存档」弹窗关闭
    $("btn-archive-close").addEventListener("click", () => {
      $("modal-archive").classList.add("hidden");
    });

    // 弹题「直接查看答案」：AI 判题卡死也能看答案继续（需求1）
    $("q-peek-answer").addEventListener("click", () => {
      Streaming.peekAnswer();
    });

    // 弹题「继续」按钮
    $("q-continue").addEventListener("click", () => {
      Modes.pausedForQuestion = false;
      Render.hideQuestion();
      Render.showDialogBox();
      Modes.stepIndex += 1;
      const ch = Modes.currentScript.chapters[Modes.chapterIndex];
      if (ch && Modes.stepIndex >= ch.steps.length) {
        Streaming._nextChapterOrFinish();
      } else {
        Streaming.playCurrent();
      }
    });

    // 自动播放开关
    $("btn-auto").addEventListener("click", (e) => {
      const on = Modes.toggleAuto();
      e.target.classList.toggle("active", on);
      Render.toast(on ? "自动播放已开启" : "自动播放已关闭");
    });

    // 隐藏/显示对话栏
    $("btn-hide-dialog").addEventListener("click", (e) => {
      const hidden = Modes.toggleDialog();
      e.target.classList.toggle("active", hidden);
      hidden ? Render.hideDialogBox() : Render.showDialogBox();
    });

    // 播放器内的设置（打开设置屏，返回时回播放器）
    $("btn-settings-player").addEventListener("click", () => openSettings("player"));
    document.querySelector('#screen-settings .btn-back').addEventListener("click", () => {
      showScreen(settingsReturnTo === "player" ? "screen-player" : "screen-menu");
    });

    // 返回主菜单：先自动存一档再回
    $("btn-return-menu").addEventListener("click", async () => {
      if (Modes.scriptId) {
        try {
          await Api.saveProgress(Modes.scriptId, Modes.chapterIndex, Modes.stepIndex, 0);
        } catch {}
      }
      showScreen("screen-menu");
    });

    // 占位按钮：快进（点击提示开发中）
    // 注意：btn-history 已由 history.js 实装（打开历史面板），不在此占位列表内。
    ["btn-fastskip"].forEach((id) => {
      $(id).addEventListener("click", () => Render.toast("该功能开发中，敬请期待。"));
    });

    // 存档弹窗关闭
    $("modal-slots-close").addEventListener("click", () => Render.hideSlots());
  }

  /* —— 存档弹窗：mode = "save" | "load" —— */
  async function openSlotModal(mode) {
    if (!Modes.scriptId) {
      Render.toast("尚未进入学习，请先选择资料生成剧本。");
      return;
    }
    $("modal-slots-title").textContent = mode === "save" ? "选择存档位（保存）" : "选择存档（读取）";
    try {
      const data = await Api.listSlots(Modes.scriptId);
      Render.showSlots(data.slots, Modes.scriptId, async (slot) => {
        if (mode === "save") {
          await Api.saveProgress(Modes.scriptId, Modes.chapterIndex, Modes.stepIndex, slot);
          Render.hideSlots();
          Render.toast(`已保存到存档 ${slot === 0 ? "自动档" : "手动档 " + slot}`);
        } else {
          const hit = data.slots.find((s) => s.slot === slot);
          if (!hit) {
            Render.toast("该存档位为空。");
            return;
          }
          Render.hideSlots();
          await Streaming.loadScript(Modes.scriptId, hit.chapter_index, hit.step_index);
        }
      });
    } catch (err) {
      Render.toast(`读取存档列表失败：${err.message}`);
    }
  }

  /* ────────── 启动 ────────── */
  document.addEventListener("DOMContentLoaded", () => {
    bindMenu();
    bindLibrary();
    bindSettings();
    bindPlayer();
    window.Lecture && Lecture.bind();   // 讲师一对一辅导入口绑定
    showScreen("screen-menu");
  });
})();