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

    def test_service_policy_joins_entrances_and_keeps_resolution_for_review(self):
        tracker = ChatTracker(merge_policy="service_context_6h")
        one = tracker.consume(
            {"id": "1", "house_id": "A", "text": "Нет горячей воды в 1 подъезде",
             "ts": "2026-09-26T10:00:00"}, pred("no_hot_water", entrance=1))
        two = tracker.consume(
            {"id": "2", "house_id": "A", "text": "Нет горячей воды в 2 подъезде",
             "ts": "2026-09-26T10:10:00"}, pred("no_hot_water", entrance=2))
        self.assertEqual(one["case_id"], two["case_id"])
        self.assertIsNone(tracker.cases[0].entrance)
        done = tracker.consume(
            {"id": "3", "house_id": "A", "text": "Воду дали",
             "ts": "2026-09-26T11:00:00"},
            pred("no_hot_water", utterance="resolved_notice", entrance=None))
        self.assertEqual(done["action"], "resolution_pending_human")
        self.assertEqual(tracker.cases[0].status, "open")

    def test_service_policy_does_not_join_distinct_parking_issues(self):
        tracker = ChatTracker(merge_policy="service_context_6h")
        first = tracker.consume(
            {"id": "1", "text": "Машина закрыла проезд у 1 подъезда",
             "ts": "2026-09-26T10:00:00"}, pred("parking_violation", entrance=1))
        second = tracker.consume(
            {"id": "2", "text": "Машина закрыла проезд у 2 подъезда",
             "ts": "2026-09-26T10:10:00"}, pred("parking_violation", entrance=2))
        self.assertNotEqual(first["case_id"], second["case_id"])

    def test_context_reply_requires_evidence(self):
        tracker = ChatTracker(merge_policy="service_context_6h")
        first = tracker.consume(
            {"id": "1", "text": "Нет отопления", "ts": "2026-09-26T10:00:00"},
            pred("heating_none", entrance=None))
        negative = {"is_problem": False, "fine_class": None, "urgent_human_review": False}
        attached = tracker.consume(
            {"id": "2", "reply_to": "1", "text": "У нас тоже",
             "ts": "2026-09-26T10:05:00"}, negative)
        unrelated = tracker.consume(
            {"id": "3", "reply_to": "1", "text": "Спасибо за фото",
             "ts": "2026-09-26T10:06:00"}, negative)
        self.assertEqual(attached["case_id"], first["case_id"])
        self.assertIsNone(unrelated["case_id"])


if __name__ == "__main__":
    unittest.main()
