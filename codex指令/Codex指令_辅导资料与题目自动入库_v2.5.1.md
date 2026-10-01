# Codex指令：辅导资料支持 + 题目自动入库 + 难度判定优化 + LLM模型适配
# 版本号：v2.5.1
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深全栈开发工程师，精通Streamlit、Python、LLM应用开发、教育业务逻辑。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v2.5.0，本次为辅导资料支持与题目自动入库，升级到v2.5.1。

## 任务目标
1. 支持辅导资料导入分类
2. 资料习题自动检测入库
3. 批改后题目自动入库
4. 题目来源追踪
5. 难度判定体系优化（不用得分率直接判定）
6. LLM模型配置体验优化（下拉选择、状态标注、能力说明）

---

## 第一部分：资料类型分类

### 1.1 数据库变更

**文件：models/models.py**

Textbook表增加字段：
```python
type = Column(String(20), default="textbook")  # textbook/workbook/exam_collection/lesson_plan/knowledge_summary
```

**文件：utils/db.py**

在待补列清单中增加textbooks表的type字段。

### 1.2 资料类型定义

**文件：utils/material_service.py 或新建utils/material_type_service.py**

定义资料类型常量：
```python
MATERIAL_TYPES = {
    "textbook": {"label": "📖 课本", "icon": "📖", "desc": "正规教材"},
    "workbook": {"label": "📚 练习册", "icon": "📚", "desc": "练习题集"},
    "exam_collection": {"label": "📄 试卷集", "icon": "📄", "desc": "试卷汇编"},
    "lesson_plan": {"label": "📋 教案", "icon": "📋", "desc": "教学设计"},
    "knowledge_summary": {"label": "📝 知识点总结", "icon": "📝", "desc": "知识梳理"},
}
```

### 1.3 导入时类型选择

**文件：modules/lesson_plan.py 的 tab_materials()**

在资料导入区域增加类型选择：
- 下拉选择资料类型（默认"课本"）
- 显示每种类型的说明
- 导入后自动设置类型

### 1.4 资料管理按类型筛选

**文件：modules/lesson_plan.py 的 _materials_browse_mode()**

在筛选区域增加：
- 类型筛选下拉框：全部 / 📖课本 / 📚练习册 / 📄试卷集 / 📋教案 / 📝知识点总结
- 与学科、年级筛选并列

### 1.5 资料列表显示类型图标

在资料列表中，资料名前显示类型图标。

---

## 第二部分：资料习题自动检测入库

### 2.1 题目识别功能

**文件：utils/question_extract_service.py（新建）**

新增函数：
```python
def extract_questions_from_material(material_id: int, chat_func) -> list[dict]:
    """从资料中提取题目，返回题目列表"""
    
def parse_question_structure(text: str) -> dict:
    """解析单道题的结构：题干、题型、选项、答案、解析"""
    
def estimate_question_difficulty(question: dict) -> dict:
    """AI多维度预估题目难度"""
```

### 2.2 题目识别流程

1. 用户在资料详情页点击"🔍 检测题目"
2. AI扫描资料内容，识别所有题目
3. 提取每道题的：题干、题型、难度、知识点、答案、解析
4. 显示识别结果预览列表
5. 用户可编辑修改每道题
6. 批量勾选审核
7. 确认后自动加入题库，标注来源

### 2.3 识别结果预览界面

**文件：modules/lesson_plan.py**

在资料详情页增加"检测题目"按钮，点击后显示：
- 识别进度条
- 题目列表（可编辑）：
  - 题号
  - 题干（可编辑）
  - 题型（下拉选择）
  - 难度（下拉选择）
  - 知识点（可编辑）
  - 答案（可编辑）
  - 勾选框（选择要入库的题目）
- 底部按钮：全选 / 全不选 / 确认入库 / 取消

### 2.4 题目来源标注

入库时自动设置：
- source_type = "material"
- source_id = 资料ID
- source_info = 资料名 + 页码

---

## 第三部分：批改后题目自动入库

### 3.1 批改完成提示

**文件：modules/homework.py 的 tab_grading_analysis()**

批改完成后，显示提示：
```
本次批改共XX道题，是否加入题库？
[全部加入] [只加高频错题] [只加易错题] [手动选择] [暂不加入]
```

### 3.2 题目提取

从批改数据中提取题目信息：
- 题干
- 题型
- 答案
- 知识点
- 批改数据（仅作参考标签）：
  - 本班得分率
  - 平均用时
  - 高频错题标记
  - 区分度

### 3.3 难度判定（优化后）

