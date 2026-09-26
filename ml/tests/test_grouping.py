import unittest

from domsignal_ml.grouping import ChatTracker
from domsignal_ml.slots import slots
from domsignal_ml.safety import direct_rule


def pred(name="elevator_out", utterance="report", entrance=2):
    return {
        "is_problem": True, "fine_class": name, "utterance": utterance,
        "slots": {"entrance": entrance, "floor": None},
    }


class GroupingTests(unittest.TestCase):
    def test_grouping_entrance_reply_and_unverified_closure(self):
        tracker = ChatTracker()
        one = tracker.consume(
            {"id": "1", "text": "Во втором подъезде не работает лифт",
             "ts": "2026-09-26T10:00:00"}, pred())
        two = tracker.consume(
            {"id": "2", "reply_to": "1", "text": "Во 2 подъезде тоже стоит лифт",
             "ts": "2026-09-26T10:05:00"}, pred())
        self.assertEqual(one["case_id"], two["case_id"])
        self.assertEqual(two["action"], "attached")
        other = tracker.consume(
            {"id": "3", "text": "В третьем подъезде не работает лифт",
             "ts": "2026-09-26T10:06:00"}, pred(entrance=3))
        self.assertNotEqual(other["case_id"], one["case_id"])
        done = tracker.consume(
            {"id": "4", "reply_to": "2", "text": "Лифт во втором подъезде заработал",
             "ts": "2026-09-26T11:00:00"}, pred(utterance="resolved_notice"))
        self.assertEqual(done["action"], "closed_unverified")
        self.assertEqual(len(done["open_cases"]), 1)
        self.assertEqual(done["open_cases"][0]["case_id"], other["case_id"])

    def test_house_and_class_boundaries(self):
        tracker = ChatTracker()
        a = tracker.consume({"id": "a", "house_id": "A", "text": "Лифт не работает",
                             "ts": "2026-09-26T10:00:00"}, pred())
        b = tracker.consume({"id": "b", "house_id": "B", "text": "Лифт не работает",
                             "ts": "2026-09-26T10:01:00", "reply_to": "a"}, pred())
        c = tracker.consume({"id": "c", "house_id": "A", "text": "Нет воды",
                             "ts": "2026-09-26T10:02:00", "reply_to": "a"},
                            pred(name="no_hot_water"))
        self.assertEqual(len({a["case_id"], b["case_id"], c["case_id"]}), 3)

    def test_word_entrance_slot(self):
        self.assertEqual(slots("Во втором подъезде сломан лифт")["entrance"], 2)
        self.assertEqual(slots("3 подъезд, 9 этаж"), {"entrance": 3, "floor": 9})

    def test_urgent_review_does_not_create_case(self):
        tracker = ChatTracker()
        result = tracker.consume(
            {"id": "risk", "text": "Запах газа в подъезде"},
            {"is_problem": False, "fine_class": None, "urgent_human_review": True},
        )
        self.assertEqual(result["action"], "urgent_human_review")
        self.assertEqual(result["open_cases"], [])
        self.assertEqual(direct_rule("Запах газа в подъезде"), "gas")
        self.assertIsNone(direct_rule("Нет запаха газа в подъезде"))


if __name__ == "__main__":
    unittest.main()
