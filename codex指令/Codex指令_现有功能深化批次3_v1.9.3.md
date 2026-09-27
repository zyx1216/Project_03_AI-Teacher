# Codex指令：现有功能深化（批次3）—— 教学反思改进闭环
# 版本号：v1.9.3
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深AI Agent开发工程师，精通Streamlit+Python+SQLite+LLM API开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.2，本次升级到v1.9.3。

## 项目结构说明
- 入口：app.py
- 学情区：modules/analysis.py（含教学反思功能，当前在tab_reflection函数）
- 服务层：utils/reflection_service.py（现有教学反思服务）
- 数据库：data/database.db
- LLM调用：utils/llm_client.py

## 本次升级目标
将教学反思从"一次性生成文本"升级为"反思→计划→执行→验证"完整闭环：
1. 反思生成后可制定改进计划
2. 改进计划关联下次验证考试
3. 下次考试后自动验证改进效果
4. 形成可追溯的教学改进历史

---

## 功能：教学反思改进闭环

### 1. 数据库设计

#### 1.1 新增表：reflection_plans（改进计划表）
```sql
CREATE TABLE IF NOT EXISTS reflection_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reflection_id INTEGER NOT NULL,  -- 关联teaching_reflections.id
    content TEXT NOT NULL,           -- 改进措施内容（JSON数组，每条含措施、负责方式、预期效果）
    verify_exam_id INTEGER,          -- 验证考试ID（关联exams.id）
    status TEXT DEFAULT 'pending',   -- pending待验证 / verified已验证 / expired已过期
    created_at TEXT,
    verified_at TEXT,
    verify_result TEXT,              -- 验证结果（JSON，含各措施效果评估）
    FOREIGN KEY (reflection_id) REFERENCES teaching_reflections(id),
    FOREIGN KEY (verify_exam_id) REFERENCES exams(id)
);
```

#### 1.2 修改表：teaching_reflections
新增字段：
- has_plan INTEGER DEFAULT 0  -- 是否有关联改进计划（0无，1有）

### 2. 功能流程

#### 2.1 生成反思后制定改进计划
1. 用户在教学反思页生成反思内容后
2. 在反思内容下方新增"📋 制定改进计划"按钮
3. 点击后弹出对话框：
   - AI根据反思内容自动生成3-5条改进措施（可编辑）
   - 每条措施包含：
     - 措施内容（文本框，可编辑）
     - 实施方式（下拉：课堂调整 / 作业优化 / 个别辅导 / 其他）
     - 预期效果（文本框，可编辑）
   - 选择验证考试：下拉框，选择未来的某次考试（从exams表中选日期在反思之后的考试）
   - 确认按钮："保存改进计划"

#### 2.2 改进计划展示
1. 保存后，在反思详情中显示改进计划区域
2. 展示内容：
   - 改进措施列表（编号、内容、实施方式、预期效果）
   - 验证考试信息（考试名称、时间）
   - 当前状态：待验证（黄色标签）/ 已验证（绿色标签）/ 已过期（灰色标签）
3. 操作按钮：
   - 编辑计划（仅待验证状态可编辑）
   - 删除计划
   - 手动标记已验证（如果不想等考试自动验证）

#### 2.3 自动验证改进效果
1. 当验证考试的成绩录入完成后
2. 系统自动触发验证（在成绩导入成功后检查是否有关联的待验证计划）
3. 验证逻辑：
   - 对比反思对应的考试（前一次）和验证考试（后一次）的成绩
   - 针对反思中提到的薄弱知识点/班级/学生，对比两次考试的掌握率变化
   - AI生成验证报告：
     - 整体效果：有效 / 部分有效 / 效果不明显
     - 每条措施的效果评估：达到预期 / 部分达到 / 未达到
     - 数据支撑：具体的分数变化、掌握率变化
     - 后续建议：继续坚持 / 需要调整 / 放弃该措施
4. 验证完成后，计划状态变为"已验证"，保存验证结果

