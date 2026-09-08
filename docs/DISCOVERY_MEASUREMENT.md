# Discovery measurements

The collector records GitHub repository discovery measurements in private files.
It reads views, clones, referrers, and star counts through four GitHub API requests.
It does not publish results, change the repository, or measure active users.

## Sources and access

GitHub provides daily views and clones for the last 14 days.
It also provides the top 10 referrers for that period.
Daily timestamps use UTC boundaries.
Traffic access requires repository write access. Fine-grained tokens require the repository **Administration: read** permission.
See the [GitHub repository traffic API](https://docs.github.com/en/rest/metrics/traffic).

The collector reads `stargazers_count` from the [repository API](https://docs.github.com/en/rest/repos/repos#get-a-repository).
It preserves each star-count observation so later reports can calculate a net change.

Provide a token through `GH_TOKEN` or standard input.
Do not put the token in a command argument, source file, or public workflow.
The default workflow `GITHUB_TOKEN` is not assumed to have traffic access.
Use a private token configuration with the required repository permission.

The client sends only `GET` requests to `api.github.com`.
It validates the `OWNER/REPO` argument and blocks redirects.
A moved repository requires an explicit repository argument update.
The client does not follow a redirect with the credential.

## Establish a baseline

Run the collector in the project's installed environment, which includes `filelock`.
Set `GITHUB_REPOSITORY` to the intended `OWNER/REPO` identifier.
Set `PRIVATE_METRICS_DIRECTORY` to a private output directory.
Supply `GH_TOKEN` through the private process environment.

```sh
python scripts/collect_github_metrics.py collect \
  --repo "$GITHUB_REPOSITORY" \
  --data-dir "$PRIVATE_METRICS_DIRECTORY" \
  --baseline
```

A private credential wrapper can use standard input instead:

```sh
python scripts/collect_github_metrics.py collect \
  --repo "$GITHUB_REPOSITORY" \
  --data-dir "$PRIVATE_METRICS_DIRECTORY" \
  --token-stdin \
  --baseline
```

The wrapper must supply one token line through standard input.
The collector does not print the token or save request headers.
An explicit baseline can be recorded only once in a metrics directory.
If its star request fails, the baseline star count and later star delta remain unknown.

Without `--baseline`, the summary uses the first successful star observation as its star baseline.
The summary identifies which baseline rule it used.

## Collect weekly

Run the same command each week without `--baseline`:

```sh
python scripts/collect_github_metrics.py collect \
  --repo "$GITHUB_REPOSITORY" \
  --data-dir "$PRIVATE_METRICS_DIRECTORY"
```

Configure the timer and credential outside the public checkout.
Use one private output directory for each repository.
Review the timer's result after each run.
Collection gaps longer than the available traffic window can leave permanent gaps in the saved daily history.

| Exit code | Meaning |
|---|---|
| `0` | All four metrics were available in the latest report. |
| `2` | The latest report is partial, or no saved reports exist. |
| `1` | The collector could not complete its local operation. |

A partial report preserves successful requests and records errors for the other requests.
It never substitutes zero for an unavailable value.
A zero returned in a valid GitHub response remains zero.

## Read the report

The summary command reads saved files and makes no network requests:

```sh
python scripts/collect_github_metrics.py summary \
  --repo "$GITHUB_REPOSITORY" \
  --data-dir "$PRIVATE_METRICS_DIRECTORY"
```

The collector writes a checksummed report for each observation in `reports/`.
It also writes derived `state.json` and `summary.json` files.
Files use atomic replacement. New report and state files receive owner-only file permissions on systems that support those modes.
A process lock serializes updates to the metrics directory.
The next collection rebuilds derived state from the reports if an earlier write was interrupted.

| Measurement | Storage and interpretation |
|---|---|
| Daily views and clones | The newest observation replaces an older value for the same UTC date. Overlapping dates are not added together. |
| Previous seven complete UTC dates | Counts are added only when every date has a saved value. Missing dates remain listed explicitly. |
| Unique visitors and cloners | Daily and 14-day values remain separate. Daily uniques are not added into a weekly unique-user count. |
| Referrers | Each 14-day snapshot remains separate. Overlapping snapshots are not summed. |
| Stars | The report compares the latest successful count with the selected baseline. Net change can be negative. |

The summary exposes the latest request status and the time of the latest successful window or snapshot.
An older successful result does not hide a newer request failure.
Daily values can change when a later GitHub response revises them.
The stored daily observation time identifies the source of each retained value.

Repository views, clones, referrers, and stars do not establish installations, active users, or retained users.
Use them to compare discovery patterns with dated outreach or release activity.
Treat a matching change in traffic as an association unless separate evidence supports a causal claim.

## Privacy and validation

Keep reports, credentials, private timer files, and deployment details outside Git and release artifacts.
Repository traffic and referrer data can be private even when the repository is public.
Review a report before sharing it.
Public examples must use placeholders or fictional identifiers.

Tests use fictional responses and no GitHub requests.
They cover partial failures, overlapping dates, repeat imports, star baselines, redirect blocking, scope validation, and interrupted writes.
The first authenticated production collection and installed timer checks are recorded in [discovery acceptance](DISCOVERY_ACCEPTANCE.md).
