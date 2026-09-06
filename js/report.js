/* ═══════════════════════════════════════════════
 * report.js — 学习报告面板（嵌入 ECharts）
 *
 * 职责：
 *  1. 播放器右上角「📊 学习报告」悬浮按钮 → 弹窗面板。
 *  2. GET /api/analytics/overview?script_id=xxx 拉取聚合数据。
 *  3. 渲染两张图：雷达图（维度=各章节标题）+ 柱状图（各章正确率）。
 *  4. 重复打开/关闭时 dispose 旧图表，避免实例堆积。
 *
 * ECharts 已本地化到 vendor/echarts.min.js（离线可用），
 * 全局对象 window.echarts 在 index.html <head> 由该脚本提供。
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

  const Report = {
    _masteryChart: null,
    _barChart: null,
    _treeChart: null,
    _timeChart: null,
    _typeChart: null,
    _coverageChart: null,
    _diagCache: null,
    _scriptId: 0,

    /* —— 打开面板：拉取数据并渲染两张图 —— */
    async open(scriptId) {
      try { await ensureEcharts(); } catch (e) { /* echarts 缺失时下方各图自行兜底 */ }
      this._scriptId = scriptId;
      const desc = $("report-desc");
      const stats = $("report-stats");
      const empty = $("report-empty");
      stats.classList.add("hidden");
      empty.classList.add("hidden");
      desc.textContent = "加载中…";

      // 重置：薄弱诊断面板收起，等用户点按钮再展开
      this._diagCache = null;
      const diagWrap = $("report-diagnosis-wrap");
      if (diagWrap) diagWrap.classList.add("hidden");
      const diagBtn = $("btn-report-diagnosis");
      const diagHint = $("report-diag-hint");
      if (diagBtn) diagBtn.disabled = false;
      if (diagHint) diagHint.textContent = "查看薄弱知识点、掌握度与推荐复习顺序";

      try {
        const data = await Api.analyticsOverview(scriptId);
        $("report-modal").classList.remove("hidden");

        // 思维导图始终渲染：组织「资料 → 知识点 → 考点」的知识结构（不含角色对话），
        // 不依赖作答记录，即使尚无答题数据也展示学习资料的知识结构。
        let scriptChapters = [];
        try {
          const script = await Api.getScript(scriptId);
          scriptChapters = script.chapters || [];
        } catch {
          scriptChapters = [];
        }
        this._renderTree(scriptChapters);

        // 没有任何作答记录：展示空态（掌握度/正确率/趋势暂不渲染，思维导图已渲染）
        if (!data.chapters_accuracy || !data.chapters_accuracy.some((c) => c.total > 0)) {
          desc.textContent = `《${data.script_title}》暂无可汇总的答题数据（上方为知识点结构思维导图）`;
          stats.classList.add("hidden");
          empty.classList.remove("hidden");
          this._disposeMastery(null);
          this._disposeBar(null);
          this._disposeTime(null);
          this._disposeType(null);
          this._disposeCoverage(null);
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
        this._renderCoverage(data.coverage || {});
      } catch (err) {
        $("report-modal").classList.remove("hidden");
        desc.textContent = `加载学习报告失败：${err.message}`;
        stats.classList.add("hidden");
        empty.classList.remove("hidden");
        empty.textContent = `加载失败：${err.message}`;
        this._dispose();
      }
    },

    /* —— 切换「薄弱诊断与复习建议」面板（首次点开才拉取）—— */
    async toggleDiagnosis(scriptId) {
      const wrap = $("report-diagnosis-wrap");
      const btn = $("btn-report-diagnosis");
      const hint = $("report-diag-hint");
      if (!wrap) return;

      // 面板当前展开 → 收起
      if (!wrap.classList.contains("hidden")) {
        wrap.classList.add("hidden");
        if (btn) btn.classList.remove("active");
        if (hint) hint.textContent = "查看薄弱知识点、掌握度与推荐复习顺序";
        return;
      }

      // 展开：首次需要拉取诊断数据
      if (btn) btn.classList.add("active");
      if (hint) hint.textContent = "正在加载学情诊断…";
      if (!this._diagCache) {
        let diag = null;
        try {
          diag = await Api.analyticsDiagnosis(scriptId);
        } catch {
          diag = null;
        }
        this._diagCache = diag;
      }
      this._renderDiagnosis(this._diagCache);
      wrap.classList.remove("hidden");
      if (hint) hint.textContent = this._diagEmpty() ? "暂无足够的作答数据用于诊断，继续学习后可查看" : "";
    },

    _diagEmpty() {
      const d = this._diagCache;
      return !d || !d.points || !d.points.length;
    },

    /* —— 关闭面板：隐藏 + 释放图表实例（防止重复打开堆积）—— */
    close() {
      $("report-modal").classList.add("hidden");
      this._dispose();
    },

    /* —— 知识点掌握程度：横向条形，仅标注关键词（去掉冗长文字）—— */
    _renderMastery(chapters) {
      const el = $("report-mastery");
      this._disposeMastery(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }
      if (!chapters || !chapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点掌握度</div>';
        return;
      }

      const chart = echarts.init(el);
      this._masteryChart = chart;

      // 按掌握度降序（未作答排最后）
      const ordered = chapters.slice().sort((a, b) => (b.total > 0 ? b.rate : -1) - (a.total > 0 ? a.rate : -1));
      const names = ordered.map((c) => kw(c.title));      // 只留关键词
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
        grid: { left: 8, right: 54, top: 12, bottom: 20, containLabel: true },
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
          axisLabel: { color: INK, fontSize: 12, width: 130, overflow: "truncate" },
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
            barMaxWidth: 16,
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
      this._disposeBar(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }

      const chart = echarts.init(el);
      this._barChart = chart;

      const names = chapters.map((c) => kw(c.title));
      const rates = chapters.map((c) => c.rate);
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
            return `${kw(row.title)} · ${row.rate}%${need ? " · 建议复习" : ""}`;
          },
        },
        grid: { left: 8, right: 16, top: 22, bottom: 66 },
        dataZoom: [
          { type: "inside", xAxisIndex: 0 },
          { type: "slider", xAxisIndex: 0, bottom: 10, height: 16, start: 0, end: 100,
            borderColor: "transparent", backgroundColor: "rgba(255,255,255,0.03)",
            fillerColor: "rgba(242,160,82,0.12)", dataBackground: { lineStyle:{color:"rgba(255,255,255,0.1)"} } },
        ],
        xAxis: {
          type: "category",
          data: names,
          axisLabel: {
            color: INK_SOFT,
            fontSize: 10,
            rotate: names.length > 6 ? 32 : 0,
            interval: 0,
            hideOverlap: true,
            formatter: (v) => (v.length > 4 ? v.slice(0, 4) + "…" : v),
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
            barMaxWidth: 26,
            label: {
              show: true,
              position: "top",
              color: INK,
              fontSize: 10,
              formatter: (p) => (p.value > 0 ? p.value + "" : ""),
            },
          },
        ],
      });
    },

    /* —— 知识点串联结构图：每个知识点作为一张卡片，按学习顺序串联起来，横向蛇形排布，一目了然 —— */
    _renderTree(scriptChapters) {
      const el = $("report-tree");
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

      const n = scriptChapters.length;
      const KW_MAX = 7;                       // 每张卡片标题截断到 ~7 字
      const nodeTexts = scriptChapters.map((c, i) => kw(c.title || `知识点${i + 1}`, KW_MAX));

      // —— 横向蛇形排布：每行约 4 张卡片（按容器宽自适应），偶数行左→右，奇数行右→左 ——
      const colW = 196;
      const perRow = Math.max(3, Math.floor((el.clientWidth || 1100) / colW));
      const rowH = 88;

      const nodes = nodeTexts.map((text, idx) => {
        const r = Math.floor(idx / perRow);
        const c = idx % perRow;
        const col = r % 2 === 0 ? c : perRow - 1 - c;
        return {
          id: "n" + idx,
          name: `#${idx + 1}  ${text}`,
          chapterTitle: scriptChapters[idx].title || "",
          x: 28 + col * colW,
          y: 24 + r * rowH,
          symbol: "roundRect",
          symbolSize: [colW - 20, 56],     // 每张卡片宽 ≈ colW-20，高 56
          label: { show: true, position: "inside" },
        };
      });

      const links = [];
      for (let i = 0; i < n - 1; i++) {
        links.push({ source: "n" + i, target: "n" + (i + 1) });
      }

      // 主题感知的卡片配色（深 / 浅）
      const isLight = document.documentElement.getAttribute("data-theme") === "light";
      const cardFill = isLight ? "#ffffff" : "#1e1b2c";
      const cardBorder = isLight ? "#d98a35" : "#f2a052";
      const cardLabel = isLight ? "#1a1620" : "#f2efe8";
      const cardShadow = isLight ? "rgba(217,138,53,.22)" : "rgba(242,160,82,.3)";
      const edgeColor = isLight ? "rgba(180,110,40,.55)" : "rgba(242,160,82,.65)";
      const tooltipBg = isLight ? "#ffffff" : "#1b1a24";
      const tooltipText = isLight ? "#241f2e" : "#f2efe8";
      const tooltipBorder = isLight ? "rgba(27,24,32,.15)" : "rgba(242,239,232,.15)";

      chart.setOption({
        tooltip: {
          backgroundColor: tooltipBg,
          borderColor: tooltipBorder,
          textStyle: { color: tooltipText, fontSize: 12 },
          formatter: (p) => {
            if (p.dataType === "edge") return "";
            const d = p.data;
            const full = d.chapterTitle || d.name;
            return `<b>${d.name || ""}</b>${full && full !== d.name ? "<br/>" + full : ""}`;
          },
        },
        series: [
          {
            type: "graph",
            layout: "none",
            data: nodes,
            links,
            roam: true,                // 可拖动 / 滚轮缩放
            draggable: true,
            edgeSymbol: ["none", "arrow"],
            edgeSymbolSize: [0, 9],
            label: {
              show: true,
              position: "inside",
              fontSize: 12,
              fontWeight: 700,
              color: cardLabel,
              formatter: (p) => p.data.name,
            },
            lineStyle: {
              color: edgeColor,
              width: 2,
              curveness: 0.0,           // 直连串联
              opacity: .85,
            },
            emphasis: {
              focus: "adjacency",
              itemStyle: { borderColor: isLight ? "#c96a12" : "#ffba6c", borderWidth: 3 },
              lineStyle: { color: isLight ? "#c96a12" : "#ffba6c", width: 3 },
            },
            itemStyle: {
              color: cardFill,
              borderColor: cardBorder,
              borderWidth: 1.5,
              shadowBlur: 14,
              shadowColor: cardShadow,
            },
            top: 6,
            bottom: 8,
            left: 6,
            right: 24,
          },
        ],
      });
    },

    /* —— 作答次数时间线（按天）：柱状作答量 + 折线正确率 —— */
    _renderTime(timeSeries) {
      const el = $("report-time");
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
          Report.toggleDiagnosis(id);
        });
      }
    },
  };

  window.Report = Report;
  document.addEventListener("DOMContentLoaded", () => Report.bind());
})();