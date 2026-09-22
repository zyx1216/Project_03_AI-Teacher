# -*- coding: utf-8 -*-
import pymupdf

doc = pymupdf.open(r'D:\Codex\Project_03_AI数学教师工作台\test_math.pdf')
output_path = r'D:\Codex\Project_03_AI数学教师工作台\pdf_extract_test.txt'

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(f'总页数: {len(doc)}\n')
    f.write('=' * 50 + '\n')
    f.write('前20页内容:\n')
    for i in range(min(20, len(doc))):
        f.write(f'--- 第{i+1}页 ---\n')
        text = doc[i].get_text('text')
        f.write(text[:1200] + '\n\n')
doc.close()
print('提取完成')
