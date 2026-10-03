from tests.evaluation_setup import create_submitted_assessment
from tests.test_brief import manual_brief


def create_brief_ready_case(test_case):
    from app.services.interview_brief_service import InterviewBriefService

    case, question_set, member_id, attempt = create_submitted_assessment(test_case)
    with test_case.database.transaction() as connection:
        connection.execute(
            "UPDATE interview_cases SET status='AI_ANALYSIS_FAILED' WHERE id=?",
            (case["id"],),
        )
    brief = InterviewBriefService(test_case.database).create_manual(
        case["id"], attempt["id"], manual_brief(), member_id
    )
    return case, question_set, member_id, attempt, brief
