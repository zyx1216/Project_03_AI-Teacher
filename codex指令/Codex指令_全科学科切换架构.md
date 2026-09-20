# Codex 执行指令：全科学科切换架构（v1.2）

## 角色设定

你是一名资深AI应用开发工程师，同时也是一名资深中学高级教师。你正在开发一个面向中小学教师的AI教学工作台项目。

**工作原则：**
1. 先读懂现有代码再改，不破坏已有的169个测试
2. 改动最小化，能加配置不改逻辑
3. 每改完一个模块跑对应测试，确保零回归
4. 所有用户可见的文字用中文，代码注释用中文
5. 不新增第三方依赖
6. 保持数据库向后兼容，不删字段、不改字段类型

---

## 任务目标

把当前"数学专用"的应用改造成"全科通用"的学科切换架构。这是全科化的第一步，只做地基，不做各学科的题型/知识点差异化。

**核心思路：** 当前学科作为一个全局配置存在 `data/app_config.json` 里，教师在设置页选择当前任教的学科，整个应用的标题、提示语、默认值都跟着变。数据库 `subject` 字段已经存在，不需要改表结构。

---

## 具体改动清单

### 1. 新建 `utils/app_config.py` —— 全局应用配置服务

**职责：** 管理当前学科等全局配置，存储到 `data/app_config.json`。

**要求：**
- 定义 `ALL_SUBJECTS` 常量：`["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]`
- 定义 `SUBJECT_ICONS` 常量：每个学科对应一个emoji
  - 语文：📖
  - 数学：📐
  - 英语：🔤
  - 物理：⚛️
  - 化学：🧪
  - 生物：🧬
  - 政治：⚖️
  - 历史：📜
  - 地理：🌍
- 提供 `load_app_config() -> dict`：读取 `data/app_config.json`，文件不存在则返回默认值 `{"current_subject": "数学"}`
- 提供 `save_app_config(config: dict) -> None`：写入 `data/app_config.json`
- 提供 `get_current_subject() -> str`：快速获取当前学科，默认"数学"
- 提供 `set_current_subject(subject: str) -> None`：设置当前学科
- 提供 `get_subject_icon() -> str`：获取当前学科emoji
- 文件不存在时自动创建，目录不存在自动创建
- JSON 用 UTF-8 编码，ensure_ascii=False

---

### 2. 修改 `config.py`

- 把 `APP_NAME = "AI 数学教师工作台"` 改成不写死学科名
- 新增一个函数 `get_app_name()`：从 `app_config.get_current_subject()` 读取学科，返回 `f"AI {subject}教师工作台"`
- 保留 `APP_NAME` 常量作为兜底，但注释说明优先用 `get_app_name()`
- `APP_VERSION` 升到 `"1.2.0"`

---

### 3. 修改 `app.py` —— 侧边栏标题跟随学科

- 侧边栏标题从写死的 `"📐 AI 数学教师工作台"` 改成动态读取
- 用 `config.get_app_name()` 和 `app_config.get_subject_icon()` 拼接
- 标题格式：`f"{icon} {app_name}"`
- 四个页面导航选项保持不变

---

### 4. 修改 `modules/settings.py` —— 新增学科设置区

在设置页"关于"之前，新增一个 **"当前学科"** 区块：

- 标题：`当前学科`
- 说明文字：`选择你当前任教的学科，应用标题和默认设置会跟着切换。已有的成绩数据不受影响。`
- 用 `st.selectbox` 下拉选择，选项是 `app_config.ALL_SUBJECTS`
- 默认值是 `app_config.get_current_subject()`
- 选择变化时自动保存到 `data/app_config.json`
- 保存后用 `st.success("学科已切换")` 提示
- 不需要重启应用，侧边栏标题下一次rerun就会变

---

### 5. 修改各模块里硬编码的"数学"

**注意：只改用户可见的提示语和默认值，不改数据库字段默认值。**

