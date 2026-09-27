import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import CorpusDB, DomainError


class CorpusFlowTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = CorpusDB(self.path)
        self.a1 = self.db.add_user("甲", "annotator")
        self.a2 = self.db.add_user("乙", "annotator")
        self.arb = self.db.add_user("仲裁", "arbitrator")
        self.mgr = self.db.add_user("管理", "manager")
        self.g = self.db.add_guideline("v1", "独立标注")
        self.batch = self.db.create_batch("测试批次", self.g)
        self.item1 = self.db.add_item(self.batch, 1, "这个版本很快。")
        self.item2 = self.db.add_item(self.batch, 2, "没有明显变化。")

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_full_annotation_disagreement_adjudication_freeze_flow(self):
        for item in (self.item1, self.item2):
            self.db.assign(item, self.a1)
            self.db.assign(item, self.a2)
        self.db.submit_annotation(self.item1, self.a1, "正向")
        self.db.submit_annotation(self.item1, self.a2, "中性")
        self.db.submit_annotation(self.item2, self.a1, "中性")
        self.db.submit_annotation(self.item2, self.a2, "中性")
        self.assertEqual(1, len(self.db.disagreements(self.batch)))
        with self.assertRaisesRegex(DomainError, "分歧"):
            self.db.freeze_batch(self.batch, self.mgr)
        self.db.adjudicate(self.item1, "正向", "速度描述构成明确正向倾向", self.arb)
        result = self.db.freeze_batch(self.batch, self.mgr)
        self.assertIsNotNone(result["metrics"]["pairwise_agreement"])
        exported = self.db.export_gold(self.batch)
        self.assertEqual(2, len(exported["records"]))
        self.assertEqual("adjudication", exported["records"][0]["source"])

    def test_answer_isolation_and_role_validation(self):
        self.db.assign(self.item1, self.a1)
        self.db.assign(self.item1, self.a2)
        self.db.add_discussion(self.item1, self.a2, "我认为是正向", True)
        secret = self.db.get_item_for_user(self.item1, self.a1)
        self.assertTrue(secret["discussions"][0]["hidden"])
        self.db.submit_annotation(self.item1, self.a1, "负向")
        visible = self.db.get_item_for_user(self.item1, self.a1)
        self.assertFalse(visible["discussions"][0].get("hidden", False))
        with self.assertRaisesRegex(DomainError, "标注员"):
            self.db.assign(self.item2, self.arb)

    def test_batch_assignment_is_idempotent(self):
        # 已有单条分配沿用：a1 已领 item1，批量派发不应新增
        self.db.assign(self.item1, self.a1)
        first = self.db.assign_batch(self.batch, [self.a1, self.a2])
        self.assertEqual(3, first["created"])  # item1-a2, item2-a1, item2-a2
        self.assertEqual(1, first["skipped"])  # item1-a1 沿用
        # 多人重复勾选同一批：不新增任何任务
        second = self.db.assign_batch(self.batch, [self.a1, self.a2])
        self.assertEqual(0, second["created"])
        self.assertEqual(4, second["skipped"])
        # 列表内重复 ID 不会重复派发
        third = self.db.assign_batch(self.batch, [self.a1, self.a1])
        self.assertEqual(0, third["created"])
        self.assertEqual(2, third["skipped"])
        # 不能把任务派给非标注员
        with self.assertRaisesRegex(DomainError, "标注员"):
            self.db.assign_batch(self.batch, [self.arb])
        # 每批每条目每人恰好一条
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM assignments WHERE batch_id=?", (self.batch,)
        ).fetchone()[0]
        self.assertEqual(4, rows)

    def test_taskboard_and_batch_progress_gaps(self):
        self.db.assign_batch(self.batch, [self.a1, self.a2])
        # a1 完成两条，a2 一条未交
        self.db.submit_annotation(self.item1, self.a1, "正向")
        self.db.submit_annotation(self.item2, self.a1, "中性")
        self.db.submit_annotation(self.item1, self.a2, "中性")

        board = self.db.tasks_for_user(self.a1)
        self.assertEqual(0, board["pending_count"])
        self.assertEqual(2, board["submitted_count"])
        self.assertEqual("正向", board["submitted"][0]["label"])

        board2 = self.db.tasks_for_user(self.a2)
        self.assertEqual(1, board2["pending_count"])
        self.assertEqual(self.item2, board2["pending"][0]["item_id"])
        self.assertEqual(1, board2["submitted_count"])

        with self.assertRaisesRegex(DomainError, "标注员"):
            self.db.tasks_for_user(self.arb)

        progress = self.db.batch_progress(self.batch)
        by_id = {p["annotator_id"]: p for p in progress["people"]}
        self.assertEqual((2, 2, 0), (by_id[self.a1]["total"], by_id[self.a1]["completed"], by_id[self.a1]["remaining"]))
        self.assertEqual((2, 1, 1), (by_id[self.a2]["total"], by_id[self.a2]["completed"], by_id[self.a2]["remaining"]))
        self.assertFalse(progress["all_submitted"])
        self.assertEqual([self.item2], [g["item_id"] for g in progress["gaps"]])
        self.assertEqual(["乙"], progress["gaps"][0]["missing_annotators"])

        # 缺口存在时冻结被拒（条目1同时是分歧）
        with self.assertRaises(DomainError):
            self.db.freeze_batch(self.batch, self.mgr)

        # 补齐剩余任务并仲裁后可以冻结
        self.db.adjudicate(self.item1, "正向", "明确的积极表达", self.arb)
        self.db.submit_annotation(self.item2, self.a2, "中性")
        progress2 = self.db.batch_progress(self.batch)
        self.assertTrue(progress2["all_submitted"])
        self.assertEqual([], progress2["gaps"])
        frozen = self.db.freeze_batch(self.batch, self.mgr)
        self.assertEqual(self.batch, frozen["batch_id"])

    def test_progress_flags_unassigned_items(self):
        # 只派给一个人、且只覆盖 item1
        self.db.assign(self.item1, self.a1)
        progress = self.db.batch_progress(self.batch)
        self.assertFalse(progress["all_submitted"])
        self.assertEqual([2], progress["unassigned_items"])
        self.assertEqual(1, progress["gaps"][0]["item_id"])


if __name__ == "__main__":
    unittest.main()
