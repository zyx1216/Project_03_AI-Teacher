# Codex指令：代码质量提升 v3.0.0

## 角色
你是资深Python架构师，负责「AI教学辅助」项目的代码质量提升。当前版本v2.9.1，目标版本v3.0.0。

## 项目信息
- 项目路径：D:\Codex\Project_03_AI数学教师工作台
- 技术栈：Streamlit + Python + SQLite + SQLAlchemy + LLM API
- 数据库：data/database.db，30张表

## 当前问题
1. lesson_plan.py 约4000行，过于庞大
2. homework.py 约3600行，过于庞大
3. 部分模块职责不清晰
4. 缺少统一的代码规范
5. 部分核心逻辑缺少注释

## 本次目标
在不改变任何功能的前提下，提升代码可维护性，为后续Agent深化打基础。

---

## 任务1：拆分大文件

### 1.1 拆分 lesson_plan.py（备课区）
按子功能拆分为以下模块，放在 modules/lesson/ 目录下：

```
modules/lesson/
├── __init__.py          # 导出show()函数，保持原入口不变
├── material_tab.py      # 资料管理Tab
├── lesson_plan_tab.py   # AI备课Tab
├── question_gen_tab.py  # AI出题Tab
├── question_bank_tab.py # 题库管理Tab
├── unit_design_tab.py   # 单元整体设计Tab
└── common.py            # 公共组件（学科切换、年级切换等）
```

**要求**：
- 原 modules/lesson_plan.py 保留，只做入口转发（from modules.lesson import show）
- 每个Tab文件包含该Tab的所有UI逻辑
- common.py 放跨Tab复用的组件
- 所有import路径正确，不破坏现有功能

### 1.2 拆分 homework.py（学业测评区）
按子功能拆分为以下模块，放在 modules/assessment/ 目录下：

```
modules/assessment/
├── __init__.py          # 导出show()函数
├── homework_tab.py      # 作业管理Tab
├── smart_compose_tab.py # 智能组卷Tab
├── grading_tab.py       # 批改与分析Tab
├── wrong_book_tab.py    # 错题本Tab
├── layered_tab.py       # 分层作业Tab
└── common.py            # 公共组件
```

**要求**：
- 原 modules/homework.py 保留，只做入口转发
- 每个Tab文件包含该Tab的所有UI逻辑
- 所有import路径正确

### 1.3 拆分 analysis.py（学情区）
按子功能拆分为以下模块，放在 modules/analytics/ 目录下：

```
modules/analytics/
├── __init__.py           # 导出show()函数
├── student_tab.py        # 学生管理Tab
├── score_tab.py          # 成绩管理Tab
├── exam_analysis_tab.py  # 考试分析Tab
├── trend_tab.py          # 趋势分析Tab
├── diagnosis_tab.py      # AI教学诊断Tab
└── common.py             # 公共组件
```

---

## 任务2：统一代码规范

### 2.1 统一异常处理
- 所有AI调用必须使用utils/error_handler.py的统一异常处理
- 所有文件操作必须有try-except，给用户友好中文提示
- 禁止裸except，必须指定异常类型

### 2.2 统一日志
- 关键操作（AI调用、数据库写入、文件生成）必须有日志
- 使用logging模块，统一格式
- 日志级别：INFO（正常操作）、WARNING（可恢复问题）、ERROR（失败）

### 2.3 统一常量
- 学科列表、年级列表、难度等级等常量统一放在utils/constants.py
- 各模块从constants导入，不硬编码

### 2.4 统一类型注解
- 所有函数添加类型注解（参数和返回值）
- 复杂数据结构用TypedDict或dataclass定义

---

## 任务3：补充核心注释

### 3.1 核心服务模块注释
以下模块的核心函数必须有详细docstring：
- utils/llm_client.py：每个函数说明用途、参数、返回值
- utils/question_service.py：题目生成、难度判定逻辑
- utils/grading_service.py：批改逻辑
- utils/rag_service.py：检索逻辑
- utils/knowledge_graph_service.py：图谱构建逻辑

### 3.2 复杂算法注释
- 难度判定算法（AI预估50%+知识点复杂度20%+步骤数15%+易错点10%+老师5%）
- 分层作业算法
- 知识点掌握度计算
- 趋势分析算法

---

## 任务4：项目结构优化

### 4.1 整理utils目录
按功能分类：
```
utils/
├── ai/              # AI相关（llm_client, rag_service, knowledge_graph）
├── data/            # 数据处理（excel_handler, pdf_parser, ocr_service）
├── business/        # 业务逻辑（question_service, grading_service）
├── ui/              # UI辅助（chart_service, full_score_service）
└── core/            # 核心（db, config, error_handler, cache_service）
```

**注意**：为避免大量import修改，可先在utils/__init__.py中做兼容导出，后续逐步迁移。

### 4.2 整理配置
- config.py集中管理所有配置项
- 移除硬编码的路径、URL、超时时间
- 支持环境变量覆盖

---

## 验收标准

1. ✅ 所有原有功能完全不变（用户感知不到差异）
2. ✅ lesson_plan.py/homework.py/analysis.py拆分为子模块
3. ✅ 原入口文件保留，只做转发
4. ✅ 所有模块可正常import，无循环依赖
5. ✅ 语法检查通过（py_compile全项目）
6. ✅ 应用可正常启动（streamlit run app.py）
7. ✅ 核心函数有docstring
8. ✅ 无裸except
9. ✅ 版本号改为3.0.0
10. ✅ 更新CHANGELOG.md

## 注意事项
- **绝对不能改变任何功能逻辑**，只做代码结构调整
- 拆分过程中保持变量名、函数名不变
- 每拆分一个文件就测试一次，确保不破坏功能
- 数据库操作保持不变
- AI调用逻辑保持不变

## 执行后输出
- 版本号、新增目录结构、拆分文件列表、测试结果
