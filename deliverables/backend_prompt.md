# VocabBuddy 后端实现提示词（完整版 · 可直接使用）

> 你是资深后端架构师。请基于以下完整规格，为「VocabBuddy」英语单词学习 App 设计并实现一套**稳定、安全、可水平扩展**的后端服务。该后端将被一个纯前端单页（`index.html`，手机端 UI）通过 REST API 调用。产出物需可运行、有测试、有文档，并能被前端零改动对接（仅替换 `test_data.js` 的读取逻辑）。

---

## 一、项目背景与范围

- **应用**：VocabBuddy，碎片化时间英语单词学习 App，核心是 **SRS（间隔重复 Spaced Repetition）记忆引擎**。
- **当前前端**：单个 `index.html`，目前用本地 `data.js`（静态单词字典 + 词库列表）和 `test_data.js`（**模拟后端返回的假数据**：设置项、首页统计、学习统计、生词本）驱动。后端上线后，前端改为调用真实 API，并删除 `test_data.js`。
- **本提示词目标**：产出一套可运行的 **FastAPI + MySQL** 后端，包含鉴权、单词/词库、新词学习、SRS 复习、生词本、练习、统计、设置等全套接口与数据模型。
- **明确不做（避免范围蔓延）**：社交、AI 例句生成、云同步/多端、会员付费、UGC 词库市场、图片联想、游戏化。

---

## 二、技术栈（固定）

| 维度 | 选型 |
|------|------|
| 语言 / 框架 | Python 3.11+，FastAPI |
| ORM / 迁移 | SQLAlchemy 2.x，Alembic |
| 数据库 | MySQL 8.0（InnoDB，utf8mb4，时区 UTC） |
| 校验 | Pydantic v2 |
| 鉴权 | JWT（PyJWT 或 python-jose，HS256）+ 密码哈希（passlib[bcrypt] 或 argon2） |
| 限流 | slowapi 或自研中间件 |
| 测试 | pytest + httpx（FastAPI TestClient） |
| 部署 | Dockerfile + docker-compose（MySQL + 后端），环境变量驱动配置 |
| 文档 | FastAPI 自带 OpenAPI / Swagger（`/docs`） |

---

## 三、核心领域模型与 MySQL 表结构

> 约定：所有表含 `created_at` / `updated_at`（`TIMESTAMP DEFAULT CURRENT_TIMESTAMP`）；用户相关数据软删除；索引务必按下面的定义建立，保证 `next_review_date` 范围查询走索引。

### 1) users（账号）
```sql
CREATE TABLE users (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  uuid        CHAR(36) NOT NULL UNIQUE,
  email       VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(64) DEFAULT '同学',
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted_at  TIMESTAMP NULL
);
CREATE INDEX idx_users_email ON users(email);
```

