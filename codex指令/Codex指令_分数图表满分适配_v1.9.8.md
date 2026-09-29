# Codex指令：分数图表满分适配优化
# 版本号：v1.9.8
# 执行方式：将本文件内容全部复制到Codex对话框执行

## 角色设定
你是一名资深全栈开发工程师，精通数据可视化、Streamlit+Python+SQLite+Plotly开发。
当前项目是面向中小学教师的AI教学辅助系统，路径：D:\Codex\Project_03_AI数学教师工作台
当前版本v1.9.7，本次升级到v1.9.8。

## 问题背景
当前数据看板的分数图表存在以下问题：
1. 雷达图硬编码满分（语数英150，其他100），没有从考试配置读取
2. 分数段分布按固定分数段（0-59, 60-69...），不适合不同满分
3. 各科对比柱状图显示原始分，不同满分无法直接对比
4. 没有考虑不同年级学科不同、满分不同的情况

## 项目结构说明
- 数据看板：modules/databoard.py
- 数据服务：utils/databoard_service.py
- 图表服务：utils/chart_service.py（ability_radar已支持full_scores参数）
- 考试表：exams.full_scores字段（JSON格式，如{"语文":150,"数学":150,"英语":150,"物理":100}）
- 考试服务：utils/exam_service.py

## 本次优化目标
所有与分数有关的图表统一使用"得分率"（实际分数/满分×100%），适配不同年级、不同学科、不同满分。

---

## 修改1：数据层——_subject_compare返回满分

### 文件：utils/databoard_service.py

### 1.1 新增满分获取函数
```python
def get_subject_full_scores(session, exam_ids=None, grade=None):
    """获取各科满分配置。
    优先级：筛选范围内考试的full_scores > 年级默认满分 > 全部100分
    返回：{学科: 满分}
    """
    # 1. 从考试full_scores读取（取最近一次有配置的考试）
    # 2. 如果没有，按年级默认：
    #    - 小学（一到六年级）：语数英100
    #    - 初中（初一到初三）：语数英150，其他100
    #    - 高中（高一到高三）：语数英150，其他100
    # 3. 都没有则全部100
```

### 1.2 修改_subject_compare函数
当前返回：[{"subject": "语文", "average": 104.2}, ...]
修改后返回：[{"subject": "语文", "average": 104.2, "full_score": 150, "rate": 69.5}, ...]
- average：原始平均分
- full_score：该科满分
- rate：得分率（average/full_score×100，保留1位小数）

### 1.3 修改_score_bands函数
当前按固定分数段（0-59, 60-69...）
修改为按得分率分段：
- 不及格（0-60%）
- 及格（60-70%）
- 中等（70-80%）
- 良好（80-90%）
- 优秀（90-100%）

需要先将每行的score转为得分率（需要知道该科满分），然后统计各段人数。

### 1.4 修改collect_rows函数
每行增加full_score字段，方便后续计算得分率。

---

## 修改2：图表层——所有分数图表使用得分率

### 文件：modules/databoard.py

### 2.1 雷达图（_radar_fig）
当前：硬编码满分
修改：从subject_compare数据中提取full_scores，传给chart_service.ability_radar

```python
def _radar_fig(subject_rows):
    subjects = [r["subject"] for r in subject_rows]
    full_scores = {r["subject"]: r.get("full_score", 100) for r in subject_rows}
    row = {"name": "全体平均"}
    for r in subject_rows:
        row[r["subject"]] = r["average"]
    return chart_service.ability_radar([row], subjects, full_scores=full_scores)
```

### 2.2 各科对比柱状图（_subject_compare_fig）
当前：显示原始平均分
修改：显示得分率，悬停时显示原始分/满分

```python
def _subject_compare_fig(rows):
    fig = go.Figure(go.Bar(
        x=[r["subject"] for r in rows],
        y=[r.get("rate", r["average"]) for r in rows],  # 显示得分率
        text=[f"{r['average']}/{r.get('full_score',100)}" for r in rows],
        hovertemplate="%{x}<br>得分率：%{y}%<br>原始分：%{text}<extra></extra>"))
    fig.update_layout(
        title="各学科得分率对比", xaxis_title="学科", yaxis_title="得分率(%)",
        yaxis=dict(range=[0, 100]), height=380)
    return fig
```

