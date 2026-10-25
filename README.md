# UARB Regulatory Document Agent

An email agent for the Nova Scotia Utility and Review Board's public documents database. Email it a matter number and a document type. It downloads up to 10 of those documents, zips them, and replies with the ZIP plus a summary of the matter.

**You send:**
> Hi Agent, can you give me Key Documents from M12205? Thanks!

**It replies (about 20 seconds later), with `M12205_Key_Documents.zip` attached:**
> Hi Frank,
>
> M12205 is about Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,275,000. It relates to Capital Expenditure Approvals within the Water category. The matter had an initial filing on April 7, 2025 and a final filing on October 23, 2025. Its status is Closed, with the outcome: Directions given. I found 13 Exhibits, 6 Key Documents, 43 Other Documents, and no Transcripts or Recordings (62 files in total). I downloaded all 6 Key Documents and am attaching them as a ZIP here.
>
> Attached:
> - 97289: Notice of Paper Hearing (April 11, 2025)
> - 97291: Hearing Order (April 11, 2025)
> - …

---

# Initial System Design

I broke the problem into independent components so the agent could build and test each step quickly.

```
Inbox poller → Parser → Scraper → Zipper → Reply sender
            (all wired together by one orchestrator)
```


### Components
1. **Inbox Poller**
   - Check the Gmail inbox for unread emails every 30s
   - Process one request at a time

2. **Email Parser**
   - Extract `matter_number` (e.g. M12205)
   - Extract `document_type` (Exhibits, Key Documents, Other Documents, Transcripts, Recordings)
   - Use an LLM for this, since people phrase requests differently
   - Double-check the matter number with a regex so the LLM can't make one up

3. **Website Navigation**
   - Navigate to:
   https://uarb.novascotia.ca/fmi/webd/UARB15
   - Enter matter number
   - Open relevant document tab

4. **Document Scraper**
   - Count available documents in every tab
   - Download up to 10 using the **GO GET IT** links

5. **Metadata Extractor**
   Extract:
   - Matter title
   - Category
   - Type
   - Date received
   - Date final submissions

6. **ZIP Compressor**
   - Bundle downloaded files

7. **Email Response**
   - Attach ZIP
   - Include metadata summary
   - Include document counts
   - Reply with a helpful error if something goes wrong (bad matter number, no documents, etc.)

### Key Decisions
- **Playwright for the browser.** The site is a FileMaker WebDirect app, so there's no plain HTML to scrape. Everything renders with JavaScript.
- **LLM only for parsing the email.** Metadata comes straight from the page, so numbers and dates can't be hallucinated.
- **Gmail IMAP/SMTP with an App Password.** Simplest setup with no OAuth.
- **Pydantic** to validate the parsed request and the scraped data.

### Tech Stack
- **Python 3.12**
- **Playwright** (Chromium) for browser automation
- **Claude Haiku 5.5** (Anthropic API) to parse emails into a structured request
- **Pydantic** for validation, and **pydantic-settings** to load secrets from `.env`
- **imap-tools** to read the Gmail inbox
- **smtplib** (built-in) to send replies
- **zipfile** (built-in) to build the ZIP
- **tenacity** to retry flaky page loads

---


# How It Works

```
Email to yourname+uarb@gmail.com
  → main.py        checks the inbox every 30s for requests without the "UARB-handled" label
  → orchestrator   skips machines (auto-replies, mailing lists, no-reply), then for each request:
      → parser     Claude + regex → { matter: M12205, type: Key Documents }
      → scraper    Playwright: search matter → read details + tab counts → download ≤ 10 files
      → zipper     one ZIP, kept under Gmail's size limit
      → mailer     reply in the same thread with the ZIP and the summary
  → label the request "UARB-handled"
```

| File | What it does |
|---|---|
| `src/main.py` | Commands (`run`, `inbox`, `parse`, `fetch`) and the inbox loop |
| `src/orchestrator.py` | Handles one email from start to finish, with a reply for every outcome |
| `src/parser.py` | Turns the email into a matter number and document type |
| `src/scraper.py` | Drives the UARB site: search, metadata, tab counts, downloads |
| `src/zipper.py` | Builds the ZIP within the size budget |
| `src/mailer.py` | Reads requests from Gmail, sends replies, and writes the reply text |
| `src/models.py` | Shared data shapes (Pydantic), validated at each step |
| `src/config.py` | Secrets from `.env`, everything else as constants |

---

# Setup

**1. Install** (Python 3.12):
```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt   # or: source .venv/bin/activate && pip install -r requirements.txt
.venv/bin/playwright install chromium
```

**2. Get a Gmail App Password.**
1. Turn on 2-Step Verification for the Gmail account the agent will use.
2. Create an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Google shows a 16-character password once; copy it.

**3. Get an Anthropic API key** from [console.anthropic.com](https://console.anthropic.com).

**4. Create `.env`:**
```bash
cp .env.example .env
```

| Variable | What it is |
|---|---|
| `GMAIL_ADDRESS` | The Gmail account the agent uses, e.g. `yourname@gmail.com` |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from step 2 |
| `ANTHROPIC_API_KEY` | Your Anthropic key from step 3 |
| `HEADLESS` | `true` to hide the browser, `false` to watch it work |

The agent's address is your Gmail address with `+uarb` added: `yourname+uarb@gmail.com`. Gmail delivers it to your normal inbox, and the agent ignores everything that wasn't sent to that address.

---

# Running It

```bash
.venv/bin/python -m src.main run            # watch the inbox and answer requests (Ctrl+C to stop)
.venv/bin/python -m src.main run --once     # answer what's waiting, then exit
```

Try each part on its own:
```bash
.venv/bin/python -m src.main inbox                                     # list waiting requests (changes nothing)
.venv/bin/python -m src.main parse "send me the exhibits for m12205"   # see what the parser understood
.venv/bin/python -m src.main fetch M12205 "Other Documents"            # scrape + zip + preview the reply, no email sent
```

### Demo
1. Start the agent: `.venv/bin/python -m src.main run`
2. From any other email account, send this to `yourname+uarb@gmail.com`:
   > Hi Agent, can you give me Other Documents files from M12205? Thanks!
3. Watch the terminal: email found → request parsed → 10 files downloaded → reply sent.
4. The reply arrives in the sender's inbox in the same thread, with a ZIP of 10 PDFs.

---

# When Things Go Wrong

Every request gets an answer. The only exception is automatic mail, which is never answered, to avoid reply loops.

| Situation | What the agent does |
|---|---|
| No matter number in the email | Asks for one, with an example |
| No document type | Asks which type, listing the five options |
| Two matters or two types in one email | Handles the first, and says so in the reply |
| Matter doesn't exist | "I couldn't find matter M99999…" |
| Requested tab is empty | Sends the matter summary and says there's nothing to attach |
| Files too big for one email | Attaches what fits (under 18 MB) and lists what was left out |
| One file fails to download | Sends the rest and lists the one that failed |
| Website down or broken | Retries once, then replies asking them to try again later |
| Out-of-office, mailing list, no-reply sender | Ignored |
| Sending the reply fails | Leaves the email unhandled and retries on the next check (up to 3 times) |
