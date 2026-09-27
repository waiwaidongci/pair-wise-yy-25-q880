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


class TaskBoardTest(unittest.TestCase):
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

    def test_bulk_assign_is_idempotent_and_keeps_existing_rows(self):
        original_id = self.db.assign(self.item1, self.a1)
        result = self.db.assign_batch(self.batch, [self.a1, self.a2, self.a1])
        self.assertEqual(3, result["created"])
        self.assertEqual(1, result["skipped"])
        again = self.db.assign_batch(self.batch, [self.a1, self.a2])
        self.assertEqual(0, again["created"])
        self.assertEqual(4, again["skipped"])
        kept = self.db.conn.execute(
            "SELECT id FROM assignments WHERE item_id=? AND annotator_id=?", (self.item1, self.a1)
        ).fetchone()
        self.assertEqual(original_id, kept["id"])
        with self.assertRaisesRegex(DomainError, "标注员"):
            self.db.assign_batch(self.batch, [self.arb])
        with self.assertRaisesRegex(DomainError, "至少"):
            self.db.assign_batch(self.batch, [])

    def test_annotator_tasks_split_pending_and_submitted(self):
        self.db.assign_batch(self.batch, [self.a1])
        self.db.submit_annotation(self.item1, self.a1, "正向", "语气积极")
        tasks = self.db.annotator_tasks(self.a1)
        self.assertEqual([self.item2], [t["item_id"] for t in tasks["pending"]])
        self.assertEqual([self.item1], [t["item_id"] for t in tasks["submitted"]])
        self.assertEqual("正向", tasks["submitted"][0]["label"])
        self.assertEqual("语气积极", tasks["submitted"][0]["comment"])
        with self.assertRaisesRegex(DomainError, "标注员"):
            self.db.annotator_tasks(self.arb)

    def test_progress_reports_gaps_and_blocks_freeze_until_done(self):
        self.db.assign_batch(self.batch, [self.a1, self.a2])
        self.db.submit_annotation(self.item1, self.a1, "正向")
        progress = self.db.batch_progress(self.batch)
        stats = {a["annotator_id"]: a for a in progress["annotators"]}
        self.assertEqual({"total": 2, "submitted": 1, "pending": 1}, {
            k: stats[self.a1][k] for k in ("total", "submitted", "pending")})
        self.assertEqual(3, len(progress["pending_gaps"]))
        self.assertFalse(progress["freeze_ready"])
        with self.assertRaisesRegex(DomainError, "未提交"):
            self.db.freeze_batch(self.batch, self.mgr)
        self.db.submit_annotation(self.item1, self.a2, "正向")
        self.db.submit_annotation(self.item2, self.a1, "中性")
        self.db.submit_annotation(self.item2, self.a2, "中性")
        progress = self.db.batch_progress(self.batch)
        self.assertEqual([], progress["pending_gaps"])
        self.assertEqual([], progress["under_annotated"])
        self.assertTrue(progress["freeze_ready"])
        self.db.freeze_batch(self.batch, self.mgr)
        self.assertFalse(self.db.batch_progress(self.batch)["freeze_ready"])


if __name__ == "__main__":
    unittest.main()
