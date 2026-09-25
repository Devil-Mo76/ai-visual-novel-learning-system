/* ═══════════════════════════════════════════════
 * report.js — 学习报告面板（ECharts + markmap 思维导图）
 *
 * 职责：
 *  1. 播放器右上角「📊 学习报告」悬浮按钮 → 弹窗面板。
 *  2. GET /api/analytics/overview?script_id=xxx 拉取聚合数据。
 *  3. 渲染：掌握度条形 + 各章正确率柱状 + 每日趋势 + 题型分布（ECharts），
 *     「知识点思维导图」优先用本地 markmap（参考 LjyYano/skill-pack），失败回退 ECharts 树。
 *  4. 重复打开/关闭时 dispose 旧图表，避免实例堆积。
 *
 * ECharts 本地化到 vendor/echarts.min.js；
 * markmap 三件套本地化到 vendor/markmap/{d3,markmap-lib,markmap-view}.min.js（均离线可用）。
 * ═══════════════════════════════════════════════ */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  /* 按需加载 ECharts：仅当打开学习报告时才注入 vendor/echarts.min.js。
     加载过一次后缓存；失败时各图表自行兜底显示提示。 */
  let _echartsPromise = null;
  function ensureEcharts() {
    if (window.echarts) return Promise.resolve();
    if (!_echartsPromise) {
      _echartsPromise = new Promise((resolve) => {
        const s = document.createElement("script");
        s.src = "vendor/echarts.min.js";
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => { _echartsPromise = null; resolve(); };  // 失败也继续，由各图兜底
        document.head.appendChild(s);
      });
    }
    return _echartsPromise;
  }

  /* 按需加载 markmap（vendor/markmap 本地三件套，离线可用）。
     依序注入 d3 → markmap-lib → markmap-view；全部成功且 window.markmap 就绪则 resolve(true)，
     任一环节失败则 resolve(false)，调用方回退到 ECharts 树。 */
  let _markmapPromise = null;
  function ensureMarkmap() {
    if (window.markmap && window.markmap.Transformer && window.markmap.Markmap) {
      return Promise.resolve(true);
    }
    if (!_markmapPromise) {
      const urls = [
        "vendor/markmap/d3.min.js",
        "vendor/markmap/markmap-lib.min.js",
        "vendor/markmap/markmap-view.min.js",
      ];
      _markmapPromise = (async () => {
        try {
          for (const u of urls) {
            await new Promise((resolve) => {
              const s = document.createElement("script");
              s.src = u;
              s.async = true;
              s.onload = () => resolve();
              s.onerror = () => resolve();
              document.head.appendChild(s);
            });
          }
          return !!(window.markmap && window.markmap.Transformer && window.markmap.Markmap);
        } catch {
          return false;
        }
      })();
      // 失败后允许下次重试
      _markmapPromise.then((ok) => { if (!ok) _markmapPromise = null; });
    }
    return _markmapPromise;
  }

  /* 图表主色与文字色取自项目 :root 主题（紫色系），与整体 UI 一致 */
  const ACCENT = "#7c6bd5";     // var(--accent)  系列主色（雷达/柱状正常区间）
  const GOOD = "#2e7d32";      // var(--good)
  const BAD = "#c62828";       // var(--bad)     低正确率章节（复习重点）标记色
  const INK = "#2a2a35";       // var(--ink)     主文字/轴线
  const INK_SOFT = "#55555f";  // var(--ink-soft)次要文字
  const GRID = "#e1e0d9";      // 网格线
  const TOOLTIP_BG = "#2a2a35";

  /* 低于该阈值判为「需要复习」的章节（柱状图标记为红色） */
  const LOW_RATE = 60;

  /* 长标题压缩为「大概的关键词」：优先在分隔符处截断，否则取前若干字 */
  function kw(t, max = 6) {
    if (!t) return "";
    const s = String(t).trim();
    const cut = s.split(/[·:：,，、;；|/\\()（）-]\s*/).filter(Boolean);
    let seg = cut[0] || s;
    // 单段太长再按整段截断
    seg = seg.length > max ? seg.slice(0, max) + "…" : seg;
    return seg;
  }

  /* —— 主题感知文字/网格色（需求：报告中图模块暗色=白字、浅色=黑字）——
     在各图 render 内以同名 const 遮蔽模块级 INK/INK_SOFT/GRID，实现白字/深字切换。 */
  function _dark() {
    return (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
  }
  function _txt() { return _dark() ? "#f4f6fc" : "#2b2833"; }     // 主文字/值
  function _sub() { return _dark() ? "#c6ccde" : "#5f5a6d"; }     // 轴/次文字
  function _grid() { return _dark() ? "rgba(255,255,255,0.16)" : "rgba(30,26,45,0.12)"; }

  const Report = {
    _masteryChart: null,
    _barChart: null,
    _treeChart: null,
    _mmInstance: null,             // 真正 markmap 思维导图实例（未命中则用 ECharts 树）
    _timeChart: null,
    _typeChart: null,
    _coverageChart: null,          // 已弃用（考点覆盖度移除），保留字段避免误删报错
    _diagCache: null,
    _scriptId: 0,

    /* —— 打开面板：拉取数据并渲染主视图 —— */
    async open(scriptId) {
      try { await ensureEcharts(); } catch (e) { /* echarts 缺失时下方各图自行兜底 */ }
      this._scriptId = scriptId;
      this._diagCache = null;

      // 默认显示主视图，回到顶部
      $("report-main").classList.remove("hidden");
      $("report-diag-page").classList.add("hidden");
      $("report-modal").scrollTop = 0;

      const desc = $("report-desc");
      const stats = $("report-stats");
      const empty = $("report-empty");
      stats.classList.add("hidden");
      empty.classList.add("hidden");
      desc.textContent = "加载中…";

      try {
        const data = await Api.analyticsOverview(scriptId);
        $("report-modal").classList.remove("hidden");

        // 没有任何作答记录：展示空态
        if (!data.chapters_accuracy || !data.chapters_accuracy.some((c) => c.total > 0)) {
          desc.textContent = `《${data.script_title}》暂无可汇总的答题数据，先去学习并作答后再来查看。`;
          stats.classList.add("hidden");
          empty.classList.remove("hidden");
          this._disposeMastery(null);
          this._disposeBar(null);
          this._disposeTime(null);
          this._disposeType(null);
          return;
        }

        desc.textContent = `《${data.script_title}》学习情况汇总`;
        $("stat-total").textContent = data.total_questions;
        $("stat-correct").textContent = data.total_correct;
        $("stat-rate").textContent = data.overall_rate + "%";
        stats.classList.remove("hidden");

        this._renderMastery(data.chapters_accuracy);
        this._renderBar(data.chapters_accuracy);
        this._renderTime(data.time_series || []);
        this._renderType(data.type_distribution || []);
      } catch (err) {
        $("report-modal").classList.remove("hidden");
        desc.textContent = `加载学习报告失败：${err.message}`;
        stats.classList.add("hidden");
        empty.classList.remove("hidden");
        empty.textContent = `加载失败：${err.message}`;
        this._dispose();
      }
    },

    /* —— 进入「薄弱诊断」全屏子页（首次点开才拉取数据）—— */
    async openDiagnosis(scriptId) {
      $("report-diag-desc").textContent = "正在加载学情诊断…";
      $("report-diag-empty").classList.add("hidden");
      $("report-diagnosis").innerHTML = "";

      if (!this._diagCache) {
        let diag = null;
        try {
          diag = await Api.analyticsDiagnosis(scriptId);
        } catch {
          diag = null;
        }
        this._diagCache = diag;
      }

      const d = this._diagCache;
      if (!d || !d.points || !d.points.length) {
        $("report-diag-desc").textContent = "";
        $("report-diag-empty").classList.remove("hidden");
      } else {
        $("report-diag-desc").textContent = "以下是针对本剧本的薄弱点诊断与建议复习顺序：";
        this._renderDiagnosis(d);
      }

      // 切换到子页：仅显示诊断页
      $("report-main").classList.add("hidden");
      $("report-diag-page").classList.remove("hidden");
      $("report-modal").scrollTop = 0;
    },

    /* —— 从薄弱诊断子页切回主报告 —— */
    backToReport() {
      $("report-main").classList.remove("hidden");
      $("report-diag-page").classList.add("hidden");
      $("report-modal").scrollTop = 0;
    },

    _diagEmpty() {
      const d = this._diagCache;
      return !d || !d.points || !d.points.length;
    },

    /* —— 关闭面板：隐藏 + 释放图表实例（防止重复打开堆积）—— */
    close() {
      $("report-modal").classList.add("hidden");
      // 复位到主视图，避免下次打开停留在诊断子页
      $("report-main").classList.remove("hidden");
      $("report-diag-page").classList.add("hidden");
      this._dispose();
    },

    /* —— 打开「🧠 思维导图」独立面板（markmap：按关键词横向展开，词下再分条列出知识点）—— */
    async openMindmap() {
      const id = this._scriptId || (typeof Modes !== "undefined" && Modes.scriptId) || 0;
      if (!id) { Render.toast("请先进入学习（选择资料生成剧本）后再查看思维导图。"); return; }
      this._scriptId = id;
      const ok = await ensureMarkmap();
      if (!ok) {
        Render.toast("思维导图组件加载失败，请刷新重试。");
        return;
      }
      const box = $("mm-box");
      const desc = $("mm-desc");
      this._disposeTree(box);
      box.innerHTML = "";
      $("mindmap-modal").classList.remove("hidden");
      desc.textContent = "生成中…";
      let chapters = [];
      try {
        const script = await Api.getScript(id);
        chapters = script.chapters || [];
      } catch { chapters = []; }
      desc.textContent = "";
      this._renderMarkmap(chapters, box);
    },
    closeMindmap() {
      $("mindmap-modal").classList.add("hidden");
      this._disposeTree($("mm-box"));
      const b = $("mm-box"); if (b) b.innerHTML = "";
    },

    /* —— 知识点掌握程度：横向条形，仅标注关键词（去掉冗长文字）—— */
    _renderMastery(chapters) {
      const el = $("report-mastery");
      // 主题色遮蔽：暗色=白字、浅色=深字（模块级常量按主题动态）
      const INK = _txt(), INK_SOFT = _sub(), GRID = _grid();
      this._disposeMastery(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }
      if (!chapters || !chapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点掌握度</div>';
        return;
      }
      // 容器高度随章节数自适应：保证每个知识点独占一行且上下隔开（不堆叠）。
      // 每章保底行距 ~ 92px；章节多时线性增高，用户可滚动查看。
      const _n = chapters.length;
      const per = _n <= 8 ? 92 : 64;
      el.style.height = Math.max(360, 60 + _n * per) + "px";

      const chart = echarts.init(el);
      this._masteryChart = chart;

      // 按掌握度降序（未作答排最后）
      const ordered = chapters.slice().sort((a, b) => (b.total > 0 ? b.rate : -1) - (a.total > 0 ? a.rate : -1));
      const names = ordered.map((c) => c.title || "知识点");      // 完整标题（不省略）
      const wrapName = (s) => {
        const t = String(s || "");
        return t.length > 10 ? t.replace(/(.{9})/g, "$1\n").trim() : t;   // 超长自动折行，完整显示
      };
      const values = ordered.map((c) => c.rate);
      const colors = ordered.map((c) => (c.total > 0 && c.rate < LOW_RATE ? BAD : ACCENT));
      const hasData = ordered.some((c) => c.total > 0);

      chart.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff", fontSize: 12 },
          formatter: (params) => {
            const row = ordered[params[0].dataIndex];
            return `${kw(row.title)} · ${row.total > 0 ? row.rate + "%" : "未作答"}`;
          },
        },
        grid: { left: 180, right: 60, top: 12, bottom: 20, containLabel: true },
        xAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: INK_SOFT, fontSize: 11, formatter: "{value}" },
          splitLine: { lineStyle: { color: GRID, opacity: .5 } },
        },
        yAxis: {
          type: "category",
          data: names,
          inverse: true,
          boundaryGap: true,
          axisLabel: {
            color: INK,
            fontSize: 12,
            interval: 0,                                   // 每项都显示
            formatter: (v) => String(v || "").length > 13 ? String(v).replace(/(.{13})/g, "$1\n").trim() : v,   // 超长再换行
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [
          {
            name: "掌握度",
            type: "bar",
            data: values.map((v, i) => ({
              value: v,
              itemStyle: { color: hasData && colors[i] || "rgba(215,210,205,0.35)" },
            })),
            barMaxWidth: 24,      // 条高适配左侧 12px 字体（略高于字高更醒目）
            showBackground: true,
            backgroundStyle: { color: "rgba(255,255,255,0.04)" },
            label: {
              show: true,
              position: "right",
              color: INK,
              fontSize: 11,
              formatter: (p) => {
                const row = ordered[p.dataIndex];
                return row.total > 0 ? p.value + "%" : "·";
              },
            },
          },
        ],
      });
    },

    /* —— 柱状图：各章正确率，仅标注关键词 —— */
    _renderBar(chapters) {
      const el = $("report-bar");
      const INK = _txt(), INK_SOFT = _sub(), GRID = _grid();   // 主题色遮蔽（暗=白字）
      this._disposeBar(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }

      const chart = echarts.init(el);
      this._barChart = chart;

      const names = chapters.map((c) => c.title || "知识点");   // 完整章名（不省略）
      const colors = chapters.map((c) => (c.total > 0 && c.rate < LOW_RATE ? BAD : ACCENT));

      chart.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff", fontSize: 12 },
          formatter: (params) => {
            const row = chapters[params[0].dataIndex];
            const need = row.total > 0 && row.rate < LOW_RATE;
            return `${row.title || row.name} · ${row.rate}%${need ? " · 建议复习" : ""}`;
          },
        },
        grid: { left: 8, right: 16, top: 26, bottom: 62 },   // 无滚动条，留出旋转章名空间
        xAxis: {
          type: "category",
          data: names,
          axisLabel: {
            color: INK_SOFT,
            fontSize: 11,
            interval: 0,                                  // 全部章都显示（不省略）
            rotate: (names.some((s) => s && s.length > 10) || names.length > 6) ? 40 : 0,
            align: "right",
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: INK_SOFT, fontSize: 10 },
          splitLine: { lineStyle: { color: GRID, opacity: .5 } },
        },
        series: [
          {
            name: "正确率",
            type: "bar",
            data: chapters.map((c, i) => ({
              value: c.rate,
              itemStyle: {
                color: c.total > 0 ? colors[i] : "rgba(215,210,205,0.3)",
                borderRadius: [3, 3, 0, 0],
              },
            })),
            barMaxWidth: 60,        // 允许按章节数自适应收缩；无滚动条、整屏展示
            label: {
              show: true,
              position: "top",
              color: INK,
              fontSize: 11,
              formatter: (p) => (p.value > 0 ? p.value + "" : ""),
            },
          },
        ],
      });
    },

    /* —— 思维导图（ECharts 树版）：每个知识点按关键词成块、颜色字体区分；
     *    章 → 考点/易错点 等细节向右分展，知识要点完整显示、字体颜色随知识块不同。 —— */
    _renderMindmapEcharts(scriptChapters, el) {
      el = el || $("mm-box");
      this._disposeTree(el);
      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功</div>';
        return;
      }
      if (!scriptChapters || !scriptChapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点结构</div>';
        return;
      }
      const chart = echarts.init(el);
      this._treeChart = chart;

      const dark = _dark();
      const PALETTE = ["#7c5cfc", "#0ea5e9", "#f59e0b", "#22c55e", "#ef4444", "#8b5cf6"];
      // 按主题把某章颜色转成可读的标签色（深色提亮、浅色加深）
      const mixW = (hex, f) => {
        const h = hex.replace("#", ""), v = parseInt(h, 16);
        const r = (v >> 16) & 255, g = (v >> 8) & 255, b = v & 255;
        const m = (c) => Math.round(c + (255 - c) * f);
        return `rgb(${m(r)},${m(g)},${m(b)})`;
      };
      const mixB = (hex, f) => {
        const h = hex.replace("#", ""), v = parseInt(h, 16);
        const r = (v >> 16) & 255, g = (v >> 8) & 255, b = v & 255;
        const m = (c) => Math.round(c * (1 - f));
        return `rgb(${m(r)},${m(g)},${m(b)})`;
      };
      const labelCol = (hex, isChapter) => {
        if (dark) return mixW(hex, isChapter ? 0.5 : 0.32);   // 深色底：提亮成柔和彩色字体
        return mixB(hex, isChapter ? 0.1 : 0.18);             // 浅色底：加深
      };
      const chipBg = (hex, isChapter) => dark
        ? `rgba(${parseInt(hex.slice(1,3),16)},${parseInt(hex.slice(3,5),16)},${parseInt(hex.slice(5,7),16)},${isChapter?0.16:0.10})`
        : `rgba(${parseInt(hex.slice(1,3),16)},${parseInt(hex.slice(3,5),16)},${parseInt(hex.slice(5,7),16)},${isChapter?0.12:0.07})`;

      // 每个知识点(章) 的细节/考点文本
      const knowledgeOf = (ch) => {
        const q = (ch.steps || []).find((s) => s.type === "question");
        if (!q) return [{ t: "本章为概述性导入，暂无独立考点", k: 0 }];
        const out = [];
        try {
          if (q.quiz_type === "short") {
            (q.reference_points || []).slice(0, 3).forEach((p) => out.push({ t: String(p).trim(), k: 0 }));
          } else if (q.quiz_type === "fill") {
            const a = String(q.answer_text || "").trim();
            if (a) out.push({ t: a, k: 0 });
          } else if (q.quiz_type === "choice") {
            const cor = (q.choices && q.choices[q.answer]) ? String(q.choices[q.answer]).trim() : "";
            const good = (q.choices || []).filter((_, i) => i !== q.answer).map((c) => String(c).trim());
            if (cor) out.push({ t: `√ 正确答案：${cor}`, k: 1 });
            // 把其余选项作为“易混淆点”也列出，充实细节
            good.slice(0, 2).forEach((g) => out.push({ t: `◦ ${g}`, k: 0 }));
          }
          const ex = String(q.explain || "").trim();
          if (ex) out.push({ t: `易错提醒：${ex}`, k: 2 });
          if (!out.length && q.text) out.push({ t: String(q.text).trim(), k: 0 });
        } catch { /* noop */ }
        return out.slice(0, 5);
      };

      const nodes = scriptChapters.map((ch, i) => {
        const col = PALETTE[i % PALETTE.length];
        const children = knowledgeOf(ch).map((it) => ({
          name: it.t,
          itemStyle: { color: chipBg(col, false), borderColor: labelCol(col, false), borderWidth: 1 },
          label: { color: labelCol(col, false), fontWeight: 500 },
        }));
        return {
          name: `#${i + 1} ${kw(ch.title || "知识点", 7)}`,
          chapterTitle: ch.title || "",
          itemStyle: { color: chipBg(col, true), borderColor: labelCol(col, true), borderWidth: 1.8 },
          label: { color: labelCol(col, true), fontWeight: 700 },
          children: children.length ? children : undefined,
          _col: col,
        };
      });
      const rootCol = PALETTE[0];
      const rootData = {
        name: "知识结构",
        itemStyle: { color: dark ? mixW(rootCol, 0.7) : "#5b47c0", borderWidth: 0 },
        label: { color: dark ? "#ffffff" : "#ffffff", fontWeight: 800 },
        children: nodes,
      };

      chart.setOption({
        tooltip: {
          formatter: (p) => {
            const d = p.data;
            if (!d) return "";
            return `<b>${d.name || ""}</b>${d.chapterTitle ? "<br/>" + d.chapterTitle : ""}`;
          },
          backgroundColor: dark ? "#16131f" : "#ffffff",
          textStyle: { color: dark ? "#fff" : "#241f2e" },
          borderWidth: 0,
        },
        series: [{
          type: "tree",
          data: [rootData],
          layout: "orthogonal",
          orient: "LR",                    // 根在左、向右展开（横向）
          initialTreeDepth: 2,             // 默认展到章，细节点开
          roam: true,
          expandAndCollapse: true,
          top: 16, bottom: 16, left: 20, right: 90,
          symbol: "roundRect",
          symbolSize: [118, 38],
          edgeShape: "curve",
          lineStyle: { color: dark ? "rgba(255,255,255,0.18)" : "rgba(30,26,45,0.22)", width: 1.6, curveness: 0.5 },
          label: { position: "inside", overflow: "truncate", width: 112, fontSize: 12 },
          leaves: { symbolSize: [88, 30], label: { position: "inside", fontSize: 10, overflow: "truncate", width: 82 } },
          emphasis: { focus: "descendant" },
        }],
      });
    },

    /* —— 知识点思维导图（分派器）：优先本地 markmap，失败回退 ECharts 树。
     *    el 为渲染容器（独立「🧠 思维导图」面板的 #mm-box）。 —— */
    _renderTree(scriptChapters, el) {
      el = el || $("mm-box");
      this._disposeTree(el);
      if (!scriptChapters || !scriptChapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点结构</div>';
        return;
      }
      ensureMarkmap().then((ok) => {
        if (ok) this._renderMarkmap(scriptChapters, el);
        else this._renderTreeEcharts(scriptChapters, el);
      });
    },

    /* —— 真正 markmap 思维导图：把「知识结构 → 章节 → 考点」转成 markdown 大纲，
     *    交给 markmap Transformer/Markmap 渲染为可缩放、可折叠的层级脑图。
     *    节点/连线/配色由 markmap 自带，画板沿用紫调渐变；深/浅主题仅调文字色。
     *    el：渲染容器（默认 #mm-box）。 —— */
    _renderMarkmap(scriptChapters, el) {
      el = el || $("mm-box");
      el.innerHTML = "";
      if (window._mmTimer) { clearTimeout(window._mmTimer); window._mmTimer = null; }

      // 章下考点（markdown 二级 bullet，完整文字；每章最多取前几条避免过长）
      const chapterKps = (ch) => {
        const q = (ch.steps || []).find((s) => s.type === "question");
        if (!q) return [];
        try {
          const take = (arr, n) => (arr || []).slice(0, n).map((p) => String(p).trim()).filter(Boolean);
          if (q.quiz_type === "short") return take(q.reference_points, 3);
          if (q.quiz_type === "fill") { const a = String(q.answer_text || "").trim(); return a ? [a] : []; }
          if (q.quiz_type === "choice") {
            const correct = (q.choices && q.choices[q.answer]) ? String(q.choices[q.answer]).trim() : "";
            if (correct) return [correct];
            return take(q.choices, 3);
          }
          const t = String(q.text || "").trim();
          return t ? [t] : [];
        } catch {
          return [];
        }
      };

      // markmap markdown 大纲（章标题用完整文字；考点作为章下二级项也完整展示，
      // 「知识块」= 每一章，其下考点归组；默认全部展开，fit 后字体随画布放大）
      const lines = ["# 知识结构"];
      scriptChapters.forEach((c, i) => {
        const title = `#${i + 1} ${c.title || "知识点"}`;   // 完整章标题（不截断）
        const kps = chapterKps(c);
        lines.push(`- ${title}`);
        kps.forEach((kp) => lines.push(`  - ${kp}`));       // 考点完整文本
      });
      const md = lines.join("\n");

      // 在容器内创建 svg 交给 markmap 渲染
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "markmap");
      el.appendChild(svg);

      const { Transformer, Markmap } = window.markmap;
      const { root } = new Transformer().transform(md);
      const isLight = document.documentElement.getAttribute("data-theme") === "light";
      const PALETTE = ["#7c5cfc", "#0ea5e9", "#f59e0b", "#22c55e", "#ef4444", "#8b5cf6"];
      const inst = Markmap.create(svg, {
        autoFit: true,          // 打开后自动缩放至整图可见
        duration: 500,
        maxWidth: 640,          // 超宽文本自动换行，避免单节点无限宽撑爆画布
        paddingX: 28,
        // 「横向展开、落落大方」：一级知识块(章)横向向右铺开；考点默认折叠(点开再展开)，
        // 避免一长条竖向堆叠；纵向行距收紧、横向层级拉宽 → 更扁更开阔。
        initialExpandLevel: 2,   // 展开到 depth<2 → 根 + 章(一级)可见，考点(二级)收起可点开
        spacingHorizontal: 180, // 层与层向右大幅拉开
        spacingVertical: 14,    // 同一分支纵向收紧
        scrollForPan: true,
        color: (node) => {
          // 根用首色，其余按层级取 markmap 调色板（同参考项目逻辑，安全无副作用）
          const d = node.depth || 0;
          return PALETTE[d % PALETTE.length];
        },
      }, root);
      this._mmInstance = inst;
      // 初次 fitContent 后延时缩放至刚好可见
      window._mmTimer = setTimeout(() => { try { inst.fit(); } catch { /* ignore */ } }, 30);
      // 主题/字体微调：白字（深）/深字（浅）交给 CSS 变量；不额外处理。
    },

    /* —— 回退版：ECharts 树形思维导图（当 markmap 依赖缺失/加载失败时兜底）：
     *    「知识结构」根节点在左，各章节(知识点)作为一级彩色分支向右展开，
     *    章节内的考点作为二级叶子挂在对应章下；节点是圆角色块、按调色板逐章取色、
     *    柔和曲线连接，画板为 markmap 同款紫调渐变。深/浅主题自适应，可缩放/拖动。 —— */
    _renderTreeEcharts(scriptChapters, el) {
      el = el || $("mm-box");
      this._disposeTree(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }
      if (!scriptChapters || !scriptChapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点结构</div>';
        return;
      }

      const chart = echarts.init(el);
      this._treeChart = chart;

      const isLight = document.documentElement.getAttribute("data-theme") === "light";

      // —— markmap 调色板（skill-pack template.html）—— 根用首色，各章按序取色 ——
      const PALETTE = ["#7c5cfc", "#0ea5e9", "#f59e0b", "#22c55e", "#ef4444", "#8b5cf6"];
      const hexRgba = (hex, a) => {
        const h = hex.replace("#", "");
        const num = parseInt(h, 16);
        return `rgba(${(num >> 16) & 255},${(num >> 8) & 255},${num & 255},${a})`;
      };
      // markmap 色块：浅主题 = 淡彩底 + 同色描边 + 深字；深主题 = 半透明彩底 + 同色描边 + 白字
      const chipFill = (hex, strong) => (isLight ? hexRgba(hex, strong ? 0.2 : 0.12) : hexRgba(hex, strong ? 0.5 : 0.3));
      const chipBorder = (hex) => (isLight ? hexRgba(hex, 0.8) : hexRgba(hex, 0.95));
      const lab = isLight ? "#201a2e" : "#ffffff";
      const linkCol = isLight ? hexRgba("#8f7fe0", 0.5) : hexRgba("#a69be8", 0.42);
      const tooltipBg = isLight ? "#ffffff" : "#16131f";
      const tooltipText = isLight ? "#241f2e" : "#f2efe8";
      const tooltipBorder = isLight ? "rgba(27,24,32,.12)" : "rgba(255,255,255,.12)";

      const n = scriptChapters.length;
      const dense = n > 9;
      const KW1 = dense ? 5 : 8;      // 章标题截断
      const KW2 = dense ? 6 : 9;      // 考点截断

      // —— 从章节的弹题中提取考点文本（章下的二级叶子） ——
      const chapterKps = (ch) => {
        const q = (ch.steps || []).find((s) => s.type === "question");
        if (!q) return [];
        try {
          if (q.quiz_type === "short") return (q.reference_points || []).slice(0, 3).map((p) => kw(String(p), KW2));
          if (q.quiz_type === "fill") return [kw(String(q.answer_text || "填词考点"), KW2)];
          if (q.quiz_type === "choice") {
            const correct = (q.choices && q.choices[q.answer]) ? String(q.choices[q.answer]) : null;
            if (correct) return [kw(correct, KW2)];
            return (q.choices || []).slice(0, 3).map((c) => kw(String(c), KW2));
          }
          return [kw(String(q.text || "考点"), KW2)];
        } catch {
          return [];
        }
      };

      // —— 组装 markmap 树：根(知识结构) → 各章(知识点) → 考点叶子 ——
      const children = scriptChapters.map((c, i) => {
        const col = PALETTE[i % PALETTE.length];
        const node = {
          name: `#${i + 1} ${kw(c.title || "知识点", KW1)}`,
          title: c.title || "",                 // 完整标题（tooltip 用）
          col,
          itemStyle: { color: chipFill(col, true), borderColor: chipBorder(col), borderWidth: 1.6,
                       shadowBlur: 10, shadowColor: hexRgba(col, isLight ? 0.16 : 0.26) },
        };
        const leaves = chapterKps(c);
        if (leaves.length) node.children = leaves.map((t) => ({
          name: t,
          col,
          isLeaf: true,
          itemStyle: { color: chipFill(col, false), borderColor: chipBorder(col), borderWidth: 1,
                       shadowBlur: 6, shadowColor: hexRgba(col, 0.12) },
        }));
        return node;
      });

      const rootCol = PALETTE[0];
      const rootData = {
        name: "知识结构",
        itemStyle: { color: hexRgba(rootCol, isLight ? 0.9 : 1), borderWidth: 0,
                     shadowBlur: 18, shadowColor: hexRgba(rootCol, 0.4) },
        children,
      };

      chart.setOption({
        // markmap 同款渐变画板
        backgroundColor: isLight
          ? { type: "linear", x: 0, y: 0, x2: 1, y2: 1, colorStops: [{ offset: 0, color: "#f6f4ff" }, { offset: 1, color: "#edeaff" }] }
          : { type: "linear", x: 0, y: 0, x2: 1, y2: 1, colorStops: [{ offset: 0, color: "#16131f" }, { offset: 1, color: "#0f0d18" }] },
        tooltip: {
          backgroundColor: tooltipBg,
          borderColor: tooltipBorder,
          textStyle: { color: tooltipText, fontSize: 12 },
          formatter: (p) => {
            const d = p.data;
            if (!d || !d.name) return "";
            const full = d.title || "";
            return `<b>${d.name}</b>${full ? "<br/>" + full : ""}`;
          },
        },
        series: [
          {
            type: "tree",
            data: [rootData],
            layout: "orthogonal",
            orient: "LR",                 // 根在左，向右展开（markmap 同款方向）
            initialTreeDepth: 2,          // 默认展开到「章」一级，考点收起可点开
            roam: true,                   // 可拖动 / 滚轮缩放
            expandAndCollapse: true,      // 点击节点展开/收起其下考点
            top: 18,
            bottom: 18,
            left: 24,
            right: 120,
            symbol: "roundRect",
            symbolSize: dense ? [92, 28] : [116, 36],
            // 根节点视觉更大、居中主题
            itemStyle: {},
            edgeShape: "curve",
            lineStyle: { color: linkCol, width: 1.8, curveness: 0.55 },
            label: {
              position: "inside",
              distance: 4,
              fontSize: dense ? 9 : 11,
              fontWeight: 600,
              color: lab,
              overflow: "truncate",
              width: dense ? 84 : 108,
            },
            leaves: {
              symbolSize: dense ? [78, 22] : [96, 26],
              label: { fontSize: dense ? 8 : 10, fontWeight: 500, color: lab },
            },
            emphasis: {
              focus: "descendant",
              lineStyle: { color: isLight ? "#6d5bd0" : "#cfc6ff", width: 2.4 },
            },
          },
        ],
      });
    },

    /* —— 作答次数时间线（按天）：柱状作答量 + 折线正确率 —— */
    _renderTime(timeSeries) {
      const el = $("report-time");
      const INK = _txt(), INK_SOFT = _sub(), GRID = _grid();   // 主题色遮蔽
      this._disposeTime(el);
      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功</div>';
        return;
      }
      if (!timeSeries || !timeSeries.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的每日趋势</div>';
        return;
      }
      const chart = echarts.init(el);
      this._timeChart = chart;
      const days = timeSeries.map((d) => d.date);
      const totals = timeSeries.map((d) => d.total);
      const rates = timeSeries.map((d) => d.rate);
      chart.setOption({
        tooltip: { trigger: "axis", backgroundColor: TOOLTIP_BG, borderColor: "transparent", textStyle: { color: "#fff" } },
        legend: { data: ["作答量", "正确率"], textStyle: { color: INK_SOFT } },
        grid: { left: 46, right: 46, top: 40, bottom: 40 },
        xAxis: { type: "category", data: days, axisLabel: { color: INK_SOFT, fontSize: 11 }, axisLine: { lineStyle: { color: GRID } } },
        yAxis: [
          { type: "value", name: "作答量", axisLabel: { color: INK_SOFT }, splitLine: { lineStyle: { color: GRID } } },
          { type: "value", name: "正确率%", min: 0, max: 100, axisLabel: { color: INK_SOFT, formatter: "{value}%" }, splitLine: { show: false } },
        ],
        series: [
          { name: "作答量", type: "bar", data: totals, itemStyle: { color: ACCENT, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 32 },
          { name: "正确率", type: "line", yAxisIndex: 1, data: rates, smooth: true, symbol: "circle", symbolSize: 6, lineStyle: { color: GOOD }, itemStyle: { color: GOOD } },
        ],
      });
    },

    /* —— 题型分布：各题型答对数 / 总次数 横向条形 —— */
    _renderType(typeDistribution) {
      const el = $("report-type");
      const INK = _txt(), INK_SOFT = _sub(), GRID = _grid();   // 主题色遮蔽
      this._disposeType(el);
      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功</div>';
        return;
      }
      if (!typeDistribution || !typeDistribution.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的题型分布</div>';
        return;
      }
      const chart = echarts.init(el);
      this._typeChart = chart;
      const TYPE_NAME = { choice: "选择题", fill: "填空题", short: "简答题" };
      const names = typeDistribution.map((d) => TYPE_NAME[d.quiz_type] || d.quiz_type);
      chart.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff" },
          formatter: (params) => {
            const row = typeDistribution[params[0].dataIndex];
            return `${TYPE_NAME[row.quiz_type] || row.quiz_type}<br/>答对 ${row.correct} / 共 ${row.total} 次<br/>正确率 <b>${row.rate}%</b>`;
          },
        },
        grid: { left: 70, right: 40, top: 20, bottom: 30 },
        xAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: INK_SOFT, formatter: "{value}%" },
          splitLine: { lineStyle: { color: GRID } },
        },
        yAxis: {
          type: "category",
          data: names,
          axisLabel: { color: INK, fontSize: 12 },
          axisLine: { lineStyle: { color: GRID } },
          axisTick: { show: false },
        },
        series: [
          {
            name: "正确率",
            type: "bar",
            data: typeDistribution.map((d) => ({ value: d.rate, itemStyle: { color: d.rate < LOW_RATE ? BAD : ACCENT } })),
            barMaxWidth: 26,
            label: { show: true, position: "right", color: INK, fontSize: 11, formatter: (p) => `${p.value}%` },
          },
        ],
      });
    },

    /* —— 考点覆盖度：已作答章节 / 总章节 进度 —— */
    _renderCoverage(coverage) {
      const el = $("report-coverage");
      this._disposeCoverage(el);
      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功</div>';
        return;
      }
      if (!coverage || !coverage.total_chapters) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的覆盖度</div>';
        return;
      }
      const chart = echarts.init(el);
      this._coverageChart = chart;
      const total = coverage.total_chapters;
      const covered = coverage.covered_count || 0;
      const pct = Math.round((covered / total) * 100);
      chart.setOption({
        tooltip: {
          formatter: (p) =>
            p.dataIndex === 0 ? `已作答：<b>${covered}</b> 章` : `尚未作答：<b>${total - covered}</b> 章`,
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff" },
        },
        series: [
          {
            type: "pie",
            radius: ["58%", "82%"],
            center: ["50%", "50%"],
            label: {
              show: true,
              fontSize: 12,
              color: INK,
              formatter: () => `覆盖 ${pct}%（${covered}/${total} 章）`,
            },
            labelLine: { show: false },
            data: [
              { value: covered, name: "已作答", itemStyle: { color: ACCENT } },
              { value: Math.max(0, total - covered), name: "未作答", itemStyle: { color: "#d8d5cd" } },
            ],
          },
        ],
      });
    },

    /* —— 学情诊断面板：掌握度条 + 状态徽章 + 自适应建议 + 前置依赖 + 学习时长 —— */
    _renderDiagnosis(diag) {
      const el = $("report-diagnosis");
      if (!diag || !diag.points || !diag.points.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:20px">暂无可诊断的知识点</div>';
        return;
      }
      const mode = diag.review_mode === "naive" ? "普通" : "智能";
      const header =
        `<div class="diag-summary">⏱ 累计学习 <b>${diag.total_study_minutes}</b> 分钟 · 活跃 <b>${diag.active_days}</b> 天 · 复习模式：<b>${mode}</b></div>`;

      const STATUS = {
        due: ["今日复习", "diag-due"],
        weak: ["薄弱", "diag-weak"],
        untouched: ["未作答", "diag-untouched"],
        ok: ["已掌握", "diag-ok"],
      };

      const items = diag.points.map((p, i) => {
        const st = STATUS[p.status] || ["", ""];
        const mastery = Math.round(p.mastery * 100);
        return (
          `<div class="diag-item">` +
          `<div class="diag-head"><span class="diag-num">${i + 1}</span><span class="diag-title">${p.title}</span><span class="diag-chip ${st[1]}">${st[0]}</span></div>` +
          `<div class="diag-mastery"><div class="diag-mastery-track"><div class="diag-mastery-fill" style="width:${mastery}%"></div></div>` +
          `<span class="diag-mastery-num">${p.covered ? mastery + "%" : "未作答"}</span></div>` +
          `<div class="diag-action">💡 ${p.recommended_action}</div>` +
          (p.prerequisite_of
            ? `<div class="diag-prereq">前置：${p.prerequisite_of}${p.needs_prereq ? "（需先补前置）" : ""}</div>`
            : "") +
          `</div>`
        );
      }).join("");

      const order = diag.next_review_priority && diag.next_review_priority.length
        ? `<div class="diag-order">🎯 建议复习顺序：${diag.next_review_priority.map((i) => diag.points[i].title).join(" → ")}</div>`
        : "";

      el.innerHTML = header + order + items;
    },

    _disposeMastery(el) {
      if (this._masteryChart) {
        this._masteryChart.dispose();
        this._masteryChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _disposeBar(el) {
      if (this._barChart) {
        this._barChart.dispose();
        this._barChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _disposeTree(el) {
      if (this._mmInstance) {
        try { this._mmInstance.destroy(); } catch { /* ignore */ }
        this._mmInstance = null;
      }
      if (this._treeChart) {
        this._treeChart.dispose();
        this._treeChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _disposeTime(el) {
      if (this._timeChart) {
        this._timeChart.dispose();
        this._timeChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _disposeType(el) {
      if (this._typeChart) {
        this._typeChart.dispose();
        this._typeChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _disposeCoverage(el) {
      if (this._coverageChart) {
        this._coverageChart.dispose();
        this._coverageChart = null;
      }
      if (el) el.innerHTML = "";
    },
    _dispose() {
      this._disposeMastery(null);
      this._disposeBar(null);
      this._disposeTree(null);
      this._disposeTime(null);
      this._disposeType(null);
      this._disposeCoverage(null);
    },

    /* —— 绑定界面事件 —— */
    bind() {
      const btn = $("btn-report-fab");
      if (btn) {
        btn.addEventListener("click", () => {
          // 仅当有已加载的剧本（当前学习上下文）时才可查看
          // 注意：Modes 是顶层 const（不挂到 window），须直接引用模块级同名全局，
          // 不能用 window.Modes（总为 undefined 会误判“未进入学习”）。
          if (typeof Modes === "undefined" || !Modes.scriptId) {
            Render.toast("请先进入学习（选择资料生成剧本后）再查看学习报告。");
            return;
          }
          Report.open(Modes.scriptId);
        });
      }
      $("btn-report-close").addEventListener("click", () => Report.close());
      const diagBtn = $("btn-report-diagnosis");
      if (diagBtn) {
        diagBtn.addEventListener("click", () => {
          const id = Report._scriptId || (typeof Modes !== "undefined" && Modes.scriptId) || 0;
          if (!id) { Render.toast("请先进入学习再查看薄弱诊断。"); return; }
          Report.openDiagnosis(id);
        });
      }
      const backBtn = $("btn-report-back");
      if (backBtn) backBtn.addEventListener("click", () => Report.backToReport());
      // 「🧠 思维导图」独立面板：播放器右侧按钮打开，面板内关闭
      const mmFab = $("btn-mindmap-fab");
      if (mmFab) mmFab.addEventListener("click", () => Report.openMindmap());
      const mmClose = $("btn-mm-close");
      if (mmClose) mmClose.addEventListener("click", () => Report.closeMindmap());
    },
  };

  window.Report = Report;
  document.addEventListener("DOMContentLoaded", () => Report.bind());
})();