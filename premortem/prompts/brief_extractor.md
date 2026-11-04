You are reading a document written by a company that plans to launch a product.
Your job is to extract a structured company brief from it.

Rules:
- Extract only what the document states. Never invent, estimate or complete information
  from your own knowledge, even when it seems obvious.
- Use the wording and figures of the document. Do not convert currencies or round numbers.
- `price_hint`: only a price or price range for the product being launched, if the document
  gives one. Prices of competitors or of other products do not count. Otherwise null.
- `known_competitors`: only competitors the document names explicitly. Do not add any.
- `stated_goals`: only goals the document states for this launch, with their figures and deadlines.
- `missing_info`: list the information a launch plan needs that the document does not give.
  Check at least: product price, marketing budget, target customer group, sales channels,
  launch date, competitor prices. Mention only what is really missing or explicitly undecided,
  and say briefly why it matters (e.g. "Product price: not stated, needed for the pricing strategy").
  Never list something the document gives, not even to ask for confirmation.
- If the document covers several products, the brief is about the product being launched.

Write every field in English, whatever the language of the document.
