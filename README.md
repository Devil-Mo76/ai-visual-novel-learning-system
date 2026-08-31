# AI 视觉小说学习 1.0

**AI视觉小说互动式学习系统** —— 基于 AI 生成"双人对话式教学剧本"的视觉小说学习平台（版本 1.0）。

> 设计定位：将枯燥的学习资料转化为「讲述者 · 提问者」双人互动的视觉小说。AI 依据用户上传的 Word / PDF 资料自动生成分章剧本，用户以"看小说 + 弹题作答"的方式吸收知识点；遇到疑难可随时召唤「讲师」一对一深度辅导。全程中文界面，角色为虚构人物（二阶堂希罗 / 樱羽艾玛），不含任何真实人物信息。

---

## 目录

1. [项目简介](#1-项目简介)
2. [总体架构](#2-总体架构)
3. [目录结构](#3-目录结构)
4. [快速启动](#4-快速启动)
5. [核心功能与玩法流程](#5-核心功能与玩法流程)
6. [前端模块说明](#6-前端模块说明)
7. [后端架构说明](#7-后端架构说明)
8. [数据库设计](#8-数据库设计)
9. [完整 API 文档](#9-完整-api-文档)
10. [教学剧本 JSON 结构](#10-教学剧本-json-结构)
11. [AI 提示词与角色设定](#11-ai-提示词与角色设定)
12. [判题规则说明](#12-判题规则说明)
13. [讲师一对一辅导（SSE 流式）](#13-讲师一对一辅导sse-流式)
14. [环境与配置](#14-环境与配置)
15. [预留模块与已知边界](#15-预留模块与已知边界)
16. [常见问题](#16-常见问题)

---

## 1. 项目简介

**AI 视觉小说学习 1.0** 是一个"把文档变成互动小说"的演示级学习系统，核心流程：

```
上传学习资料(Word/PDF) → AI 解析正文 → 生成分章教学剧本 → 双人对话播放
       → 剧情推进中弹题作答 → AI 判题讲评 → 召唤讲师一对一辅导
       → 自动/手动存档 → 随时“继续学习”
```

**技术栈**

| 层 | 技术 |
|---|---|
| 前端 | 原生 HTML / CSS / JavaScript（无框架，静态资源由 http.server 托管） |
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

---

## 2. 总体架构

前后端分离，均为本机单机部署：

```
┌───────────────────────────── Browser ─────────────────────────────┐
│  index.html (8 个 JS 模块 + 2 个 CSS)                              │
│  config → api → modes → typing → render → streaming → lecture →  app │
└───────────────┬──────────────────────────────────▲─────────────────┘
                │ ① 静态页面 (http://localhost:8080)│
                │ ② REST/SSE (http://127.0.0.1:8000)│
┌───────────────▼──────────────────────────────────┴─────────────────┐
│  前端静态服务  python -m http.server 8080                           │
│  后端服务      python -m uvicorn backend.main:app --port 8000       │
│                ├── routers: documents / scripts / progress /        │
│                │            settings / lecture                      │
│                ├── services: extractor / script_engine /            │
│                │            lecture_service                         │
│                └── db: SQLite (backend/learning.db)                 │
└─────────────────────────────────────────────────────────────────────┘
```

**设计原则**

- 前端不直接接触 AI 接口，所有 AI 调用都收敛在后端 services 层。
- 前端仅负责界面渲染与 HTTP 通信（js/api.js 是唯一 HTTP 通信层）。
- 后端只下发语义化标签（表情标签 `talk_emo`、背景 key），图片路径映射全部由前端 `js/config.js` 负责。
- API Key 只落后端数据库，前端永远拿不到完整 Key（只返回掩码）。
- 一键启动脚本 `run_app.py` 自动拉起前后端并打开浏览器。

---

## 3. 目录结构

```
frontend/
├── index.html               # 唯一入口页面（含主菜单/资料库/设置/播放器/弹窗）
├── start.bat                # Windows 一键启动入口（双击运行）
├── run_app.py               # 启动器：检查/拉起后端(8000)+前端(8080)，健康检查通过后开浏览器
├── README.md                # 本文件
├── css/
│   ├── style.css            # 主样式（1364 行）
│   └── animations.css       # 动画样式（92 行）
├── js/
│   ├── config.js            # 全局配置：API 地址、表情图片映射、背景图片映射、角色名
│   ├── api.js               # 唯一 HTTP 通信层（全部 REST + SSE 请求）
│   ├── modes.js             # 播放模式状态（自动播放、打字速度、进度指针）
│   ├── typing.js            # “打字机”逐字显示台词效果
│   ├── render.js            # 画面渲染层（切背景/立绘/对话栏/弹题/存档列表/toast）
│   ├── streaming.js         # 播放器状态机（剧本逐句驱动核心）
│   ├── lecture.js           # 讲师一对一辅导模式
│   ├── login.js             # 模拟登录模块（*预留，当前页面未接入*）
│   ├── history.js           # 对话/测验历史模块（*预留，当前页面未接入*）
│   └── app.js               # 入口与全局事件绑定、屏幕切换
├── images/
│   ├── 背景/                # 6 张剧情背景图（客厅/河流树木/破旧房间/紫色河流树木/草地/走廊）
│   ├── 讲述者/              # 希罗 6 种表情立绘
│   ├── 提问者/              # 艾玛 7 种表情立绘
│   ├── 讲师/                # 讲师 5 种表情立绘
│   ├── 用户头像/ 前端背景/ 历史记录头像/   # 头像与菜单背景图
└── backend/
    ├── main.py              # FastAPI 入口：CORS + 路由注册 + 启动建表
    ├── config.py            # 环境配置（数据库地址、默认模型、CORS 白名单）
    ├── db.py                # SQLAlchemy 引擎与会话管理
    ├── models.py            # ORM：Document / Script / Progress / Settings
    ├── schemas.py           # Pydantic 请求/响应模型（剧本结构、进度、设置、文档）
    ├── requirements.txt     # 后端依赖清单
    ├── .env.example         # 环境变量示例
    ├── learning.db          # SQLite 数据库（自动生成）
    ├── routers/
    │   ├── documents.py     # 资料上传/解析/列表/删除
    │   ├── scripts.py       # 剧本生成/详情/章节列表/AI 判题
    │   ├── progress.py      # 进度保存/续播/存档列表/删除
    │   ├── settings.py      # 设置读写（Key 掩码）/连接测试
    │   └── lecture.py       # 讲师 SSE 流式问答/结束会话
    └── services/
        ├── extractor.py     # .docx/.pdf → 纯文本
        ├── script_engine.py # AI 剧本生成引擎 + 判题引擎
        └── lecture_service.py # 讲师流式会话服务（多轮记忆）
```

---

## 4. 快速启动

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
2. 等待后端 `/api/health` 健康检查通过（最长 90 秒）；
3. 检查前端 :8080，否则自动拉起 `python -m http.server 8080`；
4. 自动打开浏览器 `http://localhost:8080`；
5. 按 Ctrl+C 可统一停掉所有子进程。

> 注意：若 8000/8080 端口被其他程序占用，启动器会自动改用 8001+/8081+ 的空闲端口，但 **前端 `js/config.js` 中的 `API_BASE` 写死为 `http://127.0.0.1:8000`**。若遇到"请求失败/加载失败"，请确认后端确实监听在 8000，或同步修改 `API_BASE`。

### 手动分离启动（可选）

```bash
# 终端 1：后端
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000   # 依赖 import 路径时从仓库根目录执行

# 终端 2：前端
python -m http.server 8080
# 浏览器访问 http://localhost:8080
```

### 首次体验路径

```
启动 → 登录遮罩(若已接入) → 主菜单
  →「开始学习」→ 上传或选择资料 →「生成教学剧本」
        → 设置章节数(1~30)、勾选弹题类型(选择/填空/简答)、填写学习背景说明(可选)
  → 剧本生成完成 → 「进入学习」或稍后再学
  → 播放器：双人对话逐句播放 → 每章末尾弹题作答 → 判题讲评 → 下一章
  → 学习中可：保存/读取存档、自动播放、隐藏对话栏、召唤讲师(📖)、返回主菜单
```

---

## 5. 核心功能与玩法流程

### 5.1 主菜单（`#screen-menu`）

| 按钮 | 行为 |
|---|---|
| 开始学习 | 进入「资料库」屏 |
| 继续学习 | 读取最近一次自动进度并直接进入播放器（`GET /api/progress/latest`） |
| 读取存档 | 打开全档列表，按学习资料名标注，任选一份读档 |
| 设置 | 连接设置（API 地址/Key/模型）、显示设置（字体大小）、弹题类型勾选 |
| 退出 | 提示手动关闭浏览器 |

### 5.2 资料库（`#screen-library`）

- **上传并解析**：支持 `.docx` / `.pdf`，上限 20MB；前端直接上传 → 后端解析正文 → 入库。
- **资料列表**：显示标题、文件名、上传时间、正文预览（前 200 字）。有剧本的资料显示「▶ 进入学习」。
- **生成剧本**：选中资料 → 设定章节数（默认 8）→ 可选填「学习背景说明」→ 勾选弹题类型 → 点击生成（可能耗时数十秒）。
- **生成完成弹窗**：`进入学习` 或 `下次再学`（剧本已持久化，稍后仍可从列表进入）。

### 5.3 播放器（`#screen-player`）

- 背景随章节切换（6 张背景图）；角色立绘按台词说话者轮播；下方对话栏"打字机"逐字显示。
- 每句台词都携带「说话者表情」与「倾听者表情」，双向表情联动。
- **推进方式**：点击画面 / 空格键推进；打字中途点击可跳过本句。
- 每完成一个节点自动保存进度到主槽（slot 0）。
- **控制栏**：保存、读取、返回主菜单、历史(占位)、设置、快进(占位)、自动播放、隐藏对话栏。
- **快捷键**：空格 = 下一句（焦点在输入框内时不触发，避免影响正常输入）。

### 5.4 弹题（三种题型）

每章末尾至多 1 道题，`quiz_type` 决定题型：

| 题型 | 作答方式 | 判题方式 |
|---|---|---|
| choice 选择题 | 点选项 | 前端本地比较下标即判错对 |
| fill 填空题 | 文本框输入 | AI 判题（与参考答案同义即正确） |
| short 简答题 | 文本框复述 | AI 判题（覆盖要点 70%~80% 即通过） |

配套交互：
- 「直接查看答案」按钮：AI 判题卡死/超时时仍可看答案继续学习。
- 填空/简答答错满 3 次自动亮出正确答案并继续。
- 「深入学习」按钮：对该题召唤讲师一对一讲解。

### 5.5 存档系统

- **自动存档**：slot 0，每播放完一个节点自动覆盖保存。
- **手动存档**：slot 1~9，播放器中「保存」选择槽位。
- **读取**：主菜单「读取存档」列出全部存档（标注学习资料名），点击即读档。

### 5.6 讲师一对一辅导

- 入口一：播放器右侧「📖 讲师」悬浮按钮（带当前章节上下文）。
- 入口二：弹题框「🔍 深入学习」（带当前题目+讲评上下文）。
- 进入后：讲师立绘单独占屏，底部对话栏变为「一对一辅导面板」，用户可自由提问。
- 后端按 `script_id` 维护多轮会话记忆，讲师"记得上一轮说了什么"。
- 退出（✕ 关闭 / 返回学习）会清空该剧本讲师会话，且返回原弹题/对话续播。

---

## 6. 前端模块说明

以下按 `index.html` 脚本加载顺序说明（均含"use strict"的 IIFE）。

| 模块 | 关键全局 | 职责 |
|---|---|---|
| config.js | `API_BASE`、`TEACHER_EMO_MAP`、`STUDENT_EMO_MAP`、`LECTURER_EMO_MAP`、`BG_MAP`、`ROLE_NAME`、`EMO_MAP`、`LISTEN_FALLBACK` | 全局配置与"标签→图片路径"权威映射 |
| api.js | `Api` | 唯一 HTTP 通信层：所有 REST 请求 + SSE 读取器 |
| modes.js | `Modes` | 播放模式状态：自动播放、打字速度、对话栏显隐、章节/步骤指针 |
| typing.js | `Typing` | 打字机逐字显示，支持跳过/取消/回调 |
| render.js | `Render` | 画面渲染：切背景、立绘 crossfade、对话栏、弹题框、存档槽网格、toast |
| streaming.js | `Streaming` | 播放器状态机：载入剧本、逐节点推进、判题、讲评、自动保存 |
| lecture.js | `Lecture` | 讲师辅导模式：进入/提问(SSE)/退出/静默复位 |
| login.js | `Login` | 模拟登录（任意账号可进）。**预留：index.html 当前未加载此模块** |
| history.js | `History→ window.VNHistory` | 对话/测验历史记录与面板。**预留：index.html 当前未加载** |
| app.js | （IIFE 内部） | 屏幕切换、资料库/生成/设置/播放器全部事件绑定、启动入口 |

> 注意（v1.0 已修复）：`window.History` 是浏览器内置 BOM 接口且不可覆盖，因此历史模块挂载全局对象名为 `window.VNHistory`，`streaming.js` 调用处同步使用 `VNHistory`。若将来在 index.html 接入 history.js，务必保持 `VNHistory` 命名一致。

**前端文件依赖图**（加载顺序即依赖顺序）：

```
config.js → api.js → modes.js → typing.js → render.js → streaming.js → lecture.js → app.js
```

---

## 7. 后端架构说明

### 7.1 路由总览

| Router | 前缀 | 路由数 | 说明 |
|---|---|---|---|
| documents | `/api/documents` | 4 | 资料上传/列表/详情/删除 |
| scripts | `/api/scripts` | 4 | 剧本生成/判题/详情/章节列表 |
| progress | `/api/progress` | 6 | 进度保存/最近/槽位/全档/删除/单剧本 |
| settings | `/api/settings` | 3 | 设置读/写/连接测试 |
| lecture | `/api/lecture` | 2 | 讲师 SSE 问答/结束 |
| main | `/api/health` | 1 | 健康检查 |

### 7.2 核心调用链

**生成剧本**

```
前端 POST /api/scripts/generate
  → routers/scripts.py 校验文档存在、读取 Settings（api_base/key/model）
  → services/script_engine.py generate_script()
      → 读资料前 80000 字符 + 学习背景 + 题型要求 拼 user_prompt
      → _LLMClient 调 DeepSeek（SYSTEM_PROMPT 含双角色卡 + JSON 输出约束）
      → _extract_json 去 markdown 围栏、剥外层花括号定位 JSON
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

**判题**

- 选择题：前端本地比较下标（后端 `/api/scripts/answer` 也提供兜底）。
- 填空/简答：前端 `POST /api/scripts/answer` → `judge_answer()` 用短超时/小 token 调 AI。

**讲师 SSE**

```
前端 POST /api/lecture/chat
  → lecture_service.chat_stream() 流式拆段
  → 每段 yield {talk_emo, text} → router 拼 SSE "data: ..." 
  → 流结束 "data: [DONE]"
前端 POST /api/lecture/end → 清空该剧本会话记忆
```

### 7.3 安全与健壮性设计

- AI 调用全部收敛到后端，前端永远不持有 API Key。
- 无 API Key 时生成剧本**直接拒绝并报错**，不静默降级为样例。
- JSON 解析失败（最常因输出被 max_tokens 截断）自动重试并提示压缩；重试仍失败则抛结构化错误。
- 数据库路径锚定 `backend/learning.db`，不随启动目录变化；同时预留 PostgreSQL 路径（设置 `DATABASE_URL`）。
- 上传文件先识别扩展名，仅 `.docx/.pdf` 可上传；依赖缺失时给出明确的 pip 安装提示。
- 判题失败保守处理：不判通过，返回可读提示。
- 进度保存失败静默吞掉，不阻断播放体验。

---

## 8. 数据库设计

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
| created_at | DateTime | 创建时间 |

### progress —— 学习进度 / 存档

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 自增主键 |
| script_id | FK → scripts.id（带索引） | 所属剧本 |
| slot | Integer（索引） | 0=自动档，1~9=手动档 |
| chapter_index | Integer | 章节下标 |
| step_index | Integer | 步骤下标 |
| updated_at | DateTime | 最近更新时间（同槽覆盖式更新） |

### settings —— 系统配置（单行表，id 恒为 1）

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | 恒为 1 |
| api_base | String(255) | 默认 `https://api.siliconflow.cn/v1` |
| api_key | String(255) | 只落后端，仅返回掩码 |
| model | String(100) | 默认 `deepseek-ai/DeepSeek-V3` |
| updated_at | DateTime | 更新时间 |

---

## 9. 完整 API 文档

> 服务地址：`http://127.0.0.1:8000`。除特殊标注外，请求与响应均为 JSON（utf-8）。错误响应格式统一为 `{"detail": "错误信息"}`。所有路由带路由前缀，CORS 默认放开（`*`）。

### 9.1 健康检查

#### GET `/api/health`

启动器靠它判断后端是否就绪。

响应示例：

```json
{"status": "ok"}
```

---

### 9.2 学习资料（documents）

#### POST `/api/documents` — 上传并解析学习资料

- 请求类型：`multipart/form-data`，字段 `file`
- 支持：`.docx`、`.pdf`（上限 20MB）
- 状态码：201

请求示例（curl）：

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
  -F "file=@操作系统原理.docx"
```

响应（DocumentOut）：

```json
{
  "id": 3,
  "filename": "操作系统原理.docx",
  "title": "操作系统原理",
  "content_preview": "操作系统原理\n一、操作系统概述\n1.操作系统\n（1）概念：……",
  "created_at": "2026-08-30T07:47:49.657274",
  "has_script": false,
  "latest_script_id": null
}
```

字段说明：
- `content_preview`：正文前 200 字（不整篇回传）。
- `has_script`：是否已生成过剧本；`latest_script_id`：最近一份剧本 ID（前端据此显示「进入学习」）。

错误：`400` 解析失败/不支持类型/无文本；`413` 文件过大。

#### GET `/api/documents` — 资料列表

响应：`DocumentOut[]`，按 `created_at` 倒序。

```json
[
  {
    "id": 3,
    "filename": "操作系统原理.docx",
    "title": "操作系统原理",
    "content_preview": "操作系统原理\n一、……",
    "created_at": "2026-08-30T07:47:49.657274",
    "has_script": true,
    "latest_script_id": 2
  }
]
```

#### GET `/api/documents/{doc_id}` — 资料详情

响应：单个 `DocumentOut`。 `404`：文档不存在。

#### DELETE `/api/documents/{doc_id}` — 删除资料

- 状态码：204（无响应体）
- 说明：级联删除关联剧本及其进度（瀑布式清理）。
- `404`：文档不存在。

---

### 9.3 教学剧本（scripts）

#### POST `/api/scripts/generate` — 生成教学剧本

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

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| document_id | int | 是 | 目标资料 ID |
| title | string | 否 | 剧本标题，缺省用资料标题/文件名 |
| chapter_count | int | 否 | 1~30，默认 8；仅作为"不少于 N 章"的下限约束 |
| learning_goal | string | 否 | 学习背景说明（仅作上下文增强，不改剧本规则） |
| quiz_types | string[] | 否 | `["choice"]`；可选 `choice/fill/short`，决定每章末尾题型 |

响应（ScriptGenerateOut，含落库后的完整剧本）：

```json
{
  "script_id": 12,
  "script": {
    "title": "计算机四级（精简版）",
    "source": "操作系统原理.docx",
    "chapters": [ ... ]
  }
}
```

错误：`404` 文档不存在；`400` 无 API Key / AI 生成连续失败。

**内部机制**：无 Key 直接拒绝；资料取前 80000 字符；成功前最多重试 3 次；JSON 未闭合/坏结构自动以更精炼的输出重试。

#### POST `/api/scripts/answer` — 判题（填空/简答交 AI，选择走本地兜底）

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

响应（AnswerOut）：

```json
{
  "correct": true,
  "explain": "作答与参考答案意思一致，判定正确。",
  "message": "AI 判题"
}
```

行为说明：
- `quiz_type=choice`：后端仅作兜底比较（`picked_index == node.answer`），前端本地已判。
- `quiz_type=fill`：从资料前 6000 字中锚定答案，AI 判断与 `answer_text` 是否同义。
- `quiz_type=short`：按 `reference_points` 判定复述覆盖率 70%~80%。
- `message`：`AI 判题` 或 `选择题本地判定`。
- `404`：剧本/章节/步骤索引越界或不存在。

#### GET `/api/scripts/{script_id}` — 剧本详情

响应（ScriptDetailOut）：

```json
{
  "script_id": 12,
  "document_id": 3,
  "title": "计算机四级（精简版）",
  "source": "操作系统原理.docx",
  "chapters": [ ... ]
}
```

`404`：剧本不存在。这是「进入学习」/「继续学习」读取剧本的主接口。

#### GET `/api/scripts/{script_id}/list` — 章节列表

响应：

```json
{
  "script_id": 12,
  "chapters": [
    { "index": 0, "id": "ch_1", "title": "操作系统概述", "background": "客厅" }
  ]
}
```

`404`：剧本不存在。

---

### 9.4 学习进度（progress）

#### POST `/api/progress/save` — 保存进度

请求（ProgressSaveIn）：

```json
{ "script_id": 12, "chapter_index": 1, "step_index": 3, "slot": 0 }
```

- `slot`：0（自动档）或 1~9（手动档）；同槽位同剧本只保留一份（覆盖更新）。

响应（ProgressOut）：

```json
{
  "script_id": 12,
  "slot": 0,
  "chapter_index": 1,
  "step_index": 3,
  "updated_at": "2026-08-30T09:12:00.123456"
}
```

`404`：剧本不存在。

#### GET `/api/progress/latest` — 最近一次进度

响应：

```json
{
  "exists": true,
  "script_id": 12,
  "slot": 0,
  "chapter_index": 1,
  "step_index": 3,
  "title": "计算机四级（精简版）",
  "background": "走廊",
  "updated_at": "2026-08-30T09:12:00.123456"
}
```

`exists=false`：尚无任何进度记录（"继续学习"空态）。

#### GET `/api/progress/slots/{script_id}` — 某剧本的全部存档槽

响应：

```json
{
  "script_id": 12,
  "slots": [
    { "script_id": 12, "slot": 0, "chapter_index": 1, "step_index": 3, "updated_at": "..." }
  ]
}
```

#### GET `/api/progress/list` — 全部存档（含资料名，供主菜单读取存档）

响应（`ArchiveOut[]`，按更新时间倒序）：

```json
[
  {
    "script_id": 12,
    "slot": 0,
    "chapter_index": 1,
    "step_index": 3,
    "updated_at": "2026-08-30T09:12:00.123456",
    "document_title": "操作系统原理"
  }
]
```

`document_title` 回退到剧本 `source`。

#### DELETE `/api/progress/{script_id}/{slot}` — 删除某剧本某个存档槽

响应：

```json
{ "deleted": 1 }
```

#### GET `/api/progress/{script_id}` — 某剧本最近一次进度（续播）

响应（ProgressOut）；无记录时返回空档（`chapter_index/step_index` 为 0，`updated_at` 为空串）。

---

### 9.5 设置（settings）

#### GET `/api/settings` — 读取设置

响应（SettingsOut）：

```json
{
  "api_base": "https://api.siliconflow.cn/v1",
  "model": "deepseek-ai/DeepSeek-V3",
  "api_key_set": true,
  "key_masked": "sk-****abcd",
  "updated_at": "2026-08-30T09:00:00.123456"
}
```

- 前端只拿到 `api_key_set` 与 `key_masked`（掩码），拿不到 Key 本体。

#### PUT `/api/settings` — 更新设置

请求（SettingsIn）：

```json
{ "api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-xxx", "model": "deepseek-ai/DeepSeek-V3" }
```

- 字段留空则保持数据库旧值（Key 留空不变更，避免误清空）。

响应：同 `GET /api/settings`。

#### POST `/api/settings/test` — 连接测试

请求（SettingsIn，可整体省略直接测已存配置）：

```json
{ "api_base": "", "api_key": "", "model": "" }
```

响应（TestResult）：

```json
{ "success": true, "message": "连接成功，SiliconFlow 已响应。" }
```

- 无 Key：`success=false`，提示先填 Key。
- 后端实际发一次 `chat/completions` 验证连通性。

---

### 9.6 讲师一对一辅导（lecture，SSE 流式）

#### POST `/api/lecture/chat` — 讲师流式问答

请求（LectureChatIn）：

```json
{
  "script_id": 12,
  "question": "内存管理和进程管理有什么区别？",
  "context": "当前章节：进程管理\n当前题目：下列哪项不是进程的特点？\n讲评：……"
}
```

- `question`：用户提问（必填，非空）。
- `context`：可选，前端拼好的当前上下文（章节/题目/讲评），帮助讲师定位疑难。

响应：`text/event-stream`（SSE）。逐段推送：

```
data: {"talk_emo": "jiangjie", "text": "打个比方来说，内存管理管的是“空间”……"}
data: {"talk_emo": "yansutixing", "text": "关键在于，这里的重点是……"}

data: [DONE]
```

- 每段含 `talk_emo`（讲师表情标签：`jiangjie/kaixin/sikao/yansutixing/shengqi`）与 `text` 片段，前端实时换立绘并追加气泡。
- 多轮记忆：会话历史按 `script_id` 在进程内维护，只保留最近 12 轮，首轮注入资料前 6000 字。
- 异常兜底：流中断时后端仍会推一条可辨认的提示段 + `[DONE]`。
- 错误：`400` 无 API Key / 提问为空；`404` 剧本不存在。

#### POST `/api/lecture/end` — 结束讲师会话

请求（LectureEndIn）：

```json
{ "script_id": 12 }
```

响应：

```json
{ "ok": true }
```

说明：清空该剧本的讲师会话记忆，下次进入为全新对话（会话是一次性的，不留脏数据）。

---

## 10. 教学剧本 JSON 结构

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

- `speaker`：`teacher`（希罗）或 `student`（艾玛）。
- `talk_emo`：说话者表情标签；`listen_emo`：倾听者表情标签（双向表情联动）。

**question（弹题）**

选择：

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

填空：

```json
{
  "type": "question",
  "speaker": "teacher",
  "text": "进程是程序的一次______活动。",
  "quiz_type": "fill",
  "answer_text": "运行",
  "explain": "进程是程序关于数据集合的一次运行活动。"
}
```

简答：

```json
{
  "type": "question",
  "speaker": "teacher",
  "text": "请用自己的话复述操作系统的四大功能。",
  "quiz_type": "short",
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

## 11. AI 提示词与角色设定

### 11.1 角色卡（`script_engine.py` 中定义）

**二阶堂希罗（讲述者/老师）**：完美优等生设定，认真知礼、追求"正确"，说话冷静干脆、条理清晰。不得互相用"老师/学生"称呼，一律用名字。

**樱羽艾玛（提问者/学生）**：外表开朗、内心怕寂寞，说话带男孩气的可爱感；平时笨手笨脚，关键时刻冷静准确。习惯用"诶？""原来是这样！"等感叹词。

### 11.2 SYSTEM_PROMPT 核心约束（生成剧本）

- 每句对话携带 `talk_emo` + `listen_emo`，永远有人说话、有人配合。
- 按逻辑知识点拆章节：**每章节一个知识点**，内容长则多分章（默认 10~20+ 章），每章围绕该知识点讲透（6~8 句）。
- 资料中所有知识点必须全部覆盖，宁多勿少。
- **每讲解完一个知识点后，才在章节最后一个步骤弹 1 道题**；每章至多 1 题，不中途频繁抛题。
- 题型：choice 带 `choices+answer`；fill 带 `answer_text`；short 带 `reference_points`。
- 输出仅 JSON，无 markdown 围栏/注释；台词尽量精炼（每句 ≤40 字）防截断。
- `学习背景（learning_goal）`仅增强讲解侧重点，不改变结构规则；`quiz_types` 让题型在勾选集合中轮换。

### 11.3 JSON 健壮解析（`_extract_json`）

剥 markdown 代码围栏（含"只有开围栏"的截断形态）→ 定位最外层 `{}` → 校验闭合；未闭合判定输出截断并触发重试。

### 11.4 判题提示词（GRADING_PROMPT）

- 填空题：与 `answer_text` 意思一致即正确（允许同义替换）。
- 简答题：必须复述出 `reference_points` 至少 70%~80%。
- 只依据用户资料（source 前 6000 字）判定。
- 输出 `{"correct": bool, "explain": "…", "keywords": ["…"]}`；前端讲评里会展示命中关键词。
- **已知坑（已修复）**：GRADING_PROMPT 含 JSON 示例花括号，占位符填充必须用 `str.replace` 逐词替换，不能用 `.format()`，否则把花括号当嵌套替换字段抛 KeyError。

---

## 12. 判题规则说明

| 场景 | 规则 |
|---|---|
| 选择题 | 前端本地 `picked == answer` 即判；后端 `/api/scripts/answer` 提供兜底 |
| 填空题 | AI 判题：与参考答案同义即可，允许多种表达 |
| 简答题 | AI 判题：复述覆盖参考要点 70%~80% 通过 |
| 判题失败 | 保守处理：不算通过，提示"AI 判题出错，请重新作答或核对答案" |
| 答错重试 | 填空/简答答错计数（sessionStorage 按剧本+位置），满 3 次自动亮答案并继续 |
| 直接查看答案 | `q-peek-answer`：不依赖 AI，本地亮答案，判题卡死也可继续学习 |

---

## 13. 讲师一对一辅导（SSE 流式）

### 13.1 前端接入（lecture.js）

```
用户点「📖 讲师」(fab) 或「🔍 深入学习」(question)
  → Lecture.enter(enterFrom, context)
      → 立绘切到讲师占屏、底部对话栏变辅导面板、弹题框收起
  → 用户输入问题 → Lecture.ask()
      → Api.lectureChat(script_id, question, context, onEvent)  // SSE
      → onEvent({talk_emo, text}) → Render.showLecturer(emo) + 气泡追加文本
  → "✕ 关闭"/"返回学习" → Lecture.end()
      → POST /api/lecture/end 清会话
      → 恢复双人立绘；若从弹题进入则用 Streaming._playQuestion 重放原题
```

### 13.2 后端流式切段（lecture_service.chat_stream）

- 模型每段先吐 `【表情:xxx】` 标签 → 后端流式过程中识别完整标签切段 → 输出 `{talk_emo, text}`。
- 漏标兜底：连续正文 >220 字时按段落边界（`\n\n`）切。
- 历史记忆：`{script_id: [{"role","content"}, ...]}` 进程内维护，只留最近 12 轮；首轮注入资料前 6000 字，后续轮不再重复注入。
- 退出（`/api/lecture/end`）或进程重启即清空——会话一次性，不留脏数据。

### 13.3 SSE 数据流示例

```
data: {"talk_emo": "kaixin", "text": "你问的这个问题很好，我们一步步拆开看。"}

data: {"talk_emo": "jiangjie", "text": "内存管理面向“空间”……"}

data: [DONE]
```

---

## 14. 环境与配置

### 14.1 后端依赖（`backend/requirements.txt`）

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

> langchain 未安装时，代码会自动回退 `requests` 直连（含流式），不阻塞运行。

### 14.2 环境变量（`.env`，参考 `.env.example`）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 留空=本地 SQLite；接 PostgreSQL 时填写连接串 |
| `CORS_ORIGINS` | CORS 白名单，默认 `*` |
| `DEFAULT_MODEL` | 默认模型兜底（设置界面可改） |

### 14.3 API 配置（设置界面，落库 `settings` 表）

- API 地址默认 `https://api.siliconflow.cn/v1`（硅基流动中转站）。
- API Key：只在后端保存；前端只见掩码。生成剧本/判题/讲师必须配置。
- 默认模型 `deepseek-ai/DeepSeek-V3`。

### 14.4 端口

| 服务 | 端口 |
|---|---|
| 后端 FastAPI | 8000（写死在 `js/config.js` 的 `API_BASE`） |
| 前端静态 | 8080 |

---

## 15. 预留模块与已知边界

**v1.0 明确标注：**

| 模块 | 状态 | 说明 |
|---|---|---|
| `js/login.js`（模拟登录遮罩） | 预留，未接入 | index.html 当前未加载该脚本，也无 `#login-overlay` 等 DOM。若接入，注意播放器空格推进逻辑已做判空守卫（见下）。 |
| `js/history.js`（对话/测验历史面板） | 预留，未接入 | index.html 当前未加载；播放器「历史」按钮为占位（提示"开发中"）。模块全局对象名为 `window.VNHistory`（避开浏览器内置 History）。接入时需引入对应弹窗 HTML 并保持命名一致。 |
| 播放器「快进」按钮 | 占位 | 提示"开发中"。 |

**已知边界与避坑（v1.0 已修复历史问题）：**

1. **`window.History` 陷阱**：浏览器内置 `History` 接口不可覆盖，`history.js` 须挂 `window.VNHistory`，`streaming.js` 调用用 `VNHistory.addDialogue/VNHistory.addQuiz`。曾因在真实浏览器中取到内置 History 而报 `History.addDialogue is not a function`，导致「进入学习」加载剧本失败。
2. **`#login-overlay` 判空守卫**：播放器空格推进、点击推进中对 `#login-overlay` 均先判空（`const loginEl = $("login-overlay"); if (loginEl && ...)`），避免 HTML 中不存在该节点时 TypeError 卡死播放。
3. **GRADING_PROMPT 用 `str.replace`**：判题提示词含 JSON 花括号，不能用 `.format()`。
4. **LangChain 模板花括号坑**：SYSTEM_PROMPT 含合法 JSON 花括号，不能用 `ChatPromptTemplate` 做 f-string 模板解析，改为手工组装 `SystemMessage/HumanMessage`。
5. **端口被占用时**：启动器会改用空闲端口，但前端 `API_BASE` 写死 8000，需同步修改。

---

## 16. 常见问题

**Q：点「进入学习」提示"剧本加载失败：Failed to fetch / NetworkError"？**
A：多为浏览器连不上后端。确认后端健康（`curl http://127.0.0.1:8000/api/health`）；若后端在 8001+（8000 被占），同步修改 `js/config.js` 的 `API_BASE`。另可用 Ctrl+F5 强刷清除缓存旧 JS。

**Q：提示"剧本加载失败：History.addDialogue is not a function"？**
A：旧版本命名冲突问题，v1.0 已修复为 `VNHistory`。强刷（Ctrl+F5）后重试。

**Q：生成剧本很慢/一直重试？**
A：AI 生成可能耗时数十秒；JSON 解析失败会自动重试 3 次。若最终失败：检查 API Key、网络、SiliconFlow 服务可用性。

**Q：填空/简答判题卡死？**
A：点「直接查看答案」可绕过判题继续学习；判题请求走短超时（100s）与 512 token，正常很快。

**Q：如何接入 PostgreSQL？**
A：安装 `psycopg2-binary`，在 `.env` 配置 `DATABASE_URL=postgresql://...`。当前 SQLite 演示零配置。

**Q：能改 AI 服务商或模型吗？**
A：设置界面即可（API 地址/Key/模型）。默认 SiliconFlow 中转站的 DeepSeek。

---

*本文档为 AI 视觉小说学习 1.0 的完整项目说明。接口清单即「9. 完整 API 文档」，前端行为即「5. 核心功能与玩法流程」。*