**重要：不用得分率直接判定难度**

使用AI多维度预估：
```python
def estimate_difficulty(question: dict) -> dict:
    """
    AI多维度预估难度，返回：
    - difficulty: 易/中/难
    - evidence: {
        "knowledge_complexity": "概念理解/简单应用/综合应用/创新应用",
        "step_count": 1/2-3/4+,
        "error_prone_points": 数量,
        "ai_estimate": "易/中/难"
    }
    """
```

难度维度：
| 维度 | 说明 | 占比 |
|------|------|------|
| AI预估难度 | AI根据题目内容综合判断 | 50% |
| 知识点复杂度 | 概念理解/简单应用/综合应用/创新应用 | 20% |
| 解题步骤数 | 1步/2-3步/4步以上 | 15% |
| 易错点数量 | 题目中容易出错的地方 | 10% |
| 教师手动调整 | 老师根据经验最终确认 | 5% |

AI预估标准：
- 易：单一知识点，直接套用，1-2步解答
- 中：1-2个知识点，简单变形，2-3步解答
- 难：多知识点综合，思路转换，4步以上

### 3.4 批改数据参考标签

批改数据**不参与难度计算**，仅作为参考标签显示：
- 本班得分率：XX%
- 平均用时：XX分钟
- 高频错题：是/否
- 区分度：高/中/低

老师可参考这些数据手动调整难度。

### 3.5 入库选项

- 全部加入题库
- 只加入高频错题（得分率<60%）
- 只加入好题（得分率60-80%且区分度高）
- 手动勾选加入

---

## 第四部分：题目来源追踪

### 4.1 数据库变更

**文件：models/models.py**

Question表增加字段：
```python
source_type = Column(String(20), default="manual")  # ai/manual/material/grading
source_id = Column(Integer, nullable=True)  # 来源ID（资料ID/作业ID）
source_info = Column(String(200), nullable=True)  # 来源详情
ai_difficulty = Column(String(10), nullable=True)  # AI预估难度
difficulty_evidence = Column(Text, nullable=True)  # 难度判定依据（JSON）
```

**文件：utils/db.py**

在待补列清单中增加这些字段。

### 4.2 来源类型定义

```python
QUESTION_SOURCES = {
    "ai": {"label": "🤖 AI生成", "icon": "🤖"},
    "manual": {"label": "✍️ 手动录入", "icon": "✍️"},
    "material": {"label": "📚 资料提取", "icon": "📚"},
    "grading": {"label": "📝 批改入库", "icon": "📝"},
}
```

### 4.3 题库管理增加来源筛选

**文件：modules/lesson_plan.py 的 tab_bank()**

在筛选区域增加：
- 来源筛选：全部 / 🤖AI生成 / ✍️手动录入 / 📚资料提取 / 📝批改入库

### 4.4 题目详情显示来源

在题目查看弹窗中显示：
- 来源类型和图标
- 来源详情（资料名+页码 / 作业名）
- 点击来源可跳转到对应资料/作业

---

## 第五部分：LLM模型配置体验优化

### 5.1 模型列表定义

**文件：utils/llm_client.py 或新建utils/model_registry.py**

定义常用模型列表：
```python
CHAT_MODELS = [
    {
        "id": "Doubao-Seed-2.1-pro",
        "name": "Doubao-Seed-2.1-pro",
        "status": "stable",  # stable/deprecated/offline
        "status_label": "✅稳定",
        "ability": "中文内容生成强，适合教案/出题",
        "speed": "中等",
        "context": "128K",
        "use_for": "content",  # main/content/both
    },
    {
        "id": "Doubao-Seed-2.1-lite",
        "name": "Doubao-Seed-2.1-lite",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "快速响应，适合分析总结",
        "speed": "快",
        "context": "128K",
        "use_for": "main",
    },
    {
        "id": "Doubao-Seed-2.0-pro",
        "name": "Doubao-Seed-2.0-pro",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "稳定通用",
        "speed": "中等",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "Doubao-Seed-2.0-lite",
        "name": "Doubao-Seed-2.0-lite",
        "status": "deprecated",
        "status_label": "⚠️即将下线（10月9日）",
        "ability": "轻量快速",
        "speed": "快",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "deepseek-chat",
        "name": "deepseek-chat",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "推理能力强",
        "speed": "中等",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "deepseek-reasoner",
        "name": "deepseek-reasoner",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "深度推理，适合难题",
        "speed": "慢",
        "context": "128K",
        "use_for": "content",
    },
    {
        "id": "custom",
        "name": "自定义输入...",
        "status": "custom",
        "status_label": "",
        "ability": "",
        "speed": "",
        "context": "",
        "use_for": "both",
    },
]

EMBED_MODELS = [
    {"id": "Doubao-embedding-vision", "name": "Doubao-embedding-vision", "status": "stable", "status_label": "✅稳定"},
    {"id": "Doubao-embedding-text", "name": "Doubao-embedding-text", "status": "stable", "status_label": "✅稳定"},
    {"id": "text-embedding-3-small", "name": "text-embedding-3-small", "status": "stable", "status_label": "✅稳定"},
    {"id": "custom", "name": "自定义输入...", "status": "custom", "status_label": ""},
]
```