#### `modules/lesson_plan.py`
- 资料名称 placeholder：从 `"如：人教版八年级上册数学 第13章"` 改成 `"如：人教版八年级上册{subject} 第X章"`（subject从配置读）
- 保存资料时 `subject="数学"` 改成 `subject=app_config.get_current_subject()`
- 导出文件名 `"数学习题卷.docx"` 改成 `f"{subject}习题卷.docx"`
- 导出文件名 `"数学习题教师卷.docx"` 改成 `f"{subject}习题教师卷.docx"`

#### `modules/homework.py`
- 错题本导出标题 `"数学错题本"` 改成 `f"{subject}错题本"`

#### `modules/analysis.py`
- 满分格式 placeholder `"格式：数学=120,语文=120,英语=120"` 保留（这是多科示例，不改）
- 错误提示 `"满分格式不对..."` 保留
- 如果有其他写死"数学"的用户可见文字，改成动态读取

#### `modules/settings.py`
- LLM配置提示 `"建议用中文/数学能力更强的通用模型..."` 改成 `"建议用中文能力更强的通用模型..."`（去掉"数学"）

#### `utils/question_service.py`
- 导出标题默认参数 `title: str = "数学习题"` 改成 `title: str = "{subject}习题"`（从配置读）
- 检查其他用户可见文字，有"数学"的改成动态读取

---

### 6. 修改 `models/models.py`

- `Score.subject` 的 `default="数学"` 保留（数据库层默认值，不影响）
- `Textbook.subject` 的 `default="数学"` 保留
- 加注释说明：默认值是历史遗留，实际使用时从 `app_config.get_current_subject()` 读取

---

### 7. 测试要求

**必须保持169个已有测试全部通过，零回归。**

新增以下测试：

#### `tests/test_app_config.py`（新建）
- 测试 `load_app_config()` 文件不存在时返回默认值
- 测试 `save_app_config()` 和 `load_app_config()` 往返一致
- 测试 `get_current_subject()` 默认返回"数学"
- 测试 `set_current_subject()` 设置后能读回来
- 测试 `get_subject_icon()` 返回对应emoji
- 测试 `ALL_SUBJECTS` 包含9个学科
- 测试 JSON 中文不乱码（ensure_ascii=False）

#### 补充到 `tests/test_app_smoke.py`
- 测试设置页学科选择器能渲染
- 测试切换学科后 `app_config.json` 文件更新

---

### 8. 版本记录

- 更新 `CHANGELOG.md`，在最上面加 v1.2.0 条目
- 标题：`v1.2.0 — 2026-09-19 · 全科学科切换架构`
- 记录完成内容、新增文件、测试情况、已知取舍
- 更新 `MEMORY.md`，在最上面加阶段7的架构决策和踩坑记录
- 保存版本快照到 `versions/v1.2.0_学科切换架构/`

---

## 已知取舍（不需要做的）

1. **不改数据库表结构**：`subject` 字段已经存在，只是默认值保留"数学"
2. **不做各学科题型差异化**：这是后续阶段的事，这次只做学科切换地基
3. **不做各学科知识点体系**：后续再补
4. **不做各学科独立的AI提示词**：后续再补
5. **不改已有测试数据**：demo数据里的"数学"成绩保留不动
6. **不做多学科并行**：一次只有一个当前学科，切换是全局的

---

## 验收标准

1. 运行 `streamlit run app.py` 能正常启动
2. 侧边栏标题显示当前学科的工作台名称
3. 设置页能看到学科选择器，切换后保存到 `data/app_config.json`
4. 重启应用后学科选择保持不变
5. 导出文件的文件名跟着学科变
6. 备课页保存资料时subject用当前学科
7. **全量测试通过（169个旧测试 + 新增测试），零回归**
8. 不新增第三方依赖
9. 数据库文件不被破坏（已有成绩数据正常显示）

---

## 执行顺序

1. 先读 `config.py`、`app.py`、`modules/settings.py`、`utils/db.py` 了解现有结构
2. 新建 `utils/app_config.py`
3. 改 `config.py`
4. 改 `app.py`
5. 改 `modules/settings.py`
6. 改 `modules/lesson_plan.py`、`modules/homework.py`、`utils/question_service.py`
7. 写测试
8. 跑全量测试
9. 更新 CHANGELOG 和 MEMORY
10. 保存版本快照
