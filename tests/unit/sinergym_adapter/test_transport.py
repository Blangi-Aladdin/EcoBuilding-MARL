import unittest
from datetime import datetime
from threading import Event, Thread

from ecobuilding.sinergym_adapter.transport import Action, EpisodeCancelled, EpisodeError, Result, Transport


def result(i=None, episode=1):
    return Result(episode, i, datetime(2025, 1, 1), datetime(2025, 1, 1, 0, 15), {"energy": {"total_j": 3}})


class TransportTests(unittest.TestCase):
    def test_T02_capacity_and_stale_identity(self):
        t = Transport(1)
        with self.assertRaises(EpisodeError):
            t.send_action(Action(2, 0, (0, 0, 0)))
        with self.assertRaises(EpisodeError):
            t.publish(result(episode=2))
        action = Action(1, 0, (0, 0, 0))
        with self.assertRaises(EpisodeError):
            t.send_action(action)
        t.publish(result())
        with self.assertRaises(EpisodeError):
            t.publish(result())
        with self.assertRaises(EpisodeError):
            t.send_action(action)
        self.assertEqual(t.receive_result(1, lambda: True), result())
        t.send_action(action)
        with self.assertRaises(EpisodeError):
            t.send_action(Action(1, 1, (0, 0, 0)))
        self.assertEqual(t.receive_action(), action)

    def test_T02_consumed_messages_cannot_be_resent(self):
        t = Transport(1)
        t.publish(result())
        t.receive_result(1, lambda: True)
        action = Action(1, 0, (0, 0, 0))
        t.send_action(action)
        t.receive_action()
        with self.assertRaises(EpisodeError):
            t.send_action(action)
        with self.assertRaises(EpisodeError):
            t.publish(result())

    def test_T02_snapshot_is_detached_on_publication(self):
        t = Transport(1)
        message = result()
        t.publish(message)
        message.physical["energy"]["total_j"] = -1
        self.assertEqual(t.receive_result(1, lambda: True).physical["energy"]["total_j"], 3)

    def test_T02_first_error_wins_even_with_pending_result(self):
        t = Transport(1)
        original = ValueError("root")
        t.publish(result())
        t.fail("first", original)
        threads = [Thread(target=t.fail, args=(str(i),), daemon=True) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        with self.assertRaisesRegex(EpisodeError, "first") as error:
            t.receive_result(1, lambda: True)
        self.assertIs(error.exception.__cause__, original)

    def test_T02_spurious_notification_and_200_cancelled_waits(self):
        for action_side in (True, False):
            for _ in range(100):
                t, waiting, waiting_again, done = Transport(1), Event(), Event(), Event()
                errors = []
                original_wait = t._ready.wait

                def notify_when_waiting(timeout=None):
                    (waiting_again if waiting.is_set() else waiting).set()
                    return original_wait(timeout)

                t._ready.wait = notify_when_waiting

                def receive():
                    try:
                        if action_side:
                            t.receive_action()
                        else:
                            t.receive_result(2, lambda: True)
                    except EpisodeCancelled:
                        done.set()
                    except BaseException as exc:
                        errors.append(exc)

                thread = Thread(target=receive, daemon=True)
                thread.start()
                try:
                    self.assertTrue(waiting.wait(1))
                    with t._ready:
                        t._ready.notify_all()
                    self.assertTrue(waiting_again.wait(1))
                    self.assertFalse(done.is_set())
                finally:
                    t.cancel()
                    thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertTrue(done.is_set(), errors)

    def test_T02_result_liveness_probe_is_outside_lock(self):
        t = Transport(1)
        def alive():
            self.assertFalse(t._ready._is_owned())
            return False
        with self.assertRaisesRegex(EpisodeError, "worker exited"):
            t.receive_result(1, alive)

    def test_T02_1200_atomic_exchanges(self):
        t = Transport(1)
        errors = []
        def respond():
            try:
                t.publish(result())
                for i in range(1200):
                    action = t.receive_action()
                    if (action.episode_id, action.decision_id, action.values) != (1, i, (0, 1, 2)):
                        raise AssertionError(f"Invalid request at {i}: {action}")
                    t.publish(result(i))
            except BaseException as exc:
                errors.append(exc)
                t.fail("worker failed", exc)

        thread = Thread(target=respond, daemon=True)
        thread.start()
        try:
            self.assertEqual(t.receive_result(1, thread.is_alive), result())
            for i in range(1200):
                t.send_action(Action(1, i, (0, 1, 2)))
                self.assertEqual(t.receive_result(1, thread.is_alive), result(i))
        finally:
            t.cancel()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)

    def test_T02_duplicate_result_after_action_is_consumed(self):
        t = Transport(1)
        t.publish(result())
        t.receive_result(1, lambda: True)
        t.send_action(Action(1, 0, (0, 1, 2)))
        t.receive_action()
        t.publish(result(0))
        t.receive_result(1, lambda: True)
        with self.assertRaisesRegex(EpisodeError, "duplicate"):
            t.publish(result(0))

    def test_T02_cannot_publish_a_transition_before_its_action_is_consumed(self):
        t = Transport(1)
        t.publish(result())
        t.receive_result(1, lambda: True)
        t.send_action(Action(1, 0, (0, 1, 2)))
        with self.assertRaises(EpisodeError):
            t.publish(result(0))
