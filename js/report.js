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
    _radarChart: null,
    _barChart: null,

    /* —— 打开面板：拉取数据并渲染两张图 —— */
    async open(scriptId) {
      const desc = $("report-desc");
      const stats = $("report-stats");
      const empty = $("report-empty");
      stats.classList.add("hidden");
      empty.classList.add("hidden");
      desc.textContent = "加载中…";

      try {
        const data = await Api.analyticsOverview(scriptId);
        $("report-modal").classList.remove("hidden");

        // 没有任何作答记录：展示空态（图表暂不渲染）
        if (!data.chapters_accuracy || !data.chapters_accuracy.some((c) => c.total > 0)) {
          desc.textContent = `《${data.script_title}》暂无可汇总的答题数据`;
          stats.classList.add("hidden");
          empty.classList.remove("hidden");
          this._dispose();
          return;
        }

        desc.textContent = `《${data.script_title}》学习情况汇总`;
        $("stat-total").textContent = data.total_questions;
        $("stat-correct").textContent = data.total_correct;
        $("stat-rate").textContent = data.overall_rate + "%";
        stats.classList.remove("hidden");

        this._renderRadar(data.radar);
        this._renderBar(data.chapters_accuracy);
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

    /* —— 雷达图：维度为各章节标题，值为该章正确率% —— */
    _renderRadar(radar) {
      const el = $("report-radar");
      this._disposeRadar(el);

      if (typeof echarts === "undefined") {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">图表库 ECharts 未加载成功（离线 vendor/echarts.min.js 缺失？）</div>';
        return;
      }
      if (!radar || !radar.length) {
        el.innerHTML = '<div style="color:var(--ink-soft);text-align:center;padding-top:60px">暂无可展示的知识点维度</div>';
        return;
      }

      const chart = echarts.init(el);
      this._radarChart = chart;

      const indicators = radar.map((d) => ({ name: d.name, max: 100 }));
      const values = radar.map((d) => d.value);

      chart.setOption({
        tooltip: {
          trigger: "item",
          backgroundColor: TOOLTIP_BG,
          borderColor: "transparent",
          textStyle: { color: "#fff" },
          formatter: (p) => {
            const item = radar[p.dataIndex];
            return `${item.name}<br/>正确率：<b>${item.value}%</b>`;
          },
        },
        radar: {
          indicator: indicators,
          radius: "62%",
          splitNumber: 4,
          axisName: {
            color: INK_SOFT,
            fontSize: 12,
          },
          splitLine: { lineStyle: { color: GRID } },
          splitArea: { areaStyle: { color: ["rgba(124,107,213,0.03)", "rgba(124,107,213,0.07)"] } },
          axisLine: { lineStyle: { color: GRID } },
        },
        series: [
          {
            type: "radar",
            symbol: "circle",
            symbolSize: 6,
            lineStyle: { color: ACCENT, width: 2 },
            areaStyle: { color: "rgba(124,107,213,0.28)" },
            data: [
              {
                value: values,
                name: "正确率%",
                itemStyle: { color: ACCENT },
                areaStyle: { color: "rgba(124,107,213,0.28)" },
              },
            ],
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
        grid: { left: 46, right: 20, top: 20, bottom: 64 },
        xAxis: {
          type: "category",
          data: names,
          axisLabel: {
            color: INK_SOFT,
            fontSize: 11,
            rotate: names.length > 6 ? 30 : 0,   // 章节多时斜排防止重叠
            interval: 0,
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

    _disposeRadar(el) {
      if (this._radarChart) {
        this._radarChart.dispose();
        this._radarChart = null;
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
    _dispose() {
      this._disposeRadar(null);
      this._disposeBar(null);
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