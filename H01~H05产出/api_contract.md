# Tilt 前端接口契约（H02）

> 适用对象：4 个静态原型页 `01_questionnaire.html` / `02_report.html` / `03_dailytask.html` / `04_domains.html` 改造为真实 H5 时的后端接口定义。
> 本文件**只定义契约，不含任何前端实现代码**。字段值一律取自第 3 节冻结事实源（SSOT）。

---

## 0 · 通用约定

### 0.1 基础路径与协议

- 基础路径：`/api/v1`
- Base URL（域名）由部署环境注入，**待定**
- 协议：HTTPS；请求/响应编码 UTF-8，`Content-Type: application/json`

### 0.2 鉴权方式

- 方式：**待定：Bearer Token（JWT）**
- 用法：所有请求在 Header 携带 `Authorization: Bearer <token>`
- token 的获取途径（宿主环境注入 / 独立登录接口）**待定**，需与需求方及 C12c 数据库侧对齐
- token 失效时服务端返回 `401 UNAUTHORIZED`，前端引导用户重新获取登录态，不向用户暴露报错细节

### 0.3 时间与 ID 约定

- 时间字段一律 ISO 8601 UTC，形如 `2026-09-21T10:30:00Z`
- `user_id` / `session_id` / `event_id` 为 uuid 字符串
- `task_id` 遵循 3.7 命名规范：`{domain_id}_L{level}_{三位序号}`
- 领域标识字段统一命名为 `domain`，取值必须命中 3.1 的 50 个 ID 白名单

### 0.4 数值量纲说明

SPEC 未在本文档给定 5 维客观指标、进步斜率、客观水平等的归一化区间。本契约的示例值暂按与 `objective_score`（SPEC 4.2 示例值 72.5）一致的量纲书写；最终区间以 C12c 数据库 schema 为准（**待定**）。

