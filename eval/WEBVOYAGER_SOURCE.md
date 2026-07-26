# WebVoyager subset provenance

`webvoyager.jsonl` contains 10 unchanged tasks selected from the official WebVoyager dataset:

- Source: `MinorJerry/WebVoyager`
- Source file: `data/WebVoyager_data.jsonl`
- Source revision: GitHub `main`, retrieved 2026-07-21
- Original dataset size: 643 tasks across 15 websites

The subset uses one read-only information-retrieval task from each of 10 websites. Tasks that
explicitly require login, purchase, booking, cart changes, posting, or form submission were
excluded. The live websites and time-sensitive answers may still differ from the 2024 benchmark.

`webvoyager-round2.jsonl` contains 10 additional unchanged tasks from the same source. It focuses
on the six websites that loaded successfully in round 1 so the second run measures agent
navigation more directly instead of repeating known Cloudflare and CAPTCHA failures.
