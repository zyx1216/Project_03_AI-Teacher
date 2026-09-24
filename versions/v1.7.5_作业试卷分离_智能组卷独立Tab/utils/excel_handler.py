# -*- coding: utf-8 -*-
"""
Excel 导入识别层（纯函数，不碰数据库、不依赖 Streamlit）。

职责：
1. 读入学生名单或成绩表；
2. 模糊识别表头（姓名/学号/班级 等允许多种写法）；
3. 提取成标准化记录并标出问题行，供页面先预览、老师确认后再写库。

科目列识别规则：先排除"姓名、学号、班级、序号、名次"等元数据列，
剩余含数字的列一律视为科目，列名去掉"成绩/分数/得分"等后缀得到科目名。
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# 各字段允许的表头别名（全部先做规范化再比较）
STUDENT_ALIASES = {
    "name": ["姓名", "名字", "学生姓名", "学生", "name", "学生名字"],
    "student_no": ["学号", "编号", "学籍号", "考号", "number", "no", "id"],
    "class_name": ["班级", "行政班", "所在班级", "班别", "class"],
    "gender": ["性别", "性別", "sex", "gender"],
    "remark": ["备注", "说明", "附注", "remark", "note"],
}

# 成绩表里不是科目、必须排除的元数据列
SCORE_META_ALIASES = {
    "name": ["姓名", "名字", "学生姓名", "学生", "name"],
    "student_no": ["学号", "编号", "学籍号", "考号", "准考证号", "number", "no", "id"],
    "class_name": ["班级", "行政班", "所在班级", "班别", "class"],
    "gender": ["性别", "sex", "gender"],
    "rank": ["名次", "排名", "班级排名", "年级排名", "总分排名", "rank"],
    "remark": ["备注", "说明", "附注", "remark", "note"],
}

# 无论如何都不当作科目名的词（含序号类）
META_KEYWORDS = ["序号", "序號", "编号", "考号", "准考证", "名次", "排名", "总分",
                 "合计", "平均分", "均分", "备注", "姓名", "班级", "学号", "性别"]

# 科目列名里要剥掉的后缀
SUBJECT_SUFFIXES = ["成绩", "分数", "得分", "成績", "分數", "学科", "科目", "成绩分"]


def normalize_text(value) -> str:
    """规范化表头：转字符串、去空白和换行、全角转半角、英文小写。"""
    if value is None:
        return ""
    text = str(value).strip().lower()
    # 去掉所有空白字符（含全角空格、换行）
    text = re.sub(r"\s+", "", text)
    # 常见全角标点转半角
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    return text


def clean_subject_name(col_name) -> str:
    """从列名提取科目名，如 '数学成绩' -> '数学'；剥不掉就用原名。"""
    name = str(col_name).strip()
    for suffix in SUBJECT_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip()


def _build_alias_lookup(alias_map: dict) -> dict:
    """把 {字段: [别名]} 反转成 {规范化别名: 字段}。"""
    lookup = {}
    for field, aliases in alias_map.items():
        for alias in aliases:
            lookup[normalize_text(alias)] = field
    return lookup


def _to_text(value) -> Optional[str]:
    """单元格转干净字符串；空值返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    return text


