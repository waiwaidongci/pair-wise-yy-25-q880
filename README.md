# 语料标注与争议仲裁

项目使用 Python 标准库、SQLite 和 `http.server`，实现批次、指南版本、重复标注、分歧检测、仲裁、一致性指标、金标准冻结与导出，并以“提交前不可查看含答案讨论”的方式隔离讨论区答案。

首页是任务台：管理员勾选多名标注员一键分派整个批次（已有分配沿用原记录，重复分派不产生新任务）；标注员选择本人后查看待标注与已提交条目，待办展开即可提交标签和备注；批次详情展示每人任务总数、完成数、待完成数，任务未交齐时冻结入口保持不可用并列出缺口。

## 启动

```bash
python app.py
```

默认地址 <http://127.0.0.1:8112>，默认数据库为 `corpus.db`。首次启动会写入两位标注员、一位仲裁员、一位管理员和一个含分歧的示例批次。

```bash
PORT=9002 CORPUS_DB=/tmp/corpus.db python app.py
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试包括：分配、标注、发现分歧、阻止提前冻结、仲裁、计算一致性、冻结和导出；另一条测试验证提交答案前后讨论可见性变化，以及错误角色不能领取标注任务；任务台测试覆盖批量分派幂等、待办/已提交拆分、进度缺口与未交齐时阻止冻结。

## 接口

- `POST /api/users`、`POST /api/guidelines`、`POST /api/batches`
- `POST /api/batches/{id}/items`、`POST /api/batches/{id}/assign`
- `POST /api/batches/{id}/assign_all`（请求体 `{"annotator_ids": [...]}`，把本批全部条目派给勾选标注员，幂等）
- `GET /api/annotators/{id}/tasks?batch_id=`（待标注与已提交任务）
- `GET /api/batches/{id}/progress`（每人总数/完成/待完成、未提交缺口与冻结就绪状态）
- `POST /api/annotations`、`POST /api/adjudications`
- `GET /api/items/{id}?user_id=`
- `GET /api/batches/{id}/disagreements`
- `GET /api/batches/{id}/consistency`
- `POST /api/batches/{id}/freeze`
- `GET /api/batches/{id}/gold`

一致性同时返回逐条成对一致率和 Fleiss Kappa。冻结要求每条至少有两人标注、所有已分派任务均已提交、没有未仲裁分歧；冻结后不能修改标注，导出结果来自不可变的 `gold_records`。
