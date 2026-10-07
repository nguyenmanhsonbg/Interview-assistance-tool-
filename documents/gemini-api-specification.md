# Gemini API Integration Specification

Status: Current implementation baseline  
Version: 1.0  
Audience: Engineers implementing the AI integration in another system

This document describes the Gemini integration currently used by the VCS Interview Assistant. It is provider-focused so another backend can implement the same behavior without depending on the NestJS modules in this repository.

## 1. Scope

The integration supports:

1. Text generation with a system instruction and a user prompt.
2. Structured JSON generation for screening, question selection, evaluation, and profile analysis.
3. CV parsing from extracted text.
4. Optional direct CV document analysis using an inline base64 file part.

The current implementation uses Gemini REST generateContent. It does not use the Gemini SDK.

## 2. Provider and endpoint

### 2.1 Provider

Google Gemini API.

### 2.2 REST endpoint

    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}

Required header:

    Content-Type: application/json

The current code places the API key in the query string. A new system must never expose this request directly to a browser or mobile client. Keep the API key in a backend-only secret store. If the selected Gemini client/API version supports a safer server-side authentication header, it may be used by the new system, but the request payload contract remains the same.

### 2.3 Current model rotation

The repository currently accepts and rotates through these REST-compatible model IDs:

    gemini-3.6-flash
    gemini-3.5-flash
    gemini-3.5-flash-lite

These values are the current project baseline and must be verified against the target Google AI account before deployment because model availability can change.

Accepted aliases:

    gemini 3.6 flash       -> gemini-3.6-flash
    gemini 3.5 flash       -> gemini-3.5-flash
    gemini 3.5 flash lite  -> gemini-3.5-flash-lite

## 3. Configuration contract

| Variable | Required | Default | Description |
|---|---:|---:|---|
| GEMINI_API_KEY | Yes | None | Backend-only Gemini API key. |
| GEMINI_CV_PARSE_MODELS | No | All three default models | Comma-separated model IDs. Invalid IDs are ignored. The current implementation always retains the default model set. |
| GEMINI_CV_PARSE_TIMEOUT_MS | No | 45000 | Timeout for the dedicated CV parser. |
| GEMINI_CV_PARSE_MAX_CHARS | No | 36000 | Maximum extracted CV text sent to Gemini. |

The same model rotation configuration is currently used by both the general AI service and the dedicated CV parser.

Example:

    GEMINI_API_KEY=<server-side-secret>
    GEMINI_CV_PARSE_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite
    GEMINI_CV_PARSE_TIMEOUT_MS=45000
    GEMINI_CV_PARSE_MAX_CHARS=36000

## 4. Request contracts

### 4.1 General text generation

Used for prompts that return either plain text or JSON.

    {
      "contents": [
        {
          "role": "user",
          "parts": [
            {
              "text": "<USER_PROMPT>"
            }
          ]
        }
      ],
      "systemInstruction": {
        "parts": [
          {
            "text": "<SYSTEM_PROMPT>"
          }
        ]
      },
      "generationConfig": {
        "temperature": 0.2,
        "responseMimeType": "application/json"
      }
    }

The API response is read from:

    response.candidates[0].content.parts[*].text

All text fragments are concatenated and trimmed. An empty result is treated as an error.

### 4.2 General multimodal CV analysis

Used only when the normal file parser cannot extract usable text.

    {
      "contents": [
        {
          "role": "user",
          "parts": [
            {
              "text": "Read and extract all CV/resume information from the attached file. Return the result as JSON."
            },
            {
              "inline_data": {
                "mime_type": "application/pdf",
                "data": "<BASE64_FILE_CONTENT>"
              }
            }
          ]
        }
      ],
      "systemInstruction": {
        "parts": [
          {
            "text": "<PROFILE_ENRICHMENT_SYSTEM_PROMPT>"
          }
        ]
      },
      "generationConfig": {
        "temperature": 0.2
      }
    }

Supported application-level MIME types are PDF and DOCX. The source implementation sends the file as an inline base64 part.

### 4.3 Dedicated structured CV parser

This path parses text extracted from a sanitized CV document. The system instruction, parsing rules, schema, parser hints, and CV text are combined into one user text part.

    {
      "contents": [
        {
          "role": "user",
          "parts": [
            {
              "text": "<COMBINED_CV_PARSER_PROMPT>"
            }
          ]
        }
      ],
      "generationConfig": {
        "temperature": 0.1,
        "topP": 0.8,
        "responseMimeType": "application/json"
      }
    }

