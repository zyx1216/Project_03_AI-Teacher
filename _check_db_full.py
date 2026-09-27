# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect(r'D:\Codex\Project_03_AI数学教师工作台\data\database.db')
cursor = conn.cursor()

# 列出所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print(f'数据库表数量: {len(tables)}')
print('表列表:', tables)

# 检查关键表的记录数
key_tables = ['students', 'exams', 'scores', 'questions', 'homeworks', 'teaching_reflections', 'reflection_plans', 'textbooks']
for t in key_tables:
    if t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {t}')
        count = cursor.fetchone()[0]
        print(f'  {t}: {count}条记录')
    else:
        print(f'  {t}: 表不存在!')

# 检查questions表的parent_question_id字段
cursor.execute('PRAGMA table_info(questions)')
q_cols = [row[1] for row in cursor.fetchall()]
print(f'questions表有parent_question_id: {"parent_question_id" in q_cols}')

# 检查teaching_reflections表的has_plan字段
cursor.execute('PRAGMA table_info(teaching_reflections)')
tr_cols = [row[1] for row in cursor.fetchall()]
print(f'teaching_reflections表有has_plan: {"has_plan" in tr_cols}')

conn.close()
