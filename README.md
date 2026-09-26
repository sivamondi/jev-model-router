# Jev Model Router

Send every AI task to the right model.

Most organizations use several AI models. Some are cheap and fast, some can read images or
write code, and only some are approved for confidential data. Sending everything to the most
powerful model wastes money, and sending everything to the cheapest one is risky.

This app is a **model router**. You describe a task, [Jev](https://thejevai.com) works out what
the task needs, and the router picks the **cheapest model that meets every requirement**. It
tells you why each other model was ruled out, and whether a person should check the output.

**How it works**

1. **You describe the task**, plus any attachment and how fast you need the answer.
2. **Jev analyzes it** by answering six questions: Does it involve code? Does it need to see
   images? How much reasoning does it need? How sensitive is the data? How fast is it needed?
   How risky is a mistake?
3. **Every model is checked** against its skills, the data it's approved for, its speed, and how
   much text it can read (its context window).
4. **You get the best fit**: the cheapest model that passes, its estimated cost, and whether a
   person should review the output.

---

## Contents

- [1. Requirements](#1-requirements)
- [2. Create a Jev API key](#2-create-a-jev-api-key)
- [3. Install and run the app](#3-install-and-run-the-app)
- [4. Use the app](#4-use-the-app)
- [5. Configure models and rules](#5-configure-models-and-rules)
- [6. Run the tests](#6-run-the-tests)
- [7. Troubleshooting](#7-troubleshooting)
- [8. API reference](#8-api-reference)
- [9. Project layout and design notes](#9-project-layout-and-design-notes)

---

## 1. Requirements

- **Python 3.9 or newer.** Check with:
  ```bash
  python3 --version
  ```
- **A Jev account and API key** (next section). The app runs without one, but it can't
  analyze tasks automatically until you add a key.
- Internet access to reach `https://thejevai.com`.

## 2. Create a Jev API key

1. Go to **https://thejevai.com** and click **Get Started**.
2. **Sign in, or sign up** if you don't have an account yet.
3. Open the API keys page: **https://thejevai.com/settings/apikeys**
   (the docs at https://thejevai.com/docs also link to it under "Create an API key").
4. **Create a new key** and copy it. Keys start with `sk_`.
   Store it somewhere safe; treat it like a password.
5. **Check you have credits.** Each task the app sends to Jev uses **one credit**. See
   https://thejevai.com/pricing to add credits. If you run out, the app shows
   "Your Jev account is out of credits".

> **Keep the key secret.** Put it only in the `.env` file (step 3.4 below). Never paste it into
> source code, chat, or a commit. `.env` is already listed in `.gitignore`.

## 3. Install and run the app

Run these commands in a terminal.

**3.1 Go to the project folder**

```bash
cd ~/projects/jev-model-router
```

**3.2 Create a virtual environment** (a private Python install for this project; only needed once)

```bash
python3 -m venv .venv
```

**3.3 Activate it and install the dependencies**

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

**3.4 Add your API key**

```bash
cp .env.example .env
```

Open `.env` in any text editor and paste your key after `JEV_API_KEY=`, with no quotes or spaces:

```
JEV_API_KEY=sk_your_key_here
JEV_URL=https://thejevai.com/v1/systemone
JEV_MODEL=jev-latest
JEV_TIMEOUT_S=5
```

Save the file. (Files starting with a dot are hidden in Finder; press **Cmd + Shift + .** to show them.)

**3.5 Start the server**

```bash
uvicorn app.main:app --reload
```

You should see `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open;
press **Ctrl + C** to stop the server.

**3.6 Open the app**

Go to **http://localhost:8000**. The badge in the top right should say **Jev connected**.
If it says "Jev not connected", see [Troubleshooting](#7-troubleshooting).

**Next time**, you only need:

```bash
cd ~/projects/jev-model-router && source .venv/bin/activate && uvicorn app.main:app --reload
```

## 4. Use the app

**Describe your task**

1. Type a task in the box the way someone would ask an AI assistant, for example
   *"Summarize this 40-page contract and flag any risky clauses"*.
   Or click an example chip, such as **Write code with tests** or **Reply to a client dispute**,
   to fill in the form.
2. **Is anything attached?** Jev only reads your text, so tell it about files here:
   Nothing, Image or screenshot, Short doc (~10 pages), Report (~50 pages), or
   Very long doc (~600 pages). Choosing an image means only image-capable models qualify.
3. **How fast is the answer needed?** Leave on **Auto** to let Jev judge, or choose
   **Instant** (under 1s, live chat), **A few seconds** (someone is waiting), or
   **No rush** (background job). Slower models are ruled out for faster needs.
4. Click **Find the best model** (or press **Cmd + Enter** / **Ctrl + Enter**).

**Read the recommendation**

- **Best model for this task**: the model name, the requirements it meets, the estimated cost
  per task (and per 1,000 tasks), its typical speed, and the size of the input.
- **Human check**: either *"Have a person check the output before it's used"* with the reason,
  or *"Safe to use without a human check"*. Highly sensitive data is always flagged.
- **What Jev understood**: Jev's six answers in plain words. **counts** means the answer passed
  the policy threshold (for example, "Involves code: Very likely, 98%" means a coding model is
  required). **set by you** marks answers that came from your attachment or speed choice.
- **How the models compare**: every model from cheapest to most expensive. A green tick means
  it qualifies; a red cross shows exactly why it was ruled out, such as "Can't read images" or
  "Not approved for confidential data".
- **Send it to a person**: shown when no model meets every requirement.

**Try "what if" changes without using credits**

Click **Adjust** under "What Jev understood", change any answer (for example, raise the data
sensitivity), and click **Re-check with these answers**. Jev isn't called again, so no credit is
used. Click **Go back to Jev's answers** to return.

If Jev is unavailable (no key, no credits, or a network problem), click
**Answer the questions myself** to set the answers by hand and still see which model would be picked.

**Saving credits**

- Clicking an example only fills in the form; Jev is called when you click **Find the best model**.
- Running the same text again reuses Jev's earlier answers at no cost, even if you change the
  attachment or speed. The page says *"Reused Jev's earlier answers"*. Saved answers are cleared
  when the server restarts.

**Other things on the page**

- **Developer details** (at the bottom of a result): the exact request sent to Jev and its raw response.
- **Models and routing rules**: the model catalog and thresholds the app is using.
- The **sun/moon button** in the top right switches between light and dark themes.

## 5. Configure models and rules

The shipped model names and prices are **placeholders**. Replace them with the models you
actually use and your contract rates.

**`config/models.yaml`**: one entry per model.

```yaml
models:
  - name: small-fast
    input_price: 0.25        # dollars per million input tokens
    output_price: 1.25       # dollars per million output tokens
    context_k: 128           # context window, in thousands of tokens
    vision: false            # can it read images?
    coding: basic            # none | basic | good | strong
    max_reasoning: simple    # trivial | simple | moderate | hard
    p50_latency_s: 0.4       # typical (median) response time in seconds
    max_sensitivity: low     # none | low | medium | high  (highest data it's approved for)
    note: Optional description shown on hover in the catalog
```

Sensitivity levels in the UI: `none` = public, `low` = internal, `medium` = confidential,
`high` = highly sensitive (personal, financial, or regulated).

**`config/policy.yaml`**: thresholds that turn Jev's answers into decisions.

| Setting | Default | Meaning |
|---|---|---|
| `vision_threshold` | 0.5 | "Needs to see images" at or above this requires an image model |
| `coding_threshold` | 0.5 | "Involves code" at or above this requires good coding (strong for moderate or hard tasks) |
| `review_threshold` | 0.7 | "Risky if wrong" at or above this flags the output for a human check |
| `review_high_sensitivity` | true | Always flag highly sensitive data for a human check |
| `realtime_max_s` | 1.0 | Slowest typical speed allowed for "Instant" |
| `interactive_max_s` | 3.0 | Slowest typical speed allowed for "A few seconds" |

**`.env`**: `JEV_API_KEY`, `JEV_URL`, `JEV_MODEL`, `JEV_TIMEOUT_S` (seconds before a Jev call times out).

**Restart the server after changing any of these files.** Stop it with Ctrl + C, then run
`uvicorn app.main:app --reload` again.

## 6. Run the tests

```bash
source .venv/bin/activate
```

```bash
pytest -q
```

The tests cover the routing rules, Jev response parsing, retries, the fallback when Jev is
unavailable, reusing saved answers, and input validation. They use a fake Jev, so they need
no key, no network, and no credits.

## 7. Troubleshooting

| What you see | What to do |
|---|---|
| Badge says **Jev not connected** | `.env` is missing or `JEV_API_KEY` is empty. Add the key (step 3.4) and restart the server. |
| **Your Jev account is out of credits** | Add credits at https://thejevai.com/pricing. Meanwhile, use **Answer the questions myself**. |
| **Jev didn't accept your API key** | The key is wrong, expired, or deleted. Create a new one at https://thejevai.com/settings/apikeys, update `.env`, and restart. |
| **Jev couldn't read this task** with "could not reach Jev" | Network problem or Jev is down. Check your internet connection and try again. You can raise `JEV_TIMEOUT_S` in `.env`. |
| `address already in use` when starting | Another program uses port 8000. Stop it, or run on another port: `uvicorn app.main:app --reload --port 8010` and open http://localhost:8010. |
| `SyntaxError` or `TypeError` as soon as the server starts | Your Python may be older than 3.9 (`python3 --version`). Install a newer Python, delete `.venv`, and repeat steps 3.2–3.3. |
| `ModuleNotFoundError: No module named 'fastapi'` | The virtual environment isn't active. Run `source .venv/bin/activate`, then `pip install -r requirements.txt`. |
| Config changes don't show up | Restart the server. |
| **Send it to a person: No model in the catalog meets every requirement** | Working as intended. See "How the models compare" for why each model was ruled out, and add a suitable model to `config/models.yaml` if needed. |

## 8. API reference

Interactive docs are at **http://localhost:8000/docs** while the server is running.

**`POST /api/route`**: analyze a task with Jev and pick a model.

```json
{
  "text": "Write a Java retry decorator with JUnit tests",
  "attachment_tokens": 0,
  "has_image": false,
  "latency": "interactive"
}
```

- `text` (required): the task description.
- `attachment_tokens` (optional): approximate size of attached content, in tokens.
- `has_image` and `latency` (optional): facts you know better than Jev, since Jev only reads the
  text and urgency is rarely stated. They override Jev's answers. `latency` is `realtime`,
  `interactive`, or `batch`.
- `signals` (optional): skip Jev and route with your own answers:
  ```json
  "signals": {"needs_vision": 0, "needs_coding": 0.9, "complexity": "moderate",
              "sensitivity": "low", "latency": "interactive", "needs_review": 0.2}
  ```

The response has `source` (`jev`, `manual`, or `fallback`), `signals`, `user_set`, `cached`,
`jev_response`, and `decision` (`selected`, `estimated_cost`, `human_review`, `review_reason`,
`requirements`, and `candidates` with each model's `ruled_out` reasons).

Example with curl:

```bash
curl -s http://localhost:8000/api/route -H 'Content-Type: application/json' -d '{"text": "Translate hello into Spanish", "latency": "realtime"}'
```

**Other endpoints**

- `POST /api/jev-request`: returns the exact body that would be sent to Jev (contains no API key).
- `GET /api/config`: the model catalog and policy.
- `GET /healthz`: liveness check.

## 9. Project layout and design notes

```
app/
  main.py        FastAPI app: API endpoints and the web page
  router.py      Routing rules: pure functions, no I/O, fully unit tested
  jev_client.py  The six questions sent to Jev, the HTTP call, and response parsing
  config.py      Loads .env and the YAML config files
config/
  models.yaml    Model catalog
  policy.yaml    Routing thresholds
static/
  index.html     The web interface
tests/
  test_router.py
```

- **Jev supplies judgments; code supplies facts.** Input size is measured, not asked, and the
  user states attachments and urgency directly.
- **The final decision is made in code** (`app/router.py`), so it's predictable and testable.
- **Fail safe:** if Jev is unreachable or returns something unusable, the task goes to a person
  instead of guessing a model. Server errors and timeouts are retried once.
- **Privacy:** logs record the routing decision and token count, not the task text.
- Jev's responses are parsed from `data.result.answers`. Score answers use the per-level
  `probabilities` when present, falling back to `score`. If Jev changes its response format,
  update `app/jev_client.py`.
