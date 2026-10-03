from tests.test_questions import valid_questions


def create_approved_case(test_case):
    from app.services.case_service import CaseService
    from app.services.document_service import DocumentService
    from app.services.question_service import QuestionService

    cases = CaseService(test_case.database)
    job = cases.create_job("JOB-ASSESS", "Engineer", "Senior")
    candidate = cases.create_candidate("CAND-ASSESS", "Candidate")
    case = cases.create_case(
        candidate["id"], job["id"],
        committee_members=[{"displayName": "Lead", "role": "LEAD"}],
    )
    data_root = getattr(
        test_case, "data_root", test_case.database.path.resolve().parents[1]
    )
    documents = DocumentService(test_case.database, data_root)
    jd = documents.import_manual_text(case["id"], "JD", "Senior engineer role")
    cv = documents.import_manual_text(case["id"], "CV", "Backend engineering experience")
    documents.confirm(jd["id"], jd["contentSha256"])
    documents.confirm(cv["id"], cv["contentSha256"])
    with test_case.database.transaction() as connection:
        member_id = connection.execute(
            "SELECT id FROM interview_case_committee_members WHERE interview_case_id=?",
            (case["id"],),
        ).fetchone()[0]
    questions = QuestionService(test_case.database)
    question_set = questions.create_manual_draft(case["id"], valid_questions(5))
    question_set = questions.approve(question_set["id"], member_id)
    return case, question_set, member_id