### 2.3 分数段分布（_bands_fig）
当前：显示固定分数段
修改：显示得分率分段，标题改为"得分率分布"

### 2.4 班级趋势折线图（_class_trend_fig）
当前：显示原始平均分
修改：增加"显示得分率"切换按钮，默认显示原始分，可切换为得分率
- 原始分模式：y轴显示平均分
- 得分率模式：y轴显示得分率（需要每场考试的满分配置）

如果实现复杂，可先保持原始分，但在悬停时显示得分率。

---

## 修改3：满分配置界面（可选，优先级低）

### 文件：modules/settings.py 或 modules/analysis.py

在设置页或学情区增加"学科满分配置"：
- 按年级设置各科满分
- 支持自定义（如物理80分、化学70分等）
- 保存到配置文件data/full_score_config.json
- 考试创建时默认使用该配置

如果工作量大，本次可暂不做，优先保证数据看板图表正确。

---

## 通用要求

### 版本号更新
- config.py中APP_VERSION改为"1.9.8"
- CHANGELOG.md新增v1.9.8更新记录

### 代码规范
- 所有新增函数必须有中文注释
- 得分率计算必须处理满分=0的除零情况
- 满分缺失时默认100，不能报错
- 图表必须有标题、坐标轴标签
- 悬停信息必须完整（学科、原始分、满分、得分率）

### 验证要求
1. 运行python -m py_compile检查所有修改文件语法
2. 启动streamlit run app.py，确认无报错
3. 数据看板雷达图：9科都有连接点，悬停显示"语文：104.2/150分（70%）"
4. 数据看板各科对比：y轴显示得分率0-100%，悬停显示原始分
5. 数据看板分数段分布：显示"不及格/及格/中等/良好/优秀"五段
6. 切换不同年级数据时，满分自动适配
7. 没有满分配置时，默认100分制，不报错

### 历史版本
- 在versions/目录下创建v1.9.8_分数图表满分适配/文件夹
- 将修改前的关键文件复制进去作为备份

---

## 执行顺序
1. 先备份当前版本到versions/
2. 修改config.py版本号
3. 实现get_subject_full_scores函数
4. 修改_subject_compare返回满分和得分率
5. 修改_score_bands按得分率分段
6. 修改collect_rows增加full_score字段
7. 修改_radar_fig传入实际满分
8. 修改_subject_compare_fig显示得分率
9. 修改_bands_fig显示得分率分段
10. （可选）增加满分配置界面
11. 更新CHANGELOG.md
12. 语法验证
13. 启动测试


---

## 修改4：学情分析（analysis.py）所有分数图表适配

### 文件：modules/analysis.py

学情分析是分数图表最多的模块，以下所有涉及分数的图表都需要适配满分：

### 4.1 考试分析模块
- **班级对比柱状图**（约1196行）：显示得分率而非原始分，悬停显示原始分/满分
- **分数段分布图**（约1298行）：按得分率分段（不及格/及格/中等/良好/优秀）
- **各科对比图**（约1315行）：y轴显示得分率0-100%
- **排名图**（约1364行）：可保持原始分，但需标注满分
- **雷达图**（约1381行）：使用实际满分计算得分率

### 4.2 趋势分析模块
- **班级趋势折线图**（约1722行）：增加得分率显示模式，或悬停时显示得分率
- **学生个人趋势图**（约1749-1763行）：单科趋势显示得分率，总分趋势保持原始分
- **单科趋势图**（约1812-1845行）：y轴显示得分率
- **总分趋势图**（约1846行）：保持原始分，但需考虑不同考试总分可能不同

### 4.3 学生画像模块
- **能力雷达图**（约1938行）：使用实际满分计算得分率
- **得分率仪表盘**（约2656-2668行）：已使用得分率，确认满分来源正确

