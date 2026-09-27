# 语料标注与争议仲裁

项目使用 Python 标准库、SQLite 和 `http.server`，实现批次任务台、批量分派、指南版本、重复标注、分歧检测、仲裁、一致性指标、金标准冻结与导出，并以“提交前不可查看含答案讨论”的方式隔离讨论区答案。

## 启动

```bash
python app.py
```

默认地址 <http://127.0.0.1:8112>，默认数据库为 `corpus.db`。首次启动会写入两位标注员、一位仲裁员、一位管理员和一个含分歧的示例批次。

```bash
PORT=9002 CORPUS_DB=/tmp/corpus.db python app.py
```

首页即任务台，顶部切换当前身份：

- **管理员**：选择批次后勾选多位标注员，一次把本批全部条目派给他们；已有的 `(条目, 标注员)` 分配沿用原记录，重复勾选只返回跳过数量、不新增任务。批次详情按人列出总数/完成/待完成，逐条列出“谁还没交”的缺口；任务未交齐时冻结按钮保持禁用，未仲裁分歧也会阻止冻结。
- **标注员**：选择本人后看到待标注与已提交条目；待办展开即可填写标签和备注直接提交，已提交条目可重新提交（冻结后只读）。讨论区答案隔离规则同样生效。
- **仲裁员**：按批次加载分歧并提交最终标签与理由。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试包括：分配、批量幂等分派、任务台与批次缺口、标注、发现分歧、阻止提前冻结、仲裁、计算一致性、冻结和导出；另一条测试验证提交答案前后讨论可见性变化，以及错误角色不能领取标注任务。

## 接口

- `POST /api/users`、`POST /api/guidelines`、`POST /api/batches`
- `POST /api/batches/{id}/items`
- `POST /api/batches/{id}/assign`：整批分派 `{"annotator_ids":[...]}`（幂等，返回 `created`/`skipped`）；旧的单条形式 `{"item_id":..,"annotator_id":..}` 仍保留
- `GET /api/users/{id}/tasks?batch_id=`：标注员任务台，返回 `pending` 与 `submitted` 条目
- `GET /api/batches/{id}/progress`：每人总数/完成数/待完成数、未提交缺口、未分派条目、未仲裁分歧数与 `all_submitted`
- `POST /api/annotations`、`POST /api/adjudications`
- `GET /api/items/{id}?user_id=`
- `GET /api/batches/{id}/disagreements`
- `GET /api/batches/{id}/consistency`
- `POST /api/batches/{id}/freeze`
- `GET /api/batches/{id}/gold`

一致性同时返回逐条成对一致率和 Fleiss Kappa。冻结要求每条至少有两人标注、没有未仲裁分歧；冻结后不能修改标注，导出结果来自不可变的 `gold_records`。
