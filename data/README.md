# Data

`banking77_routes.jsonl` is built from the test split of **Banking77** by PolyAI
([github.com/PolyAI-LDN/task-specific-datasets](https://github.com/PolyAI-LDN/task-specific-datasets)),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Paper: Casanueva et al., 2020,
*Efficient Intent Detection with Dual Sentence Encoders*.

Changes: the 77 intents are grouped into 7 support teams (see `banking77_mapping.json`), and the 3 intents
that no single team owns are left out (`supported_cards_and_currencies`, `fiat_currency_support`,
`country_support`). That leaves 2,960 of the 3,080 test messages. Each line keeps the original text and intent
and adds the team as `label`.

`banking77_question.json` is the question Jeff answers for every message: the 7 teams and what each one handles.
