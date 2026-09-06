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

  // 转义 HTML 特殊字符，防止模型返回文本里的标签破坏渲染
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ────────── 屏幕切换 ────────── */
  const SCREENS = ["screen-menu", "screen-library", "screen-settings", "screen-player"];

  function showScreen(name) {
    SCREENS.forEach((s) => {
      document.getElementById(s).classList.toggle("active", s === name);
    });
    document.body.classList.toggle("player-visible", name === "screen-player");

    // 头像 / 用户面板仅出现在主页（其它界面强制隐藏）
    const onMenu = name === "screen-menu";
    const avatarEl = document.getElementById("user-avatar");
    const userMenuEl = document.getElementById("user-menu");
    if (avatarEl) avatarEl.classList.toggle("screen-hidden", !onMenu);
    if (userMenuEl && !onMenu) userMenuEl.classList.add("hidden");

    if (name !== "screen-player") {
      // 离开播放器时取消自动播放
      Modes.resetRun();
      Typing.cancel();
      Streaming._clearAutoTimer && Streaming._clearAutoTimer();
      // 正在讲师辅导中离开播放器 → 静默复位（不触发网络请求）
      window.Lecture && Lecture.active && Lecture.resetSilently();
    }
  }

  /* ────────── 存档统一面板：主界面「读取」 + 游戏内「存档」（保存+读取）────────── */
  // opts.currentScriptId：游戏内传入当前剧本 id，则顶部显示「保存当前进度」区；
  // 读取列表始终展示全部存档并标注学习资料名，当前剧本的存档会高亮。
  async function openArchiveModal(opts = {}) {
    const curId = opts.currentScriptId || null;
    const hasCtx = curId != null && !!Modes.scriptId;
    $("archive-title").textContent = hasCtx ? "存档（保存 · 读取）" : "读取存档";

    // —— 保存区（仅游戏内有当前剧本时展示）——
    const saveArea = $("archive-save-area");
    const saveGrid = $("archive-save-grid");
    if (hasCtx) {
      saveArea.classList.remove("hidden");
      saveGrid.innerHTML = "";
      let slots = [];
      try {
        const d = await Api.listSlots(curId);
        slots = d.slots || [];
      } catch (e) { /* 读档列表失败不阻断 */ }
      for (let i = 0; i <= 9; i++) {
        const hit = slots.find((s) => s.slot === i);
        const cell = document.createElement("div");
        cell.className = "slot-cell " + (hit ? "slot-occupied" : "slot-empty");
        cell.innerHTML = hit
          ? `<div class="slot-name">${i === 0 ? "⭐ 自动档" : "档 " + i}</div>` +
            `<div class="slot-time">第 ${hit.chapter_index + 1} 章</div>` +
            `<div class="slot-empty-tip">点击覆盖保存</div>`
          : `<div class="slot-name">${i === 0 ? "⭐ 自动档" : "档 " + i}</div>` +
            `<div class="slot-empty-tip">空 · 点击保存当前进度</div>`;
        cell.addEventListener("click", async () => {
          const label = i === 0 ? "自动档" : `档 ${i}`;
          try {
            await Api.saveProgress(curId, Modes.chapterIndex, Modes.stepIndex, i);
            Render.toast(`已保存到 ${label}`);
            openArchiveModal(opts);   // 刷新保存区，让刚存的槽变占用态
          } catch (err) {
            Render.toast(`保存失败：${err.message}`);
          }
        });
        saveGrid.appendChild(cell);
      }
    } else {
      saveArea.classList.add("hidden");
    }

    // —— 读取区（全部存档，标注资料名）——
    await renderArchiveList($("archive-list"), curId);
    $("modal-archive").classList.remove("hidden");
  }

  async function renderArchiveList(listEl, curId) {
    listEl.innerHTML = "";
    try {
      const list = await Api.listArchive();
      if (!list || !list.length) {
        listEl.innerHTML = `<div class="archive-empty">暂无存档。请先「开始学习」导入资料并学习后，会自动生成存档。</div>`;
        return;
      }
      list.forEach((a) => {
        const item = document.createElement("div");
        item.className = "archive-item" + (a.script_id === curId ? " archive-current" : "");
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
        // 删除按钮：阻止冒泡，删完刷新
        item.querySelector(".archive-del").addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!confirm(`确认删除「${a.document_title || "未命名资料"}」的${a.slot === 0 ? "自动存档" : `手动存档 ${a.slot}`}？`)) return;
          try {
            await Api.deleteProgress(a.script_id, a.slot);
            Render.toast("存档已删除");
            await renderArchiveList(listEl, curId);   // 就地刷新读取区
          } catch (err) {
            Render.toast(`删除失败：${err.message}`);
          }
        });
        listEl.appendChild(item);
      });
    } catch (err) {
      listEl.innerHTML = `<div class="archive-empty">读取存档失败：${err.message}</div>`;
    }
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
  let demoMode = false;   // 演示模式：无 Key/断网也能用样例数据（P1）

  // 按 demoMode 同步「演示角标 + 资料库载入演示按钮」显隐
  function updateDemoBadge() {
    const badge = $("demo-badge");
    const loadBtn = $("btn-load-demo");
    if (badge) badge.classList.toggle("hidden", !demoMode);
    if (loadBtn) loadBtn.classList.toggle("hidden", !demoMode);
  }

  async function loadSettingsBadge() {
    try {
      const s = await Api.getSettings();
      demoMode = Boolean(s.demo_mode);
      Modes.reviewMode = s.review_mode || "smart";
      updateDemoBadge();
    } catch {}
  }

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
            ? `<div class="doc-btns-row">
                 <button class="doc-enter" data-enter="${d.id}" data-script="${d.latest_script_id}" title="直接进入学习">▶ 进入学习</button>
                 <button class="doc-edit" data-editscript="${d.latest_script_id}" title="编辑剧本（标题/背景/台词/题目）">✏ 编辑剧本</button>
               </div>
               <div class="doc-btns-row doc-tools">
                 <button class="doc-tool" data-tool="report" data-script="${d.latest_script_id}" title="查看该剧本学习报告">📊 报告</button>
                 <button class="doc-tool" data-tool="wrongbook" data-script="${d.latest_script_id}" title="打开该剧本错题本">📕 错题</button>
                 <button class="doc-tool" data-tool="wrongreview" data-script="${d.latest_script_id}" title="进入只看错题复习">🔁 错题复习</button>
               </div>`
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
        // 「编辑剧本」→ 打开编辑弹窗（加载该剧本完整 JSON 供修改）
        const editBtn = li.querySelector(".doc-edit");
        if (editBtn) {
          editBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const scriptId = Number(editBtn.dataset.editscript);
            openEditScript(scriptId);
          });
        }
        // 资料库入口补齐：📊 报告 / 📕 错题本 / 🔁 错题复习（按当前文档的剧本）
        li.querySelectorAll(".doc-tool").forEach((toolBtn) => {
          toolBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const scriptId = Number(toolBtn.dataset.script);
            const tool = toolBtn.dataset.tool;
            if (tool === "report") {
              Report.open(scriptId);   // 打开学习报告（无需先进播放器）
            } else if (tool === "wrongbook") {
              WrongBook.open(scriptId);   // 打开错题本（无需先进播放器）
            } else if (tool === "wrongreview") {
              Streaming.playOnlyWrong(scriptId);   // 加载剧本并直接进入只看错题复习
              showScreen("screen-player");
            }
          });
        });
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

  /* ────────── 编辑剧本弹窗 ────────── */
  let editScriptId = null;   // 当前正在编辑的剧本 id（供保存用）

  // 打开编辑弹窗：拉取剧本 → 以缩进 JSON 填充文本域
  async function openEditScript(scriptId) {
    editScriptId = scriptId;
    $("edit-desc").textContent = "载入中…";
    $("edit-error").classList.add("hidden");
    $("modal-edit-script").classList.remove("hidden");
    const ta = $("edit-json");
    ta.value = "";
    try {
      const data = await Api.getScript(scriptId);
      $("edit-desc").textContent = `《${data.title}》 · 共 ${data.chapters.length} 章`;
      ta.value = JSON.stringify(data.chapters, null, 2);
    } catch (err) {
      $("edit-desc").textContent = `加载剧本失败：${err.message}`;
      $("edit-error").textContent = `加载失败：${err.message}`;
      $("edit-error").classList.remove("hidden");
    }
  }

  // 保存：JSON 解析 → 校验 chapters → 调 update 接口覆盖剧本
  async function saveEditScript() {
    if (!editScriptId) return;
    const errBox = $("edit-error");
    errBox.classList.add("hidden");
    let chapters;
    try {
      const parsed = JSON.parse($("edit-json").value);
      if (!Array.isArray(parsed) || !parsed.length) throw new Error("chapters 必须是至少包含一章的数组");
      chapters = parsed;
    } catch (err) {
      errBox.textContent = `JSON 格式错误：${err.message}`;
      errBox.classList.remove("hidden");
      return;
    }
    try {
      const out = await Api.updateScript(editScriptId, chapters);
      $("modal-edit-script").classList.add("hidden");
      Render.toast(`剧本《${out.title}》已保存修改`);
    } catch (err) {
      errBox.textContent = `保存失败：${err.message}`;
      errBox.classList.remove("hidden");
    }
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

    // 基于选中资料生成剧本（章节按资料主题考点自动划分，无需手动指定章节数）
    $("btn-generate").addEventListener("click", async () => {
      if (!selectedDocId) {
        $("gen-status").textContent = "请先在列表中选择一份资料。";
        return;
      }
      const learningGoal = $("learning-goal").value.trim();
      // 需求3：读取弹题类型勾选（选择题/填空题/简答题）
      const quizTypes = [];
      if ($("qtype-choice") && $("qtype-choice").checked) quizTypes.push("choice");
      if ($("qtype-fill") && $("qtype-fill").checked) quizTypes.push("fill");
      if ($("qtype-short") && $("qtype-short").checked) quizTypes.push("short");
      if (!quizTypes.length) quizTypes.push("choice");  // 至少保留选择题作兜底
      const statusEl = $("gen-status");
      statusEl.textContent = `正在按资料主题考点生成剧本（题型：${quizTypes.join("/")}，可能需数十秒）…`;
      statusEl.classList.add("spin");
      try {
        const out = await Api.generateScript(selectedDocId, learningGoal, quizTypes);
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

    // 演示模式「载入演示资料并生成」：后端 demo 路径会自动为当前用户建样例文档+剧本
    $("btn-load-demo").addEventListener("click", async () => {
      if (!demoMode) {
        Render.toast("请先在「设置」中开启「演示模式」。");
        return;
      }
      const statusEl = $("gen-status");
      statusEl.textContent = "正在载入演示样例资料并生成示例剧本…";
      statusEl.classList.add("spin");
      try {
        const out = await Api.generateScript(0, "", ["choice", "fill", "short"]);
        lastScriptId = out.script_id;
        statusEl.textContent = `演示剧本已生成：《${out.script.title}》`;
        showGenerateDoneModal(out.script_id, out.script.title);
        await refreshDocList();
      } catch (err) {
        statusEl.textContent = `载入演示失败：${err.message}`;
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
      $("set-thinking").value = s.thinking_level || "high";
      $("set-web-search").checked = Boolean(s.web_search);
      $("set-demo-mode").checked = Boolean(s.demo_mode);
      demoMode = Boolean(s.demo_mode);
      updateDemoBadge();
      $("set-review-mode").value = s.review_mode || "smart";
      Modes.reviewMode = s.review_mode || "smart";
      $("set-llm-engine").value = s.llm_engine || "auto";
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
          web_search: $("set-web-search").checked,
          demo_mode: $("set-demo-mode").checked,
          review_mode: $("set-review-mode").value,
          llm_engine: $("set-llm-engine").value,
          thinking_level: $("set-thinking").value,
        });
        demoMode = Boolean(s.demo_mode);
        Modes.reviewMode = s.review_mode || "smart";
        updateDemoBadge();
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

    // —— 模型路由面板（云端-边缘混合降级）——
    function engineTag(eng) {
      if (eng === "local") return "本地 Qwen2.5-1.5B";
      if (eng === "cloud") return "云端 DeepSeek";
      if (eng === "none") return "不可用";
      return "自动";
    }
    function badge(text, cls) {
      return `<span class="r-badge ${cls || ""}">${text}</span>`;
    }
    function renderRouterStatus(data) {
      const choice = data.engine_choice || "auto";
      const eff = data.effective || {};
      const local = (data.local || {});
      const cloud = (data.cloud || {});
      // 兼容两种接口返回结构：
      //  /status:  cloud={..., probe:{reachable,latency_ms,status_code,error}, state,...}, local={installed,model_file,...}
      //  /probe:   cloud={reachable,status_code,latency_ms,error, circuit:{state,...}},      local={available,latency_ms,sample}
      const probe = cloud.probe || cloud;
      const cloudReach = probe.reachable ?? cloud.reachable;
      const state = cloud.state || (cloud.circuit && cloud.circuit.state) || "closed";
      const stateCls = state === "closed" ? "ok" : (state === "open" ? "bad" : "warn");
      // 本地就绪判定：status 用 installed，probe 用 available，统一二选一
      const localOk = local.installed ?? local.available;
      return `
        <div class="r-line"><b>当前策略：</b>${badge(engineTag(choice), "sel")} 
          <span class="r-sub">（LLM_ENGINE=${choice}）</span></div>
        <div class="r-line"><b>判题/评估/讲师：</b>${badge(engineTag(eff.short), eff.short === "local" ? "ok" : "cloud")}
          &nbsp;&nbsp;<b>生成剧本：</b>${badge(engineTag(eff.long), eff.long === "cloud" ? "ok" : "warn")}</div>
        <div class="r-line"><b>本地引擎：</b>${localOk
          ? badge("已就绪", "ok") + detailLocal(local)
          : badge("不可用", "bad") + ` <span class="r-sub">${local.load_error || "未安装/未配置"}</span>`}</div>
        <div class="r-line"><b>云端链路：</b>${cloudReach
          ? badge("可达", "ok") + ` <span class="r-sub">${probe.latency_ms != null ? probe.latency_ms + "ms · " : ""}HTTP ${probe.status_code != null ? probe.status_code : "-"}</span>`
          : badge("不可达", "bad") + ` <span class="r-sub">${probe.error || ""}</span>`}</div>
        <div class="r-line"><b>云端熔断：</b>${badge(state, stateCls)}
          <span class="r-sub">失败 ${cloud.consecutive_failures != null ? cloud.consecutive_failures : "-"}/${cloud.threshold != null ? cloud.threshold : "-"} · 累计降级 ${cloud.degrade_count != null ? cloud.degrade_count : "-"} · 回切 ${cloud.recovery_count != null ? cloud.recovery_count : "-"}</span></div>
        <div class="r-sub">路由策略：${routeDesc()}</div>`;
      // 本地探测结果里没有 model_file/load_seconds 时，给出最小可读信息
      function detailLocal(l) {
        if (l.model_file) {
          return ` <span class="r-sub">${l.model_file} · ${l.model_size_mb != null ? l.model_size_mb + "MB" : ""} · 加载 ${l.load_seconds != null ? l.load_seconds + "s" : "?"}${l.load_error ? " · " + l.load_error : ""}</span>`;
        }
        if (l.latency_ms != null) {
          return ` <span class="r-sub">本地加载成功 · 实测首字 ${l.latency_ms}ms</span>`;
        }
        return "";
      }
      // 路由策略说明：短任务=判题+讲师讲解，长任务=生成剧本，各自标注当前引擎链
      function routeDesc() {
        const pol = data.policy || null;
        const shortChain = (pol && pol.short_order && pol.short_order.length)
          ? pol.short_order : (eff.short ? [eff.short] : []);
        const longChain = (pol && pol.long_order && pol.long_order.length)
          ? pol.long_order : (eff.long ? [eff.long] : []);
        const chain = (arr) => (arr && arr.length ? arr.map((e) => (e === "local" ? "本地" : e === "cloud" ? "云端" : engineTag(e))).join(" → ") : "（不可用）");
        return `短任务（判题 · 讲师讲解）→ ${chain(shortChain)} ｜ 长任务（生成剧本）→ ${chain(longChain)}`;
      }
    }

    function bindRouterPanel() {
      $("btn-router-status").addEventListener("click", async () => {
        const el = $("router-status");
        el.innerHTML = "加载中…";
        try {
          const data = await Api.llmStatus();
          el.innerHTML = renderRouterStatus(data);
        } catch (err) {
          el.innerHTML = `<span class="r-badge bad">状态读取失败</span> ${err.message}`;
        }
      });

      $("btn-router-test").addEventListener("click", async () => {
        const el = $("router-test-out");
        el.innerHTML = "运行中…";
        try {
          const r = await Api.llmTest({
            engine: $("router-test-engine").value,
            task: $("router-test-task").value,
          });
          if (!r.success) {
            el.innerHTML = `${badge("失败", "bad")} <span class="r-sub">${r.error || "未知错误"}</span>`;
            return;
          }
          el.innerHTML = `${badge(engineTag(r.engine), r.engine === "local" ? "ok" : "cloud")}
            <span class="r-sub">任务=${r.task} · 模型=${r.model || "-"} · 耗时 ${r.latency_ms}ms${r.degraded ? " · 已降级" : ""}</span>
            <div class="r-sample">${escapeHtml(r.text)}</div>`;
        } catch (err) {
          el.innerHTML = `<span class="r-badge bad">自测失败</span> ${err.message}`;
        }
      });
    }

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
      $("font-preview").textContent = px + "px";   // 仅显示文字大小，预览框高度固定，不随字号自适应
    }
    applyFontSize();   // 载入已保存的字号（此时才调用，声明在前）
    const fontRange = $("font-size");
    const fontVal = $("font-size-val");
    fontRange.addEventListener("input", () => {
      const px = Number(fontRange.value);
      fontVal.textContent = px + "px";                       // 实时数值反馈
      document.documentElement.style.setProperty("--base-font", px + "px");  // 实时预览（作用于全局）
      $("font-preview").textContent = px + "px";             // 预览框仅显示文字大小，不自适应
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

    // 模型路由面板绑定（bindRouterPanel 是本函数内的局部函数，
    // 不能在 DOMContentLoaded 顶层直接调用，否则 ReferenceError 中断绑定链，
    // 导致其后 bindPlayer 等永不执行——须在此函数作用域内调用）。
    bindRouterPanel();
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

    // 存档管理（保存 + 读取合一的统一面板：顶部保存当前剧本进度，下方读取全部存档）
    $("btn-archive").addEventListener("click", () => openArchiveModal({ currentScriptId: Modes.scriptId }));

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

    // 只看错题开关：开启后状态机跳过非错题步骤，仅播放答错题目所在章节（针对性复习）
    $("btn-only-wrong").addEventListener("click", async (e) => {
      const wasOn = Modes.onlyWrong;
      await Streaming.toggleOnlyWrong();
      e.target.classList.toggle("active", Modes.onlyWrong);
      if (wasOn === Modes.onlyWrong && !Modes.onlyWrong) {
        e.target.classList.remove("active");
      }
    });

    // 编辑弹窗：取消 / 保存
    $("btn-edit-cancel").addEventListener("click", () => {
      $("modal-edit-script").classList.add("hidden");
    });
    $("btn-edit-save").addEventListener("click", () => saveEditScript());

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

    // 注意：btn-history 已由 history.js 实装（打开历史面板），不在此绑定。

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

  /* ────────── 存档管理（播放器内「存档」按钮：保存 + 读取合一）────────── */
  async function openSaveLoadManage() {
    if (!Modes.scriptId) {
      Render.toast("尚未进入学习，请先选择资料生成剧本。");
      return;
    }
    $("modal-slots-title").textContent = "存档管理";
    const grid = $("slot-grid");
    grid.classList.add("slot-manage");
    grid.innerHTML = "";
    let data;
    try {
      data = await Api.listSlots(Modes.scriptId);
    } catch (err) {
      Render.toast(`读取存档列表失败：${err.message}`);
      return;
    }
    const slots = data.slots || [];

    const closeModal = () => Render.hideSlots();
    const saveTo = async (slot, label) => {
      try {
        await Api.saveProgress(Modes.scriptId, Modes.chapterIndex, Modes.stepIndex, slot);
        Render.toast(`已保存：${label}`);
        openSaveLoadManage();          // 刷新面板，让刚存的槽变成可读状态
      } catch (err) {
        Render.toast(`保存失败：${err.message}`);
      }
    };
    const loadFrom = (hit) => {
      closeModal();
      Streaming.loadScript(Modes.scriptId, hit.chapter_index, hit.step_index)
        .catch((e) => Render.toast(`加载存档失败：${e.message}`));
    };

    for (let i = 0; i <= 9; i++) {
      const cell = document.createElement("div");
      const hit = slots.find((s) => s.slot === i);
      cell.className = "slot-cell";
      if (hit) {
        // 已占用：整格点击 = 读取；右上小按钮 = 覆盖保存当前进度到该档
        cell.classList.add("slot-occupied");
        cell.innerHTML =
          `<div class="slot-name">${i === 0 ? "⭐ 自动存档" : `手动存档 ${i}`}</div>` +
          `<div class="slot-info">第 ${hit.chapter_index + 1} 章 · 步 ${hit.step_index + 1}</div>` +
          `<div class="slot-time">${formatDateTimeShort(hit.updated_at)}</div>` +
          `<button class="slot-overwrite" data-slot="${i}">覆盖保存</button>`;
        cell.addEventListener("click", () => loadFrom(hit));
        cell.querySelector(".slot-overwrite").addEventListener("click", (e) => {
          e.stopPropagation();
          if (!confirm(`把当前进度覆盖保存到${i === 0 ? "自动档" : `手动档 ${i}`}？`)) return;
          saveTo(i, i === 0 ? "自动档" : `手动档 ${i}`);
        });
      } else {
        // 空位：点击 = 保存当前进度到该档
        cell.classList.add("slot-empty");
        cell.innerHTML =
          `<div class="slot-name">${i === 0 ? "⭐ 自动存档" : `手动存档 ${i}`}</div>` +
          `<div class="slot-empty-tip">空 · 点击保存当前进度</div>`;
        cell.addEventListener("click", () => saveTo(i, i === 0 ? "自动档" : `手动档 ${i}`));
      }
      grid.appendChild(cell);
    }
    $("modal-slots").classList.remove("hidden");
  }

  /* ────────── 启动 ────────── */
  document.addEventListener("DOMContentLoaded", () => {
    bindMenu();
    bindLibrary();
    bindSettings();
    bindPlayer();   // 播放器控制（单击/空格推进、保存/读取等）；必须在 bindRouterPanel 已并入 bindSettings 之后执行
    window.Lecture && Lecture.bind();   // 讲师一对一辅导入口绑定
    loadSettingsBadge();   // 读演示模式开关，刷新角标
    showScreen("screen-menu");
  });

  // 退出登录时复位当前屏本地的选中/生成态（防止残留上一账号数据）
  function resetSession() {
    selectedDocId = null;
    lastScriptId = null;
    const genBtn = $("btn-generate");
    if (genBtn) genBtn.disabled = true;
  }

  // 暴露给 login.js / wrongbook.js：登录成功刷新、切换屏幕、退出复位
  window.App = {
    onLogin: async () => {
      await loadSettingsBadge();
      const lib = document.getElementById("screen-library");
      if (lib && lib.classList.contains("active")) {
        await refreshDocList();
      }
    },
    showScreen,
    resetSession,
  };
})();