# -*- coding: utf-8 -*-
"""
生成《AI 数学教师工作台 · 功能说明》PDF（阶段 5，v1.0.1 文档版）。

- 纯文档脚本，不改任何业务代码、不调用 LLM、不新增第三方依赖；
- 用已安装的 PyMuPDF Story（HTML/CSS 排版）渲染，微软雅黑嵌入并子集化；
- 各版本功能以本文件顶部的结构化常量维护（整理自 CHANGELOG.md，不解析自由文本），
  以后新增版本时在 VERSIONS 里追加一节并重跑本脚本即可。

运行：
    python scripts/generate_feature_pdf.py
输出：
    docs/功能说明_v<版本号>.pdf          （入库的正式交付件）
    data/exports/功能说明_v<版本号>.pdf   （日常取用副本）
"""

from __future__ import annotations

import gc
import html
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

# 让脚本能 import 项目根的 config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402  PyMuPDF

import config  # noqa: E402

# 系统自带微软雅黑（常规 + 粗体）。不把字体文件复制进仓库，仅在生成时读取。
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
PRIMARY = "#1F4E79"   # 与教案 PPT、图表一致的深蓝
HEADER_BG = "#DEEAF6"  # 表头浅蓝

# ---------------------------------------------------------------------------
# 版本功能数据（整理自 CHANGELOG：只记“功能”，不记测试数/已知取舍/文件清单）
# 字段：id 版本号 / when 日期 / stage 阶段名 / tables 当时数据表数 /
#       core 核心交付（总览表用）/ groups 分组功能要点
# ---------------------------------------------------------------------------
VERSIONS = [
    {
        "id": "v0.1",
        "when": "2026-09-18",
        "stage": "阶段 0 · 项目骨架",
        "tables": "9 张",
        "core": "可运行骨架：环境装齐、4 页面可切换、9 张表建好",
        "groups": [
            ("运行环境", [
                "新建 conda 环境 math_teacher（Python 3.11），12 个核心依赖一次装齐并用 == 锁定版本。",
                "streamlit run app.py 启动，浏览器访问本机 8501 端口无报错。",
            ]),
            ("页面与数据库", [
                "侧边栏 4 个主页面：备课、作业、学情、设置，可点击切换，各页先放占位内容。",
                "学生、考试、成绩、题目、作业、作业题目、作业成绩、教案、资料共 9 张数据表一次建好。",
                "题目答案设为必填（数据库层非空约束）；同考试同学生同科目唯一，防止成绩重复录入。",
                "启动时幂等建表：表不存在才创建，已有数据不被破坏。",
            ]),
        ],
    },
    {
        "id": "v0.2",
        "when": "2026-09-18",
        "stage": "阶段 1 · 学情工作台（成绩分析）",
        "tables": "9 张",
        "core": "学生成绩 Excel 导入、统计分析、趋势画像、AI 总结、模型配置",
        "groups": [
            ("学生与成绩管理", [
                "学生和成绩均可 Excel 批量导入，表头模糊识别，先出预览和字段映射、确认后才写库。",
                "系统里没有的学生导入成绩时自动新建；同一考试重复导入按更新处理。",
                "支持手动新增、修改学生和成绩。",
            ]),
            ("考试分析", [
                "均分、中位数、标准差、最高最低、及格率、优秀率、参考人数等指标一次出齐。",
                "分数段柱状图、各科占比图；班内并列同名次排名。",
                "与上一场考试比进退步，进步标绿、退步标红。",
            ]),
            ("趋势与画像", [
                "班级均分趋势、单个学生历次总分和单科折线，可选最近 3 次、5 次或全部。",
                "学生画像：信息卡、各科得分率雷达图、成绩层次与进步趋势等自动标签、强弱科提示。",
                "考试分析和学生画像各有一处 AI 自然语言总结；未配置 Key 时明确提示而不报错。",
            ]),
            ("模型与配置", [
                "设置页配置主模型 Base URL、模型名和 API Key，支持一键测试连接。",
                "Key 存 Windows 凭据管理器，非敏感配置存本地；提供 2 班 30 人示例数据生成脚本。",
            ]),
        ],
    },    {
        "id": "v0.3",
        "when": "2026-09-18",
        "stage": "阶段 2 · 备课工作台 + 题库",
        "tables": "9 张",
        "core": "资料 RAG 检索、AI 教案与出题、题库管理、离线 PPT",
        "groups": [
            ("教学资料与检索", [
                "上传 PDF、Word 课本或直接粘贴文本，自动提取全文并按章节切分、预览。",
                "章内按约 500 字切块、相邻块保留重叠，向量化后状态变为已向量化。",
                "检索三级降级：云端中文向量 → 本地向量模型 → 纯关键词重叠，未配置向量模型也能备课。",
                "检索取最相关的片段并标明来源，作为数据随提问传给模型。",
            ]),
            ("AI 备课", [
                "输入课题、年级、章节、课时和教学风格，生成结构完整的教案。",
                "含三维目标、重点、难点、教学过程五个环节（带时长）、板书设计和反思预设。",
                "每个模块都能单独在线编辑、保存留档，并导出排版清晰的 Word。",
            ]),
            ("AI 出题与题库", [
                "按知识点、题型、难度一次生成题目，题干、答案、分步解析、易错点齐全。",
                "没有答案的题一律拒绝入库；能计算的题用 SymPy 自动验算并显示结果。",
                "题库支持按题型、难度、知识点、状态、来源筛选，以及审核、编辑、删除。",
                "支持 Word、Excel、粘贴三种外部导入；可导出仅题目卷和含答案解析的教师卷。",
            ]),
            ("PPT 与模型配置", [
                "基于已保存教案一键生成 PPT：白底深蓝标题、固定结构，可用 WPS 或 PowerPoint 二次编辑。",
                "设置页新增内容生成模型和向量模型两组配置，留空时内容模型自动回退主模型。",
            ]),
        ],
    },
    {
        "id": "v0.4",
        "when": "2026-09-18",
        "stage": "阶段 3 · 作业工作台",
        "tables": "10 张",
        "core": "混合组卷、AI 自动组卷、成绩录入批改、作业分析、错题本",
        "groups": [
            ("作业设计", [
                "新建作业或试卷用弹窗选择五种类型（预习、课中、课后、复习、试卷），默认参数随类型变化。",
                "题目有四个来源：题库勾选、AI 即时出题、外部导入、手动添加。",
                "可调整题目顺序、设置每题分值并实时汇总总分，预览并导出学生卷和教师卷。",
                "作业可存为模板，下次新建可从模板复制题目。",
            ]),
            ("AI 自动组卷", [
                "试卷类型可一键自动组卷：按题型题量和难度配比，从已审核题库确定性抽题。",
                "题库不足的部分自动调用 AI 出题补齐，并给出知识点覆盖情况提示，之后仍可增删调序。",
            ]),
            ("成绩录入", [
                "支持 Excel 导入总分（先预览标红、确认入库、重复导入更新）和表格手动录入。",
                "班内并列排名自动计算；支持一行一学生、一列一题的逐题批改，记录对错、得分和错误类型。",
            ]),
            ("作业分析", [
                "提交率、均分、最高最低、分数段柱状图、学生排名和与上一份作业的进退步标记。",
                "每题正确率条形图、高频错题 TOP5，全班错误率高的题自动标为典型错题。",
                "提供 AI 自然语言总结和 Word 分析报告导出。",
            ]),
            ("错题本", [
                "逐题批改判错后自动收集，可按学生、作业、知识点、错误类型筛选。",
                "详情含原题、作答得分、正确答案和解析；典型错题置顶，支持导出 Word。",
                "新增作业每题作答表作为正确率和错题本数据源（表数量 9 → 10）。",
            ]),
        ],
    },
    {
        "id": "v1.0",
        "when": "2026-09-19",
        "stage": "阶段 4 · 完善与打磨（正式版）",
        "tables": "13 张",
        "core": "教学反思、期末评语、数据备份恢复清空、新建考试弹窗、完整使用说明",
        "groups": [
            ("教学反思", [
                "学情工作台新增教学反思页，可针对单次考试或起止两场考试的一段时间生成。",
                "AI 同时参考考试成绩指标和作业错题，输出成功之处、不足之处、学生反馈、改进措施四段。",
                "每段可在线编辑、保存留档、查看历史并导出 Word。",
            ]),
            ("期末评语", [
                "按班级、学期和三种风格（鼓励、中肯、严格）逐学生生成 100–150 字个性化评语。",
                "批量生成带进度和成功失败统计，单条失败可单独重试，不影响其他学生。",
                "每条可编辑，按学生和学期留档（重复生成是更新），附可增删的常用评语模板库。",
                "可按班级名单批量导出排版好的 Word 评语集。",
            ]),
            ("数据管理", [
                "一键把整个数据目录备份成带时间戳和版本清单的压缩包，可下载或在本机留存。",
                "上传备份即可恢复：恢复前校验文件，当前数据先自动改名留底，失败自动回退，并提示重启。",
                "可清空 13 张业务表数据，保留 AI 配置、密钥和已有备份，需输入确认文字并二次确认。",
            ]),
            ("交互与文档", [
                "新建考试改为弹窗，与新建作业的交互风格统一；备课页保留原有页内表单。",
                "交付完整使用说明 USAGE.md，覆盖四个工作台、模型配置、备份恢复和常见问题。",
                "数据表由 10 张增至 13 张（教学反思、评语模板、学生评语），旧数据无需迁移。",
            ]),
        ],
    },
]
# ---------------------------------------------------------------------------
# HTML / CSS 排版
# ---------------------------------------------------------------------------