### 2) libraries（词库，参考 data.js 的 libraryOptions）
```sql
CREATE TABLE libraries (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  code        VARCHAR(32) NOT NULL UNIQUE,   -- cet4 / cet6 / kaoyan / ielts / toefl / business
  name        VARCHAR(64) NOT NULL,
  icon        VARCHAR(16),
  description VARCHAR(255),
  word_count  INT DEFAULT 0,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3) words（单词字典）
```sql
CREATE TABLE words (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  library_id  BIGINT NOT NULL,
  en          VARCHAR(64) NOT NULL,
  phonetic    VARCHAR(64),
  pos         VARCHAR(16),
  cn          VARCHAR(255),
  example     TEXT,
  example_cn  TEXT,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_lib_word (library_id, en),
  INDEX idx_words_lib (library_id)
);
```

### 4) user_settings（每用户一行）
```sql
CREATE TABLE user_settings (
  user_id             BIGINT PRIMARY KEY,
  library_id          BIGINT,                       -- 当前选中词库
  daily_new_goal      TINYINT DEFAULT 15,           -- 10~25，步进5
  daily_review_cap    SMALLINT DEFAULT 100,         -- 50~200，步进10
  accent              ENUM('us','gb') DEFAULT 'us',
  auto_play           BOOLEAN DEFAULT FALSE,
  remind_on           BOOLEAN DEFAULT TRUE,
  remind_time         TIME DEFAULT '20:00',
  dark_mode           ENUM('system','light','dark') DEFAULT 'system',
  review_priority_mode BOOLEAN DEFAULT FALSE,       -- 复习>50时暂停新词
  created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### 5) srs_cards（SRS 状态 + 生词本状态，合并存储避免重复）
```sql
CREATE TABLE srs_cards (
  id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id              BIGINT NOT NULL,
  word_id              BIGINT NOT NULL,
  library_id           BIGINT NOT NULL,
  status               ENUM('unlearned','learning','reviewing','graduated') DEFAULT 'unlearned',
  interval_days        INT DEFAULT 0,               -- 当前间隔（天）
  reps                 INT DEFAULT 0,               -- 复习次数
  consecutive_good     INT DEFAULT 0,
  last_grade           VARCHAR(8),                 -- known/fuzzy/never 或 again/hard/good/easy
  last_reviewed_at     TIMESTAMP NULL,
  next_review_date     DATE NULL,
  -- 生词本相关
  in_vocab_book        BOOLEAN DEFAULT FALSE,
  vocab_priority       ENUM('normal','high') DEFAULT 'normal',
  vocab_consecutive_good INT DEFAULT 0,
  vocab_added_at       DATE NULL,
  vocab_graduated_at   DATE NULL,
  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_word (user_id, word_id),
  INDEX idx_due (user_id, next_review_date),
  INDEX idx_user_lib_status (user_id, library_id, status)
);
```

### 6) review_logs（每次评分/学习的明细，供统计与趋势）
```sql
CREATE TABLE review_logs (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id       BIGINT NOT NULL,
  word_id       BIGINT NOT NULL,
  session_date  DATE NOT NULL,
  action        ENUM('learn','review','spelling','quiz') NOT NULL,
  rating        VARCHAR(8),                        -- known/fuzzy/never 或 again/hard/good/easy 或 correct/wrong
  is_correct    BOOLEAN,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_date (user_id, session_date),
  INDEX idx_user_word (user_id, word_id)
);
```

### 7) daily_stats（按天聚合，供统计/打卡/连续天数）
```sql
CREATE TABLE daily_stats (
  user_id          BIGINT NOT NULL,
  date             DATE NOT NULL,
  new_learned      INT DEFAULT 0,
  reviewed         INT DEFAULT 0,
  quiz_total       INT DEFAULT 0,
  quiz_correct     INT DEFAULT 0,
  practice_words   INT DEFAULT 0,
  effective_words  INT DEFAULT 0,                   -- new_learned + reviewed + practice_words
  check_in         BOOLEAN DEFAULT FALSE,           -- 完成任意1个学习单元即打卡
  PRIMARY KEY (user_id, date),
  INDEX idx_user_date (user_id, date)
);
```

---

## 四、SRS 引擎规格（核心算法，必须严格实现）

### 4.1 评分档位与间隔规则（对齐 PRD §4.1）
- 所有间隔**向上取整为整数天**，并**钳制到 [1, 180] 天**。
- **新词首次学习**（三档标记）：
  - `known`（认识）→ 间隔 = **4 天**，状态 `reviewing`
  - `fuzzy`（不熟）→ 间隔 = **1 天**，加入生词本（priority=normal）
  - `never`（不会）→ 间隔 = **1 天**，加入生词本（priority=high）
- **复习四档评分**（基于当前间隔 `I`，首次复习时 `I` 取上一轮设定值）：
  - `again` → 间隔 = **1**；`consecutive_good=0`，`vocab_consecutive_good=0`；若不在生词本则加入（priority=normal）
  - `hard`  → 间隔 = `ceil(I * 1.2)`（至少 +1 天）；`vocab_consecutive_good=0`
  - `good`  → 间隔 = `ceil(I * 2.5)`；`consecutive_good++`，`vocab_consecutive_good++`
  - `easy`  → 间隔 = `ceil(I * 3.0)`；`consecutive_good++`，`vocab_consecutive_good++`
- `next_review_date = today + interval_days`。
- **连续 Again 提示**：同一词连续 2 次 `again`，第 3 次出现时前端提示「这个词你可能需要更多关注」（后端在响应里带 `needAttention:true`）。

### 4.2 掌握度分层（对齐 PRD §2.6）
- **新学**：`status != unlearned` 且 `reps == 0`（已学但未首次复习）
- **熟悉**：`reps` 1~2 且 `interval_days < 7`
- **掌握**：`reps >= 3` 且 `interval_days >= 7`
- **长期记忆**：`interval_days >= 30` 且最近 3 次评分无 `again`

### 4.3 生词本融合与毕业
- 加入生词本时：`in_vocab_book=true`，`interval_days=1`，`vocab_added_at=today`，priority 按来源（见 §4.1）。
- 复习排序时，生词本中的词排在非生词**之前**（priority=high 再优先于 normal）。
- **毕业**：`vocab_consecutive_good >= 3` → `in_vocab_book=false`，`vocab_graduated_at=today`（恢复正常 SRS 调度）。
- 中途评 `again`/`hard` → `vocab_consecutive_good` 清零。
- 手动移除（`DELETE /api/vocab/{word_id}`）→ 标记「已掌握」：`in_vocab_book=false`，保留 srs_card。

### 4.4 防雪崩（对齐 PRD §4.4.2）
- 计算 `due_count` = `next_review_date <= today` 且 `status='reviewing'` 的卡片数。
- 若 `due_count > 80`：今日复习上限取 `min(due_count, daily_review_cap)` 中的前 **80** 个（按遗忘概率排序），其余卡片的 `next_review_date` 顺延到未来 2~3 天，并在响应里返回 `avalanche:{triggered:true, message:"今日复习量较大，已为您分摊部分到后续几天"}`。
- `review_priority_mode=true` 且 `due_count > 50` → 响应返回 `suggestPauseNewWords:true`。

### 4.5 断链恢复（对齐 PRD §4.5.2）
- 在拉取今日复习/新词时，计算 `gap` = 距上次 `check_in` 的天数：
  - `gap 1~3`：积压分摊到 3~5 天，首日负荷 = `min(due, daily_review_cap * 0.5)`
  - `gap 4~7`：分摊 5~7 天，首日 30
  - `gap >= 7`：分摊 7~10 天，首日 20，返回 `welcomeBack:true` + `suggestPauseNewWords:true`
- 非首日正常按 `due_count` 与上限取词。

### 4.6 每日学习量（对齐 PRD §4.4）
- 新词默认 15（10~25，步进 5）；复习上限默认 100（50~200，步进 10）；每日总交互建议上限 150。
- 触发防雪崩时，建议新词临时降至 10（前端展示建议）。

### 4.7 遗忘概率排序（用于复习列表排序，需确定且可复现）
排序键（降序 = 越该优先复习）：
1. `in_vocab_book` 优先（high > normal > 非生词）
2. `next_review_date` 升序（越 overdue 越前）
3. 遗忘风险分 `risk = overdue_days * (1 + lastGradePenalty)`，其中 `lastGradePenalty`: again=1.0, hard=0.5, good=0.1, easy=0.0；未复习过记 0.5
4. `last_reviewed_at` 越早越前

---

## 五、REST API 端点（除 auth 外均需 `Authorization: Bearer <JWT>`）

> 统一 JSON 错误格式：`{ "error": "描述", "code": "ERROR_CODE", "message": "可读信息" }`，**不泄露堆栈**。

### 鉴权
- `POST /api/auth/register` `{email, password, display_name?}` → `{access_token, token_type:"bearer"}`
- `POST /api/auth/login` `{email, password}` → `{access_token, token_type}`
- `GET /api/auth/me` → `{id, email, display_name}`

### 词库与单词
- `GET /api/libraries` → `[{id, code, name, icon, word_count}]`
- `GET /api/libraries/{id}/words?limit=20&cursor=` → `[{id, en, phonetic, pos, cn, example, example_cn}]`（分页，返回 `next_cursor`）
- 首次部署用 seed 脚本导入 `data.js` 的 20 个词；另提供可导入完整词库的 seed 入口。

### 新词学习
- `GET /api/learn/today` → `{ words:[<完整单词对象>], learnedToday, learnedGoal, completed:false }`（取 `daily_new_goal` 个未学词）
- `POST /api/learn/{word_id}/rate` `{rating:"known"|"fuzzy"|"never"}` → `{ nextWordId?, completed:bool, learnedToday, learnedGoal }`
- 进度自动保存：每评一词即写库；中断后下次从断点续接（`status='unlearned'` 且未完成者优先）。

### SRS 复习
- `GET /api/review/today` →
  ```json
  {
    "words": [
      { "id":"<word_id>", "en":"academy", "phonetic":"…", "pos":"n.", "cn":"…",
        "example":"…", "lastGrade":"good", "intervalDays":7,
        "nextReviewPreview": {"again":1,"hard":9,"good":18,"easy":21} }
    ],
    "reviewToday": 8, "reviewGoal": 15,
    "avalanche": {"triggered":false,"message":null},
    "welcomeBack": false, "suggestPauseNewWords": false
  }
  ```
- `POST /api/review/{word_id}/grade` `{grade:"again"|"hard"|"good"|"easy"}` →
  `{ nextReviewDate:"2026-07-15", intervalDays:18, graduated:false, nextWordId?, completed:bool, reviewToday, reviewGoal, summary? }`
- 全部复习完时 `completed:true` 且返回 `summary:{total, again, hard, good, easy, accuracy}`。

### 生词本
- `GET /api/vocab` → `[{en, cn, date:"06-28", status:"reviewing", priority:"normal", daysInVocab:9}]`
- `POST /api/vocab` `{en, cn?}` → 若 `cn` 缺失则查 `words` 表补全（查不到返回 404）；加入生词本，`interval_days=1`，返回该生词项
- `DELETE /api/vocab/{word_id}` → 标记已掌握（移出生词本，保留 srs_card）
- `POST /api/vocab/review` → 仅拉取 `in_vocab_book=true` 的词走复习流程（其余同 `/api/review`）

### 练习（P1，保持稳定最小实现）
- `GET /api/practice/quiz?count=10` / `POST /api/practice/quiz/{session_id}/answer` `{choiceIndex}` → 答错自动加入生词本
- `GET /api/practice/spelling?count=10` / `POST /api/practice/spelling/{session_id}/answer` `{spelling}` → 忽略大小写与首尾空格，答错自动加入生词本

### 统计（**响应形状必须对齐 `test_data.js`，前端可直接替换**）
- `GET /api/settings` →
  ```json
  { "defaultDailyGoal":15, "defaultAccent":"us",
    "dailyNewGoal":15, "dailyReviewCap":100, "accent":"us",
    "autoPlay":false, "remindOn":true, "remindTime":"20:00",
    "darkMode":"system", "reviewPriorityMode":false, "libraryId":1 }
  ```
- `GET /api/stats/home` →
  ```json
  { "learnedToday":12, "learnedGoal":15, "reviewToday":8,
    "reviewGoal":15, "streakDays":12, "mastered":156 }
  ```
- `GET /api/stats` →
  ```json
  { "totals":{"mastered":156,"studyDays":12,"accuracy":78},
    "weekly":{"labels":["一","二","三","四","五","六","日"],"values":[12,18,9,22,15,20,14]},
    "details":[
      {"label":"总学习时长","value":"24.5 小时"},
      {"label":"最长连续打卡","value":"21 天"},
      {"label":"生词本数量","value":8,"dynamic":true},
      {"label":"本周新学","value":"64 词"} ] }
  ```
- `GET /api/stats/trend?range=7|30` → 近 N 天每日有效学习单词数 + SRS 评分分布
- `GET /api/data/export` → 返回该用户全部数据 JSON（设置、srs_cards、生词本、daily_stats），供「数据导出」

### 杂项
- `GET /health` → `{status:"ok"}`

---

## 六、关键业务流程（实现级要求）

**新词学习（对齐 PRD §3.1）**：拉取未学词 → 逐个翻转 + 三档标记 → 写 srs_card（按 §4.1 设间隔/状态/生词本）→ 累加 `daily_stats.new_learned` 与 `check_in` → 全部完成返回摘要。可随时退出，下次从断点续接。

**SRS 复习（对齐 PRD §3.2）**：按 §4.7 排序拉取到期词 → 先考后看 → 四档评分 → 按 §4.1 更新间隔/状态 → 生词本联动（§4.3）→ 掌握度重算 → 累加 `daily_stats.reviewed` 与 `check_in` → 完成返回摘要。

**生词闭环（对齐 PRD §3.3）**：多来源（不熟/不会、复习 again、拼写错、选择错、手动添加）入生词本 → 在 SRS 队列享优先级 → 连续 3 次 Good 毕业 → 手动移除标记已掌握。

---

## 七、安全与稳定性要求（强制）

1. **鉴权**：密码 bcrypt/argon2 哈希；JWT 密钥取自环境变量，access token 有效期 7 天（可配）；无 token 访问受保护接口返回 401。
2. **幂等**：所有写接口（rate / grade / practice answer）用 `(user_id, word_id, action, session_date, client_nonce)` 去重，防止网络重试导致重复计学习量 / 重复评分。
3. **注入与校验**：全部输入走 Pydantic；SQL 一律参数化（ORM）；防 SQL 注入 / XSS（输出由前端转义）。
4. **限流**：登录 10 次/分钟/IP；通用接口 60 次/分钟/用户。
5. **CORS**：仅放行前端域名（环境变量配置，禁止 `*`）。
6. **日志**：结构化 JSON 日志，敏感字段脱敏，**不记录密码/token**。
7. **数据库**：连接池（pool_size + max_overflow）；所有写表带 `updated_at`；软删除。
8. **迁移**：Alembic 管理，禁止手动改表；首次部署自动 seed 词库（先 20 词，支持全量导入）。
9. **健康检查 / 优雅关闭 / 请求超时**：`/health` 返回 ok；进程退出释放连接；设合理超时。
10. **并发**：同一用户并行复习同一词时，用 `SELECT ... FOR UPDATE` 行锁或 `updated_at` 乐观锁，避免状态错乱 / 重复计数。
11. **分页**：所有列表接口默认 `limit=20`，最大 100，返回 `next_cursor`。
12. **测试**：pytest 覆盖——SRS 算法全档位与边界（间隔钳制、毕业、防雪崩、断链恢复）、鉴权、关键接口。CI 跑 pytest，全绿方可交付。
13. **预警**：统计接口在 Again 率 > 20% 时返回 `warnAgainRate:true`（前端提示降低每日新词量）。

---

## 八、工程结构与交付

```
app/
  main.py
  core/{config.py, security.py, db.py, errors.py}
  models/{user.py, word.py, srs.py, stats.py}
  schemas/{auth.py, learn.py, review.py, vocab.py, stats.py, settings.py}
  routers/{auth.py, libraries.py, learn.py, review.py, vocab.py, practice.py, stats.py, settings.py}
  services/{srs_engine.py, stats_service.py, vocab_service.py, seed.py}
  db/session.py
  alembic/
tests/
  test_srs_engine.py  test_auth.py  test_review.py  test_learn.py  test_stats.py
requirements.txt  Dockerfile  docker-compose.yml  .env.example  README.md  alembic.ini
```

**README 必须含**：`docker-compose up` 本地启动步骤、环境变量说明、API 概览、前端对接说明（如何把 `index.html` 中 `TEST.settings / TEST.homeStats / TEST.stats / TEST.vocabSeed` 的读取替换为 `fetch` 真实接口，并把 JWT 存 `localStorage` 后在请求头带上）。

---

## 九、验收标准（交付前自检）

- [ ] `docker-compose up` 后 MySQL + 后端正常启动，`/health` 返回 ok
- [ ] 注册/登录返回 JWT；受保护接口无 token 返回 401
- [ ] 完整学习闭环：选词库 → 学新词（三档）→ 复习（四档）→ 生词本联动 → 统计更新，数据持久化正确
- [ ] SRS 间隔规则与 PRD §4.1 完全一致（**附 pytest 证明**）
- [ ] 防雪崩（>80）与断链恢复（gap 分级）在到期词超阈值时正确分摊
- [ ] 生词连续 3 次 Good 自动毕业；again 重新入生词本
- [ ] `/api/stats`、`/api/stats/home`、`/api/settings`、`/api/vocab` 返回的 JSON 形状与 `index.html` 当前 `TEST_DATA` 契约一致，可直接替换
- [ ] pytest 全绿，CI 通过
- [ ] 限流、CORS、输入校验、统一错误格式均生效
- [ ] 并发复习同一词不产生重复计数 / 状态错乱

---

**交付时请同时给出**：可运行代码仓库结构、Alembic 迁移脚本、seed 脚本、pytest 结果、以及一份「前端如何 3 步对接」的简短说明。