### 0.5 统一错误响应结构

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：domain 不在白名单内",
    "request_id": "uuid"
  }
}
```

### 0.6 错误码表

| HTTP | code | 含义 | 前端建议处理 |
|---|---|---|---|
| 400 | `INVALID_PARAMETER` | 参数错误（字段缺失 / 格式非法 / 枚举越界） | 提示"信息没填对"，引导重试 |
| 401 | `UNAUTHORIZED` | 未授权 / token 失效 | 引导重新获取登录态 |
| 403 | `FORBIDDEN` | 无访问权限 | 提示暂无权限 |
| 404 | `NOT_FOUND` | 资源不存在 | 展示空态 |
| 429 | `RATE_LIMITED` | 请求过频 | 稍后重试 |
| 500 | `INTERNAL_ERROR` | 服务错误 | 展示错误态 + 重试入口 |

---

## 1 · 页面 01 · Day 0 坐标系问卷（`01_questionnaire.html`）

### 1.0 接口清单

| # | 方法 | 路径 | 用途 | 必需 / 增补 |
|---|---|---|---|---|
| 1.1 | GET | `/api/v1/questionnaire/questions` | 拉取 18 题题目与选项 | 必需 |
| 1.2 | POST | `/api/v1/questionnaire/answers` | 提交答案，返回 6 维坐标系结果 | 必需 |
| 1.3 | GET | `/api/v1/coordinate` | 查询当前用户已算出的坐标系（刷新 / 重进恢复） | 增补 |

### 1.1 GET `/api/v1/questionnaire/questions`

**用途：** 拉取 18 题（分 6 组，每组对应一个坐标系维度）的题目文案与选项，用于渲染问卷、进度条与选项列表。每题携带 `allow_unknown` 开关，对应原型中的"我不知道"选项。

**请求：** GET 无请求体。可选 query `questionnaire_version`（默认 `v1`）。

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `questionnaire_version` | string | 问卷版本 |
| `total` | int | 题目总数（18） |
| `questions` | array | 题目列表 |
| `questions[].question_id` | string | 题目 ID |
| `questions[].group_index` | int | 分组序号 1-6，对应 6 个维度 |
| `questions[].dimension` | string | 所属坐标系维度，字段名取自 3.4 |
| `questions[].text` | string | 题目文案（中文，引导性表述） |
| `questions[].options` | array | 选项列表 |
| `questions[].options[].option_id` | string | 选项值，取自该 `dimension` 在 3.4 的冻结枚举 |
| `questions[].options[].text` | string | 选项文案（中文） |
| `questions[].allow_unknown` | bool | 是否提供"我不知道" |

**成功响应 200（节选 2 题示意，实际返回 18 题）：**

```json
{
  "questionnaire_version": "v1",
  "total": 18,
  "questions": [
    {
      "question_id": "q01",
      "group_index": 1,
      "dimension": "cognitive_style",
      "text": "接触一个全新领域时，你最容易进入状态的方式是？",
      "options": [
        {"option_id": "visual", "text": "看图、看演示"},
        {"option_id": "auditory", "text": "听讲解、和人讨论"},
        {"option_id": "textual", "text": "读文字材料"},
        {"option_id": "logical", "text": "先理清结构和原理"},
        {"option_id": "bodily", "text": "直接上手做一遍"}
      ],
      "allow_unknown": true
    },
    {
      "question_id": "q07",
      "group_index": 3,
      "dimension": "feedback_speed",
      "text": "做一件事时，你更愿意多久看到一次回响？",
      "options": [
        {"option_id": "short", "text": "几小时内就能知道做得怎么样"},
        {"option_id": "long", "text": "几周甚至几个月后的结果也算数"}
      ],
      "allow_unknown": true
    }
  ]
}
```

> 题目文案为示例，实际文案由内容侧提供；`option_id` 必须取自 3.4 冻结枚举，`feedback_speed` 维度按 SPEC 2.2 只给 `short` / `long` 两档。

**失败响应 401：**

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "登录态已失效，请重新进入",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 401、500

### 1.2 POST `/api/v1/questionnaire/answers`

**用途：** 提交 18 题答案；服务端计算并返回 6 维坐标系结果，供末屏 Chart.js 雷达图渲染。

**请求 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `questionnaire_version` | string | 问卷版本 |
| `answers` | array | 18 条答案 |
| `answers[].question_id` | string | 题目 ID |
| `answers[].option_id` | string \| null | 所选选项值，取自 3.4 枚举；`null` 表示用户选了"我不知道" |

**请求示例：**

```json
{
  "questionnaire_version": "v1",
  "answers": [
    {"question_id": "q01", "option_id": "logical"},
    {"question_id": "q02", "option_id": "solitude"},
    {"question_id": "q03", "option_id": null}
  ]
}
```

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID |
| `coordinate` | object | 6 维坐标系结果，字段名取自 3.4 |
| `coordinate.cognitive_style` | string | `visual` / `auditory` / `textual` / `logical` / `bodily` |
| `coordinate.energy_source` | string | `solitude` / `social` / `competition` / `collaboration` |
| `coordinate.feedback_speed` | string | `short` / `long` |
| `coordinate.value_orientation` | string | `creation` / `helping` / `influence` / `money` / `aesthetics` |
| `coordinate.risk_attitude` | string | `conservative` / `neutral` / `aggressive` |
| `coordinate.abstraction_level` | string | `theory` / `application` / `operation` |
| `computed_at` | string | 计算时间，ISO 8601 |

**成功响应 200：**

```json
{
  "user_id": "uuid",
  "coordinate": {
    "cognitive_style": "logical",
    "energy_source": "solitude",
    "feedback_speed": "short",
    "value_orientation": "creation",
    "risk_attitude": "neutral",
    "abstraction_level": "theory"
  },
  "computed_at": "2026-09-21T10:30:00Z"
}
```

> **雷达图取值说明：** 6 维雷达的每个轴由该维度选项在 3.4 冻结枚举中的序号归一化得到。服务端只返回枚举值，序号映射由前端按题目接口返回的 `options` 顺序完成——避免在契约中引入 SPEC 之外的分数字段。

**失败响应 400：**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：question_id q99 不属于 questionnaire_version v1",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、500

### 1.3 GET `/api/v1/coordinate`（增补）

**增补理由：** 问卷完成后用户刷新或重新进入 H5 时，应能恢复已算出的坐标系，不必重答 18 题；02 报告页引用坐标系时也可复用此接口。原始必需清单未包含，此处补齐。

**请求：** GET 无请求体。

**响应 schema：** 与 1.2 的 `coordinate` 部分一致（`user_id` / `coordinate` / `computed_at`）。

**成功响应 200：**

```json
{
  "user_id": "uuid",
  "coordinate": {
    "cognitive_style": "logical",
    "energy_source": "solitude",
    "feedback_speed": "short",
    "value_orientation": "creation",
    "risk_attitude": "neutral",
    "abstraction_level": "theory"
  },
  "computed_at": "2026-09-21T10:30:00Z"
}
```

**失败响应 404（尚未完成问卷）：**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "还没有你的坐标系结果，先完成 18 题试试",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 401、404、500

### 1.4 页面 01 加载时序

1. 进入页面 → **并行**发起 `GET /api/v1/questionnaire/questions` 与 `GET /api/v1/coordinate`
2. 若 `GET /api/v1/coordinate` 返回结果：直接跳到末屏，用 `coordinate` 渲染 6 维雷达图（已答过）
3. 若返回 404：渲染问卷；用户逐题作答（前端可用 localStorage 暂存，支持离线作答与返回上一题）
4. 18 题完成 → `POST /api/v1/questionnaire/answers`，拿回 `coordinate`
5. 用 `coordinate` 渲染 6 维雷达图

**依赖关系：** `GET questions` 与 `GET coordinate` 可并行；`POST answers` 必须在 18 题全部作答后发起；雷达图渲染依赖 `POST answers` 或 `GET coordinate` 的返回。

---

## 2 · 页面 02 · 4 周报告（`02_report.html`）

### 2.0 接口清单

| # | 方法 | 路径 | 用途 | 必需 / 增补 |
|---|---|---|---|---|
| 2.1 | GET | `/api/v1/report/overview` | 拉取 4 周报告总览：跨领域对比卡片 + 各领域进步斜率 | 必需 |
| 2.2 | GET | `/api/v1/report/domains/{domain_id}` | 拉取单领域明细：水平-时间曲线 + 5 维客观指标雷达 | 必需 |

> **拆分说明：** 需求的最小清单是"拉取 4 周报告"一个接口。此处拆为"总览 + 单领域明细"两个，原因是报告数据量随领域数（3-5 个）线性增长，拆分后首屏可先渲染跨领域对比卡片，再并行加载各领域曲线与雷达，避免单次响应过大拖慢首屏。

### 2.1 GET `/api/v1/report/overview`

**用途：** 拉取某用户的 4 周报告总览，渲染跨领域对比卡片与各领域进步斜率。

**请求：** GET 无请求体。

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID |
| `cycle_start` | string | 周期开始日期 |
| `cycle_end` | string | 周期结束日期 |
| `week_count` | int | 周数（4） |
| `domains` | array | 用户投入的 3-5 个领域 |
| `domains[].domain` | string | 领域 ID，取自 3.1 白名单 |
| `domains[].domain_name` | string | 领域中文名，取自 3.1 |
| `domains[].progress_slope` | number | 进步斜率（产品核心输出） |
| `domains[].current_level` | int | 当前任务等级，MVP 阶段 1-5 |
| `domains[].objective_score` | number | 客观水平，字段名对齐 SPEC 4.2 |
| `domains[].session_count` | int | 周期内完成任务次数 |

**成功响应 200：**

```json
{
  "user_id": "uuid",
  "cycle_start": "2026-08-24",
  "cycle_end": "2026-09-20",
  "week_count": 4,
  "domains": [
    {
      "domain": "writing_general",
      "domain_name": "写作（通用）",
      "progress_slope": 0.42,
      "current_level": 3,
      "objective_score": 72.5,
      "session_count": 24
    },
    {
      "domain": "go",
      "domain_name": "围棋",
      "progress_slope": 0.31,
      "current_level": 3,
      "objective_score": 65.0,
      "session_count": 22
    },
    {
      "domain": "photography",
      "domain_name": "摄影",
      "progress_slope": 0.55,
      "current_level": 4,
      "objective_score": 78.0,
      "session_count": 26
    }
  ]
}
```

**失败响应 404（周期未满 / 无数据）：**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "还没有你的 4 周记录，先把这几天过完再看",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 401、404、500

### 2.2 GET `/api/v1/report/domains/{domain_id}`

**用途：** 拉取单个领域的 4 周明细，渲染水平-时间曲线（Chart.js 折线）与 5 维客观指标雷达图。

**路径参数：** `domain_id` 必须命中 3.1 的 50 个 ID 白名单。

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID |
| `domain` | string | 领域 ID |
| `domain_name` | string | 领域中文名 |
| `level_curve` | array | 水平-时间曲线数据点 |
| `level_curve[].date` | string | 采样日期 |
| `level_curve[].week_index` | int | 周序号 1-4 |
| `level_curve[].objective_level` | number | 客观水平 |
| `objective_metrics` | object | 5 维客观指标，**字段名固定**见 3.5 |
| `objective_metrics.bounce_back` | number | 挫败后反弹力 |
| `objective_metrics.repetition` | number | 重复意愿 |
| `objective_metrics.detail_sensitivity` | number | 细节敏感度 |
| `objective_metrics.proactive_optimization` | number | 主动优化倾向 |
| `objective_metrics.pain_tolerance` | number | 痛苦耐受度 |
| `progress_slope` | number | 该领域进步斜率 |

**成功响应 200：**

```json
{
  "user_id": "uuid",
  "domain": "writing_general",
  "domain_name": "写作（通用）",
  "level_curve": [
    {"date": "2026-08-24", "week_index": 1, "objective_level": 1.2},
    {"date": "2026-08-31", "week_index": 2, "objective_level": 1.8},
    {"date": "2026-09-07", "week_index": 3, "objective_level": 2.4},
    {"date": "2026-09-14", "week_index": 4, "objective_level": 3.1}
  ],
  "objective_metrics": {
    "bounce_back": 62.0,
    "repetition": 71.5,
    "detail_sensitivity": 55.0,
    "proactive_optimization": 48.5,
    "pain_tolerance": 66.0
  },
  "progress_slope": 0.42
}
```

**失败响应 400（领域 ID 越界）：**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：domain xyz 不在领域白名单内",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、404、500

### 2.3 页面 02 加载时序

1. `GET /api/v1/report/overview` → 渲染跨领域对比卡片与领域切换
2. 依据 `overview` 返回的 `domains` 列表，**并行**发起 `GET /api/v1/report/domains/{domain_id}`，渲染水平-时间曲线与 5 维雷达图
3. 若 `overview` 返回 404 → 展示空态（"还没有 4 周记录"）
4. 用户切换领域时，若该领域明细未缓存 → 再发一次 2.2

**依赖关系：** 2.2 依赖 2.1 返回的领域列表；多个 2.2 之间可并行。

---

## 3 · 页面 03 · 每日任务（`03_dailytask.html`）

### 3.0 接口清单

| # | 方法 | 路径 | 用途 | 必需 / 增补 |
|---|---|---|---|---|
| 3.1 | GET | `/api/v1/tasks/today` | 拉取今日任务列表（3-5 张卡片） | 必需 |
| 3.2 | POST | `/api/v1/events` | 上报埋点事件（`task_start` / `task_pause` / `task_resume` / `task_complete` 等） | 必需 |
| 3.3 | GET | `/api/v1/tasks/{task_id}` | 拉取单个任务详情（展开卡片看完整内容） | 增补 |

### 3.1 GET `/api/v1/tasks/today`

**用途：** 拉取今日任务列表，渲染 3-5 个任务卡片与打卡入口。

**请求：** GET 无请求体。可选 query `date`（默认服务端当日）。

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 任务日期 |
| `tasks` | array | 今日任务，3-5 个 |
| `tasks[].task_id` | string | 任务 ID，遵循 3.7 规范 |
| `tasks[].domain` | string | 领域 ID，取自 3.1 白名单 |
| `tasks[].domain_name` | string | 领域中文名 |
| `tasks[].task_level` | int | 任务等级，MVP 阶段 1-5（3.7 / 3.8） |
| `tasks[].task_variant` | string | `standard` / `disaccharide`（3.7） |
| `tasks[].title` | string | 任务标题（中文） |
| `tasks[].estimated_minutes` | int | 预计时长（15-30 分钟区间） |
| `tasks[].status` | string | `not_started` / `in_progress` / `completed`，由该任务最近一次事件推导 |
| `tasks[].evaluator_type` | string | 评估器类型，取自 3.3 的 10 个枚举 |

> 任务等级按 3.9 的 4 周递进节奏下发（第 1 周 L1-L2、第 2 周 L2-L3、第 3 周 L3-L4、第 4 周 L4-L5），MVP 仅 L1-L5。

**成功响应 200：**

```json
{
  "date": "2026-09-21",
  "tasks": [
    {
      "task_id": "go_L3_001",
      "domain": "go",
      "domain_name": "围棋",
      "task_level": 3,
      "task_variant": "standard",
      "title": "完成一盘 9 路对局并复盘前三手",
      "estimated_minutes": 20,
      "status": "not_started",
      "evaluator_type": "katago"
    },
    {
      "task_id": "writing_general_L2_003",
      "domain": "writing_general",
      "domain_name": "写作（通用）",
      "task_level": 2,
      "task_variant": "standard",
      "title": "写一段 300 字的观察笔记",
      "estimated_minutes": 15,
      "status": "not_started",
      "evaluator_type": "llm_writing"
    },
    {
      "task_id": "photography_L4_002",
      "domain": "photography",
      "domain_name": "摄影",
      "task_level": 4,
      "task_variant": "disaccharide",
      "title": "用同一场景拍两组不同光比",
      "estimated_minutes": 25,
      "status": "in_progress",
      "evaluator_type": "llm_image"
    }
  ]
}
```

**失败响应 500：**

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "服务开小差了，稍后再试一次",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 401、404、500

### 3.2 POST `/api/v1/events`

**用途：** 上报埋点事件。页面 03 主要使用 `task_start` / `task_pause` / `task_resume` / `task_complete`；同一接口承载 3.6 的全部 12 个 `event_type`，其余事件由其他页面或后续版本复用，不另开接口。

**请求 schema（原样使用 SPEC 4.2 的 event schema）：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID，uuid |
| `event_type` | string | 12 个冻结枚举之一（3.6） |
| `domain` | string | 领域 ID，取自 3.1 白名单 |
| `task_id` | string | 任务 ID，遵循 3.7 规范 |
| `task_level` | int | 任务等级 1-10（MVP 1-5） |
| `task_variant` | string | `standard` / `disaccharide` |
| `timestamp` | string | 事件发生时间，ISO 8601 |
| `duration_seconds` | int | 时长（秒） |
| `pause_count` | int | 暂停次数 |
| `pause_durations` | array[int] | 每次暂停时长（秒） |
| `completion_rate` | number | 完成度 0-1 |
| `retry_count` | int | 重试次数 |
| `objective_score` | number | 客观分 |
| `success` | bool | 是否成功 |
| `metadata` | object | `device` / `app_version` / `session_id` |

> **约定：** 当前 `event_type` 不适用的字段置为 `null`（不省略），保证 schema 稳定、前后端字段数一致。

**请求示例 A · `task_complete`（完整字段）：**

```json
{
  "user_id": "uuid",
  "event_type": "task_complete",
  "domain": "go",
  "task_id": "go_L3_001",
  "task_level": 3,
  "task_variant": "standard",
  "timestamp": "2026-09-21T10:30:00Z",
  "duration_seconds": 1847,
  "pause_count": 3,
  "pause_durations": [120, 80, 300],
  "completion_rate": 0.85,
  "retry_count": 0,
  "objective_score": 72.5,
  "success": true,
  "metadata": {
    "device": "iPhone",
    "app_version": "1.2.3",
    "session_id": "uuid"
  }
}
```

**请求示例 B · `task_start`（不适用字段置 null）：**

```json
{
  "user_id": "uuid",
  "event_type": "task_start",
  "domain": "go",
  "task_id": "go_L3_001",
  "task_level": 3,
  "task_variant": "standard",
  "timestamp": "2026-09-21T10:00:00Z",
  "duration_seconds": null,
  "pause_count": 0,
  "pause_durations": [],
  "completion_rate": null,
  "retry_count": 0,
  "objective_score": null,
  "success": null,
  "metadata": {
    "device": "iPhone",
    "app_version": "1.2.3",
    "session_id": "uuid"
  }
}
```

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | string | 服务端生成的事件 ID |
| `accepted` | bool | 是否接收成功 |
| `received_at` | string | 服务端接收时间，ISO 8601 |

**成功响应 200：**

```json
{
  "event_id": "uuid",
  "accepted": true,
  "received_at": "2026-09-21T10:30:01Z"
}
```

**失败响应 400：**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：event_type 不在允许枚举内",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、429、500

### 3.3 GET `/api/v1/tasks/{task_id}`（增补）

**增补理由：** 列表接口只返回卡片摘要；用户展开卡片查看完整任务说明、所需材料与产出要求时需按需拉取，避免首屏一次性返回全部正文导致响应体过大。

**路径参数：** `task_id` 遵循 3.7 规范。

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `domain` | string | 领域 ID |
| `domain_name` | string | 领域中文名 |
| `task_level` | int | 任务等级 |
| `task_variant` | string | `standard` / `disaccharide` |
| `title` | string | 任务标题 |
| `instruction` | string | 任务说明（中文） |
| `materials` | array[string] | 所需材料清单 |
| `submission_format` | string | 产出 / 提交格式要求 |
| `estimated_minutes` | int | 预计时长 |
| `evaluator_type` | string | 评估器类型，取自 3.3 |

**成功响应 200：**

```json
{
  "task_id": "go_L3_001",
  "domain": "go",
  "domain_name": "围棋",
  "task_level": 3,
  "task_variant": "standard",
  "title": "完成一盘 9 路对局并复盘前三手",
  "instruction": "先下完一盘 9 路对局，再回头看前三手有没有更好的选择。",
  "materials": ["9 路棋盘", "计时器"],
  "submission_format": "上传对局截图 + 三句话复盘",
  "estimated_minutes": 20,
  "evaluator_type": "katago"
}
```

**失败响应 404：**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "这个任务找不到了，换一个试试",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、404、500

### 3.4 页面 03 加载时序

1. `GET /api/v1/tasks/today` → 渲染首屏任务卡片
2. 用户点开某张卡片 → `GET /api/v1/tasks/{task_id}`（按需，不阻塞首屏）
3. 点"开始" → `POST /api/v1/events`（`task_start`），本地计时器启动
4. 暂停 / 继续 → `POST /api/v1/events`（`task_pause` / `task_resume`），客户端累计 `pause_count` 与 `pause_durations`
5. 完成 → `POST /api/v1/events`（`task_complete`），携带 `duration_seconds` / `pause_count` / `pause_durations` / `completion_rate` / `objective_score` / `success`
6. 上报失败 → 写入本地队列并持久化，联网后按 `task_id + event_type + timestamp` 做幂等重发

**依赖关系：** 3.3 依赖 3.1 返回的 `task_id`；事件上报按用户实际操作顺序发生，**同一任务的事件需保序**，不同任务的事件之间互不依赖。

---

## 4 · 页面 04 · 候选领域筛选（`04_domains.html`）

### 4.0 接口清单

| # | 方法 | 路径 | 用途 | 必需 / 增补 |
|---|---|---|---|---|
| 4.1 | GET | `/api/v1/domains` | 拉取 50 个领域卡片，支持按机制强度筛选 | 必需 |
| 4.2 | GET | `/api/v1/domains/{domain_id}` | 拉取单个领域详情 | 必需 |
| 4.3 | POST | `/api/v1/user_domains` | 保存用户筛出的 3-5 个领域 | 增补 |

### 4.1 GET `/api/v1/domains`

**用途：** 拉取 50 个领域卡片（SSOT 静态数据），支持按机制强度筛选。

**Query 参数：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `mechanism_strength` | int 或 int[] | 1-5，按机制强度筛选，可多值（如 `3,4,5`） |
| `gardner_type` | string | 可选，按 Gardner 智能筛选，取自 3.2 的 8 个枚举 |

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 命中数量 |
| `domains` | array | 领域列表，50 个 ID 取自 3.1 |
| `domains[].domain` | string | 领域 ID，取自 3.1 白名单 |
| `domains[].domain_name` | string | 领域中文名，取自 3.1 |
| `domains[].gardner_type` | string | Gardner 智能，取自 3.2 |
| `domains[].startup_difficulty` | int | 启动成本，3.1 数值原样使用 |
| `domains[].feedback_speed` | int | 领域反馈速度，3.1 数值原样使用 |
| `domains[].mechanism_strength` | int | 机制强度，3.1 数值原样使用 |

> ⚠️ **命名提示：** `domains[].feedback_speed` 是 3.1 的**领域数值属性**（1-5），与 3.4 坐标系维度 `feedback_speed`（`short` / `long` 枚举）**同名不同义**，分属不同响应对象，实现时请勿混淆或复用同一份解析逻辑。

**成功响应 200（节选 3 条示意，默认返回全量 50 条）：**

```json
{
  "total": 50,
  "domains": [
    {
      "domain": "writing_general",
      "domain_name": "写作（通用）",
      "gardner_type": "linguistic",
      "startup_difficulty": 2,
      "feedback_speed": 3,
      "mechanism_strength": 2
    },
    {
      "domain": "go",
      "domain_name": "围棋",
      "gardner_type": "logical_mathematical",
      "startup_difficulty": 2,
      "feedback_speed": 3,
      "mechanism_strength": 1
    },
    {
      "domain": "djing",
      "domain_name": "DJ",
      "gardner_type": "musical",
      "startup_difficulty": 3,
      "feedback_speed": 5,
      "mechanism_strength": 4
    }
  ]
}
```

**失败响应 400：**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：mechanism_strength 需在 1-5 之间",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、500

> 50 个领域为 SSOT 静态数据，筛选也可在前端基于已拉取的全量数据本地完成；服务端筛选仅为统一口径与后续扩展保留。

### 4.2 GET `/api/v1/domains/{domain_id}`

**用途：** 拉取单个领域详情，供领域卡片展开时使用。

**路径参数：** `domain_id` 必须命中 3.1 白名单。

**响应 schema：** 在 4.1 的领域对象基础上追加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `description` | string | 领域说明（中文，引导性表述） |
| `evaluator_types` | array[string] | 该领域可用评估器，取自 3.3 的 10 个枚举 |
| `sample_task_ids` | array[string] | 示例任务 ID，遵循 3.7 规范 |

**成功响应 200：**

```json
{
  "domain": "writing_general",
  "domain_name": "写作（通用）",
  "gardner_type": "linguistic",
  "startup_difficulty": 2,
  "feedback_speed": 3,
  "mechanism_strength": 2,
  "description": "把看到的、想到的落成文字，是观察自己思路变化最省力的方式之一。",
  "evaluator_types": ["llm_writing"],
  "sample_task_ids": ["writing_general_L1_001", "writing_general_L2_002"]
}
```

**失败响应 404：**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "这个领域不在当前版本的清单里",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、404、500

### 4.3 POST `/api/v1/user_domains`（增补）

**增补理由：** 原型页只做展示与筛选，但产品流程要求用户把候选筛到 3-5 个并进入 4 周投入。选中结果必须落库，否则页面 03 无从生成每日任务、页面 02 无从做跨领域对比。原始必需清单未包含，此处补齐。

**请求 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `domains` | array[string] | 3-5 个领域 ID，取自 3.1 白名单，不可重复 |

**请求示例：**

```json
{
  "domains": ["writing_general", "go", "photography"]
}
```

**响应 schema：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 用户 ID |
| `domains` | array[string] | 已保存的领域 ID 列表 |
| `selected_at` | string | 保存时间，ISO 8601 |

**成功响应 200：**

```json
{
  "user_id": "uuid",
  "domains": ["writing_general", "go", "photography"],
  "selected_at": "2026-09-21T10:30:00Z"
}
```

**失败响应 400（数量越界）：**

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "参数错误：请选择 3-5 个领域",
    "request_id": "uuid"
  }
}
```