def _to_score(value) -> Optional[float]:
    """成绩单元格转 float；空值/非数字返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.strip().replace("分", "")
        if value == "":
            return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < 0:  # 负分不合理，当无效
        return None
    return round(num, 2)


def detect_student_columns(df: pd.DataFrame) -> dict:
    """
    识别学生名单表的列。
    返回 {"mapping": {字段: 原列名或None}, "problems": [问题...]}。
    """
    lookup = _build_alias_lookup(STUDENT_ALIASES)
    mapping = {"name": None, "student_no": None, "class_name": None,
               "gender": None, "remark": None}
    for col in df.columns:
        field = lookup.get(normalize_text(col))
        if field and mapping[field] is None:
            mapping[field] = col
    problems = []
    if mapping["name"] is None:
        problems.append("没有识别到姓名列（需要包含“姓名”列）")
    return {"mapping": mapping, "problems": problems}


def _is_numeric_column(df: pd.DataFrame, col) -> bool:
    """判断一列是否主要含数字（至少有一个能转成成绩的非空值）。"""
    for value in df[col].tolist():
        if _to_score(value) is not None:
            return True
    return False


def detect_score_columns(df: pd.DataFrame) -> dict:
    """
    识别成绩表的姓名列和科目列。
    返回 {"name_col", "class_col", "subjects": [(原列名, 科目名)], "problems"}。
    """
    lookup = _build_alias_lookup(SCORE_META_ALIASES)
    meta_cols = {}  # 原列名 -> 元数据字段
    for col in df.columns:
        field = lookup.get(normalize_text(col))
        if field:
            meta_cols[col] = field

    name_col = None
    class_col = None
    for col, field in meta_cols.items():
        if field == "name" and name_col is None:
            name_col = col
        elif field == "class_name" and class_col is None:
            class_col = col

    problems = []
    if name_col is None:
        problems.append("没有识别到姓名列（需要包含“姓名”列）")

    subjects = []
    for col in df.columns:
        if col in meta_cols:
            continue
        norm = normalize_text(col)
        if any(normalize_text(k) in norm for k in META_KEYWORDS):
            continue
        if _is_numeric_column(df, col):
            subjects.append((col, clean_subject_name(col)))

    if not subjects:
        problems.append("没有识别到任何成绩列（数字列的列名应为科目名，如“数学”或“数学成绩”）")
    return {"name_col": name_col, "class_col": class_col,
            "subjects": subjects, "problems": problems}


def extract_students(df: pd.DataFrame, mapping: dict) -> list[dict]:
    """按识别出的列映射，把学生表提取成记录；缺姓名的行进 problems。"""
    records = []
    for row_no, (_, row) in enumerate(df.iterrows(), start=2):  # Excel 第1行是表头
        name = _to_text(row[mapping["name"]]) if mapping["name"] else None
        problems = []
        if not name:
            problems.append("缺姓名")
        record = {
            "row_no": row_no,
            "name": name,
            "student_no": _to_text(row[mapping["student_no"]]) if mapping["student_no"] else None,
            "class_name": _to_text(row[mapping["class_name"]]) if mapping["class_name"] else None,
            "gender": _to_text(row[mapping["gender"]]) if mapping["gender"] else None,
            "remark": _to_text(row[mapping["remark"]]) if mapping["remark"] else None,
            "problems": problems,
        }
        records.append(record)
    # 全空行（姓名、学号、班级都空）直接剔除，不当问题行
    records = [r for r in records
               if r["name"] or r["student_no"] or r["class_name"] or r["remark"]]
    return records


def extract_scores(df: pd.DataFrame, detected: dict) -> list[dict]:
    """按识别结果把成绩表提取成记录；缺姓名标问题，缺考科目分数留 None。"""
    name_col = detected["name_col"]
    class_col = detected["class_col"]
    subjects = detected["subjects"]
    records = []
    for row_no, (_, row) in enumerate(df.iterrows(), start=2):
        name = _to_text(row[name_col]) if name_col else None
        scores = {}
        missing_subjects = []
        for col, subject in subjects:
            value = _to_score(row[col])
            scores[subject] = value
            if value is None:
                missing_subjects.append(subject)
        # 跳过彻底空白的行
        if not name and all(v is None for v in scores.values()):
            continue
        problems = []
        if not name:
            problems.append("缺姓名")
        if name and missing_subjects:
            problems.append("缺分科目：" + "、".join(missing_subjects))
        records.append({
            "row_no": row_no,
            "name": name,
            "class_name": _to_text(row[class_col]) if class_col else None,
            "scores": scores,
            "problems": problems,
        })
    return records


# 成绩导入模板的 9 个学科，顺序固定
SCORE_TEMPLATE_COLUMNS = [
    "姓名", "学号", "班级",
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]


def score_template_dataframe() -> pd.DataFrame:
    """构造成绩导入模板：第一行列名，第二行示例数据。"""
    return pd.DataFrame([{
        "姓名": "张三", "学号": "001", "班级": "一班",
        "语文": 110.0, "数学": 120.0, "英语": 115.0,
        "物理": 88.0, "化学": 90.0, "生物": 85.0,
        "政治": 82.0, "历史": 86.0, "地理": 91.0,
    }], columns=SCORE_TEMPLATE_COLUMNS)


def scores_preview_frame(records: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """
    把 extract_scores 的记录转成可编辑预览表。
    返回 (DataFrame, 科目顺序)。列：Excel行号/姓名/班级/各科/问题。
    科目顺序按首次出现固定，保证三格式（Excel/Word/PDF）预览一致。
    """
    subjects: list[str] = []
    for rec in records:
        for s in rec.get("scores", {}):
            if s not in subjects:
                subjects.append(s)
    rows = []
    for rec in records:
        row = {
            "Excel行号": rec.get("row_no"),
            "姓名": rec.get("name"),
            "班级": rec.get("class_name") or "",
        }
        for s in subjects:
            row[s] = rec["scores"].get(s)
        row["问题"] = "、".join(rec.get("problems", []))
        rows.append(row)
    return pd.DataFrame(rows, dtype=object), subjects


def preview_to_records(df: pd.DataFrame, subjects: list[str]) -> list[dict]:
    """
    把老师在预览表里编辑过的 DataFrame 转回 import_scores 需要的 records。
    分数列经 _to_score 归一，空值=缺考(None)；缺姓名的行保留并交给入库层跳过。
    """
    records = []
    for _, row in df.iterrows():
        name = _to_text(row.get("姓名"))
        class_name = _to_text(row.get("班级"))
        scores = {}
        missing = []
        for s in subjects:
            value = _to_score(row.get(s))
            scores[s] = value
            if name and value is None:
                missing.append(s)
        # 整行空白（无姓名且所有分数为空）直接丢弃
        if not name and all(v is None for v in scores.values()):
            continue
        problems = []
        if not name:
            problems.append("缺姓名")
        if missing:
            problems.append("缺分科目：" + "、".join(missing))
        records.append({
            "name": name,
            "class_name": class_name,
            "scores": scores,
            "problems": problems,
        })
    return records


def load_dataframe(file, sheet_name=0) -> pd.DataFrame:
    """读取上传的 Excel 文件（路径或文件对象），所有列按字符串读入再自行转换，避免学号丢前导零。"""
    return pd.read_excel(file, sheet_name=sheet_name, dtype=object, engine="openpyxl")


def list_sheets(file) -> list:
    """返回 Excel 的所有工作表名。"""
    xls = pd.ExcelFile(file, engine="openpyxl")
    return xls.sheet_names