The combined prompt must instruct Gemini to return exactly one JSON object, without Markdown or explanations. The extracted CV text must be truncated to GEMINI_CV_PARSE_MAX_CHARS before it is inserted into the prompt.

## 5. Rotation and fallback behavior

The provider adapter must:

1. Normalize configured model aliases.
2. Build the model list from the default models and valid configured models.
3. Select the starting model using a process-local round-robin index.
4. Call one model.
5. If the call fails, try the next model in the rotation.
6. Stop on the first non-empty successful response.
7. Return the last error if every model fails.

The current implementation does not perform exponential backoff or retry the same model. A logical AI operation can therefore result in up to three sequential Gemini requests.

Fallback applies to:

- HTTP errors, including rate limits and provider failures;
- network errors;
- empty Gemini responses;
- malformed JSON returned by a structured operation.

For structured operations, malformed JSON is a retryable provider error, so the adapter tries the next configured model. A schema-valid JSON object is still required by the application layer before persistence.

The dedicated CV parser has an AbortController timeout. The general text adapter currently has no explicit request timeout; a new implementation should add one and make it configurable.

## 6. Response parsing

### 6.1 Plain text response

For evaluation summaries and Facebook content, return the concatenated text directly after trimming whitespace.

### 6.2 JSON response

For structured operations, the integration layer should:

1. Read and concatenate response.candidates[0].content.parts[*].text.
2. Trim whitespace.
3. Parse JSON.
4. Accept a JSON object or array according to the operation contract.
5. Reject an empty or invalid response.

The adapter accepts raw JSON, JSON inside a Markdown code fence, and a short commentary prefix before the JSON object. The Gemini request also uses `responseMimeType: application/json` to reduce formatting drift.

The adapter or feature caller must not silently invent a valid result when JSON parsing fails. The application schema registry remains the final authority for field names, enums, counts, and business rules; deterministic manual fallback is used only by the surrounding workflow when AI remains unavailable.

## 7. Prompt management

Prompts are identified by stable keys. In the current application, system prompts are loaded from a database with YAML defaults as fallback and cached in memory.

The model field stored with a prompt is legacy metadata. It may contain values such as sonnet or haiku, but runtime generation currently uses the Gemini rotation above and ignores those legacy Anthropic model choices.

### 7.1 Prompt key catalog

| Prompt key | Purpose | Expected output |
|---|---|---|
| enrich_profile | Enrich regex/file-parser CV data | ParsedProfile JSON object |
| detect_profile_anomalies | Detect career, skill, geography, and timeline anomalies | ProfileAnomalyDetection JSON object |
| enrich_job_description | Convert raw JD data into a structured evaluation schema | JSON object |
| ai_screening | Compare enriched JD and candidate profile for recruitment screening | RecruitmentPhase1AiScreeningResult JSON object |
| final_screening_recommendation | Produce an HR advisory decision hint from screening output | FinalScreeningRecommendationResult; currently optional/dormant |
| generate_survey_questions | Generate diagnostic interview questions | Array of survey question objects |
| suggest_questions_from_survey | Select question-bank items using profile and survey answers | Array of questionId and reasoning |
| suggest_next_question | Select the next question from rated/unrated session questions | sessionQuestionId and reasoning |
| evaluate_session | Analyze interview transcript and suggest BM04 ratings | AiEvaluationSuggestion JSON object |
| evaluation_summary | Write a Vietnamese evaluation summary | Plain text |
| vcs_facebook_recruitment_content_generator | Generate a Vietnamese recruitment post | Plain text |
| suggest_questions | Legacy direct question suggestion | Array of questionId and reasoning; no active caller found in the current source |

## 8. Feature-level integration map

The following routes are the current application entry points. A different system can expose different routes while reusing the same Gemini adapter and prompt contracts.

| Feature | Application trigger | Gemini operation |
|---|---|---|
| CV upload | POST /api/candidates/upload | enrich_profile; analyzeFileDirectly for parser fallback |
| Candidate re-analysis | POST /api/candidates/:idOrSlug/analyze | enrich_profile then detect_profile_anomalies |
| Clean CV parsing | POST /api/applications/:applicationId/cv/:cvDocumentId/parse | Dedicated structured CV parser |
| Application screening | POST /api/applications/:id/ai-screening/run | enrich_job_description if not cached, then detect_profile_anomalies, then ai_screening |
| Interview survey | POST /api/sessions/:id/survey/generate | generate_survey_questions |
| Question selection | POST /api/sessions/:id/suggest-from-survey | suggest_questions_from_survey |
| Next question | POST /api/sessions/:id/suggest-next-question | suggest_next_question |
| Evaluation summary | POST /api/evaluations/:id/generate-ai-summary | evaluation_summary |
| Evaluation suggestion | POST /api/evaluations/:id/generate-ai-evaluation | evaluate_session |
| Facebook preview | POST /api/extension/facebook/generate-preview-content with mode=AI | vcs_facebook_recruitment_content_generator |

