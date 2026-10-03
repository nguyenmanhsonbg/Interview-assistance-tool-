from tests.assessment_setup import create_approved_case


def create_submitted_assessment(test_case, *, answer_first=True):
    from app.services.assessment_service import AssessmentService

    case, question_set, member_id = create_approved_case(test_case)
    service = AssessmentService(test_case.database)
    service.prepare(case["id"], question_set["id"])
    attempt = service.start(
        case["id"], candidate_code_confirmed=True, committee_authorized=True
    )
    if answer_first:
        first_question = service.candidate_view(
            attempt["id"], attempt["candidateToken"]
        )["questions"][0]
        service.save_answer(
            attempt["id"], first_question["id"], attempt["candidateToken"],
            text="My private example with concrete evidence", is_answered=True,
            client_revision=1,
        )
    submitted = service.submit(attempt["id"], attempt["candidateToken"])
    return case, question_set, member_id, submitted
