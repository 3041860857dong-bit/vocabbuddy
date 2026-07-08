# 词库丰富化功能（VocabBuddy）

把原本写死在 `data.js` 的 20 个静态单词，升级为「选择词库 → 按库从后端拉取真实单词 → 学习/复习/拼写」的完整闭环，对标百词斩式选词库体验。

## 词库覆盖
| code | 名称 | 单词数 |
|------|------|--------|
| cet4   | CET-4 四级  | 4544 |
| cet6   | CET-6 六级  | 3991 |
| kaoyan | 考研词汇     | 5047 |
| ielts  | 雅思 IELTS  | 5275 |
| toefl  | 托福 TOEFL  | 10367 |

数据来源：GitHub `KyleBing/english-vocabulary` 的 `json_original/json-full/`（含音标+例句），缺失字段留空串 `""`。

## 后端新增接口
- `GET /api/libraries` —— 返回可用词库及单词总数（前端「选择词库」页展示数量）。
- `GET /api/words?lib=<code>&limit=&offset=` —— 按词库分页取词，字段 `en/phonetic/pos/cn/example`，需登录；非法 lib → 400，无 token → 401。

## 前端改动
- 登录后 `initApp()` 按所选词库（`settings.wordLib` 索引 → `LIBS[i].code`）调用 `fetchWords()` 拉取单词，替换原来的静态 20 词。
- 词库页点击即 `selectLib(i)`：写回设置 + 拉取该库单词 + 刷新学习/复习/拼写池。
- 单次学习量按「每日新词目标」(`dailyGoal`) 截断。

## 数据库
- 新增 `words` 表（lib / en / phonetic / pos / cn / example），`en` 列使用 `utf8mb4_bin` 排序规则，确保 `resume` / `resumé` 等重音词作为不同单词共存。
- 共导入 29,224 词，5 个词库全部入库。

## 验证
- 后端接口字段对齐、鉴权、非法参数均符合预期。
- 前端内联 JS `node --check` 语法通过。
- 端到端模拟：登录 → 选 kaoyan → 拉词 → 学 3 词 → 首页 `learnedToday=3` → 切 cet4 得到不同词集 ✅

## 运行
双击 `backend/start_server.bat`，浏览器打开 http://localhost:8000
