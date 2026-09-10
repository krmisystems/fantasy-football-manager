# Repository instructions

These instructions apply to this repository and its subdirectories.

## Technical writing

- Use the `write-ste-technical-content` skill for technical writing.
- Use short sentences, active voice, and consistent terms.
- Separate verified results, estimates, planned work, and untested behavior.
- Preserve exact commands, paths, identifiers, and protocol fields.
- Do not claim formal ASD-STE100 conformity without a formal review.

## Completion checks

After repository updates, complete these checks before the final handoff:

1. Run the tests that apply to the change.
2. Run `uv run python scripts/validate_release.py` for release metadata and privacy checks.
3. Run the distribution checker:

   ```text
   python scripts/check_distribution_status.py --output .local-state/distribution-status/report.json --summary .local-state/distribution-status/summary.md
   ```

4. Read the JSON report and Markdown summary.
5. Report each pending, stale, failed, or unknown local and external state.
6. After an authorized push, merge, or publication, repeat the distribution check against the new remote state.

A successful checker process does not prove that all distribution channels are current.
Do not mark distribution verification complete while required evidence remains pending or unknown.
Distinguish completed code changes from external publication or synchronization that remains incomplete.
Use `--strict` when the calling process must fail for any pending, stale, failed, or unknown check, including local state.
The current checker cannot attest to the hosted Glama build commit, so strict mode cannot report all checks current.
Report this evidence limit instead of weakening the check.

The checker reads public service data and optional authenticated GitHub data.
Its execution does not authorize publication, a Glama sync, configuration changes, or messages to maintainers.
Do not perform these actions solely to make a status check pass.
Use existing user authorization when an external action is part of the task.
These instructions and the GitHub Actions workflow apply only to this repository.
They do not configure global Codex settings or native plugin hooks.

## Evidence and privacy

- Keep private reports under the ignored `.local-state/` directory.
- Do not commit credentials, personal team data, server names, or private paths.
- Never log tokens or session values.
- Use fictional fixtures for public tests and screenshots.
- Preserve separate version labels for the Python package and the Glama image.
- Do not infer a hosted build commit from matching README content or version text.
- Do not claim a full tool schema comparison when only names and descriptions were checked.

See [Distribution status](docs/DISTRIBUTION_STATUS.md) for the check scope and operating limits.
