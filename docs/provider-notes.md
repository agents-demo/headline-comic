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

## Tavily probe — awaiting key and billing confirmation

No Tavily API request has been made. `TAVILY_API_KEY` is absent from `.env`, and the presenter has not confirmed whether the account is restricted to the free tier or may bill over-quota usage.

Current Tavily docs say basic Extract charges 1 credit per 5 successful URL extractions and basic Search charges 1 credit per request. The planned T003 sample of 10 Extract URLs plus one Search is therefore up to 3 credits. Tavily documents 1,000 free credits/month with no card required; pay-as-you-go beyond that is $0.008/credit, so the maximum charge for this probe would be $0.024 if all credits were billable. Use `extract_depth=basic`, `format=text`, and `include_usage=true`; check both `results` and `failed_results`. For Search, use `topic=news`, `time_range=day`, and `include_domains_mode=restrict` with the four active publishers' domains. Record actual returned usage rather than assuming the estimate.

The decision whether Tavily search supplements RSS remains pending until the comparison is run. API reference: [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract), [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Credits & Pricing](https://docs.tavily.com/documentation/api-credits).
