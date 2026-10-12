# Provider notes

## T003 — RSS feed probe (2026-10-11)

Fetched candidate RSS endpoints over HTTPS; requests were to feed URLs only, not article pages. Five feeds returned HTTP 200 with parseable XML; Al Jazeera timed out at 15 seconds in the sandbox and again at 30 seconds outside it.

| Publisher | Feed | HTTP result | Items in snapshot | Last 24 hours |
|---|---|---:|---:|---:|
| BBC | `https://feeds.bbci.co.uk/news/world/rss.xml` | 200 | 26 | 14 |
| The Guardian | `https://www.theguardian.com/world/rss` | 200 | 45 | 28 |
| NPR | `https://feeds.npr.org/1001/rss.xml` | 200 | 10 | 10 |
| The Times of Israel | `https://www.timesofisrael.com/feed/` | 200 | 13 | 13 |
| Ynet | `https://www.ynet.co.il/Integration/StoryRss3082.xml` | 200 | 30 | 23 |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | timeout | — | — |

From the four feeds selected for activation, selected the ten newest items within 24 hours from each (40 candidates). A lexical title-clustering spike yielded 38 clusters. It found one Pope Leo surgery cluster across BBC/NPR/Ynet (3 items), two candidate merges. This validates some cross-source overlap; the production clustering method remains T008's decision.

The Times of Israel feed works technically, but its content-distribution guidance says article material should not be copied beyond headline/subheadline and link. Since this demo displays generated summaries based on article text, it is not enabled pending a terms review. Ynet is used as the local source; its published RSS conditions permit private, non-commercial use. The active list therefore has four working publishers: BBC, The Guardian, NPR, and Ynet. The feed list is in `config/news_feeds.json`.

## Tavily probe - completed 2026-10-12

The approved basic probe used one text Extract batch and one news Search. Its ten newest last-day RSS URLs were distributed 3 BBC, 3 The Guardian, 2 NPR and 2 Ynet. No article text was saved in the repository.

| Publisher | Basic Extract | Basic text result |
|---|---:|---|
| BBC | 3/3 | 3 usable; 481-2,841 words, title matched in each result |
| The Guardian | 0/3 | 3 failed with `Failed to fetch url` |
| NPR | 2/2 | 2 usable; 1,184-2,423 words, title matched in each result |
| Ynet | 2/2 | 2 thin; 115 and 125 words, title matched |
| Total | 7/10 | 5 usable, 2 thin, 3 failed |

For this probe, usable means a successful result with at least 120 words, at least 800 characters, and at least two title terms found in the first 3,000 characters. A successful result below either volume threshold is thin; failed URLs are unusable. This is a mechanical screen of extraction volume and headline alignment, not a human factual review.

An additional advanced Extract batch retried the two thin Ynet URLs and tested three current Guardian RSS URLs. Both Ynet articles became usable (1,144 and 1,300 words); all three Guardian articles failed again. A final advanced Extract tested a third current Ynet RSS article as a replacement for one failed Guardian URL; it was usable at 821 words. The revised ten-article set (3 BBC, 2 Guardian, 2 NPR, 3 Ynet) therefore has 8 usable results and 2 Guardian failures, meeting Gate 0's 8/10 extraction threshold. Guardian extraction remains unreliable; T010 must keep its per-article description/paste fallback.

The initial Extract response reported 1 credit and 0.77 seconds; basic Search reported 1 credit and 3.95 seconds. The five-URL advanced retry reported 1 credit and 0.10 seconds; the single-URL advanced replacement reported 0 credits and 0.01 seconds. Total reported usage across the probe was 3 credits (USD 0.024 at the listed USD 0.008 pay-as-you-go rate if billed), within the approved limit. Account plan and remaining free credits were not available to inspect. Request IDs: basic Extract `27577d8b-6bad-4808-a0ed-c065575533b6`; Search `72ae1d6f-285c-42a6-b497-4c03401bafe2`; advanced retry `b8f61c5c-c358-48d0-b492-01e96c493a2c`; advanced replacement `a7c065b0-d25b-4b48-96d5-08c1e7faba8b`.

The basic Search query was `top world news today`, with `topic=news`, `time_range=day`, and restricted domains for BBC, The Guardian, NPR and Ynet. It returned 10 results: 8 BBC, 1 NPR, 1 Ynetnews and none from The Guardian. Comparing against the ten newest RSS titles per publisher, 5/10 Search results had a lexical Jaccard title match of at least 0.30; one more result about the energy ceasefire appeared related on manual review. Search surfaced some additional headlines, but its strong BBC skew and missing Guardian results do not improve publisher balance. Keep the four-feed RSS list as the only candidate source; do not add Tavily Search for this MVP. The candidate ranking remains cross-publisher coverage, then recency.

Tavily API references: [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract), [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Credits & Pricing](https://docs.tavily.com/documentation/api-credits), [Pricing](https://www.tavily.com/pricing). Checked 2026-10-12.