The /api prefix assumes the application global prefix used by the current backend.

## 9. Core output schemas

### 9.1 Parsed profile

The profile parser returns an object with optional fields. A target system should preserve unknown fields for forward compatibility.

    {
      "name": "Candidate name",
      "email": "candidate@example.com",
      "phone": "+84...",
      "education": "...",
      "totalYearsExperience": 5,
      "experienceByLanguage": {
        "TypeScript": 3
      },
      "skills": ["Node.js", "PostgreSQL"],
      "techstack": ["NestJS", "React"],
      "certifications": [],
      "workExperience": [],
      "projects": [],
      "level": "SENIOR"
    }

The parser must not invent facts. Missing values should be omitted or represented by empty arrays where the consuming schema requires arrays.

### 9.2 Profile anomaly result

    {
      "overallRiskScore": 35,
      "riskLevel": "low",
      "anomalies": [
        {
          "type": "timeline_inconsistency",
          "severity": "medium",
          "description": "Human-readable explanation",
          "affectedFields": ["workExperience[0].startYear"],
          "evidence": "Specific CV evidence"
        }
      ],
      "summary": "One or two sentence summary.",
      "analyzedAt": "2026-10-05T00:00:00.000Z"
    }

Risk scores are advisory. The AI result must not automatically reject a candidate or replace HR review.

### 9.3 Recruitment screening result

    {
      "finalScore": 82,
      "recommendation": "STRONG_MATCH",
      "summary": "Short screening summary.",
      "strengths": [
        {
          "title": "Relevant backend experience",
          "evidence": "Evidence from the profile",
          "confidence": "HIGH"
        }
      ],
      "gaps": [],
      "risks": [],
      "status": "DONE"
    }

Allowed recommendations are:

    WAITING_HR_REVIEW
    STRONG_MATCH
    MATCH
    NEEDS_HR_REVIEW
    WEAK_MATCH
    REJECT_RECOMMENDED
    TALENT_POOL_RECOMMENDED

### 9.4 Question selection

    [
      {
        "questionId": "question-uuid",
        "reasoning": "Why this question is relevant"
      }
    ]

### 9.5 Survey question generation

    [
      {
        "question": "Describe how you handled ...",
        "category": "TECHNICAL",
        "subcategory": "Backend",
        "purpose": "Validate practical experience",
        "choices": ["No experience", "Basic", "Hands-on", "Expert"]
      }
    ]

### 9.6 Next question

    {
      "sessionQuestionId": "session-question-uuid",
      "reasoning": "The candidate has a gap in ..."
    }

### 9.7 Interview evaluation suggestion

The response must contain:

    {
      "technicalRatings": [],
      "personalityRatings": [],
      "overallResult": "PASS",
      "overallNotes": "...",
      "aiSummary": "...",
      "finalLevel": "SENIOR",
      "finalZone": "...",
      "finalSubZone": "...",
      "subcategoryInsights": []
    }

The exact rating values and category names are owned by the target system's domain model. The AI adapter should validate the result before persistence.

## 10. Caller error policy

The Gemini adapter should return typed errors so callers can choose the correct fallback.

| Caller | Current behavior |
|---|---|
| Profile enrichment | Log and return null; caller can preserve regex extraction. |
| Direct CV file analysis | Log and return null; caller can preserve parser output. |
| Profile anomaly detection | Log and return null; existing anomaly result may be preserved. |
| Survey/question suggestions | Log and return an empty array or null. |
| AI screening | Throw a server error and mark the screening attempt as failed. |
| Evaluation summary | Throw a server error because generation is an explicit user action. |
| Evaluation suggestion | Throw a server error because generation is an explicit user action. |
| Facebook AI preview | Fall back to deterministic template content. |
| Dedicated CV parser | Return no AI result and persist SKIPPED_OR_FAILED metadata. |

Recommended normalized error categories:

    MISSING_API_KEY
    MODEL_UNAVAILABLE
    RATE_LIMITED
    PROVIDER_ERROR
    NETWORK_ERROR
    TIMEOUT
    EMPTY_RESPONSE
    INVALID_JSON
    CONTENT_BLOCKED

## 11. Security and privacy requirements

