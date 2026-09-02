# Evaluation-only fictional fixtures

`fictional_korean_resume.json` and `eval_prompts.jsonl` contain synthetic test data.
Every person, company, school, credential, project, date, outcome, and job URL is
fictional. The compiler adds a visible Korean/English evaluation banner to fixture
output. **Never use these fixtures or generated artifacts for a real application.**

The prompt corpus includes one expected happy path and negative controls for:

- generation before approval;
- invented evidence or metrics;
- stale approval reuse;
- conversion of synthetic output into a production artifact.

Corpus mode removes `eval_prompts.jsonl` from the installed scratch skill before
invoking Codex, so expected labels remain controller-only. It requires a JSON-only
decision and rejects file writes, presentation artifacts, and skill mutation. This
policy corpus is separate from the full clean-agent rendering E2E. CI uses a
label-independent fake and does not invoke a model or network service.
