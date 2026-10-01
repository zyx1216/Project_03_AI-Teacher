# Codex指令：教师端功能补全（第二批）v2.9.1

## 角色
你是资深AI Agent开发工程师，负责完善「AI教学辅助」项目。当前版本v2.9.0，目标版本v2.9.1。

## 项目信息
- 项目路径：D:\Codex\Project_03_AI数学教师工作台
- 技术栈：Streamlit + Python + SQLite + SQLAlchemy + LLM API
- 数据库：data/database.db

## 本次实现2个功能

---

## 功能4：AI教学诊断

### 功能描述
综合成绩、作业、课堂数据，AI自动诊断教学问题，给出改进建议和下阶段教学重点，支持历史对比。

### 实现细节

#### 4.1 学情区增加「AI教学诊断」子功能
- 在「学情」区域增加「🔍 AI教学诊断」Tab
- 与学生管理、成绩管理、考试分析、趋势分析、学生画像并列

#### 4.2 诊断数据采集
- 综合分析维度：
  - 成绩数据：历次考试成绩、趋势、班级排名
  - 作业数据：完成率、正确率、提交及时性
  - 知识点掌握：知识点掌握度热力图、薄弱知识点
  - 教学进度：计划进度 vs 实际进度
- 新增utils/diagnosis_service.py
- 核心函数：collect_diagnosis_data(class_name, subject, grade)

#### 4.3 AI诊断生成
- AI综合分析生成诊断报告，包含：
  - 教学整体评价（优秀/良好/需改进）
  - 教学进度分析（过快/正常/过慢）
  - 知识点掌握情况（已掌握/薄弱/未覆盖）
  - 学生分层情况（各层人数、特点）
  - 存在的问题（3-5个具体问题）
  - 改进建议（每个问题对应具体建议）
  - 下阶段教学重点（3-5个重点）
- 支持选择诊断范围：单次考试/近一个月/近一学期/自定义

#### 4.4 诊断报告展示
- 报告结构清晰，分模块展示
- 支持导出PDF/Word
- 关键数据用图表展示（知识点掌握雷达图、学生分层饼图）

#### 4.5 历史诊断与对比
- 新增teaching_diagnosis表：
  - id, class_name, subject, grade, period, report_content, score, created_at
- 支持查看历史诊断记录
- 支持两次诊断对比：哪些问题改善了、哪些还存在、新出现的问题
- 诊断评分（1-100分），趋势图展示

#### 4.6 诊断建议落地
- 每条改进建议支持「生成对应教案」「生成专项练习」「加入教学计划」
- 点击后跳转到对应功能并预填参数

---

## 功能5：单元整体设计

### 功能描述
按教材单元，一次性生成整个单元的系列教案+课时安排+单元测试，支持进度跟踪。

### 实现细节

#### 5.1 备课区增加「单元整体设计」子功能
- 在「备课」区域增加「📚 单元整体设计」Tab
- 与资料管理、AI备课、AI出题、题库管理并列

#### 5.2 单元选择与目标生成
- 选择学科、年级、教材资料
- 选择具体单元（从资料目录中选择）
- AI自动生成单元教学目标：
  - 知识与技能目标
  - 过程与方法目标
  - 情感态度与价值观目标
  - 单元重点难点
  - 课时分配建议

#### 5.3 课时拆分与系列教案
- 按课时拆分单元内容（如6课时）
- 每课时自动生成：
  - 教案（教学目标、重难点、教学过程、板书设计、作业布置）
  - PPT大纲（可选生成完整PPT）
  - 课堂练习
  - 课后作业
- 支持单课时重新生成、编辑
- 支持调整课时顺序、增删课时

#### 5.4 单元测试生成
- 自动生成单元测试卷：
  - 覆盖单元所有知识点
  - 难度分布合理（易:中:难 = 3:5:2）
  - 题型完整（选择、填空、解答等）
  - 含答案和解析
- 支持手动调整题目

#### 5.5 单元进度跟踪
- 新增unit_plans表：
  - id, name, subject, grade, textbook_id, chapter, objectives, lesson_count, status, created_at
- 新增unit_lessons表：
  - id, unit_id, lesson_index, title, plan_id, ppt_path, status, completed_at
- 单元设计列表显示：单元名、学科、课时数、完成进度（X/Y课时）
- 每课时标记状态：未开始/进行中/已完成
- 支持一键标记课时完成，自动更新单元进度
- 进度可视化（进度条）

#### 5.6 单元设计管理
- 支持查看单元详情（所有课时列表）
- 支持导出整个单元的教案合集（Word）
- 支持复制单元设计（用于其他班级）
- 支持删除单元设计

---

## 数据库变更

### 新增表
1. teaching_diagnosis（教学诊断记录）
   - id, class_name, subject, grade, period, report_content, score, created_at
2. unit_plans（单元设计）
   - id, name, subject, grade, textbook_id, chapter, objectives, lesson_count, status, created_at
3. unit_lessons（单元课时）
   - id, unit_id, lesson_index, title, plan_id, ppt_path, status, completed_at

### 修改表
- 无

### 执行方式
- 新表在models中定义，init_db()时自动创建
- 写迁移脚本migrations/v2_9_1_migration.py

---

## 代码规范要求

1. 所有新功能写在独立的utils服务模块中，UI逻辑写在modules对应页面
2. 复用现有组件：lesson_service、ppt_generator、question_service、llm_client、chart_service
3. AI调用统一走utils/llm_client.py，支持超时和降级
4. 错误处理友好，不泄露技术细节
5. 所有新功能写单元测试，放在tests/test_v291.py
6. 更新CHANGELOG.md、README.md
7. 版本号改为2.9.1

---

## 验收标准

1. AI教学诊断：选择班级学科→生成诊断报告→查看历史→对比两次诊断→导出报告
2. 单元整体设计：选择单元→生成教学目标→拆分课时→生成系列教案→生成单元测试→跟踪课时进度
3. 单元测试通过，无新增bug
4. 现有功能不受影响

## 执行后输出
- 版本号、新增文件列表、数据库变更、测试结果