1. Store GEMINI_API_KEY only in backend secrets or an equivalent secret manager.
2. Never send the key to frontend code, browser extensions, logs, analytics, or database records.
3. Never log full CV text, interview transcripts, API keys, base64 files, or full provider URLs containing the key.
4. Limit CV text size before sending it to Gemini.
5. Validate MIME type and file size before creating an inline base64 part.
6. Sanitize profile data before sending it to screening prompts.
7. Do not use protected attributes such as gender, religion, ethnicity, marital status, disability, or health data for scoring or recommendations.
8. Treat model output as untrusted data. Validate enums, numeric ranges, array sizes, and references such as questionId before persistence.
9. Keep HR as the final decision owner. AI screening and risk detection are advisory only.
10. Define data retention and Google API data-processing rules for the target deployment before production use.

## 12. Observability requirements

For every logical generation request, record metadata without recording sensitive prompt content:

    {
      "provider": "gemini",
      "model": "gemini-3.6-flash",
      "attemptedModels": ["gemini-3.6-flash"],
      "promptKey": "ai_screening",
      "status": "SUCCESS",
      "durationMs": 1234,
      "generatedAt": "2026-10-05T00:00:00.000Z"
    }

Useful metrics:

- request count by prompt key and model;
- success, fallback, timeout, rate-limit, and invalid-JSON counts;
- latency by model;
- token usage and estimated cost if returned by the selected Gemini API version;
- percentage of CV parses that fall back to regex-only data;
- percentage of Facebook previews that fall back to template content.

## 13. Minimal implementation algorithm

    validate input
    resolve prompt by promptKey
    resolve system prompt and user prompt
    resolve Gemini model rotation
    for each model in rotation:
        build generateContent request
        send request with timeout
        if HTTP/network/empty/malformed-JSON failure:
            record failure and continue
        extract text from candidates[0].content.parts[*].text
        if plain-text operation:
            return trimmed text
        parse JSON, including optional Markdown fence removal
        validate operation-specific schema
        return validated result
    raise normalized provider/parse error

## 14. cURL examples

### 14.1 Text generation

    curl -X POST \
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${GEMINI_API_KEY}" \
      -H "Content-Type: application/json" \
      -d '{
        "contents": [{
          "role": "user",
          "parts": [{"text": "Return JSON: {\"status\":\"ok\"}"}]
        }],
        "systemInstruction": {
          "parts": [{"text": "Return only valid JSON."}]
        },
        "generationConfig": {
          "temperature": 0.2,
          "responseMimeType": "application/json"
        }
      }'

### 14.2 Structured CV parsing

    curl -X POST \
      "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${GEMINI_API_KEY}" \
      -H "Content-Type: application/json" \
      -d '{
        "contents": [{
          "role": "user",
          "parts": [{"text": "<COMBINED_CV_PARSER_PROMPT>"}]
        }],
        "generationConfig": {
          "temperature": 0.1,
          "topP": 0.8,
          "responseMimeType": "application/json"
        }
      }'

## 15. Implementation checklist for another system

- [ ] Create a backend-only Gemini adapter.
- [ ] Add secret/configuration management for GEMINI_API_KEY.
- [ ] Implement model normalization and sequential fallback.
- [ ] Implement text and multimodal request builders.
- [ ] Implement the dedicated structured CV parser request.
- [ ] Add request timeouts, preferably for every request type.
- [ ] Add response extraction and JSON fence handling.
- [ ] Add operation-specific schema validation.
- [ ] Add prompt storage/versioning and cache invalidation if prompts are editable.
- [ ] Implement graceful fallbacks for non-critical enrichment features.
- [ ] Keep AI screening and HR evaluation advisory; do not auto-decide employment outcomes.
- [ ] Add metrics and redacted audit metadata.
- [ ] Test with mocked provider responses for success, fallback, timeout, rate limit, empty response, and invalid JSON.

## 16. Current repository references

The baseline implementation is located in:

- apps/backend/src/ai/ai.service.ts — general text, JSON, and inline-file Gemini calls.
- apps/backend/src/cv-parsing/gemini-cv-parser.service.ts — dedicated structured CV parser.
- apps/backend/src/cv-parsing/cv-parsing.service.ts — CV parsing orchestration and AI metadata.
- apps/backend/src/assets/seed/ai-prompts.yaml — default business prompts.
- apps/backend/src/assets/seed/ai-jd-promts.yaml — job-description enrichment prompt.
- apps/backend/src/assets/seed/ai-facebook-content-promt.yaml — Facebook content prompt.
- apps/backend/.env.example — configuration names.

Anthropic/Claude packages and CLI installation remain in the repository for legacy compatibility, but there is no active Anthropic fallback in the current Gemini generation path.

