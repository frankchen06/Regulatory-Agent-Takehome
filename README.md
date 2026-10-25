# UARB Regulatory Document Agent


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

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt   # or: source .venv/bin/activate && pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env   # then fill in Gmail App Password + Anthropic API key
```
