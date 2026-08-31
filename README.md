# AI 视觉小说互动式学习系统

**「把学习资料变成互动小说」** —— 基于 AI 生成"双人对话式教学剧本"的视觉小说学习平台。

> 设计定位：将枯燥的学习资料转化为「讲述者 · 提问者」双人互动的视觉小说。AI 依据用户上传的 Word / PDF 资料自动生成分章剧本，用户以"看小说 + 弹题作答"的方式吸收知识点；遇到疑难可随时召唤「讲师」一对一深度辅导；学习后可查看雷达图/柱状图学习报告、开启「只看错题」针对性复习、编辑剧本内容。
>
> 全程中文界面，角色为虚构人物（二阶堂希罗 / 樱羽艾玛），不含任何真实人物信息。

---

## 目录

1. [项目简介](#1-项目简介)
2. [功能总览](#2-功能总览)
3. [总体架构](#3-总体架构)
4. [目录结构](#4-目录结构)
5. [快速启动](#5-快速启动)
6. [核心功能与玩法流程](#6-核心功能与玩法流程)
7. [学习报告与错题本](#7-学习报告与错题本)
8. [前端模块说明](#8-前端模块说明)
9. [后端架构说明](#9-后端架构说明)
10. [数据库设计](#10-数据库设计)
11. [完整 API 文档](#11-完整-api-文档)
12. [教学剧本 JSON 结构](#12-教学剧本-json-结构)
13. [判题规则说明](#13-判题规则说明)
14. [讲师一对一辅导（SSE 流式）](#14-讲师一对一辅导sse-流式)
15. [AI 提示词与角色设定](#15-ai-提示词与角色设定)
16. [环境与配置](#16-环境与配置)
17. [Git 版本管理与回滚](#17-git-版本管理与回滚)
18. [已知边界与避坑](#18-已知边界与避坑)
19. [常见问题](#19-常见问题)

---

## 1. 项目简介

**AI 视觉小说互动式学习系统** 是一个演示级学习平台，核心流程：

```
上传学习资料(Word/PDF) → AI 解析正文 → 生成分章教学剧本 → 双人对话播放
       → 剧情推进中弹题作答 → AI 判题讲评 → 召唤讲师一对一辅导
       → 自动/手动存档 → 随时「继续学习」
       → 查看学习报告(雷达图+柱状图+各章正确率)
       → 「只看错题」针对性复习
       → 「编辑剧本」自定义标题/背景/台词/题目
```

**技术栈**

| 层 | 技术 |
|---|---|
| 前端 | 原生 HTML / CSS / JavaScript（无框架，静态资源由 http.server 托管） |
| 图表 | ECharts（vendor/echarts.min.js，本地化离线可用） |
| 后端 | Python + FastAPI + Uvicorn |
| 数据库 | SQLAlchemy + SQLite（预留 PostgreSQL 路径） |
| AI 模型 | DeepSeek（经 SiliconFlow 硅基流动中转站，OpenAI 兼容协议） |
| AI 编排 | LangChain（langchain-openai / langchain-deepseek），未安装时回退 requests 直连 |

**关键词汇约定**

| 术语 | 含义 |
|---|---|
| 学习资料（文档） | 用户上传的 Word/PDF，后端解析出纯文本，作为 AI 取材依据 |
| 教学剧本（Script） | AI 依据资料生成的分章 JSON：章节含对话步骤与弹题 |
| 章节（Chapter） | 剧本的最小教学单元，每章围绕一个知识点、至多 1 道弹题 |
| 步骤（Step） | 章节内的一条台词（line）或一次弹题（question） |
| 讲述者 | 二阶堂希罗 —— 老师/知识点讲解角色 |
| 提问者 | 樱羽艾玛 —— 学生/以用户视角提问的角色 |
| 讲师 | 用户召唤的一对一辅导角色，可随时进出 |
| 学习报告 | 基于作答记录（analytics 表）聚合的雷达图 + 各章正确率柱状图 |
| 只看错题 | 播放器筛选模式：跳过非错题步骤，仅播放答错题目的所在章节 |

---

## 2. 功能总览

| 功能 | 入口 | 说明 |
|---|---|---|
| 上传 / 解析资料 | 资料库「上传并解析」 | .docx / .pdf，上限 20MB，自动提取正文 |
| 生成教学剧本 | 资料库「生成教学剧本」 | 选资料 → 章节数 → 题型勾选 → 学习背景（可选）→ AI 生成 |
| 双人对话播放 | 资料库「进入学习」/ 主菜单「继续学习」 | 逐句打字机播放，双向表情联动，空格/点击推进 |
| 弹题作答 | 播放器（章节末尾） | 选择 / 填空 / 简答三种题型，AI 判题讲评 |
| 学习报告 | 播放器右上角「📊 学习报告」 | 雷达图（各章维度掌握度）+ 柱状图（正确数/总尝试数）+ 总统计 |
| 只看错题 | 播放器控制栏「只看错题」 | 开启后仅播放答错题目所在章节，针对性复习 |
| 编辑剧本 | 资料库「✏ 编辑剧本」/ 播放器控制栏 | JSON 文本域修改标题/背景/台词/题目，保存覆盖 |
| 讲师辅导 | 播放器右侧「📖 讲师」/ 弹题「🔍 深入学习」 | SSE 流式一对一讲解，多轮记忆 |
| 讲师历史 | 讲师面板「📜 历史记录」 | 折叠框展示本次会话过往问答（只读气泡） |
| 存档系统 | 播放器「保存/读取」 | 自动档 slot 0 + 手动档 1~9 |
| 设置 | 主菜单「设置」 | API 地址/Key/模型、字体大小、题型勾选偏好 |

---

## 3. 总体架构

前后端分离，均为本机单机部署：

```
┌───────────────────────────── Browser ─────────────────────────────┐
│  index.html (11 个 JS 模块 + 2 个 CSS + 本地 ECharts)               │
│  config → api → modes → typing → render → streaming → lecture      │
│        → app → login → history → report                            │
└───────────────┬──────────────────────────────────▲─────────────────┘
                │ ① 静态页面 (http://localhost:8080) │
                │ ② REST/SSE (http://127.0.0.1:8000) │
┌───────────────▼──────────────────────────────────┴─────────────────┐
│  前端静态服务  python -m http.server 8080                           │
│  后端服务      python -m uvicorn backend.main:app --port 8000       │
│                ├── routers: documents / scripts / progress /        │
│                │            settings / lecture / analytics / auth  │
│                ├── services: extractor / script_engine / lecture_   │
│                │            service                                 │
│                └── db: SQLite (backend/learning.db)                 │
└─────────────────────────────────────────────────────────────────────┘
```

**设计原则**

- 前端不直接接触 AI，所有 AI 调用都收敛在后端 services 层。
- 前端仅负责界面渲染与 HTTP 通信（`js/api.js` 是唯一 HTTP 通信层）。
- 后端只下发语义化标签（表情 `talk_emo`、背景 key、题型等），图片路径映射全部由前端 `js/config.js` 负责。
- API Key 只落后端数据库，前端永远拿不到完整 Key（只返回掩码）。
- 前端脚本引用带 `?v=` 版本参数（CDN 式缓存击穿），改 JS 后用户强刷（Ctrl+F5）即加载新代码，避免旧缓存导致功能"没生效"。

---

## 4. 目录结构

```
frontend/
├── index.html               # 唯一入口页面（菜单/资料库/设置/播放器/全部弹窗）
├── start.bat                # Windows 一键启动入口（双击运行）
├── run_app.py               # 启动器：检查/拉起后端(8000)+前端(8080)，健康检查后开浏览器
├── README.md                # 本文件
├── css/
│   ├── style.css            # 主样式（含报告/编辑/讲师/资料库等全量样式）
│   └── animations.css       # 动画样式
├── js/
│   ├── config.js            # 全局配置：API_BASE、表情/背景/角色名权威映射
│   ├── api.js               # 唯一 HTTP 通信层（全部 REST + SSE + 接口方法）
│   ├── modes.js             # 播放模式状态（含只看错题开关与错题列表字段）
│   ├── typing.js            # 打字机逐字显示台词
│   ├── render.js            # 画面渲染层（背景/立绘/对话栏/弹题/存档/toast）
│   ├── streaming.js         # 播放器状态机（推进/判题/只看错题跳转/上报）
│   ├── lecture.js           # 讲师辅导（进入/SSE 提问/历史折叠/退出）
│   ├── login.js             # 模拟登录模块
│   ├── history.js           # 对话/测验历史（全局挂 VNHistory，避开内置 History）
│   ├── report.js            # 学习报告面板（ECharts 雷达+柱状图）
│   └── app.js               # 入口与全局事件绑定（含编辑剧本弹窗逻辑）
├── images/
│   ├── 背景/                # 剧情背景图（客厅/河流树木/破旧房间/紫色河流树木/草地/走廊）
│   ├── 讲述者/              # 希罗表情立绘
│   ├── 提问者/              # 艾玛表情立绘
│   ├── 讲师/                # 讲师表情立绘
│   ├── 用户头像/ 前端背景/ 历史记录头像/
├── vendor/
│   └── echarts.min.js       # ECharts（本地化离线可用，学习报告图表依赖）
└── backend/
    ├── main.py              # FastAPI 入口：CORS + 路由注册 + 启动建表
    ├── config.py            # 环境配置（数据库、默认模型、CORS）
    ├── db.py                # SQLAlchemy 引擎与会话管理
    ├── models.py            # ORM：Document/Script/Progress/Settings/Analytics/LectureHistory/User
    ├── schemas.py           # Pydantic 请求/响应模型（完整契约）
    ├── security.py          # JWT 签发/校验
    ├── auth.py              # 登录/注册路由
    ├── migrate.py           # 建表/迁移
    ├── errors.py / logger.py / tasks.py
    ├── requirements.txt     # 后端依赖清单
    ├── .env.example
    ├── learning.db          # SQLite 数据库（自动生成）
    ├── routers/
    │   ├── documents.py     # 资料上传/解析/列表/详情/删除
    │   ├── scripts.py       # 剧本生成/判题/详情/章节列表/错题/更新
    │   ├── progress.py      # 进度保存/续播/存档列表/删除
    │   ├── settings.py      # 设置读写（Key 掩码）/连接测试
    │   ├── lecture.py       # 讲师 SSE 问答/结束/历史查询
    │   ├── analytics.py     # 学习报告聚合（雷达+各章正确率）
    │   └── auth.py          # 认证
    └── services/
        ├── extractor.py     # .docx/.pdf → 纯文本
        ├── script_engine.py # 剧本生成引擎 + 判题引擎（GRADING_PROMPT）
        └── lecture_service.py # 讲师流式会话服务（多轮记忆）
```

---

## 5. 快速启动

### 方式一：双击 `start.bat`（Windows 推荐）

```bat
cd /d "%~dp0"
python run_app.py
```

### 方式二：命令行

```bash
# 进入项目根目录 frontend/
python run_app.py
```

`run_app.py` 会依次：

1. 检查后端 :8000 是否已运行，否则自动拉起 `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`；
2. 等待后端 `/api/health` 健康检查通过（最长 90 秒，返回 `{"status":"ok"}`）；
3. 检查前端 :8080，否则自动拉起 `python -m http.server 8080`；
4. 自动打开浏览器 `http://localhost:8080`；
5. 按 Ctrl+C 统一停掉所有子进程。

> **重要**：学习报告 / 错题本 / 讲师辅导依赖后端答题记录落库。若后端不在跑（`curl http://127.0.0.1:8000/api/health` 无响应），作答上报会被前端吞掉且提示"答题记录保存失败"，报告将显示"暂无可汇总的答题数据"。**一切作答类功能前务必确认后端在线。**

### 手动分离启动（可选）

```bash
# 终端 1：后端
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000   # 从仓库根目录执行以保证 import

# 终端 2：前端
python -m http.server 8080
# 浏览器访问 http://localhost:8080
```

### 首次体验路径

```
启动 → 登录(若接入) → 主菜单
  →「开始学习」→ 上传或选择资料 →「生成教学剧本」
        → 设置章节数、勾选弹题类型、填写学习背景(可选)
  → 剧本生成完成 →「进入学习」或稍后再学
  → 播放器：双人对话逐句播放 → 每章末尾弹题作答 → 判题讲评 → 下一章
  → 学习中可：保存/读取存档、自动播放、隐藏对话栏、召唤讲师(📖)、只看错题、编辑剧本、返回主菜单
  → 打开「📊 学习报告」查看雷达图与各章正确率
```

---

## 6. 核心功能与玩法流程

### 6.1 主菜单（`#screen-menu`）

| 按钮 | 行为 |
|---|---|
| 开始学习 | 进入「资料库」屏 |
| 继续学习 | 读取最近一次自动进度并直接进入播放器（`GET /api/progress/latest`） |
| 读取存档 | 打开全档列表（按资料名标注），任选一份读档 |
| 设置 | 连接设置（API 地址/Key/模型）、显示设置（字体大小）、弹题类型勾选偏好 |
| 退出 | 提示手动关闭浏览器 |

### 6.2 资料库（`#screen-library`）

- **上传并解析**：支持 `.docx` / `.pdf`，上限 20MB；前端直接上传 → 后端解析正文 → 入库。
- **资料列表**：显示标题、文件名、上传时间、正文预览（前 200 字）。有剧本的资料显示「▶ 进入学习」和「✏ 编辑剧本」两个同款按钮。
- **生成剧本**：选中资料 → 设定章节数（默认 8）→ 可选「学习背景说明」→ 勾选弹题类型 → 生成。
- **生成完成弹窗**：`进入学习` 或 `下次再学`（剧本已持久化，稍后仍可从列表进入）。
- **编辑剧本**：`✏ 编辑剧本` 打开 JSON 编辑弹窗（详见 6.5）。

### 6.3 播放器（`#screen-player`）

- 背景随章节切换；角色立绘按说话者轮播；下方对话栏打字机逐字显示。
- 每句台词携带「说话者表情」与「倾听者表情」，双向表情联动。
- **推进方式**：点击画面 / 空格键；打字中途点击可跳过本句。
- 每完成一个节点自动保存进度到主槽（slot 0）。
- **控制栏**：保存、读取、✏ 编辑剧本、历史、设置、快进(占位)、**只看错题**、自动、隐藏对话栏、返回主菜单。

### 6.4 弹题（三种题型）

每章末尾至多 1 道题，`quiz_type` 决定题型：

| 题型 | 作答方式 | 判题方式 |
|---|---|---|
| choice 选择题 | 点选项 | 前端本地比较下标判对错，**判完同步上报后端落库**（报告/错题数据源） |
| fill 填空题 | 文本框输入 | AI 判题（与参考答案同义即正确） |
| short 简答题 | 文本框复述 | AI 判题（覆盖参考要点 70%~80% 即通过） |

配套交互：
- 「直接查看答案」：AI 判题卡死/超时时仍可看答案继续学习（不经过 AI）。
- 填空/简答答错满 3 次自动亮出正确答案并继续（次数按剧本+位置记录在 sessionStorage）。
- 「深入学习」：对该题召唤讲师一对一讲解。
- 选择题上报失败时 toast 提示"答题记录保存失败"——作答仍有效，但报告会缺该条记录，需确认后端在线。

### 6.5 编辑剧本（`modal-edit-script`）

**入口**：资料库列表中「✏ 编辑剧本」（针对该资料的最新剧本）；播放器控制栏「✏ 编辑剧本」（当前播的剧本）。

- 弹窗以**缩进 JSON 文本域**展示整份剧本 `chapters`，文本域高度 Flex 自适应屏幕（禁止手动拖拽）。
- 允许直接修改：章节 `title` / `background`、每步台词 `text`、题目的 `choices` / `answer` / `explain`。
- 「保存修改」→ 前端 `JSON.parse` 校验（必须为非空数组）→ `POST /api/scripts/{id}/update` 覆盖落库（不重新调 AI）。
- 保存成功后 toast 提示；JSON 语法错误在弹窗内红字提示，不影响其它内容。

### 6.6 只看错题（`btn-only-wrong`）

- 数据源：`GET /api/scripts/{id}/wrong_questions`（analytics 表 `is_correct=False` 记录按章节去重）。
- 开启：拉取错题列表建立 step 集合 → 状态机 `_advanceToNextWrong` 自动跳到第一道错题所在章节。
- 播放中：非错题步骤一律跳过（`playCurrent`/`advance` 守卫），答完一道自动接下一道，跨章节自动衔接。
- 关闭：恢复完整播放。
- 无错题 / 未进学习：自动回退并 toast 提示；按钮高亮（active 类）表示开启。

### 6.7 存档系统

- **自动存档**：slot 0，每播放完一个节点自动覆盖保存。
- **手动存档**：slot 1~9，播放器「保存」选槽位。
- **读取**：主菜单「读取存档」列出全部存档（标注资料名），点击即读档。

---

## 7. 学习报告与错题本

### 7.1 学习报告（`modal-report`）

入口：播放器右上角悬浮按钮「📊 学习报告」（需先进入学习）。

数据源：`GET /api/analytics/overview?script_id=xxx`，后端从 analytics 表按章节聚合。

- **顶部统计条**：总作答数 / 答对数 / 总体正确率。
- **雷达图**：「知识点维度掌握度」——维度为各章节标题，数值为本章正确率%。
- **柱状图**：「各章节答题正确率（正确数 / 总尝试数）」——正确数 = 该章 `is_correct=True` 条数，总尝试数 = 该章全部作答条数；正确率低于 60% 的章节标红提示"⚠ 建议复习"；无作答章节显示浅灰占位（不误读为 0 正确率）。

渲染依赖本地 `vendor/echarts.min.js`；ECharts 未加载时文本域提示。

**数据链路**：每次作答（选择 / 填空 / 简答）都要落到 analytics 表——填空题/简答题走 `POST /api/scripts/answer` 落库；**选择题由前端本地判定后异步 `POST /api/scripts/answer` 上报落库**。三者缺一，报告就会"少一章"。

### 7.2 错题本（只看错题数据源）

`GET /api/scripts/{id}/wrong_questions` 返回该剧本全部 `is_correct=False` 记录（按 章节+步骤 去重），供「只看错题」复习模式与错题面板使用。

---

## 8. 前端模块说明

以下按 `index.html` 脚本加载顺序说明（均含 "use strict" 的 IIFE）：

| 模块 | 关键全局 | 职责 |
|---|---|---|
| config.js | `API_BASE`、`TEACHER_EMO_MAP`、`STUDENT_EMO_MAP`、`LECTURER_EMO_MAP`、`BG_MAP`、`ROLE_NAME`、`EMO_MAP`、`LISTEN_FALLBACK`、`LECTURER_NAME` | 全局配置与"标签→图片路径"权威映射 |
| api.js | `Api` | 唯一 HTTP 通信层：REST 请求 + SSE 读取器 + 全部接口方法 |
| modes.js | `Modes` | 播放模式状态：自动播放、打字速度、对话栏显隐、章节/步骤指针、`onlyWrong`/`wrongQuestions` |
| typing.js | `Typing` | 打字机逐字显示，支持跳过/取消/回调 |
| render.js | `Render` | 画面渲染：切背景、立绘 crossfade、对话栏、弹题框、存档槽网格、toast |
| streaming.js | `Streaming` | 播放器状态机：载入剧本、逐节点推进、判题、上报、自动保存、只看错题跳转 |
| lecture.js | `Lecture` | 讲师辅导：进入/提问(SSE)/历史折叠/退出/静默复位 |
| app.js | （IIFE 内部） | 屏幕切换、资料库/生成/设置/播放器/编辑剧本弹窗全部事件绑定、启动入口 |
| login.js | `Login` | 模拟登录 |
| history.js | `window.VNHistory` | 对话/测验历史记录与面板（避开浏览器内置 History） |
| report.js | `Report` + `window.echarts` | 学习报告面板：拉取聚合 → 渲染雷达/柱状图，重复打开 dispose 防堆积 |

> 注意：`window.History` 是浏览器内置 BOM 接口且不可覆盖，历史模块挂在 `window.VNHistory`，`streaming.js` 调用 `VNHistory.addDialogue/VNHistory.addQuiz`。接入时务必保持该命名一致。

**前端文件依赖图**（加载顺序即依赖顺序）：

```
config → api → modes → typing → render → streaming → lecture → app → login → history → report
```

---

## 9. 后端架构说明

### 9.1 路由总览

| Router | 前缀 | 主要路由 | 说明 |
|---|---|---|---|
| documents | `/api/documents` | 上传 / 列表 / 详情 / 删除 | 资料解析落库 |
| scripts | `/api/scripts` | generate / answer / {id} / {id}/list / {id}/wrong_questions / {id}/update | 剧本生成、判题、详情、章节列表、错题、编辑保存 |
| progress | `/api/progress` | save / latest / slots / list / {id} / {id}/{slot} | 进度与存档 |
| settings | `/api/settings` | GET / PUT / test | 设置读写与连接测试 |
| lecture | `/api/lecture` | chat(SSE) / end / history | 讲师问答、清会话、历史查询 |
| analytics | `/api/analytics` | overview | 学习报告聚合 |
| auth | `/api/auth` | 登录/注册 | 用户认证 |
| main | `/api/health` | 1 | 健康检查 |

### 9.2 核心调用链

**生成剧本**

```
前端 POST /api/scripts/generate
  → routers/scripts.py 校验文档存在、读 Settings(api_base/key/model)
  → services/script_engine.py generate_script()
      → 读资料前 80000 字符 + 学习背景 + 题型要求 拼 user_prompt
      → _LLMClient 调 DeepSeek（SYSTEM_PROMPT 含双角色卡 + JSON 输出约束）
      → _extract_json 去 markdown 围栏、剥最外层花括号定位 JSON
      → ScriptPayload.model_validate + 章节补 id
      → 失败自动重试，最多 3 次
  → 剧本整体 JSON 落库（scripts.chapters）
```

**播放（进入学习）**

```
前端 GET /api/scripts/{script_id}
  → 返回 ScriptDetailOut(script_id, document_id, title, source, chapters)
  → 前端 Streaming.loadScript → _applyChapter(切背景/章节条) → playCurrent(逐步骤)
```

**判题 + 落库**

- 选择题：前端本地 `picked === step.answer` 判对错，判完异步 POST `/api/scripts/answer`（携带 `picked_index`）→ 后端 choice 分支兜底判定并 `_record_analytics` 落库。
- 填空/简答：前端 POST `/api/scripts/answer` → `judge_answer()` 小 token/短超时调 AI → 落库。
- 每次作答都写入 analytics 一行（错题本 / 学习报告的公共数据源）。

**学习报告**

```
前端 GET /api/analytics/overview?script_id=xxx
  → 按章节 group by 聚合：总次数 + 答对次数
  → 输出 radar[{name:章节标题, value:正确率%}] + chapters_accuracy[{chapter_index,title,correct,total,rate}]
  → 前端 ECharts 渲染雷达 + 柱状图
```

**讲师 SSE**

```
前端 POST /api/lecture/chat
  → lecture_service.chat_stream() 流式拆段
  → 每段 yield {talk_emo, text} → router 拼 SSE "data: ..."
  → 流结束 "data: [DONE]"
前端 GET /api/lecture/history?script_id=xxx → 返回本次会话问答记录（只读气泡）
前端 POST /api/lecture/end → 清空该剧本会话记忆
```

### 9.3 安全与健壮性设计

- AI 调用全部收敛到后端，前端永远不持有 API Key。
- 无 API Key 时生成剧本**直接拒绝并报错**，不静默降级为样例。
- JSON 解析失败（最常因输出被 max_tokens 截断）自动重试并提示压缩；重试仍失败抛结构化错误。
- 数据库路径锚定 `backend/learning.db`，不随启动目录变化；预留 PostgreSQL（设置 `DATABASE_URL`）。
- 上传仅 `.docx/.pdf`；依赖缺失给明确的 pip 提示。
- 判题失败保守处理：不判通过，返回可读提示。
- 进度保存失败静默吞掉，不阻断播放；**答题上报失败改为 toast 提示**（见 6.4），避免用户误以为已记录。

---

## 10. 数据库设计

SQLite 默认文件：`backend/learning.db`。ORM 定义见 `backend/models.py`。

### documents —— 学习资料

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| filename | String(255) | 上传文件名 |
| title | String(255) | 标题（默认取文件名去扩展名） |
| content | Text | 解析后的纯文本正文 |
| created_at | DateTime | 创建时间 |
| scripts | relationship | 级联删除剧本 |

### scripts —— 教学剧本

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| document_id | FK → documents.id | 关联学习资料 |
| title | String(255) | 剧本标题 |
| source | String(255) | 资料文件名 |
| chapters | JSON | 完整剧本（chapters 数组，见《教学剧本 JSON 结构》） |
| goal_score / goal_comment | 数字/文本 | 学习目标评分与评语 |
| created_at / updated_at | DateTime | 创建/更新时间 |

### progress —— 学习进度 / 存档

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| script_id | FK → scripts.id（带索引） | 所属剧本 |
| slot | Integer（索引） | 0=自动档，1~9=手动档 |
| chapter_index | Integer | 章节下标 |
| step_index | Integer | 步骤下标 |
| updated_at | DateTime | 最近更新时间（同槽覆盖式更新） |

### analytics —— 作答记录（错题本 / 学习报告数据源）

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| script_id | FK → scripts.id | 所属剧本 |
| user_id | FK → users.id | 用户 |
| chapter_index | Integer | 章节下标（**正确上报此值，报告才按章归组**） |
| step_index | Integer | 步骤下标 |
| quiz_type | String | choice / fill / short |
| is_correct | Boolean | 本次是否答对 |
| attempts | Integer | 第几次作答 |
| question_text / your_answer / correct_answer / explain | Text | 题目、用户答案、正确答案、讲评 |
| time_cost | Integer | 耗时（毫秒） |
| created_at | DateTime | 时间 |

### settings —— 系统配置（单行表，id 恒为 1）

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 恒为 1 |
| api_base | String(255) | 默认 `https://api.siliconflow.cn/v1` |
| api_key | String(255) | 只落后端，仅返回掩码 |
| model | String(100) | 默认 `deepseek-ai/DeepSeek-V3` |
| updated_at | DateTime | 更新时间 |

### lecture_history —— 讲师对话记录（预留持久化）

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| user_id | FK → users.id | 用户 |
| script_id | FK → scripts.id | 剧本 |
| role | String(16) | user / assistant |
| content | Text | 消息内容 |
| created_at | DateTime | 时间 |

> 当前讲师多轮记忆由 `lecture_service` 进程内内存 dict 维护（重启清空），该表为未来持久化预留。历史查询接口当前读内存在线会话。

### users —— 用户（认证）

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| username | String | 用户名 |
| password_hash | String | 密码哈希（bcrypt/pbkdf2） |
| created_at | DateTime | 时间 |

---

## 11. 完整 API 文档

> 服务地址：`http://127.0.0.1:8000`。除特殊标注外，请求与响应均为 JSON（utf-8）。错误响应统一为 `{"detail": "错误信息"}`。CORS 默认放开（`*`）。

### 11.1 健康检查

#### GET `/api/health`

响应：`{"status": "ok"}`（启动器靠它判断后端就绪）。

---

### 11.2 学习资料（documents）

#### POST `/api/documents` — 上传并解析

- `multipart/form-data`，字段 `file`；支持 `.docx` / `.pdf`（上限 20MB）；201。
- 响应（DocumentOut）：`{id, filename, title, content_preview, created_at, has_script, latest_script_id}`。
- `has_script` 是否有剧本；`latest_script_id` 最近剧本 ID（前端据此显示「进入学习」/「编辑剧本」）。
- 错误：`400` 解析失败/不支持类型/无文本；`413` 文件过大。

#### GET `/api/documents` — 列表

`DocumentOut[]`，按 `created_at` 倒序。

#### GET `/api/documents/{doc_id}` — 详情

单个 `DocumentOut`；`404` 不存在。

#### DELETE `/api/documents/{doc_id}` — 删除

204（无响应体）；级联删除关联剧本、进度、作答记录；`404` 不存在。

---

### 11.3 教学剧本（scripts）

#### POST `/api/scripts/generate` — 生成剧本

请求（ScriptGenerateIn）：

```json
{
  "document_id": 3,
  "title": "计算机四级（精简版）",
  "chapter_count": 8,
  "learning_goal": "我是一名大四学生，正在准备考研……",
  "quiz_types": ["choice", "fill", "short"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| document_id | int | 是 | 目标资料 ID |
| title | string | 否 | 剧本标题，缺省用资料标题/文件名 |
| chapter_count | int | 否 | 1~30，默认 8；作为"不少于 N 章"下限约束 |
| learning_goal | string | 否 | 学习背景说明（仅增强讲解侧重点，不改结构规则） |
| quiz_types | string[] | 否 | `["choice"]`；可选 `choice/fill/short` |

响应（ScriptGenerateOut，含落库后的完整剧本）：`{script_id, script:{title, source, chapters}}`。
错误：`404` 文档不存在；`400` 无 API Key / AI 生成连续失败。

#### POST `/api/scripts/answer` — 判题并落库

请求（AnswerIn）：

```json
{
  "script_id": 12,
  "chapter_index": 2,
  "step_index": 6,
  "quiz_type": "fill",
  "quote": "进程是程序的一次运行活动",
  "picked_index": null
}
```

响应（AnswerOut）：`{correct, explain, message}`。

行为：
- `quiz_type=choice`：后端仅兜底比较（`picked_index == node.answer`），前端本地已判；每次判题都会 `_record_analytics` 落库。
- `quiz_type=fill`：从资料前 6000 字锚定答案，AI 判断与 `answer_text` 同义。
- `quiz_type=short`：按 `reference_points` 判定复述覆盖率 70%~80%。
- `message`：`AI 判题` 或 `选择题本地判定`。
- `404`：剧本/章节/步骤索引越界或不存在。

#### GET `/api/scripts/{script_id}` — 剧本详情

响应（ScriptDetailOut）：`{script_id, document_id, title, source, chapters}`；`404` 不存在。是「进入学习/继续学习」主接口。

#### GET `/api/scripts/{script_id}/list` — 章节列表

响应：`{script_id, chapters:[{index, id, title, background}]}`。

#### GET `/api/scripts/{script_id}/wrong_questions` — 错题列表

返回该剧本全部 `is_correct=False` 记录（按 章节+步骤 去重）：

```json
[
  { "chapter_index": 4, "step_index": 6, "question_text": "……",
    "your_answer": "……", "correct_answer": "……", "explain": "……" }
]
```

「只看错题」复习模式与错题本共用此接口。

#### POST `/api/scripts/{script_id}/update` — 编辑保存（覆盖剧本）

请求（ScriptUpdateIn）：`{"chapters": [...]}`（完整章节数组，仅做格式校验，不重新调 AI）。

响应：同 `GET /api/scripts/{script_id}`（ScriptDetailOut）。编辑弹窗「保存修改」走此接口。

---

### 11.4 学习进度（progress）

#### POST `/api/progress/save`

请求：`{script_id, chapter_index, step_index, slot}`（slot 0 自动档或 1~9 手动档，同槽同剧本覆盖更新）。
响应（ProgressOut）：`{script_id, slot, chapter_index, step_index, updated_at}`；`404` 剧本不存在。

#### GET `/api/progress/latest`

响应：`{exists, script_id, slot, chapter_index, step_index, title, background, updated_at}`；`exists=false` 时空态。

#### GET `/api/progress/slots/{script_id}`

响应：`{script_id, slots:[ProgressOut…]}`。

#### GET `/api/progress/list`

响应（`ArchiveOut[]`，按更新时间倒序，含 `document_title` 供主菜单读档标注）。

#### DELETE `/api/progress/{script_id}/{slot}`

响应：`{"deleted": 1}`。

#### GET `/api/progress/{script_id}`

响应（ProgressOut）；无记录时返回空档（chapter/step 为 0，updated_at 空串）。

---

### 11.5 设置（settings）

#### GET `/api/settings`

响应（SettingsOut）：`{api_base, model, api_key_set, key_masked, updated_at}`——前端拿不到 Key 本体。

#### PUT `/api/settings`

请求：`{api_base, api_key, model}`；字段留空保持数据库旧值（Key 留空不变更，避免误清空）。响应同 GET。

#### POST `/api/settings/test`

请求（SettingsIn，可整体省略直接测已存配置）；响应 `{success, message}`；后端实际发一次 `chat/completions` 验证连通性。

---

### 11.6 讲师一对一辅导（lecture，SSE 流式）

#### POST `/api/lecture/chat`

请求（LectureChatIn）：`{script_id, question, context}`。
响应：`text/event-stream`，逐段：

```
data: {"talk_emo": "jiangjie", "text": "打比方来说……"}
data: [DONE]
```

- 每段含 `talk_emo` 与 `text`，前端实时换立绘 + 追加气泡。
- 多轮记忆：按 `script_id` 进程内维护，只保留最近 12 轮，首轮注入资料前 6000 字。
- 异常兜底：流中断仍推一条可辨认提示段 + `[DONE]`。
- 错误：`400` 无 API Key / 提问为空；`404` 剧本不存在。

#### GET `/api/lecture/history?script_id=xxx`

响应（`LectureHistoryRecordOut[]`）：`[{id, role: "user"|"assistant", content, created_at}]`——本次讲师会话的问答记录，前端折叠框以只读气泡展示；无记录返回空数组。

#### POST `/api/lecture/end`

请求：`{script_id}`；响应：`{"ok": true}`——清空该剧本讲师会话记忆。

---

### 11.7 学习报告（analytics）

#### GET `/api/analytics/overview?script_id=xxx`

响应（AnalyticsOverviewOut）：

```json
{
  "script_id": 3,
  "script_title": "计算机四级（精简版）",
  "radar": [ { "name": "操作系统概述", "value": 100.0 }, ... ],
  "chapters_accuracy": [
    { "chapter_index": 0, "title": "操作系统概述", "correct": 1, "total": 1, "rate": 100.0 }, ...
  ],
  "total_questions": 8,
  "total_correct": 6,
  "overall_rate": 75.0
}
```

- `radar`：各章正确率% 作为雷达图维度。
- `chapters_accuracy`：各章 正确数/总尝试数 + 正确率%，供柱状图。
- 无作答记录时 `total` 全为 0，前端显示空态"暂无可汇总的答题数据"。

---

### 11.8 认证（auth）

登录/注册接口（`/api/auth/*`）。无 Key 场景下用户 id 使用占位 1。

---

## 12. 教学剧本 JSON 结构

`chapters` 为数组，每章含 `id / title / background / steps`。

### 章节

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 章节 ID（如 `ch_1`；AI 未给出时后端自动补） |
| title | string | 章节标题（围绕一个知识点） |
| background | string | 背景 key：`客厅 / 河流树木 / 破旧房间 / 紫色河流树木 / 草地 / 走廊` |
| steps | ScriptStep[] | 步骤列表（至少 1 个） |

### 步骤

每章末尾至多 1 个 question，其余为 line。

**line（台词）**

```json
{
  "type": "line",
  "speaker": "teacher",
  "text": "操作系统是计算机系统的核心软件，负责管理硬件和软件资源。",
  "talk_emo": "jiangjie",
  "listen_emo": "kunhuo"
}
```

**question（弹题）—— 选择**

```json
{
  "type": "question",
  "speaker": "teacher",
  "text": "下列哪项不是操作系统的主要功能？",
  "talk_emo": "yansu",
  "listen_emo": "sikao",
  "quiz_type": "choice",
  "choices": ["进程管理", "存储管理", "网络管理", "文件管理"],
  "answer": 2,
  "explain": "网络管理不是操作系统的主要功能……"
}
```

**question —— 填空**

```json
{
  "type": "question",
  "quiz_type": "fill",
  "text": "进程是程序的一次______活动。",
  "answer_text": "运行",
  "explain": "进程是程序关于数据集合的一次运行活动。"
}
```

**question —— 简答**

```json
{
  "type": "question",
  "quiz_type": "short",
  "text": "请用自己的话复述操作系统的四大功能。",
  "reference_points": ["进程管理", "存储管理", "文件管理", "设备管理"],
  "explain": "覆盖以上要点 70%~80% 即算通过。"
}
```

### 表情标签全集（前端 config.js 映射）

| 角色 | 标签 |
|---|---|
| 讲述者 teacher | jiangjie（讲解）/ yansu（强调）/ pingjing（铺垫）/ sikao（思考）/ gaoxing（肯定）/ guli（鼓励） |
| 提问者 student | tiwen（提问）/ sikao（思考）/ jingya（惊讶）/ kunhuo（疑惑）/ huangrandawu（恍然大悟）/ tingdongle（听懂了）/ gaoxing（赞许） |
| 讲师 lecturer | jiangjie / kaixin / sikao / yansutixing / shengqi |

未知标签一律回退角色默认表情；缺失 `listen_emo` 时默认倾听者「思考」。

---

## 13. 判题规则说明

| 场景 | 规则 |
|---|---|
| 选择题 | 前端本地 `picked == answer` 即判；判完异步 POST `/api/scripts/answer`（`picked_index`）兜底并落库 |
| 填空题 | AI 判题：与参考答案同义即可，允许多种表达 |
| 简答题 | AI 判题：复述覆盖参考要点 70%~80% 通过 |
| 判题失败 | 保守处理：不算通过，提示"AI 判题出错，请重新作答或核对答案" |
| 答错重试 | 填空/简答答错计数（sessionStorage 按剧本+位置），满 3 次自动亮答案并继续 |
| 直接查看答案 | `q-peek-answer`：不依赖 AI，本地亮答案，判题卡死也可继续学习 |
| 落库 | 每次判题都写 analytics 一行；选择题上报失败会 toast 提示（避免报告漏记而不自知） |

---

## 14. 讲师一对一辅导（SSE 流式）

### 14.1 前端接入（lecture.js）

```
用户点「📖 讲师」(fab) 或「🔍 深入学习」(question)
  → Lecture.enter(enterFrom, context)
      → 立绘切到讲师占屏、底部对话栏变辅导面板、弹题框收起
  → 用户输入问题 → Lecture.ask()
      → Api.lectureChat(script_id, question, context, onEvent)  // SSE
      → onEvent({talk_emo, text}) → Render.showLecturer(emo) + 气泡追加文本
  → 「📜 历史记录」→ Lecture.toggleHistory()
      → GET /api/lecture/history → 折叠框只读气泡展示过往问答（user 紫 / assistant 白）
  → "✕ 关闭"/"返回学习" → Lecture.end()
      → POST /api/lecture/end 清会话
      → 恢复双人立绘；从弹题进入则用 Streaming._playQuestion 重放原题
```

### 14.2 后端流式切段（lecture_service.chat_stream）

- 模型每段先吐 `【表情:xxx】` 标签 → 后端流式过程中识别完整标签切段 → 输出 `{talk_emo, text}`。
- 漏标兜底：连续正文 >220 字按段落边界（`\n\n`）切。
- 历史记忆：`{script_id: [{"role","content"}, ...]}` 进程内维护，只留最近 12 轮；首轮注入资料前 6000 字，后续轮不再重复注入（控制 token）。
- 退出（`/api/lecture/end`）或进程重启即清空——会话一次性。

### 14.3 SSE 数据流示例

```
data: {"talk_emo": "kaixin", "text": "你问的这个问题很好，我们一步步拆开看。"}

data: {"talk_emo": "jiangjie", "text": "内存管理面向"空间"……"}

data: [DONE]
```

---

## 15. AI 提示词与角色设定

### 15.1 角色卡（`script_engine.py` 中定义）

**二阶堂希罗（讲述者/老师）**：完美优等生设定，认真知礼、追求"正确"，说话冷静干脆、条理清晰。不得用"老师/学生"互相称呼，一律用名字。

**樱羽艾玛（提问者/学生）**：外表开朗、内心怕寂寞，说话带男孩气的可爱感；平时笨手笨脚，关键时刻冷静准确。习惯用"诶？""原来是这样！"等感叹词。

### 15.2 SYSTEM_PROMPT 核心约束（生成剧本）

- 每句对话携带 `talk_emo` + `listen_emo`，永远有人说话、有人配合。
- 按逻辑知识点拆章节：每章节一个知识点，内容长则多分章，每章围绕该知识点讲透（6~8 句）。
- 资料中所有知识点必须全部覆盖，宁多勿少。
- 每讲解完一个知识点后、在章节最后一个步骤弹 1 道题；每章至多 1 题。
- 题型：choice 带 `choices+answer`；fill 带 `answer_text`；short 带 `reference_points`。
- 输出仅 JSON，无 markdown 围栏/注释；台词尽量精炼（每句 ≤40 字）防截断。
- `learning_goal` 仅增强讲评针对性，不改变结构规则；`quiz_types` 让题型在勾选集合中轮换。

### 15.3 JSON 健壮解析（`_extract_json`）

剥 markdown 代码围栏（含"只有开围栏"的截断形态）→ 定位最外层 `{}` → 校验闭合；未闭合判定输出截断并触发重试。

### 15.4 判题提示词（GRADING_PROMPT）

- 填空题：与 `answer_text` 意思一致即正确（允许同义替换）。
- 简答题：必须复述出 `reference_points` 至少 70%~80%。
- 只依据用户资料（source 前 6000 字）判定。
- 输出 `{"correct": bool, "explain": "…", "keywords": ["…"]}`；前端讲评展示命中关键词。
- **已知坑（已修复）**：GRADING_PROMPT 含 JSON 示例花括号，占位符必须用 `str.replace` 逐词替换，**不能用 `.format()`**，否则把花括号当嵌套替换字段抛 KeyError。

---

## 16. 环境与配置

### 16.1 后端依赖（`backend/requirements.txt`）

```txt
fastapi
uvicorn[standard]
sqlalchemy
pydantic
pydantic-settings
python-multipart
python-docx
pypdf
requests
langchain-core
langchain-deepseek
# psycopg2-binary  # 接 PostgreSQL 时取消注释
```

安装：

```bash
cd backend
pip install -r requirements.txt
```

> langchain 未安装时，代码自动回退 `requests` 直连（含流式），不阻塞运行。

### 16.2 环境变量（`.env`，参考 `.env.example`）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 留空=本地 SQLite；接 PostgreSQL 时填写连接串 |
| `CORS_ORIGINS` | CORS 白名单，默认 `*` |
| `DEFAULT_MODEL` | 默认模型兜底（设置界面可改） |

### 16.3 API 配置（设置界面，落库 settings 表）

- API 地址默认 `https://api.siliconflow.cn/v1`（硅基流动中转站）。
- API Key：只在后端保存，前端只见掩码；生成剧本/判题/讲师必须配置。
- 默认模型 `deepseek-ai/DeepSeek-V3`。

### 16.4 端口

| 服务 | 端口 |
|---|---|
| 后端 FastAPI | 8000（写死在 `js/config.js` 的 `API_BASE`） |
| 前端静态 | 8080 |

---

## 17. Git 版本管理与回滚

本项目已 `git init`（仓库根 = `frontend/`），每次改动均以独立提交保存，便于回滚。

**常用命令**

```bash
git log --oneline                     # 查看版本历史
git diff <commit> -- <文件>           # 查看某版本差异
git checkout <commit> -- js/xxx.js    # 把某文件恢复为指定版本
git reset --hard <commit>             # 整体回滚到指定版本（谨慎，会丢其后改动）
```

**回滚约定**：需要回滚时，提供当时的原始问题描述，据此定位对应基线提交并恢复。示例基线：

- `304259b`：首版基线（修复前状态）
- `d0c2267`：选择题作答上报后端落库（学习报告数据源补全）
- `cfae556`：只看错题筛选播放模式
- `1765e8a`：script 标签加 `?v=` 版本参数（缓存击穿）
- `767a81b`：讲师辅导「历史记录」折叠框
- `a892ed4`：编辑剧本弹窗
- `2ee7522`：资料库编辑剧本按钮对齐"进入学习"外观
- `de8bc36`：编辑文本域禁拖拽、纯屏幕自适应

---

## 18. 已知边界与避坑

> 以下均为实际踩过并修复的问题，改代码时务必保持对应写法。

1. **`window.History` 嵌套陷阱**：浏览器内置 `History` 接口不可覆盖，历史模块必须挂 `window.VNHistory`，`streaming.js` 用 `VNHistory.addDialogue/VNHistory.addQuiz`。曾因真实浏览器取到内置 History 而报 `History.addDialogue is not a function` 导致进入学习失败。
2. **`#login-overlay` 判空守卫**：空格推进/点击推进中对 `#login-overlay` 先判空（`const loginEl = $("login-overlay"); if (loginEl && ...)`），避免 HTML 无该节点时 TypeError 卡死播放。
3. **GRADING_PROMPT 用 `str.replace`**：判题提示词含 JSON 花括号，不能用 `.format()`（会当嵌套替换字段抛 KeyError）。
4. **LangChain 模板花括号坑**：SYSTEM_PROMPT 含合法 JSON 花括号，不能用 `ChatPromptTemplate` 做 f-string 模板解析，改为手工组装 `SystemMessage/HumanMessage`。
5. **端口被占用**：启动器会自动改用空闲端口，但前端 `API_BASE` 写死 8000，需同步修改。
6. **前端脚本缓存**：`index.html` 的脚本引用带 `?v=` 版本参数；改了 JS 后用户需 `Ctrl+F5` 强刷，否则浏览器可能还在跑旧代码（表现为新按钮/新功能"没生效"）。
7. **学习报告依赖作答落库**：选择题本地判定后**必须异步 POST `/api/scripts/answer` 落库**，否则报告/错题只有填空简答数据。上报失败已改为 toast 提示而非静默吞掉。
8. **只看错题的数据源**：错题列表来自 analytics 表 `is_correct=False` 记录；若后端离线或选择题未上报，错题为空，开关会自动回退并提示"暂无错题"。

---

## 19. 常见问题

**Q：点「进入学习」提示"剧本加载失败：Failed to fetch / NetworkError"？**
A：多为浏览器连不上后端。确认后端健康（`curl http://127.0.0.1:8000/api/health`）；若后端在 8001+（8000 被占），同步修改 `js/config.js` 的 `API_BASE`；Ctrl+F5 强刷清缓存。

**Q：提示"剧本加载失败：History.addDialogue is not a function"？**
A：历史名称冲突，已修复为 `VNHistory`。强刷（Ctrl+F5）后重试。

**Q：学习报告显示"暂无可汇总的答题数据"？**
A：analytics 表没有作答记录。检查：(1) 后端是否在跑；(2) 作答时是否出现"答题记录保存失败"toast；(3) 选择题是否已落库（见避坑 7）；(4) 作答后强刷再看报告。

**Q：学习报告只显示第一章的题？**
A：报告按 analytics 的 `chapter_index` 分组。若后续章节的作答没进库（选择题未上报 / 作答时后端离线 / 上报失败被吞），后面章节 `total` 为 0。修复后所有题型都会落库；已作答旧数据需重新作答或清理测试污染行。

**Q：点「只看错题」没反应？**
A：先 `Ctrl+F5` 强刷（确保加载新版 JS）；确认后端在跑且已有错题记录（`GET /api/scripts/{id}/wrong_questions`）；无错题时开关会自动回退并提示"暂无错题"。

**Q：生成剧本很慢/一直重试？**
A：AI 生成可能耗时数十秒；JSON 解析失败自动重试 3 次。最终失败：检查 API Key、网络、SiliconFlow 服务可用性。

**Q：填空/简答判题卡死？**
A：点「直接查看答案」绕过判题继续学习；判题请求短超时（100s）+ 512 token，正常很快。

**Q：如何接入 PostgreSQL？**
A：安装 `psycopg2-binary`，`.env` 配置 `DATABASE_URL=postgresql://...`。当前 SQLite 演示零配置。

**Q：能改 AI 服务商或模型吗？**
A：设置界面即可（API 地址/Key/模型）。默认 SiliconFlow 中转站的 DeepSeek。

---