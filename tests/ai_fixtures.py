from tests.test_question_generation import ai_payload as question_generation_payload


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
