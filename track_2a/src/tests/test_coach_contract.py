import unittest
from pydantic import ValidationError

from src.coach.flow import decide_next_action, state_updates_for
from src.coach.schemas import InterviewInput, public_view, to_plain_text
from src.coach.state import FEEDBACK_STAGE, STAGES, TOTAL_QUESTIONS, new_state
from form_server import validate_form_config


class CoachContractTests(unittest.TestCase):
    def test_new_state_is_ready_for_graph_invocation(self):
        state = new_state({"language": "fr-CH", "candidate_id": "C-01", "posting_id": "P-01"})

        self.assertEqual(state["messages"], [])
        self.assertEqual(state["stage"], STAGES[0])
        self.assertEqual(state["config"]["language"], "fr")
        self.assertEqual(state["config"]["candidate_id"], "C-01")
        self.assertEqual(state["question_count"], 0)
        self.assertIsNone(state["final_feedback"])

    def test_form_profile_is_accepted_and_personal_extras_are_dropped(self):
        request = InterviewInput.model_validate(
            {
                "messages": [{"role": "user", "content": "Bonjour"}],
                "config": {
                    "language": "fr",
                    "profile": {
                        "first_name": "Luca Muster",
                        "age": 15,
                        "email": "private@example.com",
                        "school": {"level": "Sek A", "unknown": "ignored"},
                    },
                },
            }
        )

        profile = request.config.profile.model_dump()
        self.assertEqual(request.messages[0].content, "Bonjour")
        self.assertEqual(profile["first_name"], "Luca")
        self.assertNotIn("email", profile)
        self.assertNotIn("unknown", profile["school"])

    def test_form_backend_returns_normalized_profile_and_rejects_invalid_age(self):
        config = validate_form_config(
            {
                "language": "fr-CH",
                "profile": {
                    "first_name": "Luca Muster",
                    "age": 15,
                    "target_occupation": "Menuisier",
                    "email": "private@example.com",
                },
                "posting_text": "Formation technique de quatre ans.",
                "challenge": "motivation",
            }
        )

        self.assertEqual(config["language"], "fr")
        self.assertEqual(config["profile"]["first_name"], "Luca")
        self.assertEqual(config["posting_text"], "Formation technique de quatre ans.")
        self.assertEqual(config["challenge"], "motivation")
        self.assertNotIn("email", config["profile"])
        with self.assertRaises(ValidationError):
            validate_form_config({"profile": {"age": 99}})

    def test_weak_answer_gets_one_followup_only(self):
        state = {
            "stage": STAGES[0],
            "question_count": 1,
            "stage_question_count": 1,
            "followup_count": 0,
            "analyses": [{"quality_level": 1}],
        }

        self.assertEqual(decide_next_action(state), "followup")
        state.update(state_updates_for("followup", state))
        self.assertEqual(decide_next_action(state), "next_question")

    def test_quotas_finish_after_thirteen_main_questions(self):
        state = new_state()
        action = decide_next_action(state)

        while action != "finish":
            state.update(state_updates_for(action, state))
            state["analyses"] = [{"coach_action": "continue"}]
            action = decide_next_action(state)

        state.update(state_updates_for(action, state))
        self.assertEqual(state["question_count"], TOTAL_QUESTIONS)
        self.assertEqual(state["stage"], FEEDBACK_STAGE)

    def test_public_view_and_plain_text_output(self):
        view = public_view(new_state())

        self.assertEqual(view["stage"], STAGES[0])
        self.assertIsNone(view["final_feedback"])
        self.assertEqual(to_plain_text("## Bonjour\n- **Luca**"), "Bonjour Luca")


if __name__ == "__main__":
    unittest.main()