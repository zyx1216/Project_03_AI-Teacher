# -*- coding: utf-8 -*-
"""
数据备份 / 恢复 / 清空服务层（v1.0）。只用标准库，不新增第三方依赖。

- backup_data_dir：把整个 data 目录打包成带时间戳和版本清单的 zip；
- restore_from_zip：覆盖前自动生成“恢复前备份”，再把当前 data 改名成 data.bak-时间戳并解包，失败自动回退；
- wipe_business_data：按外键依赖顺序清空 20 张业务表，不删数据库文件，
  不碰 llm_config.json、Key（在系统凭据管理器）和已有备份 zip。

data_dir / session 都可注入，便于在临时目录和内存库上测试。
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import config

# 备份文件清单名（放在 zip 根目录）
MANIFEST_NAME = "backup_manifest.json"
# 备份落盘子目录（打包时跳过，避免备份套备份无限膨胀）
BACKUP_SUBDIR = "backups"

# 打包时跳过的临时/锁文件后缀
_SKIP_SUFFIXES = (".tmp", ".temp", ".lock", ".db-journal", ".db-wal", ".db-shm")
_SKIP_DIRS = {"__pycache__"}

# 20 张业务表，按外键依赖顺序排列（子表在前，父表在后）
# 顺序改动前先想清楚外键引用，别让清空撞上外键约束
BUSINESS_TABLES = [
    "homework_submissions", # -> homeworks
    "question_edit_logs",   # 题目修改记录
    "lesson_plan_versions", # 教案历史版本
    "grading_logs",         # -> homeworks / students
    "teaching_progress",    # 教学进度
    "agent_memory",         # Agent长期记忆
    "homework_answers",     # -> homeworks / students / questions
    "homework_scores",      # -> homeworks / students
    "homework_questions",   # -> homeworks / questions
    "scores",               # -> exams / students
    "student_comments",     # -> students
    "reflection_plans",     # -> teaching_reflections/exams
    "teaching_reflections", # 无外键
    "comment_templates",    # 无外键
    "homeworks",
    "questions",
    "lesson_plans",
    "textbooks",
    "exams",
    "students",
]


def _should_skip(path: Path, data_dir: Path) -> bool:
    """临时/锁文件、缓存目录、备份子目录里的 zip 不打进包。"""
    name = path.name
    if name.endswith(_SKIP_SUFFIXES):
        return True
    try:
        rel_parts = path.relative_to(data_dir).parts
    except ValueError:
        return False
    if rel_parts and rel_parts[0] in _SKIP_DIRS:
        return True
    # 历史备份不进新备份（防止备份套备份）
    if rel_parts and rel_parts[0] == BACKUP_SUBDIR and name.endswith(".zip"):
        return True
    return False


def default_backup_name() -> str:
    """带时间戳的备份文件名。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"backup_{stamp}_v{config.APP_VERSION}.zip"


