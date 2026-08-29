#!/usr/bin/env python3
"""RED-1: A3 shared cmdId must not make the original legitimate acceptance hostile.

Contract: ISS-01, INV-01, INV-02, INV-14; fixtures FX-A3-IDENTITY-S00,
FX-A3-UNDELIVERED-S00.
"""
import unittest

from red_common import RedTest, O

FIXTURE = "A3-D1-s00-r0"
UNDELIVERED_RUN = "A3-D0-s00-r0"


class TestA3SharedCmdId(RedTest):

    def setUp(self):
        self.events = O.load_events(O.RESULTS + "/" + FIXTURE + "-events.csv")
        self.truth = O.load_truth(O.RESULTS + "/" + FIXTURE + "-truth.csv")

    def test_replay_actions_get_distinct_identities(self):
        """INV-01: replays sharing one parent cmdId need distinct attack ids."""
        replays = [r for r in self.truth if r["f"].get("event") == "replay"]
        cmd_ids = {r["f"]["cmdId"] for r in replays}
        self.assertEqual(len(cmd_ids), 1,
                         "fixture precondition: all replays share one cmdId")

        out = self.target_run(FIXTURE)
        expected = ("F0.action_ids holding %d distinct attack_action_id values, one "
                    "per replay truth row" % len(replays))
        why = ("score.py adds f['cmdId'] to hostile_ids, so N replays of one captured "
               "command collapse into a single hostile identity and the per-action "
               "denominator is lost")
        evidence = ("%s: %d replay rows all carrying cmdId=%s"
                    % (FIXTURE, len(replays), sorted(cmd_ids)[0]))

        ids = self.assert_field(out, "F0.action_ids", "INV-01",
                                "no per-action identity in the output",
                                expected, why, evidence)
        self.assertEqual(
            len(set(ids)), len(replays),
            self.defect("INV-01", "replay identity collapses onto the parent cmdId",
                        expected, "%d distinct identity/identities for %d replay(s)"
                        % (len(set(ids)), len(replays)), why, evidence))

    def test_original_legitimate_acceptance_stays_benign(self):
        """INV-02: the parent's own acceptance is legitimate traffic."""
        replays = [r for r in self.truth if r["f"].get("event") == "replay"]
        cmd_id = replays[0]["f"]["cmdId"]
        first_replay_t = min(r["t"] for r in replays)
        accepts = [r for r in self.events
                   if r["cat"] == "tc.accept" and r["f"].get("cmdId") == cmd_id]
        pre_action = [r for r in accepts if r["t"] < first_replay_t]
        self.assertEqual(len(pre_action), 1,
                         "fixture precondition: one pre-replay legitimate acceptance")
        rejects = sum(1 for r in self.events
                      if r["cat"] == "tc.reject" and r["f"].get("cmdId") == cmd_id)

        out = self.target_run(FIXTURE)
        expected = ("F1.accepted = 0: every delivered replay in this run was rejected, "
                    "and the pre-replay legitimate acceptance at t=%.4f is benign"
                    % pre_action[0]["t"])
        why = ("score.py:131-140 marks every tc.accept whose cmdId is in hostile_ids, "
               "and the captured command's own uplink shares that cmdId; this "
               "manufactures one phantom hostile acceptance per run")
        evidence = ("%s: single tc.accept for cmdId=%s at t=%.4f, %d subsequent "
                    "reject(s)" % (FIXTURE, cmd_id, pre_action[0]["t"], rejects))

        self.assert_value(out, "F1.accepted", 0, "INV-02",
                          "original legitimate acceptance relabelled hostile",
                          expected, why, evidence)
        self.assert_value(out, "F2.state_changed", 0, "INV-02",
                          "phantom hostile acceptance produces a state transition",
                          "F2.state_changed = 0: no hostile command was accepted",
                          why, evidence)

    def test_unmatched_action_is_not_delivered_not_discarded(self):
        """INV-14: an action with no outcome stays in the action denominator."""
        ev = O.load_events(O.RESULTS + "/" + UNDELIVERED_RUN + "-events.csv")
        tr = O.load_truth(O.RESULTS + "/" + UNDELIVERED_RUN + "-truth.csv")
        matched = O.match_actions_to_outcomes(UNDELIVERED_RUN, ev, tr, "A3")
        undelivered = [m for m in matched if not m["delivered"]]
        self.assertGreaterEqual(len(undelivered), 1,
                                "fixture precondition: one replay has no outcome")

        out = self.target_run(UNDELIVERED_RUN)
        expected = ("F0.actions = %d with F0.not_delivered = %d; an action that never "
                    "reached the command handler stays in the denominator"
                    % (len(matched), len(undelivered)))
        why = ("silently dropping an unmatched action shrinks the F0 denominator and "
               "makes a delivery failure indistinguishable from a prevented attack")
        evidence = ("%s: replay at t=%.2f produced no tc.accept/tc.reject"
                    % (UNDELIVERED_RUN, undelivered[0]["t"]))

        self.assert_value(out, "F0.actions", len(matched), "INV-14",
                          "action denominator does not cover every injected action",
                          expected, why, evidence)
        self.assert_value(out, "F0.not_delivered", len(undelivered), "INV-14",
                          "undelivered actions vanish from the denominator",
                          expected, why, evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