CSS = """
@font-face { font-family: yh; src: url(regular.ttc); }
@font-face { font-family: yhb; src: url(bold.ttc); font-weight: bold; }
@page { margin: 56px 50px; }
* { box-sizing: border-box; }
body { font-family: yh; font-size: 10.5pt; line-height: 1.6; color: #222; }
h1 { font-family: yhb; color: %PRIMARY%; font-size: 23pt; margin: 0 0 6px 0; }
h2 { font-family: yhb; color: %PRIMARY%; font-size: 14pt; margin: 18px 0 8px 0;
     border-bottom: 1.5px solid %PRIMARY%; padding-bottom: 3px;
     page-break-after: avoid; }
h3 { font-family: yhb; font-size: 11pt; color: #333; margin: 10px 0 4px 0;
     page-break-after: avoid; }
.cover { margin-top: 120px; }
.subtitle { font-family: yhb; font-size: 14pt; color: #555; margin-bottom: 26px; }
.meta { font-size: 10pt; color: #666; line-height: 2; }
.lead { font-size: 10.5pt; color: #444; margin: 14px 0; }
table { border-collapse: collapse; width: 100%%; margin: 8px 0 4px 0;
        page-break-inside: auto; }
th, td { border: 1px solid #9aa7b4; padding: 5px 7px; vertical-align: top; }
th { background: %HEADER_BG%; font-family: yhb; text-align: left; }
.overview td:first-child, .overview th:first-child { white-space: nowrap; width: 12%%; }
.overview td:nth-child(2) { white-space: nowrap; width: 13%%; }
.overview td:nth-child(3) { width: 18%%; }
.overview td:last-child { white-space: nowrap; width: 9%%; text-align: center; }
ul { margin: 2px 0 8px 0; padding-left: 20px; }
li { margin: 2px 0; }
.section { page-break-inside: auto; }
.kicker { font-size: 9.5pt; color: #888; }
.footer-note { margin-top: 16px; background: #f4f7fb; border-left: 4px solid %PRIMARY%;
               padding: 10px 12px; font-size: 10pt; }
"""