def backup_data_dir(data_dir: Path | str | None = None) -> bytes:
    """
    打包整个 data 目录，返回 zip 字节内容。
    zip 内路径相对 data 目录（如 database.db、uploads/...），根目录放版本清单。
    """
    import io

    data_dir = Path(data_dir or config.DATA_DIR)
    if not data_dir.exists():
        raise FileNotFoundError(f"数据目录不存在：{data_dir}")

    manifest = {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in sorted(data_dir.rglob("*")):
            if path.is_dir() or _should_skip(path, data_dir):
                continue
            zf.write(path, path.relative_to(data_dir).as_posix())
    return buffer.getvalue()


def save_backup_to_disk(data_dir: Path | str | None = None) -> Path:
    """把备份 zip 落到 data/backups/ 下，返回文件路径。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    backup_dir = data_dir / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / default_backup_name()
    target.write_bytes(backup_data_dir(data_dir))
    return target


def _validate_backup_zip(zip_path: Path | str) -> dict:
    """校验 zip 完整且含本应用的清单，返回清单字典；不合规直接抛错（不动现有数据）。"""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"备份文件不存在：{zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("这不是有效的 zip 备份文件。")
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise ValueError(f"备份压缩包已损坏，首个坏文件：{bad}")
        names = zf.namelist()
        if MANIFEST_NAME not in names:
            raise ValueError("压缩包里没有备份清单，可能不是本程序的备份。")
        try:
            return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("备份清单无法解析，文件可能已损坏。") from exc


def restore_from_zip(zip_path: Path | str,
                     data_dir: Path | str | None = None) -> dict:
    """
    用备份 zip 覆盖恢复 data 目录。

    流程：校验 zip → 当前 data 改名 data.bak-时间戳 → 解包 → 失败回退。
    返回清单信息。恢复成功后需重启 Streamlit 才能确保连接指向新库。
    """
    data_dir = Path(data_dir or config.DATA_DIR)
    manifest = _validate_backup_zip(zip_path)
    if data_dir.exists():
        create_pre_restore_backup(data_dir)

    # 恢复的是应用正在使用的 data 目录时，先释放连接并回收对象，
    # 否则 Windows 下 database.db / chroma 被占用，目录改名会失败
    if data_dir.resolve() == Path(config.DATA_DIR).resolve():
        _release_runtime_handles()

    data_dir.parent.mkdir(parents=True, exist_ok=True)
    bak_dir = None
    if data_dir.exists():
        bak_dir = data_dir.parent / f"data.bak-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        data_dir.rename(bak_dir)

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                # 防 zip-slip：解包目标必须仍在 data_dir 内
                target = (data_dir / member).resolve()
                if target != data_dir.resolve() and data_dir.resolve() not in target.parents:
                    raise ValueError(f"备份包含非法路径：{member}")
            zf.extractall(data_dir)
    except Exception:
        # 解包失败：删掉半成品，把旧目录改回来
        shutil.rmtree(data_dir, ignore_errors=True)
        if bak_dir is not None and bak_dir.exists():
            bak_dir.rename(data_dir)
        raise
    return manifest


def _release_runtime_handles() -> None:
    """恢复前释放运行中程序对 data 目录的文件占用（尽力而为，失败不阻断）。"""
    import gc
    try:
        from utils import db as _db
        _db.engine.dispose()
    except Exception:
        pass
    gc.collect()


def prune_backup_dirs(data_dir: Path | str | None = None, keep: int = 3) -> None:
    """恢复产生的 data.bak-* 只保留最近 keep 个，防止旧数据堆积。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    baks = sorted(data_dir.parent.glob("data.bak-*"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in baks[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def wipe_business_data(session=None) -> list[str]:
    """
    清空 20 张业务表数据。返回被清空的表名列表。
    - 不删数据库文件，不碰 llm_config.json 和 data/backups 下的备份；
    - 传入内存库 session 时用于测试；默认用应用自己的连接。
    """
    own_session = session is None
    if own_session:
        from utils.db import SessionLocal
        ctx = SessionLocal()
        session = ctx
    try:
        from sqlalchemy import text
        for table in BUSINESS_TABLES:
            session.execute(text(f'DELETE FROM "{table}"'))
        # SQLite 的自增序列也归零，让清空后新建的 id 从 1 开始
        try:
            session.execute(text("DELETE FROM sqlite_sequence"))
        except Exception:
            pass  # 内存库没用 AUTOINCREMENT 序列表时可忽略
        if own_session:
            session.commit()
    finally:
        if own_session:
            session.close()
    return list(BUSINESS_TABLES)


def auto_backup_if_needed(data_dir: Path | str | None = None) -> Path | None:
    """当天还没有备份时自动备份一份；已有当天备份则跳过。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    today = datetime.now().date()
    backup_dir = data_dir / BACKUP_SUBDIR
    if backup_dir.exists():
        for path in backup_dir.glob("*.zip"):
            if datetime.fromtimestamp(path.stat().st_mtime).date() == today:
                return None
    return save_backup_to_disk(data_dir)


def prune_old_backups(data_dir: Path | str | None = None,
                      keep_days: int = 7) -> None:
    """删除修改时间早于 keep_days 的备份 zip，并清理空目录。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    cutoff = datetime.now() - timedelta(days=keep_days)
    backup_dir = data_dir / BACKUP_SUBDIR
    if not backup_dir.exists():
        return
    for path in backup_dir.rglob("*.zip"):
        if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()
    for directory in sorted(backup_dir.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def backup_stats(data_dir: Path | str | None = None) -> dict:
    """返回备份页统计：数据库大小、上传资料文件数、最后备份时间。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    db_file = data_dir / "database.db"
    upload_dir = data_dir / "uploads"
    material_count = 0
    if upload_dir.exists():
        material_count = sum(1 for path in upload_dir.rglob("*") if path.is_file())
    backups = list((data_dir / BACKUP_SUBDIR).glob("*.zip")) if (
        data_dir / BACKUP_SUBDIR).exists() else []
    last = max((path.stat().st_mtime for path in backups), default=None)
    return {
        "db_size": db_file.stat().st_size if db_file.exists() else 0,
        "material_count": material_count,
        "last_backup": datetime.fromtimestamp(last) if last else None,
    }


def create_pre_restore_backup(data_dir: Path | str | None = None) -> Path:
    """恢复覆盖前，把当前 data 额外保存成一份“恢复前备份”。"""
    data_dir = Path(data_dir or config.DATA_DIR)
    backup_dir = data_dir / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"恢复前备份_{stamp}.zip"
    target.write_bytes(backup_data_dir(data_dir))
    return target


