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

This repository contains no resume, contact details, Notion database IDs, evidence records, application history, or private quality fixtures. Candidate data stays in the local run directory selected by the user.

## Requirements

- Codex or another agent supported by [`npx skills`](https://github.com/vercel-labs/skills)
- Python 3.9+ for the optional workflow validator
- A verified standard resume or publication baseline supplied locally by the user

## License

MIT
