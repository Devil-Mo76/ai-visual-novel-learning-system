/* ═══════════════════════════════════════════════
 * config.js — 全局配置与「标签 → 图片路径」映射表
 *
 * 设计原则：前端唯一的图片映射权威在这张表。
 * 后端只下发语义化标签（jiangjie / tiwen / …），
 * 前端据此换图，后端不做任何路径判断。
 * ═══════════════════════════════════════════════ */

// 后端 API 基地址（前后端分离，前端所有请求都带 /api 前缀）
const API_BASE = "http://127.0.0.1:8000";

/* ── 讲述者（老师 / 二阶堂希罗）表情映射 ── */
const TEACHER_EMO_MAP = {
  jiangjie: "images/讲述者/讲解.png",             // 正常教授知识（默认）
  yansu:    "images/讲述者/严肃.png",             // 强调重点、提醒重要性
  pingjing: "images/讲述者/平静+正常立绘.png",     // 铺垫过渡、缓和语气
  sikao:    "images/讲述者/思考.png",             // 组织语言、引导提问
  gaoxing:  "images/讲述者/高兴.png",             // 用户答对时给予肯定
  guli:     "images/讲述者/温和.png",             // 用户答错时鼓励再接再厉
};

/* ── 提问者（学生 / 樱羽艾玛）表情映射 ── */
const STUDENT_EMO_MAP = {
  tiwen:        "images/提问者/提问+正常立绘.png",  // 抛出新问题，开启互动
  sikao:        "images/提问者/思考.png",           // 消化知识点 / 等待回答
  jingya:       "images/提问者/惊讶.png",           // 对知识点表示意外
  kunhuo:       "images/提问者/疑惑+没听懂.png",    // 不解，引导进一步阐释
  huangrandawu: "images/提问者/恍然大悟.png",       // 听明白后的顿悟
  tingdongle:   "images/提问者/听懂了.png",         // 确认已掌握当前知识点
  gaoxing:      "images/提问者/高兴+赞许.png",      // 达成共识、共同进步
};

/* 根据角色名取对应映射表 */
const EMO_MAP = {
  teacher: TEACHER_EMO_MAP,
  student: STUDENT_EMO_MAP,
};

/* ── 背景图映射（章节 background key → 图片路径）── */
const BG_MAP = {
  "客厅":            "images/背景/客厅.png",
  "河流树木":        "images/背景/河流树木.png",
  "破旧房间":        "images/背景/破旧房间.png",
  "紫色河流树木":    "images/背景/紫色河流树木.png",
  "草地":            "images/背景/草地.png",
  "走廊":            "images/背景/走廊.png",
};

/* 未匹配背景时的兜底图 */
const BG_FALLBACK = "images/背景/客厅.png";

/* ── 角色展示名（需求4：不使用"老师/学生"称谓，直接用名字）── */
const ROLE_NAME = {
  teacher: "希罗同学",   // 二阶堂希罗 · 讲述者
  student: "艾玛同学",   // 樱羽艾玛 · 提问者
};

/* 双向表情联动兜底：若后端漏发 listen_emo，用倾听者默认「思考」 */
const LISTEN_FALLBACK = "sikao";

/* ── 讲师（专属辅导）表情映射 ──
 * 讲师是用户召唤型角色，图片在 images/讲师/（中文文件名）。
 * 后端流式返回的 talk_emo 是英文标签（jiangjie/kaixin/sikao/
 * yansutixing/shengqi），此处映射到本地中文立绘，前端据此实时换表情。 */
const LECTURER_EMO_MAP = {
  jiangjie:    "images/讲师/正常立绘+讲解.png",   // 默认：正常讲解
  kaixin:      "images/讲师/开心.png",             // 欢迎/肯定用户
  sikao:       "images/讲师/思考.png",             // 组织回答/等用户思考
  yansutixing: "images/讲师/严肃提醒.png",         // 强调重点/警醒
  shengqi:     "images/讲师/生气.png",             // 用户方向错了，严肃纠正
};

/* 讲师身份展示名（讲师一对一辅导模式使用） */
const LECTURER_NAME = "讲师";