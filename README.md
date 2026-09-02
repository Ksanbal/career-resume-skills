# Career Resume Skills

Public, portable agent skills for evidence-backed resume tailoring.

## Included skill

- `jd-tailored-resume`: verifies a job description, asks the candidate targeted follow-up questions, presents resume content for approval, and only then renders final artifacts.

## Install with npx skills

```bash
npx skills add Ksanbal/career-resume-skills --skill jd-tailored-resume -a codex -g -y
```

To inspect available skills first:

```bash
npx skills add Ksanbal/career-resume-skills --list
```

## Privacy

This repository contains no real candidate resume, contact details, Notion database IDs, evidence records, application history, or private quality fixtures. Candidate data stays in the local run directory selected by the user.

## Requirements

- Codex or another agent supported by [`npx skills`](https://github.com/vercel-labs/skills)
- Python 3.11, matching CI, and the pinned packages in `requirements.lock` for deterministic rendering and validation
- A verified standard resume or publication baseline supplied locally by the user

## Workflow gates

The skill enforces three local stages:

1. `preflight` rejects generated files before content approval.
2. `generation` requires an explicit approval whose SHA-256 still matches
   `content_review.md`.
3. `final` requires `resume_data.json`, `claim_trace.json`, `resume.html`, and
   `resume.pdf`, verifies each entry in `generated_artifact_hashes`, and confirms
   `resume_data_sha256` is the approved structured-data hash.

Run the deterministic gate self-test with:

```bash
python skills/jd-tailored-resume/scripts/self_test.py
```

## Synthetic clean-agent evaluation

`skills/jd-tailored-resume/scripts/eval_runner.py` initializes a real temporary Git
repository, installs only this repository-scoped skill, and invokes Codex as:

```text
codex exec --json --ephemeral --ignore-user-config --ignore-rules --config sandbox_workspace_write.network_access=true --sandbox workspace-write --skip-git-repo-check <prompt>
```

Supply a real, public JD URL. Only the candidate fixture is fictional; the JD must
not be labeled fictional. The sandboxed agent writes only a nonempty
`run/jd_snapshot.md` and a byte-identical copy of the locked semantic fixture at
`run/resume_data.json`. After Codex exits, the trusted controller rejects any other
scratch file or symlink, verifies those inputs and skill immutability, removes any
agent-authored presentation artifacts defensively, and invokes the fixed compiler
and auditor outside the agent sandbox only if the semantic-only handoff passes. It
then grades all six files under `run/`, including fixture and artifact hashes,
`EVALUATION_ONLY` status, and a fresh independent audit. The trace, controller
stdout/stderr, prompt, graded artifacts, hashes, and per-check results are copied to
the evaluation output directory.

```bash
python skills/jd-tailored-resume/scripts/eval_runner.py \
  --jd-url https://jobs.example.com/roles/platform-lead \
  --output-dir evaluation-output/run-001
```

Corpus mode is a policy-control evaluation, not the full rendering E2E above. It
installs the skill without the labeled corpus, disables network access, sends case
data without `expected_decision`, and requires one JSON decision with no file writes
or presentation artifacts. Run all 12 controls with a supplied Codex executable:

```bash
python skills/jd-tailored-resume/scripts/eval_runner.py \
  --corpus skills/jd-tailored-resume/fixtures/evaluation/eval_prompts.jsonl \
  --output-dir evaluation-output/corpus-001
```

Live Codex corpus runs remain opt-in. CI uses a label-independent deterministic fake
and executes every corpus control without a model or network call. The separate
clean-agent E2E above remains the rendering/provenance evaluation.

## License

MIT
