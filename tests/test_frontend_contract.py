import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_branding_uses_vcs_interview_asistant_copy(self):
        root = Path(__file__).resolve().parents[1] / "web"
        index = (root / "index.html").read_text(encoding="utf-8")
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertIn('link("VCS", "#/cases", "brand")', scripts)
        self.assertIn('element("span", "Interview Asistant", "brand-subtitle")', scripts)
        self.assertIn('element("span", "VCS", "brand-name")', scripts)
        self.assertIn("<title>VCS — Interview Asistant</title>", index)

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

    def test_answers_screen_uses_versioned_import_toggle_and_collapsible_questions(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        answers_start = scripts.index("async function renderAnswers")
        answers_end = scripts.index("function renderListSection")
        answers_renderer = scripts[answers_start:answers_end]
        workspace_start = scripts.index("function renderSnapshotWorkspace")
        workspace_renderer = scripts[workspace_start:answers_start]

        self.assertIn("const hasSnapshot = Boolean(snapshot);", answers_renderer)
        self.assertIn("importCard.hidden = hasSnapshot;", answers_renderer)
        self.assertIn('button("Thêm kết quả"', answers_renderer)
        self.assertIn('document.createElement("details")', workspace_renderer)
        self.assertIn("questionDetails.className = \"card answer-question-collapse\"", workspace_renderer)
        self.assertIn("questionDetails.open = index === 0", workspace_renderer)
        for marker in (
            "answer-import-actions",
            "answer-question-list",
            "answer-question-summary",
            "answer-question-meta",
        ):
            self.assertIn(marker, styles + scripts)

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

    def test_cv_document_card_uses_short_title_and_import_label(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertIn('const title = type === "JD" ? "Job Description" : "CV";', scripts)
        self.assertIn('const importPdf = button("Import file CV PDF"', scripts)
        self.assertNotIn('const title = type === "JD" ? "Job Description" : "Curriculum Vitae";', scripts)
        self.assertNotIn('button("Đọc và import CV PDF"', scripts)

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

    def test_case_creation_uses_jd_derived_level_and_questions_wait_for_readiness(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertNotIn('field("Level", "targetLevel"', scripts)
        self.assertNotIn("values.targetLevel", scripts)
        self.assertNotIn("targetLevel: values", scripts)
        self.assertIn('targetLevelStatus === "READY"', scripts)
        self.assertIn("levelReadyForQuestions", scripts)
        self.assertIn("Cần xác định level từ JD trước khi tạo Question Set.", scripts)

    def test_jd_level_extraction_ui_has_status_progress_and_retry(self):
        root = Path(__file__).resolve().parents[1] / "web"
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in (
            "targetLevelStatus",
            "Đang xác định level từ JD",
            "Xác định level từ JD thất bại",
            "/job-level/extract",
            "retry: true",
            'resumeTask(caseId, "documents"',
            "job-level-status",
        ):
            self.assertIn(marker, styles + scripts)
        self.assertIn("targetLevel", scripts)
        self.assertIn("targetLevelConfidence", scripts)

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

    def test_question_addition_progress_uses_valid_vietnamese_copy(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        progress_start = scripts.index("function loadQuestionAdditionState")
        progress_end = scripts.index("function questionVariantPath")
        progress_copy = scripts[progress_start:progress_end]

        for marker in (
            "AI đang thêm câu hỏi",
            "Đang tải đề xuất đã tạo...",
            "Đang kiểm tra đề xuất đã lưu...",
        ):
            self.assertIn(marker, progress_copy)
        for marker in ("Ã", "Ä", "Â", "\ufffd"):
            self.assertNotIn(marker, progress_copy)

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
        self.assertIn(".modal-backdrop.question-addition-detail { padding: 12px", styles)
        self.assertIn(".modal.question-addition-detail-modal { width: min(1200px", styles)
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

    def test_read_only_question_previews_hide_next_step_objective_while_manual_payload_keeps_it(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        addition_start = scripts.index("function renderQuestionAdditionFields")
        addition_end = scripts.index("function openQuestionAdditionDetails")
        variant_start = scripts.index("function renderVariantFields")
        variant_end = scripts.index("function renderQuestionVariantPreview")
        manual_start = scripts.index("function createManualQuestionModel")
        manual_end = scripts.index("async function renderQuestions")

        self.assertNotIn("question?.nextStepObjective", scripts[addition_start:addition_end])
        self.assertNotIn("variant?.nextStepObjective", scripts[variant_start:variant_end])
        manual_renderer = scripts[manual_start:manual_end]
        self.assertIn("const objective = field(", manual_renderer)
        self.assertIn('[objective, "nextStepObjective"]', manual_renderer)

    def test_questions_workspace_restores_selected_question_after_refresh(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        self.assertIn("const rememberedSelection = getState().selectedQuestion;", scripts)
        self.assertIn("setState({ selectedQuestion: { caseId, questionId: selectedId } });", scripts)
        self.assertIn("let restoreFocusId = selectedId;", scripts)

    def test_question_detail_hides_unneeded_metadata_and_localizes_question_type(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        detail_start = scripts.index("function renderQuestionDetail")
        detail_end = scripts.index("function renderQuestionWorkspace")
        detail_renderer = scripts[detail_start:detail_end]

        for hidden_field in (
            "question.sourceKind",
            "question.nextStepObjective",
            "question.isRequired",
            "question.estimatedSeconds",
        ):
            self.assertNotIn(hidden_field, detail_renderer)
        self.assertIn("questionTypeLabel(question.questionType)", detail_renderer)
        self.assertIn("LONG_TEXT: \"Tự luận\"", scripts)
        self.assertIn("MULTI_CHOICE: \"Chọn đáp án\"", scripts)

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