def _esc(text) -> str:
    """HTML 转义，防止功能文字里的 < > & 破坏排版。"""
    return html.escape(str(text), quote=False)


def _build_html() -> str:
    """根据 VERSIONS 常量拼出完整 HTML。"""
    style = (CSS.replace("%PRIMARY%", PRIMARY)
                .replace("%HEADER_BG%", HEADER_BG)
                .replace("%%", "%"))

    today = date.today().isoformat()
    parts = ["<html><head><meta charset='utf-8'><style>", style, "</style></head><body>"]

    # 1) 封面
    parts.append(
        "<div class='cover'>"
        f"<h1>AI 数学教师工作台 · 功能说明</h1>"
        "<div class='subtitle'>版本演进记录　v0.1 → v1.0</div>"
        "<div class='meta'>"
        f"生成日期：{today}<br>"
        f"文档版本：v{config.APP_VERSION}<br>"
        "技术栈：Streamlit · SQLAlchemy / SQLite · PyMuPDF · ChromaDB · "
        "python-docx / python-pptx · Plotly · SymPy<br>"
        "运行环境：本地单机（Windows + Python 3.11），数据保存在本机 data 目录"
        "</div></div>")

    # 2) 版本总览表
    parts.append("<h2>一、版本总览</h2>")
    parts.append(
        "<table class='overview'><tr>"
        "<th>版本</th><th>日期</th><th>阶段</th><th>核心交付</th><th>数据表</th>"
        "</tr>")
    for v in VERSIONS:
        parts.append(
            "<tr>"
            f"<td><b>{_esc(v['id'])}</b></td>"
            f"<td>{_esc(v['when'])}</td>"
            f"<td>{_esc(v['stage'].split(' · ', 1)[-1])}</td>"
            f"<td>{_esc(v['core'])}</td>"
            f"<td>{_esc(v['tables'])}</td>"
            "</tr>")
    parts.append("</table>")
    parts.append(
        "<p class='kicker'>说明：v0.1–v0.3 均为 9 张表；v0.4 新增作业每题作答表增至 10 张；"
        "v1.0 新增教学反思、评语模板、学生评语 3 张表，增至 13 张。</p>")

    # 3) 每个版本一节
    parts.append("<h2>二、各版本新增功能</h2>")
    cn = {0: "三", 1: "四", 2: "五", 3: "六", 4: "七"}
    for idx, v in enumerate(VERSIONS):
        parts.append(f"<div class='section'><h3>{_esc(v['stage'])}（{_esc(v['id'])}，{_esc(v['when'])}）</h3>")
        for group_name, items in v["groups"]:
            parts.append(f"<h3>{_esc(group_name)}</h3><ul>")
            for item in items:
                parts.append(f"<li>{_esc(item)}</li>")
            parts.append("</ul>")
        parts.append("</div>")

    # 4) 结尾小结
    parts.append(
        "<div class='footer-note'>"
        "<b>当前形态（v1.0）：</b>四个侧边栏工作台——备课（5 个页签）、作业（4 个页签）、"
        "学情（7 个页签）、设置；共 13 张数据表，覆盖资料检索、AI 教案与出题、题库、"
        "组卷、成绩与作业分析、错题本、教学反思、期末评语和数据备份恢复。<br>"
        "启动方式：在项目根目录执行 <b>streamlit run app.py</b>（不要直接运行 app.py）；"
        "详细操作见随项目提供的 USAGE.md。"
        "</div>")

    parts.append("</body></html>")
    return "".join(parts)