**可能的错误码：** 400、401、500

### 4.4 页面 04 加载时序

1. `GET /api/v1/domains`（默认不带筛选，取全量 50 条）
2. 用户调整机制强度筛选 → 前端基于内存数据本地过滤（无需请求）；若以服务端口径为准，则重新 `GET /api/v1/domains?mechanism_strength=4`
3. 用户展开某领域卡片 → `GET /api/v1/domains/{domain_id}`（按需，可缓存）
4. 用户确认 3-5 个 → `POST /api/v1/user_domains`

**依赖关系：** 4.2 依赖 4.1 的列表；4.3 必须在用户确认选择后发起，是进入 4 周投入的前置动作。

---

## 5 · 冻结清单对齐自检

| 冻结项 | 出处 | 本契约使用位置 |
|---|---|---|
| 50 个领域 ID | 3.1 | 1.x（题目示例外）、2.1 / 2.2、3.1 / 3.3、4.1 / 4.2 / 4.3 |
| Gardner 8 枚举 | 3.2 | 4.1 / 4.2 的 `gardner_type` |
| 评估器 10 枚举 | 3.3 | 3.1 / 3.3 的 `evaluator_type`，4.2 的 `evaluator_types` |
| 坐标系 6 维及选项枚举 | 3.4 | 1.1 的 `dimension` / `option_id`，1.2 / 1.3 的 `coordinate` |
| 5 维客观指标字段名 | 3.5 | 2.2 的 `objective_metrics` |
| 12 个 `event_type` | 3.6 | 3.2 的 `event_type` |
| 任务 ID 规范 / `task_variant` | 3.7 | 3.1 / 3.2 / 3.3 的 `task_id` / `task_variant` |
| 任务等级语义（MVP L1-L5） | 3.8 / 3.7 | 3.1 / 3.2 的 `task_level` |
| 4 周递进节奏 | 3.9 | 3.1 的任务下发说明 |
| SPEC 4.2 event schema | 第 6.2 节 | 3.2 请求体（原样使用） |

---

# === TILT-CONTRACT-MANIFEST ===
# task_id: H02
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝（Yuanbao）
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - docs/api_contract.md   (rows: 920)
#   - docs/frontend_checklist.md   (rows: 160)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations: []
# === END MANIFEST ===
