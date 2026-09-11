# HOL scanner review

This review addresses the maintainer request on [catalog PR 411](https://github.com/hashgraph-online/awesome-codex-plugins/pull/411).
All results below are static checks. They do not verify live ESPN execution.

## Reproduction and correction

The earlier catalog job used `plugin-scanner==2.0.1116` and `cisco-ai-skill-scanner==2.0.14`.
A local reproduction against source commit `1105be07cd88b0d1202cde92f246ed89fec864f9` returned the same score and finding counts.
Both reported **97/100**, with **14 informational findings** and no critical, high, medium, or low findings.
Read the [original catalog job](https://github.com/hashgraph-online/awesome-codex-plugins/actions/runs/34544280506/job/103093464463).

The repository contains a canonical plugin and a generated repository-root mirror.
Each layout contains four skills. The scanner reports findings for both layouts.
The correction adds `license: MIT` to each skill and regenerates the mirror.
The license matches the existing repository and plugin licenses.
It also corrects outdated publication wording in three skills. Version 0.4.0 is now a published preview.

## Rule dispositions

| Rule | Earlier count | Current count | Disposition |
| --- | ---: | ---: | --- |
| `MANIFEST_MISSING_LICENSE` | 8 | 0 | Fixed. All four canonical skills and all four mirrored skills declare MIT. |
| `PLUGIN_JSON_INTERFACE_ASSET_TERMSOFSERVICEURL` | 2 | 2 | Documented omission. The optional field is absent. The project supplies its MIT license and privacy policy. No separate terms URL is claimed. |
| `PLUGIN_JSON_INTERFACE_ASSET_LOGO` | 2 | 2 | Documented omission. The optional field is absent. Both layouts declare a valid `composerIcon` asset. |
| `PLUGIN_JSON_INTERFACE_ASSET_SCREENSHOTS` | 2 | 2 | Documented omission. The optional field is absent. Public screenshots remain in the README and portfolio documentation. |

The six remaining findings concern absent optional fields. They do not identify unsafe URLs or missing declared assets.
The review retains these fields as omitted. It does not add placeholder URLs, suppress rules, or lower the scan threshold.

## Verified follow-up

On September 11, 2026, the corrected source passed these local checks:

- Scanner **3.0.153**, with Cisco skill scanner **2.0.14**, returned **97/100**, grade A, and six informational findings.
- Cisco skill scanning used the balanced policy with `static_analyzer`, `bytecode`, and `pipeline`. It returned zero findings.
- Scanner **3.0.151**, the version pinned in source CI, returned **97/100**, grade A, and the same six native findings.
- All 50 release validation tests passed.
- Root and canonical skill files match through the catalog generator.

The scanner 3.0.153 wheel matched the digest published in the catalog contribution guide:
`24ef86abac32db5b8ca2f73e84fa76c46fd758c95d74d1cd5d1e1a73f4e8cdb1`.

The [source scanner workflow](../.github/workflows/hol-plugin-scanner.yml) retains its reviewed action SHA, minimum score 80, and high-severity failure threshold.
The supplemental local scan uses the current catalog guide version. It does not replace or weaken source CI.
Cisco MCP scanning was unavailable. The scanner 3.0.151 local environment also lacked Cisco skill scanning.
These limits are separate from the completed Cisco skill check under scanner 3.0.153.

The published v0.4.0 artifacts retain their original bytes. These source skill corrections do not replace an existing release asset.