def _check_fonts() -> None:
    """字体缺失时给出明确的中文报错（不静默产出乱码 PDF）。"""
    missing = [str(p) for p in (FONT_REGULAR, FONT_BOLD) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "生成 PDF 需要系统微软雅黑字体，但未找到：" + "、".join(missing)
            + "。请在装有微软雅黑的 Windows 上运行，或修改脚本顶部的字体路径。")


def build_feature_pdf(output_path) -> Path:
    """
    渲染功能说明 PDF 到 output_path，返回文件路径。
    字体以字节形式加入 PyMuPDF Archive（不复制字体文件到项目里），
    渲染后做字体子集化并压缩，控制成品体积。
    """
    _check_fonts()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    archive = fitz.Archive()
    archive.add(FONT_REGULAR.read_bytes(), "regular.ttc")
    archive.add(FONT_BOLD.read_bytes(), "bold.ttc")

    story = fitz.Story(html=_build_html(), archive=archive)
    # 未子集化的中间文件放系统临时目录，避免污染 docs/
    tmp_dir = Path(tempfile.mkdtemp(prefix="feature_pdf_"))
    tmp_path = tmp_dir / "feature.raw.pdf"
    writer = fitz.DocumentWriter(str(tmp_path))
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (50, 56, -50, -56)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()

    # 重新打开做字体子集化 + 压缩后另存为目标文件
    doc = fitz.open(str(tmp_path))
    doc.subset_fonts()
    doc.save(str(output_path), garbage=4, deflate=True)
    doc.close()
    # Windows 下文件句柄可能延迟释放：先断开引用再清理临时目录
    del writer, doc, story
    gc.collect()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return output_path


def main() -> None:
    """命令行入口：同时输出到 docs/（入库）和 data/exports/（取用副本）。"""
    filename = f"功能说明_v{config.APP_VERSION}.pdf"
    docs_path = ROOT / "docs" / filename
    export_path = config.EXPORT_DIR / filename

    build_feature_pdf(docs_path)
    config.ensure_dirs()
    shutil.copyfile(docs_path, export_path)
    print(f"已生成：{docs_path}")
    print(f"副本：  {export_path}")


if __name__ == "__main__":
    main()