### 5.2 设置页面模型下拉选择

**文件：modules/settings.py**

将模型名称的`text_input`改为`selectbox`：

主模型配置：
```python
model_choice = st.selectbox(
    "模型名称",
    options=[m["id"] for m in CHAT_MODELS],
    format_func=lambda x: next((f"{m['name']} {m['status_label']}" for m in CHAT_MODELS if m["id"] == x), x),
    index=default_index,
)
if model_choice == "custom":
    model = st.text_input("自定义模型名称", value=cfg.get("model", ""))
else:
    model = model_choice
    # 显示模型能力说明
    selected = next(m for m in CHAT_MODELS if m["id"] == model_choice)
    st.caption(f"能力：{selected['ability']}｜速度：{selected['speed']}｜上下文：{selected['context']}")
```

内容模型配置同理。

向量模型配置同理。

### 5.3 一键切换配置方案

在设置页面增加"快速配置方案"：
```python
preset = st.radio(
    "快速配置",
    ["均衡模式", "高质量模式", "低成本模式", "自定义"],
    horizontal=True,
)
if preset == "均衡模式":
    # 主模型lite + 内容模型pro
    st.info("主模型：Doubao-Seed-2.1-lite（快速）\n内容模型：Doubao-Seed-2.1-pro（高质量）")
elif preset == "高质量模式":
    # 都用pro
elif preset == "低成本模式":
    # 都用lite
```

### 5.4 更新默认配置

**文件：config.py**

```python
DEFAULT_API_BASE = "https://ark.cn-beijing.volces.com/api/plan/v3"
DEFAULT_MODEL = "Doubao-Seed-2.1-lite"
```

### 5.5 模型下线提醒

如果当前使用的模型状态为"deprecated"，在设置页面顶部显示警告：
```
⚠️ 当前使用的模型 Doubao-Seed-2.0-lite 即将于10月9日下线，建议切换到 Doubao-Seed-2.1-lite
[一键切换]
```

---

## 第六部分：通用要求

### 版本更新
- config.py中APP_VERSION改为"2.5.1"
- CHANGELOG.md新增v2.5.1记录

### 代码规范
- 新增服务放在utils/目录
- 题目提取逻辑封装为独立服务
- 难度判定逻辑封装为独立函数
- 模型列表定义为常量，方便维护
- 保持代码风格与现有代码一致

### 数据库迁移
- textbooks表增加type字段
- questions表增加source_type、source_id、source_info、ai_difficulty、difficulty_evidence字段
- 旧数据不受影响，新增字段默认为空
- 在utils/db.py的待补列清单中增加

### 验证要求
1. 语法检查：所有文件通过py_compile
2. 单元测试：运行pytest，新增功能编写测试
3. 功能验证：按各部分清单逐项验证
4. 数据库迁移验证：新增字段正确创建
5. LLM调用验证：模型切换后功能正常

### 备份
- 在versions/目录下创建v2.5.1_辅导资料与题目入库/文件夹
- 备份修改前的所有相关文件

### 不做的事情
- ❌ 不改变现有AI生成功能的业务逻辑
- ❌ 不改变题库管理的核心功能
- ❌ 不升级技术栈
- ❌ 不新增学生端功能

---

## 执行顺序
1. 备份当前版本到versions/
2. 数据库迁移：textbooks和questions表增加字段
3. 资料类型分类（类型定义、导入选择、筛选、显示）
4. 题目来源追踪（来源类型、筛选、详情显示）
5. 难度判定体系优化（AI多维度预估、批改数据参考标签）
6. 资料习题自动检测入库（识别服务、预览界面、批量审核）
7. 批改后题目自动入库（批改完成提示、选择性入库）
8. LLM模型配置优化（模型列表、下拉选择、能力说明、一键切换、下线提醒）
9. 逐项功能验证
10. 运行语法检查和单元测试
11. 更新版本号和CHANGELOG
12. 输出修改完成报告
