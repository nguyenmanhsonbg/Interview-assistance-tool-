import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_frontend_avoids_unsafe_rendering_and_contains_refined_workflow(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        for forbidden in ("innerHTML", "new Function", "localStorage", "sessionStorage"):
            self.assertNotIn(forbidden, scripts)
        for route in (
            "/documents",
            "/questions",
            "/ai/evaluate",
            "/ai/evaluation",
        ):
            self.assertIn(route, scripts)
        for removed in (
            "/check-in",
            "/brief",
            "/live-interview",
            "/final-evaluation",
            "/assessment-attempts",
            "candidate_assessment",
            "enterCandidateMode",
        ):
            self.assertNotIn(removed, scripts)
        self.assertIn("apiDownload", scripts)
        self.assertIn("apiUpload", scripts)
        self.assertIn('pdf.input.accept = ".pdf,application/pdf"', scripts)
        self.assertIn("contentBase64: await fileToBase64(file)", scripts)
        self.assertIn("textContent", scripts)
        self.assertIn("currentSnapshotId", scripts)
        self.assertIn("clearSensitiveState", scripts)
        self.assertIn("generateCandidateCode", scripts)
        self.assertIn("readOnly", scripts)
        self.assertIn("Tên Lead HĐCM", scripts)
        self.assertNotIn("jobCode", scripts)
        self.assertNotIn("scheduledAt", scripts)

    def test_html_candidate_transfer_is_the_only_question_export_action(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        self.assertIn("/candidate-package/export", scripts)
        self.assertIn("/candidate-package/import", scripts)
        self.assertIn("candidate-html.v1", scripts)
        self.assertIn('htmlFile.accept = ".html,text/html"', scripts)
        self.assertIn('contentType: "text/html"', scripts)
        self.assertIn("MAX_HTML_PACKAGE_BYTES", scripts)
        self.assertNotIn("/question-set/export", scripts)
        self.assertNotIn("Excel fallback", scripts)

    def test_answers_screen_uses_centered_html_import_without_excel_section(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertIn("answer-import-card", scripts)
        self.assertNotIn("const excelFallback", scripts)
        self.assertNotIn("Excel fallback .xlsx", scripts)
        self.assertNotIn("Chưa có assessment snapshot.", scripts)
        self.assertIn("width: min(100%, 640px)", styles)
        self.assertIn("margin-inline: auto", styles)

    def test_no_third_party_runtime_import_manifest_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "requirements.txt").exists())
        self.assertFalse((root / "package.json").exists())

    def test_interview_workspace_shell_and_active_routes_are_present(self):
        root = Path(__file__).resolve().parents[1] / "web"
        index = (root / "index.html").read_text(encoding="utf-8")
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in ("app-shell", "main-content", "app.js"):
            self.assertIn(marker, index)
        for token in (
            "--ui-primary",
            "--ui-surface",
            "sidebar",
            "case-header",
            "case-stepper",
            "prefers-reduced-motion",
            "@media (max-width: 899px)",
        ):
            self.assertIn(token, styles)
        for marker in (
            "renderAppShell",
            "renderCaseHeader",
            "renderCaseStepper",
            "renderCasesWithStatus(status.input.value, listHost",
            "openDocumentEditor",
            "document-preview",
            "aria-modal",
            "renderTextFileImport",
            "previewText",
            "document-editor-text",
            "Lưu text và xác nhận",
            "Tiêu chí đánh giá",
            "questionPolicy",
            "item.score === null",
            "/settings",
            "/backups",
            'stepHref(caseId, "ai")',
            "/api/v1/auth/lock",
            "committee-session-expired",
            "generate.disabled",
            "manual.disabled",
            "host?.isConnected",
            "resultSnapshot",
            "item.concerns",
            "role",
            "tablist",
            "tabpanel",
            "skipLink?.addEventListener",
            "submitting",
            "X-Idempotency-Key",
            "next.addEventListener",
            "aria-selected",
            "aria-describedby",
            "role",
            "NOT_ASSESSED",
            "assessmentSnapshotId",
        ):
            self.assertIn(marker, scripts)
        self.assertIn('if (type === "JD")', scripts)
        self.assertNotIn('renderTextFileImport(caseId, "CV")', scripts)
        self.assertNotIn('field("Import file TXT, MD hoáº·c DOCX", "CV-file"', scripts)
        self.assertNotIn("renderDocumentHistory", scripts)
        self.assertNotIn("Nhập hoặc dán text", scripts)
        self.assertNotIn("textActions", scripts)
        self.assertNotIn("Rubric chấm điểm", scripts)
        self.assertNotIn("function manualQuestions", scripts)

    def test_question_generation_task_has_accessible_indeterminate_progress(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "task-progress",
            "task-progress-bar",
            'role", "progressbar"',
            'aria-valuetext',
            "PENDING_RETRY",
        ):
            self.assertIn(marker, scripts)
        self.assertIn("@keyframes task-progress", styles)

    def test_question_generation_empty_state_is_task_first_while_running(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "const taskRunning = Boolean(",
            '"Đang sinh bộ câu hỏi"',
            "if (taskRunning) {",
            "empty.append(taskHost);",
            "if (!taskRunning) {",
            "empty.append(generate, manual);",
        ):
            self.assertIn(marker, scripts)
        self.assertLess(scripts.index("empty.append(taskHost);"), scripts.index("if (!taskRunning) {"))

    def test_questions_screen_removes_legacy_copy_and_excel_button(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertNotIn("Số lượng hiển thị lấy trực tiếp từ dữ liệu question set; không hardcode theo layout.", scripts)
        self.assertNotIn("Excel fallback: xuất bộ câu hỏi", scripts)
        self.assertNotIn("/question-set/export", scripts)

    def test_question_variant_workflow_uses_proposal_first_actions(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "Gen theo prompt",
            "Tự động gen câu khác",
            "GENERATE_QUESTION_VARIANT",
            '"USER_PROMPT"',
            '"SAME_GROUP"',
            "/variants",
            "/discard",
            "/apply",
            "Dùng câu này",
            "Tạo lại",
            "Bỏ qua",
            "expectedQuestionSetUpdatedAt",
            "expectedSourceFingerprint",
            "proposalId",
            "question-variant",
            "2000",
            "question-prompt-count",
        ):
            self.assertIn(marker, scripts)
        for marker in ("question-actions", "question-variant-preview", "question-prompt-modal", "question-variant-status"):
            self.assertIn(marker, styles + scripts)
        self.assertIn('questionSet.status !== "APPROVED"', scripts)
        self.assertIn("assessmentAttemptId", scripts)
        self.assertIn("mutationLocked", scripts)
        self.assertIn("result?.task?.proposalId", scripts)
        self.assertIn("await onRefresh();\n        showError(", scripts)
        self.assertNotIn("Sửa bằng tay", scripts)
        self.assertNotIn("Lưu chỉnh sửa", scripts)

    def test_question_addition_workflow_uses_group_actions_and_proposal_first_flow(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "function openQuestionAdditionChoice(groupKey",
            "function openQuestionAdditionPrompt(groupKey",
            "function requestQuestionAddition(caseId, questionSetId, groupKey, mode, prompt)",
            "function renderQuestionAdditionProposal",
            "/question-additions",
            "QUESTION_ADDITION_OPERATION",
            '"AUTO_GROUP"',
            '"FOUNDATION"',
            '"APPLICATION"',
            '"DEEP_DIVE"',
            "question-addition-prompt",
            "question-addition-choice",
            "question-addition-proposal",
            "additionProposalId",
            "expectedQuestionSetUpdatedAt",
            "expectedSourceFingerprint",
            "ThÃªm cÃ¢u há»i",
            "questionCategory",
            "MAX_ADDITION_PROMPT_CHARS",
            "onFailed",
            "clearActiveQuestionAddition(caseId, questionSet.id, groupKey)",
        ):
            self.assertIn(marker, scripts)
        for marker in (
            "question-group-title",
            "question-add-card",
            "question-add-card-plus",
            "question-addition-choice",
            "question-addition-proposal",
            "question-addition-progress",
            "groupSection.append(addButton);",
        ):
            self.assertIn(marker, styles + scripts)
        self.assertIn('questionSet.status === "APPROVED" || assessmentStarted', scripts)
        self.assertNotIn("Sá»­a báº±ng tay", scripts)

        self.assertNotIn("question-group-count", styles + scripts)
        self.assertNotIn("group.items.length + ", scripts)

    def test_question_addition_popups_use_valid_vietnamese_copy(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        choice_start = scripts.index("function openQuestionAdditionChoice")
        prompt_start = scripts.index("function openQuestionAdditionPrompt")
        proposal_start = scripts.index("function renderQuestionAdditionFields")
        detail_start = scripts.index("function openQuestionAdditionDetails")
        detail_end = scripts.index("function renderQuestionAdditionProposal")
        popup_copy = scripts[choice_start:proposal_start]
        detail_copy = scripts[detail_start:detail_end]

        self.assertNotIn("Ã", popup_copy)
        self.assertNotIn("Â", popup_copy)
        for marker in (
            "Thêm câu hỏi",
            "Chọn cách tạo proposal cho group hiện tại.",
            "Tự động gen",
            "Hủy",
            "Gen câu hỏi theo prompt",
            "Yêu cầu bổ sung",
            "Hãy nhập prompt trước khi tạo câu hỏi.",
        ):
            self.assertIn(marker, popup_copy)
        self.assertLess(choice_start, prompt_start)
        for marker in (
            "C\u00e2u h\u1ecfi m\u1edbi \u0111\u1ec1 xu\u1ea5t",
            "C\u00e2u h\u1ecfi \u0111\u1ec1 xu\u1ea5t",
            "D\u00f9ng c\u00e2u h\u1ecfi n\u00e0y",
            "T\u1ea1o l\u1ea1i",
            "B\u1ecf qua",
            "Question Set \u0111\u00e3 thay \u0111\u1ed5i. H\u00e3y t\u1ea3i l\u1ea1i tr\u01b0\u1edbc khi \u00e1p d\u1ee5ng \u0111\u1ec1 xu\u1ea5t.",
        ):
            self.assertIn(marker, detail_copy)
        for marker in ("\u00c3", "\u00c4", "\u0081", "\u008f"):
            self.assertNotIn(marker, detail_copy)

    def test_question_addition_proposal_uses_summary_card_and_detail_modal(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        proposal_start = scripts.index("function renderQuestionAdditionProposal")
        load_start = scripts.index("function loadQuestionAdditionState")
        summary_renderer = scripts[proposal_start:load_start]

        self.assertIn("function openQuestionAdditionDetails(", scripts)
        self.assertIn("question-addition-summary", styles + scripts)
        self.assertIn("question-addition-detail", styles + scripts)
        self.assertIn("question-addition-columns", styles + scripts)
        self.assertIn("question-addition-question", styles + scripts)
        self.assertIn("question-addition-rubric", styles + scripts)
        self.assertIn("question-addition-actions", styles + scripts)
        self.assertIn("question-addition-detail-modal { width: min(960px", styles)
        self.assertIn("question-addition-choice .modal { width: min(560px", styles)
        self.assertIn("grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr)", styles)
        self.assertIn('setAttribute("aria-haspopup", "dialog")', scripts)
        self.assertIn("openQuestionAdditionDetails(proposal, questionSet, caseId, onRefresh)", scripts)
        self.assertNotIn("renderQuestionAdditionFields(question)", summary_renderer)
        self.assertNotIn("T\u00f3m t\u1eaft c\u00e2u h\u1ecfi", summary_renderer)
        fields_start = scripts.index("function renderQuestionAdditionFields")
        detail_start = scripts.index("function openQuestionAdditionDetails")
        fields_renderer = scripts[fields_start:detail_start]
        self.assertNotIn("question?.rubric", fields_renderer)
        self.assertIn('rubric.classList.add("question-addition-rubric")', scripts)
        self.assertIn("rubric.open = false", scripts)

    def test_questions_workspace_restores_selected_question_after_refresh(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertIn("const rememberedSelection = getState().selectedQuestion;", scripts)
        self.assertIn("setState({ selectedQuestion: { caseId, questionId: selectedId } });", scripts)
        self.assertIn("let restoreFocusId = selectedId;", scripts)

    def test_two_pass_evaluation_progress_preserves_previous_result_provenance(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "taskPhaseLabel",
            "EVIDENCE_ANALYSIS",
            "EVALUATION_SYNTHESIS",
            "AI đang phân tích bằng chứng",
            "AI đang tổng hợp đánh giá",
            "Kết quả hiện tại vẫn là bản cũ",
            "result.versionNo",
            "renderEvaluationResult(result, resultSnapshot)",
        ):
            self.assertIn(marker, scripts)
        self.assertNotIn("Interview Brief", scripts)
        self.assertNotIn("recommendedLiveQuestions", scripts)

    def test_ai_evaluation_result_has_summary_first_and_collapsible_answer_review(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "evaluation-result",
            "evaluation-header",
            "evaluation-summary",
            "evaluation-findings",
            "evaluation-competencies",
            "evaluation-answers",
            "evaluation-answer",
            'const details = document.createElement("details")',
            "details.open = index === 0",
            "evaluation-answer-grid",
        ):
            self.assertIn(marker, scripts)
        for marker in (
            ".evaluation-result",
            ".evaluation-header",
            ".evaluation-summary",
            ".evaluation-findings",
            ".evaluation-answer",
            ".evaluation-answer-grid",
        ):
            self.assertIn(marker, styles)


if __name__ == "__main__":
    unittest.main()
