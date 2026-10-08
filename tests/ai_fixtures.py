from tests.test_question_generation import ai_payload as question_generation_payload


def question_variant_payload():
    return {
        "schemaVersion": "question-variant.v1",
        "operation": "GENERATE_QUESTION_VARIANT",
        "mode": "USER_PROMPT",
        "questionSetId": "set-1",
        "sourceQuestionId": "question-1",
        "variant": {
            "questionText": "Hãy mô tả một quyết định kỹ thuật khó và cách bạn đánh giá trade-off.",
            "purpose": "Đánh giá khả năng ra quyết định kỹ thuật.",
            "nextStepObjective": "Làm rõ bằng chứng và tác động của quyết định.",
            "expectedEvidence": "Một ví dụ cụ thể, các lựa chọn đã cân nhắc và kết quả.",
            "rubric": {
                "score0": "Không có ví dụ.",
                "score1": "Ví dụ mơ hồ, thiếu vai trò cá nhân.",
                "score2": "Có ví dụ nhưng phân tích còn hạn chế.",
                "score3": "Có ví dụ rõ và giải thích trade-off hợp lý.",
                "score4": "Có bằng chứng sâu, đo lường được và lập luận chặt chẽ.",
            },
        },
        "confidence": 0.82,
        "limitations": [],
    }


def question_addition_payload(target_category="APPLICATION"):
    source_kind = {
        "FOUNDATION": "STANDARDIZED",
        "APPLICATION": "SITUATIONAL",
        "DEEP_DIVE": "CV_VERIFICATION",
    }[target_category]
    return {
        "schemaVersion": "question-addition.v1",
        "operation": "GENERATE_QUESTION_ADDITION",
        "mode": "AUTO_GROUP",
        "questionSetId": "set-1",
        "targetCategory": target_category,
        "question": {
            "questionText": "Bạn xử lý thế nào khi một thay đổi làm tăng lỗi production?",
            "competencyKey": "incident_management",
            "sourceKind": source_kind,
            "purpose": "Đánh giá khả năng xử lý tình huống thực tế.",
            "nextStepObjective": "Làm rõ quyết định, trade-off và kết quả.",
            "questionType": "SCENARIO",
            "difficulty": "MEDIUM",
            "expectedEvidence": "Một ví dụ cụ thể, quyết định và kết quả đo được.",
            "rubric": {
                "score0": "Không có bằng chứng.",
                "score1": "Bằng chứng mơ hồ.",
                "score2": "Có ví dụ nhưng thiếu phân tích.",
                "score3": "Có ví dụ và giải thích hợp lý.",
                "score4": "Bằng chứng sâu, có kết quả đo được.",
            },
            "isRequired": True,
            "estimatedSeconds": 100,
        },
        "confidence": 0.8,
        "limitations": [],
    }


def answer_evaluation_payload(answered=True):
    return {
        "schemaVersion": "answer-evaluation.v1",
        "operation": "ANSWER_EVALUATION",
        "perAnswerEvaluations": [
            {
                "answerId": "answer-1", "questionId": "question-1",
                "score": 3 if answered else None,
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "reasoning": "Evidence matches rubric" if answered else "No answer provided",
                "evidenceFound": ["Specific example"] if answered else [],
                "concerns": [], "cvConsistency": "CONSISTENT" if answered else "NOT_ASSESSED",
            }
        ],
        "competencyEvaluations": [
            {
                "competencyKey": "backend", "summary": "Meets expectation",
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "confidence": 0.8,
            }
        ],
        "strengths": ["Clear reasoning"] if answered else [],
        "gaps": [], "conflicts": [], "risks": [],
        "recommendedLiveQuestions": [
            {
                "questionId": f"live-{index}", "text": f"Live question {index}",
                "targetCompetency": "backend", "reason": "Verify depth",
                "evidenceToSeek": "Trade-offs", "isRequired": True,
                "priority": "REQUIRED",
            }
            for index in range(1, 4)
        ],
        "interviewBrief": {
            "summary": "Assessment summary",
            "completion": {"answeredCount": 1 if answered else 0, "totalCount": 1, "durationSeconds": 60},
            "strengths": [], "gaps": [], "conflicts": [], "competencyMatrix": [],
            "requiredLiveQuestions": ["One", "Two", "Three"],
            "additionalLiveQuestions": [], "answerSignals": [],
            "confidence": 0.8, "limitations": [],
        },
        "confidence": 0.8,
        "limitations": [],
    }


def answer_evaluation_v2_payload(answered=True):
    return {
        "schemaVersion": "answer-evaluation.v2",
        "operation": "ANSWER_EVALUATION",
        "perAnswerEvaluations": [
            {
                "answerId": "answer-1", "questionId": "question-1",
                "score": 3 if answered else None,
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "reasoning": "Evidence matches rubric" if answered else "No answer provided",
                "evidenceFound": ["Specific example"] if answered else [],
                "concerns": [],
                "cvConsistency": "CONSISTENT" if answered else "NOT_ASSESSED",
            }
        ],
        "competencyEvaluations": [
            {
                "competencyKey": "backend", "summary": "Meets expectation",
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "confidence": 0.8,
            }
        ],
        "strengths": ["Clear reasoning"] if answered else [],
        "gaps": [], "conflicts": [], "risks": [],
        "confidence": 0.8,
        "limitations": [],
    }


def answer_evidence_payload(answered=True):
    return {
        "schemaVersion": "answer-evidence.v1",
        "operation": "ANSWER_EVIDENCE_ANALYSIS",
        "perAnswerEvidence": [
            {
                "answerId": "answer-1",
                "questionId": "question-1",
                "score": 3 if answered else None,
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "reasoning": "Evidence matches the approved rubric" if answered else "No answer provided",
                "evidenceFound": ["Specific example"] if answered else [],
                "concerns": [],
                "cvConsistency": "CONSISTENT" if answered else "NOT_ASSESSED",
            }
        ],
        "competencyEvidence": [
            {
                "competencyKey": "backend",
                "evidenceSummary": "The answer provides a concrete implementation example" if answered else "No evidence available",
                "evidenceStatus": "VERIFIED" if answered else "NOT_ASSESSED",
                "confidence": 0.8,
            }
        ],
        "confidence": 0.8,
        "limitations": [] if answered else ["The answer was not provided"],
    }


def follow_up_payload():
    return {
        "schemaVersion": "follow-up.v1",
        "operation": "FOLLOW_UP",
        "questions": [
            {
                "questionId": "follow-1", "text": "Explain the trade-off",
                "targetCompetency": "backend", "reason": "Need evidence",
                "evidenceToSeek": "Decision rationale", "stopCondition": "Evidence obtained",
                "priority": "HIGH",
            }
        ],
        "stopCondition": "Required evidence obtained",
        "confidence": 0.7,
        "limitations": [],
    }