### 4.4 知识图谱模块
- **掌握度热力图**（约2732-2867行）：已基于作业答题得分率，确认逻辑正确

### 4.5 通用要求
- 所有图表的悬停信息必须包含：学科、原始分、满分、得分率
- 单科图表默认显示得分率，总分图表可显示原始分
- 满分从对应考试的full_scores字段读取，没有则用年级默认值
- 不同考试满分不同时，趋势图需注明"各次考试满分可能不同"

---

## 修改5：学业测评（homework.py）分数图表适配

### 文件：modules/homework.py

### 5.1 作业分析模块
- **得分分布图**（约1803行）：按得分率分段
- **班级对比图**（约1826行）：显示得分率
- **题目正确率图**（约1842行）：已是百分比，无需修改
- **知识点掌握图**（约1889行）：已是百分比，无需修改

### 5.2 错题本模块
- **错题分布图**（约2063行）：按知识点统计，不涉及满分，无需修改

### 5.3 通用要求
- 作业分数图表需要考虑作业满分（从homework_questions的full_score汇总）
- 作业得分率 = 学生得分 / 作业总分 × 100%
- 悬停信息显示：原始得分/作业总分（得分率）

---

## 修改6：统一满分服务层

### 文件：utils/full_score_service.py（新建）

为避免各模块重复实现满分获取逻辑，新建统一的满分服务：

```python
def get_exam_full_scores(session, exam_id) -> dict:
    """获取指定考试的各科满分配置"""

def get_grade_default_full_scores(grade: str) -> dict:
    """获取年级默认满分配置
    小学（一到六年级）：语文100、数学100、英语100
    初中（初一到初三）：语文150、数学150、英语150、物理100、化学100、生物100、政治100、历史100、地理100
    高中（高一到高三）：语文150、数学150、英语150、物理100、化学100、生物100、政治100、历史100、地理100
    """

def get_subject_full_score(session, subject: str, exam_id=None, grade=None) -> float:
    """获取单个学科的满分，优先级：考试配置 > 年级默认 > 100"""

def calc_rate(score: float, full_score: float) -> float:
    """计算得分率，处理除零和空值"""

def rate_bands() -> list:
    """返回标准得分率分段：不及格(0-60)、及格(60-70)、中等(70-80)、良好(80-90)、优秀(90-100)"""
```

所有模块统一调用此服务，避免重复代码和不一致。

---

## 修改7：首页仪表盘（dashboard.py）检查

### 文件：modules/dashboard.py

检查首页是否有分数相关的展示：
- 核心指标卡片（平均分、及格率、优秀率）：确认使用了正确的满分计算
- 如有分数图表，同样需要适配

---

## 完整修改清单汇总

| 优先级 | 文件 | 修改内容 |
|--------|------|----------|
| P0 | utils/full_score_service.py | 新建统一满分服务 |
| P0 | utils/databoard_service.py | 数据层返回满分和得分率 |
| P0 | modules/databoard.py | 数据看板所有图表适配 |
| P0 | modules/analysis.py | 学情分析所有分数图表适配 |
| P1 | modules/homework.py | 作业分析分数图表适配 |
| P1 | modules/dashboard.py | 首页分数展示检查 |
| P2 | modules/settings.py | 满分配置界面（可选） |

## 执行策略
由于涉及文件多、修改量大，建议按以下顺序执行：
1. 先新建full_score_service.py（基础服务）
2. 修改databoard_service.py和databoard.py（数据看板，已规划）
3. 修改analysis.py（学情分析，最大量）
4. 修改homework.py（学业测评）
5. 检查dashboard.py
6. 统一测试验证

## 验证要求（补充）
除数据看板外，还需验证：
- 学情分析→考试分析：各科对比显示得分率，分数段按得分率分段
- 学情分析→趋势分析：单科趋势显示得分率，悬停显示原始分
- 学情分析→学生画像：雷达图使用实际满分
- 学业测评→作业分析：得分分布按得分率分段
- 所有图表悬停信息完整（学科、原始分、满分、得分率）
- 切换不同年级/考试时，满分自动适配
