# Run data schemas

The JSON Schemas use Draft 2020-12 and version their payloads with `schema_version: "1.0"`. They describe the files used by the pipeline; they do not fetch news or approve generation.

Schema files cover candidates, the selected-article evidence ledger, summaries, the six-beat story, storyboard, checks, cost and run manifest. `tests/fixtures/t006-sample/` is deliberately synthetic and uses `.example.test` URLs. It is architecture/test data, not a claim about real news.

JSON Schema handles structural constraints. Application checks must also enforce rules requiring text or aggregate evaluation:

- Each ledger fact/quote support span must match article text after whitespace normalization; quotes must be at most 25 words.
- Every summary has two sentences and each sentence cites known verified ledger fact IDs.
- No real-person full name or surname from the ledger may occur in story, storyboard or generation prompts.
- Story beats must not imply causal links between source events; beat 5 closes the fiction.
- Storyboard narration must contain no more than two words per second of its shot; shot durations sum to 37–51 seconds. With the three-second title and five-second source cards, total duration is 45–59 seconds.
- Cost arithmetic and budget hard stops must be calculated from measured unit prices by the T007 guard.
- Manifest artifact paths must resolve under the run's own `runs/<run-id>/` directory.

The fixture has six comic panels, one per beat, in an eight-shot storyboard. Two additional non-panel shots build simple transitions while staying within the duration bounds.