#### 2.4 改进历史追踪
1. 在教学反思页新增"📚 改进历史"Tab
2. 展示所有已完成的反思→计划→验证闭环
3. 每条记录显示：
   - 反思时间、对应考试
   - 核心问题（一句话摘要）
   - 改进措施数量
   - 验证结果（有效/部分有效/效果不明显）
   - 查看详情按钮
4. 支持按学科、时间范围筛选
5. 支持导出"教学改进年度报告"（Word格式，汇总所有闭环记录）

### 3. 技术实现

#### 3.1 服务层函数（utils/reflection_service.py新增）
```python
def generate_improvement_plan(reflection_content, subject) -> list[dict]:
    """AI根据反思内容生成改进措施"""

def save_plan(session, reflection_id, measures, verify_exam_id) -> int:
    """保存改进计划"""

def get_plan_by_reflection(session, reflection_id) -> dict | None:
    """获取某反思的改进计划"""

def update_plan(session, plan_id, measures, verify_exam_id) -> None:
    """更新改进计划"""

def delete_plan(session, plan_id) -> None:
    """删除改进计划"""

def verify_plan(session, plan_id) -> dict:
    """执行验证，对比两次考试成绩，AI生成验证报告"""

def check_and_verify_pending_plans(session, exam_id) -> list[int]:
    """检查某考试是否有关联的待验证计划，有则自动验证"""

def get_improvement_history(session, subject=None, start_date=None, end_date=None) -> list[dict]:
    """获取改进历史列表"""

def export_improvement_report(session, plans) -> bytes:
    """导出教学改进年度报告Word"""
```

#### 3.2 LLM Prompt设计

**生成改进措施：**
- 系统提示：你是一名资深教学研究员，擅长根据教学反思提出具体可操作的改进措施。
- 用户提示：包含反思内容、学科、班级情况
- 输出格式：JSON数组，每条含measure（措施）、method（实施方式）、expected_effect（预期效果）

**验证报告生成：**
- 系统提示：你是一名教学评估专家，根据数据评估教学改进措施的效果。
- 用户提示：包含改进措施、前次考试数据、验证考试数据、知识点掌握率变化
- 输出格式：JSON，含overall_effect、measure_effects（数组）、data_support、suggestions

#### 3.3 自动验证触发点
在modules/analysis.py的成绩导入函数（tab_score_import）中，导入成功后调用：
```python
from utils import reflection_service
reflection_service.check_and_verify_pending_plans(session, exam_id)
```

### 4. UI要求

#### 4.1 改进计划展示
- 用st.container(border=True)包裹
- 措施列表用编号列表，每条措施一个st.expander
- 状态标签用st.markdown彩色文字
- 验证考试信息用st.caption显示

#### 4.2 验证报告展示
- 整体效果用大字号+颜色：有效（绿色）、部分有效（橙色）、效果不明显（红色）
- 每条措施效果用进度条（st.progress）展示达成度
- 数据支撑用表格展示
- 后续建议用蓝色提示框

#### 4.3 改进历史
- 用st.dataframe展示列表
- 查看详情用st.dialog弹窗
- 筛选条件放在表格上方，用st.columns布局

### 5. 数据迁移
- 现有teaching_reflections表的记录，has_plan字段默认0
- 不需要迁移历史数据，新功能从新反思开始使用

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.3"
- CHANGELOG.md新增v1.9.3更新记录

### 代码规范
- 所有新增函数必须有中文注释
- LLM调用必须有超时处理和异常捕获
- 数据库操作必须用ORM，禁止裸SQL
- 新增表必须在utils/db.py的init_db函数中创建

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 生成反思后能看到"制定改进计划"按钮
4. 能生成并保存改进计划，选择验证考试
5. 验证考试成绩导入后能自动生成验证报告
6. 改进历史页能看到已完成的闭环记录
7. 能导出教学改进报告Word

### 历史版本
- 在versions/目录下创建v1.9.3_现有功能深化批次3/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 数据库新增表和字段
4. 实现服务层函数
5. 实现UI层
6. 接入自动验证触发点
7. 更新CHANGELOG.md
8. 语法验证
9. 启动测试
