/* ═══════════════════════════════════════════════
 * api.js — 前端唯一的 HTTP 通信层
 * 设计原则：前端不涉及任何 AI 调用/表情决策/教学流程判断，
 * 仅负责把用户操作转成 HTTP 请求、把后端结构化响应转给前端。
 * ═══════════════════════════════════════════════ */

const Api = {
  base: API_BASE,

  // 统一附加登录 token（Authorization: Bearer <jwt>），用于多用户数据隔离
  _token() {
    return localStorage.getItem("vn_token") || "";
  },

  _authHeaders(existing) {
    const headers = new Headers(existing || {});
    const token = this._token();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return headers;
  },

  // 通用 fetch 封装：自动带 JSON、附加 token、解析错误信息
  async _req(path, options = {}) {
    const headers = this._authHeaders(options.headers);
    const resp = await fetch(this.base + path, { ...options, headers });
    if (resp.status === 401) {
      // token 失效：清理并通知登录层重新登录
      localStorage.removeItem("vn_token");
      localStorage.removeItem("vn_user");
      if (this.onAuthExpired) this.onAuthExpired();
    }
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      const msg = (data && data.detail) || `请求失败（HTTP ${resp.status}）`;
      throw new Error(msg);
    }
    return data;
  },

  _json(method, body) {
    return {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
  },

  // —— 健康检查 ——
  health() {
    return this._req("/api/health");
  },

  // —— 认证（真实登录闭环） ——
  login(username, password) {
    return this._req("/api/auth/login", this._json("POST", { username, password }));
  },
  register(username, password) {
    return this._req("/api/auth/register", this._json("POST", { username, password }));
  },

  // —— 文档 ——
  uploadDocument(file) {
    const fd = new FormData();
    fd.append("file", file);
    return this._req("/api/documents", { method: "POST", body: fd });
  },

  listDocuments() {
    return this._req("/api/documents");
  },

  deleteDocument(id) {
    return this._req(`/api/documents/${id}`, { method: "DELETE" });
  },

  // —— 剧本 ——
  // 章节数由后端按资料主题考点自动决定，前端不再手动指定
  generateScript(documentId, learningGoal = "", quizTypes = ["choice"]) {
    return this._req(
      "/api/scripts/generate",
      this._json("POST", {
        document_id: documentId,
        learning_goal: learningGoal,
        quiz_types: quizTypes,
      })
    );
  },

  verifyAnswer(payload) {
    // 填空题/简答题的答案由 AI 判题（简答复述 70%-80% 视为通过）
    return this._req("/api/scripts/answer", this._json("POST", payload));
  },

  getScript(scriptId) {
    return this._req(`/api/scripts/${scriptId}`);
  },

  // —— 编辑剧本：覆盖 chapters（标题/背景/台词/题目均可在其中修改）——
  updateScript(scriptId, chapters) {
    return this._req(
      `/api/scripts/${scriptId}/update`,
      this._json("POST", { chapters }),
    );
  },

  // —— 学习报告（analytics 聚合）——
  analyticsOverview(scriptId) {
    return this._req(`/api/analytics/overview?script_id=${scriptId}`);
  },

  // —— 学情诊断 / 自适应复习推荐 ——
  analyticsDiagnosis(scriptId) {
    return this._req(`/api/analytics/diagnosis?script_id=${scriptId}`);
  },

  // —— 错题本（只看错题复习模式的数据源，接口第8条）——
  // status: "pending"（默认，只看未复练）| "all"（全部，含已复练，供错题本面板）
  wrongQuestions(scriptId, status = "pending") {
    return this._req(`/api/scripts/${scriptId}/wrong_questions?status=${status}`);
  },

  // 错题本「标记已练」：把该题（chapter/step）的历史错题记录置 retested=true
  retestWrong(scriptId, chapterIndex, stepIndex) {
    return this._req(
      `/api/scripts/${scriptId}/wrong_questions/${chapterIndex}/${stepIndex}/retest`,
      { method: "POST" }
    );
  },

  // —— 进度 ——
  saveProgress(scriptId, chapterIndex, stepIndex, slot = 0) {
    return this._req(
      "/api/progress/save",
      this._json("POST", { script_id: scriptId, chapter_index: chapterIndex, step_index: stepIndex, slot })
    );
  },

  latestProgress() {
    return this._req("/api/progress/latest");
  },

  listArchive() {
    return this._req("/api/progress/list");
  },

  getProgress(scriptId) {
    return this._req(`/api/progress/${scriptId}`);
  },

  listSlots(scriptId) {
    return this._req(`/api/progress/slots/${scriptId}`);
  },

  deleteProgress(scriptId, slot) {
    return this._req(`/api/progress/${scriptId}/${slot}`, { method: "DELETE" });
  },

  // —— 设置 ——
  getSettings() {
    return this._req("/api/settings");
  },

  saveSettings({ api_base, api_key, model, web_search, demo_mode, review_mode, llm_engine, thinking_level }) {
    const body = { api_base, api_key, model };
    if (typeof web_search === "boolean") body.web_search = web_search;
    if (typeof demo_mode === "boolean") body.demo_mode = demo_mode;
    if (review_mode === "smart" || review_mode === "naive") body.review_mode = review_mode;
    if (llm_engine === "auto" || llm_engine === "local" || llm_engine === "cloud") {
      body.llm_engine = llm_engine;
    }
    if (thinking_level === "high" || thinking_level === "medium" || thinking_level === "low") {
      body.thinking_level = thinking_level;
    }
    return this._req("/api/settings", this._json("PUT", body));
  },

  testSettings(payload) {
    return this._req("/api/settings/test", this._json("POST", payload));
  },

  // —— 模型路由（云端-边缘混合降级）——
  llmStatus() {
    return this._req("/api/llm/status");
  },

  llmProbe() {
    return this._req("/api/llm/probe", this._json("POST", {}));
  },

  llmSetEngine(engine) {
    return this._req("/api/llm/engine", this._json("POST", { engine }));
  },

  llmTest({ engine = "auto", task = "short", prompt = "请用一句话说明什么是进程。" } = {}) {
    return this._req("/api/llm/test", this._json("POST", { engine, task, prompt }));
  },

  llmBench({ engines = "local,cloud", limit = 0 } = {}) {
    return this._req("/api/llm/bench", this._json("POST", { engines, limit }));
  },

  // —— 讲师一对一辅导（SSE 流式）——
  // onEvent 收到 {talk_emo, text} 分段；[DONE] / 连接关闭时 resolve。
  lectureChat(scriptId, question, context = "", onEvent) {
    return this._sse(
      "/api/lecture/chat",
      { script_id: scriptId, question, context },
      onEvent
    );
  },

  lectureEnd(scriptId) {
    return this._req("/api/lecture/end", this._json("POST", { script_id: scriptId }));
  },

  // —— 讲师历史记录（只读展示过往问答）——
  lectureHistory(scriptId) {
    return this._req(`/api/lecture/history?script_id=${scriptId}`);
  },

  // 通用 SSE 读取器：POST JSON → 逐「data: 」行解析 → 回调 onEvent(对象) → [DONE] resolve。
  async _sse(path, body, onEvent) {
    const opts = this._json("POST", body);
    opts.headers = this._authHeaders(opts.headers);
    const resp = await fetch(this.base + path, opts);
    if (!resp.ok) {
      const data = await resp.json().catch(() => null);
      throw new Error((data && data.detail) || `请求失败（HTTP ${resp.status}）`);
    }
    if (!resp.body) {
      throw new Error("当前浏览器不支持流式响应（需要现代浏览器）。");
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE 事件以空行分隔
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLine = block
          .split("\n")
          .find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        const payload = dataLine.slice(5).trim();
        if (payload === "[DONE]") return;
        try {
          const evt = JSON.parse(payload);
          if (onEvent && typeof evt.talk_emo === "string") onEvent(evt);
        } catch {
          // 忽略非 JSON 的中间行，不打断流
        }
      }
    }
  },
};