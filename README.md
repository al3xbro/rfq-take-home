Hi all, thanks so much for the challenge! This is a short README, but a longer version is supplied in [IMPLEMENTATION.md](IMPLEMENTATION.md) that goes through everything in nitty gritty detail.

Time taken: about 4 hrs 30, but I spent a good amount of time on handwriting this readme 

## Running it

Needs Python 3.11+, Node, and an Anthropic API key. Two processes: the API and the UI.

**1. API** — creates the venv and installs dependencies on first run.

```bash
cd server
cp .env.example .env          # then put your ANTHROPIC_API_KEY in it
./run.sh                      # http://localhost:8000
```

**2. UI** — in a second terminal.

```bash
cd client
yarn
yarn dev                      # http://localhost:5173
```

Open [localhost:5173](http://localhost:5173) and drag `.eml` files from `samples/`
onto the page. Vite proxies the API in dev, so there is nothing else to configure.

**Loading every sample at once**, if you'd rather not drag ten files:

```bash
cd server && ./ingest_samples.sh
```

**Tests** — 53 run offline with the model stubbed, so no API key is needed:

```bash
cd server
.venv/bin/python -m pytest tests/ -q

RFQ_LIVE=1 .venv/bin/python -m pytest tests/ -q    # + 15 live checks vs labels.json
```

Results are held in memory only, so restarting the API clears the list.
Without a key the UI still loads and the API answers `503` on `/ingest`.

## Highlights and decisions
This section could get loooonggg.... so I'm going to keep it short. Details in [IMPLEMENTATION.md](IMPLEMENTATION.md)

### In order to process the wide range of attachments we have, I came up with multiple ways to stringify them
The biggest decision here was to convert PDFs into MD files for processing. Vision capable models are great, but:

- A lot of visual and structural context from a PDF would have been lost had we relied on a multimodal model, but MD safely represents it in text, and is the chosen language for LLMs

- It's a lot more efficient to convert to text instead of dumping pdf images into a model

- Text tends to be lost or hallucinated more when in large PDF file images

### For the approach, I chose to go with a multi step pipeline. This was done over a single llm call or agent for a few reasons:
- Reduces the amount of context a single LLM call needs. This reduces laziness and hallucinations and leaves room for scalability.
- We're able to split up deterministic work from LLM assisted work.
- I feel like this is pretty basic so I'll skip the other reasons

This pipeline does increase latency in most cases, however (untested, but I'm pretty confident in that guess). But, latency isn't a very big concern for this project I feel; in the real world, this would probably crawl someones inbox, and they probably wouldn't care about the "farm to fork" time.

### Agents are actually far and few inbetween.
Agents are all the rage right now, but not everything has to be an agent. They're great for open ended tasks, but for something this deterministic and rigid, they aren't the full answer.

Here, I decided to make the extraction and classification phases a simple LLM call because that's all they need to be. Every single time we run an email through, the first steps are always going to be those two, so there's no use in having an orchestrator decide to perform them every single time. 

We did use them for the resolution step however. The reason is because the resolution step can be super ambiguous and chaotic. Sure, we do have candidates, but when it comes to actually finding the product, the agent needs to decide if it wants to requery something it wasn't able to find, how to handle weird quantities, and just so much more here.

On scalability: A great way to scale product lookup is to probably categorize them hierarchically, and agentic decision making to search or traverse this would be great as well. 

### Confidence is determined from signals and warnings we control, not from model prose
When dealing with hard numbers and metrics, it's almost always better to rely on deterministic calculations rather than LLM guessing. We're now able to see exactly why we got that score.

### Quantity and catalog ambiguity handling was done by deliberately not guessing.
When things were uncertain, instead of making something up or guessing a probable answer, we instead guess and surface it to the UI, or we don't guess at all and retain original email text.

## Things to improve
1. I'd like to make the confidence system more robust. I feel it's pretty good right now, but some of it doesn't make sense, like how it's possible to lose the whole PDF from an email, but only have your confidence go down by 15%. This would require some heavy provenance work though, so maybe a job for another day.

2. I'd like to provide better support for images in pdfs. These RFQ PDFs will definitely have valuable visuals in them. They're not shown in these examples, but I can see it being very important.

3. Add text chunking for large rfqs. Currently, the extractor is one huge LLM call, which works fine for these small RFQs, but if some company suddenly ordered like 5000 unique products, that current stage wouldn't be able to keep up. It's the weakest link in terms of scalability here. If we take care of that, I believe we'd be able to handle immensely large pieces of content.

4. Latency - I didn't do any tuning for models, and I bet if we mixed and matched providers and smartly chosen what models should be used for what, we'd be able to shave down runtime while making the pipeline better.

5. In hindsight, for server load purposes, maybe eml file parsing and processing should be client side instead.

6. I think the provenance stuff is very cool here and I'd love to do it given the time. It would be cool to have in text citations or something where we can link back to the exact line a data point came from.