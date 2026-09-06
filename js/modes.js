/* ═══════════════════════════════════════════════
 * modes.js — 播放模式状态
 * 维护：自动播放开关、对话栏显隐、打字速度、章节/进度位置指针。
 * 播放器状态机（streaming.js）从这里读取模式来决定推进节奏。
 * ═══════════════════════════════════════════════ */

const Modes = {
  // —— 播放模式 ——
  autoPlay: false,          // 自动推进已开启？
  typingSpeed: 70,          // 打字机每字间隔 ms（可调快慢）
  dialogHidden: false,      // 对话栏隐藏？

  // —— 进度指针（由 streaming.js 维护，保存进度时从这里取值）——
  scriptId: null,
  chapterIndex: 0,
  stepIndex: 0,
  currentScript: null,      // 完整剧本对象

  // —— 播放状态 ——
  isPlaying: false,         // 当前是否处于播放中（弹题弹窗时暂停）
  pausedForQuestion: false, // 是否在弹题中

  // —— 只看错题筛选模式（需求：跳过错题之外的步骤，仅播放答错题目的章节）——
  onlyWrong: false,         // 只看错题模式开启？
  wrongQuestions: [],       // 错题目标列表 [{chapter_index, step_index}](来自接口第8条)

  reviewMode: "smart",   // smart=智能复习 / naive=普通复习（实验对照）

  // 自动播放延时（比打字时长多一点，保证台词播完才推进）
  autoDelayMs: 2500,

  toggleAuto() {
    this.autoPlay = !this.autoPlay;
    return this.autoPlay;
  },

  toggleDialog() {
    this.dialogHidden = !this.dialogHidden;
    return this.dialogHidden;
  },

  resetRun() {
    this.autoPlay = false;
    this.dialogHidden = false;
    this.isPlaying = false;
    this.pausedForQuestion = false;
  },
};