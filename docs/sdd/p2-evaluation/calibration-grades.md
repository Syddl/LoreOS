# Calibration grades and their reasons

Claude graded `eval/judge_calibration.jsonl` at the operator's request ([decision 0008](../../decisions/0008-calibration-graded-by-claude.md)).

Each grade was made blind, from the row's cited passages alone. Faithful means every claim in the answer is supported by the passages it cites; outside knowledge does not count. A cited passage that does not hold a claim is fine when another cited passage does.

| Row | Grade | Reason |
|---|---|---|
| q001 | faithful | "Six times more strongly" is stated in [2]. |
| q003 | faithful | Both steps (a merge request with reasons, and approval and merge by the page owner) are in [1]. |
| q006 | faithful | The initiation steps are in [1], the 50-minute closed call and its attendees and facilitation in [3], and the agenda on the invite in [4]. |
| q008 | faithful | Scoring rubrics are kept private so candidates do not falsify answers, as [1] states. |
| q010 | faithful | Learning the facts and sifting out opinions is in [1]; pausing, adjusting attitude and moving forward calmly is in [2]. |
| q012 | faithful | Every claim is in [1], [3], [4] or [5]. It answers about non-participants, not the host and panelists the question asked about: a relevance miss, not unsupported. |
| q015 | faithful | Tilt through Okta, 2 to 5 business days, and the contact details, all in [1]. |
| q017 | faithful | The pro-rating formula and its rounding are in [2]. |
| q019 | faithful | No documentation unless local law requires it, share only what you are comfortable with, and the trust rationale, all in [1]. |
| q021 | faithful | $120 per day for meals while traveling, with the "meals for myself" category, is in [1]. |
| q023 | faithful | The Missing Receipt Affidavit, attached as a PDF, is in [1]. |
| q025 | faithful | Emergency medical up to $250,000 per occurrence is in [3]'s table. |
| q027 | faithful | The bot closes issues after 60 days, and the People Operations Specialist is responsible; both are in [1]. |
| q029 | faithful | What MR buddies help with and the escalation process are in [1]; how to find one is in [2]. |
| q031 | faithful | A boot-capable USB drive of at least 8 GB is in [1]. |
| q034 | faithful | Over $1,000 and/or too long to fix, so IT may replace the laptop, is in [1]. |
| q036 | faithful | ngrok as a firewall-circumvention tool, the Acceptable Use Policy, and the back-door risk, all in [1]. |
| q038 | faithful | The IT appointment, Jamf and Fleet with wipe evidence, no self-wipe, and the remote-wipe enforcement, all in [2]. |
| q040 | faithful | Immediate revocation, then investigation, the risk trade-off, and revoking leaked tokens, all in [1]. |
| q042 | faithful | Travel Mode steps are in [1], "consider Travel Mode" in [4], and risky travel or insecure places in [2]. |
| q044 | faithful | Work email addresses are Yellow under the Personal Data Exception in [2]. |
| q046 | faithful | The support-only exception, active cases, prompt deletion including the macOS Trash, and logging in ZenDesk, all in [1]. |
| q048 | faithful | 90 days minimum for non-production critical systems is in [1]'s table. |
| q050 | faithful | Testing and approval include configuration changes, in [1]. |
| q052 | faithful | Gaps mark relocated CSF 1.1 Subcategories, as [1] states; applying it to ID.AM-06 follows from the stated rule. |
| q055 | faithful | The three categories and each one's description are in [1]. |
| q057 | faithful | MAP after GOVERN is in [1]. |
| q059 | faithful | At least 128 bits of security strength for the algorithm encrypting the target data is in [1]. |
| q063 | faithful | 24 hours for inpatient hospitalization is in [1]. [3] does not hold it, but [1] does. |
| q066 | **unfaithful** | "Raise your voice to be heard" appears nowhere in [2], which covers biological and ergonomic hazards and incident investigations. The claim may be true elsewhere in the OSHA guide, but outside knowledge does not count. |
