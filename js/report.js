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

  const Report = {
    _masteryChart: null,
    _barChart: null,
    _treeChart: null,
    _timeChart: null,
    _typeChart: null,
    _coverageChart: null,

    /* —— 打开面板：拉取数据并渲染两张图 —— */
    async open(scriptId) {
      try { await ensureEcharts(); } catch (e) { /* echarts 缺失时下方各图自行兜底 */ }
      const desc = $("report-desc");
      const stats = $("report-stats");
      const empty = $("report-empty");
      stats.classList.add("hidden");
      empty.classList.add("hidden");
      desc.textContent = "加载中…";

      try {
        const data = await Api.analyticsOverview(scriptId);
        $("report-modal").classList.remove("hidden");

        // 学情诊断始终渲染（即使无作答，也给出"去学习/薄弱"建议）
        let diag = null;
        try {
          diag = await Api.analyticsDiagnosis(scriptId);
        } catch {
          diag = null;
        }
        this._renderDiagnosis(diag);

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

    /* —— 关闭面板：隐藏 + 释放图表实例（防止重复打开堆积）—— */
    close() {
      $("report-modal").classList.add("hidden");
      this._dispose();
    },

    /* —— 知识点掌握程度：横向条形，全部知识点按掌握度降序，章节多也可完整浏览 ——
     * 替换原雷达图（章节一多雷达就挤成一团）。未作答章节灰色占位，不误读为 0。 */
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
      const names = ordered.map((c) => c.title);
      const values = ordered.map((c) => c.rate);
      const colors = ordered.map((c) => (c.total > 0 && c.rate < LOW_RATE ? BAD : ACCENT));
      const hasData = ordered.some((c) => c.total > 0);

      chart.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff" },
          formatter: (params) => {
            const row = ordered[params[0].dataIndex];
            return `${row.title}<br/>作答 ${row.total} 次 / 答对 ${row.correct} 次<br/>掌握度 <b>${row.total > 0 ? row.rate + "%" : "未作答"}</b>`;
          },
        },
        grid: { left: 10, right: 60, top: 20, bottom: 30, containLabel: true },
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
          inverse: true,
          axisLabel: { color: INK, fontSize: 12, width: 120, overflow: "truncate" },
          axisLine: { lineStyle: { color: GRID } },
          axisTick: { show: false },
        },
        series: [
          {
            name: "掌握度",
            type: "bar",
            data: values.map((v, i) => ({
              value: v,
              itemStyle: { color: hasData && colors[i] || "#d8d5cd" },
            })),
            barMaxWidth: 18,
            label: {
              show: true,
              position: "right",
              color: INK,
              fontSize: 11,
              formatter: (p) => {
                const row = ordered[p.dataIndex];
                return row.total > 0 ? p.value + "%" : "未作答";
              },
            },
          },
        ],
      });
    },

    /* —— 柱状图：各章正确率（正确数/总尝试数），低值章节标红 —— */
    _renderBar(chapters) {
      const el = $("report-bar");
      this._disposeBar(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }

      const chart = echarts.init(el);
      this._barChart = chart;

      const names = chapters.map((c) => c.title);
      const rates = chapters.map((c) => c.rate);
      const colors = chapters.map((c) => (c.total > 0 && c.rate < LOW_RATE ? BAD : ACCENT));

      chart.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff" },
          formatter: (params) => {
            const row = chapters[params[0].dataIndex];
            const needReview = row.total > 0 && row.rate < LOW_RATE;
            return `${row.title}<br/>答对 ${row.correct} / 共 ${row.total} 次<br/>正确率 <b>${row.rate}%</b>${needReview ? "　⚠ 建议复习" : ""}`;
          },
        },
        grid: { left: 46, right: 20, top: 20, bottom: 74 },
        // 章节多时可通过下方滑块/滚轮平移缩放，保证「全部章节」都能查看
        dataZoom: [
          { type: "inside", xAxisIndex: 0, minValueSpan: 6 },
          { type: "slider", xAxisIndex: 0, bottom: 8, height: 18, start: 0, end: 100 },
        ],
        xAxis: {
          type: "category",
          data: names,
          axisLabel: {
            color: INK_SOFT,
            fontSize: 11,
            rotate: names.length > 6 ? 30 : 0,   // 章节多时斜排防止重叠
            interval: 0,
            hideOverlap: true,
          },
          axisLine: { lineStyle: { color: GRID } },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: INK_SOFT, formatter: "{value}%" },
          splitLine: { lineStyle: { color: GRID } },
        },
        series: [
          {
            name: "正确率",
            type: "bar",
            data: chapters.map((c, i) => ({
              value: c.rate,
              // 无作答的章节显示为浅灰占位，不误读为「0 正确率」
              itemStyle: { color: c.total > 0 ? colors[i] : "#d8d5cd" },
            })),
            barMaxWidth: 44,
            // 柱端 2px 白描边：让相邻柱之间留出可读间隔
            itemStyle: {
              borderRadius: [4, 4, 0, 0],
              borderColor: "#f4f1ea",
              borderWidth: 2,
            },
            label: {
              show: true,
              position: "top",
              color: INK,
              fontSize: 11,
              formatter: (p) => (p.value > 0 ? p.value + "%" : ""),
            },
          },
        ],
      });
    },

    /* —— 思维导图：剧本 chapters → 章节标题 → 步骤台词/题目（知识点树）—— */
    _renderTree(scriptChapters) {
      const el = $("report-tree");
      this._disposeTree(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }
      if (!scriptChapters || !scriptChapters.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的剧本知识点结构</div>';
        return;
      }

      const chart = echarts.init(el);
      this._treeChart = chart;

      // —— 从章节的弹题中提取「考点」，构筑 资料 → 知识点 → 考点 的知识结构（不含角色对话）——
      const knowledgeLeaves = (ch) => {
        const q = (ch.steps || []).find((s) => s.type === "question");
        if (!q) return [{ name: "（该知识点未设考点）", value: "考点" }];
        switch (q.quiz_type) {
          case "short":
            return (q.reference_points || []).map((p) => ({ name: `考核：${String(p).slice(0, 22)}`, value: "考点" }));
          case "fill":
            return [{ name: `填词考点：${String(q.answer_text || "").slice(0, 22)}`, value: "考点" }];
          case "choice": {
            const correct = (q.choices && q.choices[q.answer]) ? String(q.choices[q.answer]) : null;
            if (correct) return [{ name: `重点：${correct.slice(0, 22)}`, value: "考点" }];
            return (q.choices || []).map((c) => ({ name: `要点：${String(c).slice(0, 18)}`, value: "考点" }));
          }
          default:
            return [{ name: (q.text || "考点").slice(0, 24), value: "考点" }];
        }
      };

      // 根节点：资料/剧本标题；每章一个「知识点」子节点；其下的「考点」作为叶子
      const chapters = scriptChapters.map((ch) => ({
        name: ch.title || "未命名知识点",
        children: knowledgeLeaves(ch),
      }));

      chart.setOption({
        tooltip: {
          trigger: "item",
          triggerOn: "mousemove",
          backgroundColor: "#2a2a35",
          borderColor: "transparent",
          textStyle: { color: "#fff" },
          formatter: (p) => {
            const d = p.data;
            return d.value
              ? `<b>${d.name}</b><br/>${d.value}`
              : `<b>${p.name}</b><br/>知识点`;
          },
        },
        series: [
          {
            type: "tree",
            data: chapters,
            left: 30,
            right: 80,
            top: 30,
            bottom: 30,
            symbol: "circle",
            symbolSize: 8,
            layout: "orthogonal",
            orient: "LR",              // 从左往右展开：章节在左，步骤叶子向右
            initialTreeDepth: 2,
            roam: true,                // 可缩放/拖动，章节多时便于查看
            expandAndCollapse: true,   // 点击节点折叠/展开
            label: {
              position: "top",
              verticalAlign: "middle",
              align: "left",
              fontSize: 12,
              color: "#2a2a35",
            },
            lineStyle: {
              color: "#d8d5cd",
              width: 1.5,
            },
            itemStyle: {
              color: "#7c6bd5",
            },
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
    },
  };

  window.Report = Report;
  document.addEventListener("DOMContentLoaded", () => Report.bind());
})();