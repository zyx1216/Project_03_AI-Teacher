# AI 教学辅助 REST API（v2.7.0）

## 启动

```bash
uvicorn api.main:app --port 8000
```

- Swagger：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

## 认证

除 `/api/health` 外都需认证，二选一：

1. 请求头 `X-API-Key: <在设置页生成的 Key>`
2. 先 `POST /api/auth/token` 拿 Bearer token，再用 `Authorization: Bearer <token>`

> 带内存限流：每个认证主体每分钟 60 次，超限返回 **429**。

## 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（无需认证） |
| POST | `/api/auth/token` | 获取访问令牌（HMAC 签名，1 小时） |
| GET | `/api/materials` | 资料列表（可 `?subject=`） |
| GET | `/api/materials/{id}` | 资料详情（章节与切块数） |
| GET | `/api/students` | 学生列表 |
| POST | `/api/students` | 新增学生 |
| POST | `/api/students/import` | 批量导入学生 |
| GET | `/api/students/{id}` | 学生画像（考试次数） |
| POST | `/api/exam/compose` | 创建草稿试卷 |
| GET | `/api/exam/{id}` | 试卷详情 |
| GET | `/api/scores` / POST | 成绩查询 / 录入 |
| GET | `/api/exams/analysis` | 考试分析（按名称） |
| GET | `/api/analysis/exam/{id}` | 考试分析（按 ID） |
| GET | `/api/analysis/trends` | 班级趋势 |
| POST | `/api/questions/generate` | AI 出题 |
| POST | `/api/lesson/generate` | AI 生成教案 |
| POST | `/api/grading/objective` | 客观题批量重批 |
| POST | `/api/grading/subjective` | 主观题 AI 批改（需教师确认） |
| POST | `/api/rag/query` | RAG 智能问答 |
| POST | `/api/agent/chat` | Agent 对话 |

## 调用示例

### curl

```bash
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/json" -d "{\"subject\":\"teacher\"}"

curl -H "X-API-Key: <key>" http://localhost:8000/api/materials

curl -X POST -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d "{\"homework_id\":1,\"force\":false}" \
  http://localhost:8000/api/grading/objective
```

### Python（requests）

```python
import requests
BASE = "http://localhost:8000"
h = {"X-API-Key": "<key>"}
print(requests.get(f"{BASE}/api/materials", headers=h).json())
print(requests.post(f"{BASE}/api/rag/query", headers=h,
                    json={"query": "函数的定义", "textbook_ids": [1]}).json())
```

### JavaScript（fetch）

```javascript
const r = await fetch("http://localhost:8000/api/materials", {
  headers: { "X-API-Key": "<key>" }
});
console.log(await r.json());
```
