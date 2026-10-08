# Newsdesk: your personal daily edition

A small news site that collects stories from wire services, public broadcasters and
general outlets (in Spanish and English). It ranks them by **how many independent
newsrooms report them** and how well they match **your profile** (topics, country,
age). It rebuilds every hour and sends you a **daily WhatsApp** with the top headlines
and a link.

```
RSS feeds (sources.yaml) ─► group the same event across outlets & languages
                         ─► score: coverage × relevance × freshness × sobriety
                         ─► static site (site/index.html) + WhatsApp summary
```

## How it tries to stay unbiased

| Problem | What Newsdesk does |
|---|---|
| One outlet's slant | A story is only "important" when several **independent** outlets cover it. Feeds from one newsroom (BBC World + BBC Mundo) count as one voice. For your country, outlets from different editorial lines are included on purpose, so no single line dominates. |
| Opinion presented as news | Opinion, editorial and column pieces are dropped (by URL and headline). |
| Hype and trends | Loaded words ("IMPACTANTE", "slams", "viral", "!"…) lower a story's score, and a hyped story from a single outlet never fills the top section. Of all the headlines for a story, the most neutral one is shown. |
| Not seeing other framings | Every card links to **each** outlet that covered the story, so you can compare. Stories from one outlet only are labelled *single source*. |
| One topic taking over | No more than 3 stories from the same topic in "Most important now". |

The rules are kept in plain lists in `newsdesk/lexicon.py` and `sources.yaml`, so you can read and change them.

## Your profile (`config.yaml`)

- `topics` with weights (built in: world, politics, economy, business, science,
  technology, health, environment, education, culture, sports, security, latam), plus
  custom topics with your own keywords.
- `muted_topics`: topics you never want to see.
- `country`: adds that country's outlets and a "Your country" section. Ready-made outlet
  lists exist for AR, ES, MX and US; local keywords also exist for CL, UY, CO, PE and GB.
- `age`: gives a small boost to topics that usually matter at your life stage
  (rent/jobs, mortgages/salaries, pensions/health). Turn it off with `use_age_hints: false`.
- `ui_language`: `en` or `es` for the site and the WhatsApp message.

> **Privacy:** if this repo is public, don't put personal details in `config.yaml`. Put
> them in a GitHub secret called `NEWSDESK_PROFILE` instead. It takes the same YAML and
> overrides the file:
> ```yaml
> profile:
>   age: 34
>   city: Rosario
> ```
> Your phone number and API keys are only ever read from secrets or environment variables.

## On your phone

The site works like an app: add it to your home screen and it opens full screen with
its own icon.

- **iPhone (Safari):** open the site → Share button → **Add to Home Screen**.
- **Android (Chrome):** open the site → ⋮ menu → **Add to Home screen** / **Install app**.

On a phone, stories after the lead show as compact rows with a thumbnail, the topic tabs
stay pinned at the top, and every link and button is big enough to tap. Other features:

- **Fresh news:** coming back to the app after 15 minutes or more reloads it with the
  latest edition. The ↻ button refreshes on demand.
- **Offline:** the last edition you opened still loads without signal (photos need a
  connection).
- **Password:** an installed app on iPhone has its own storage, so enter the password
  once inside the app with *Remember me* ticked. Your phone's password manager can save
  it too.
- **Opening from WhatsApp:** links open in WhatsApp's browser. On Android, if the app is
  installed, Chrome may offer to open it there. Otherwise open the app from your home
  screen.

## Password protection

The published page is encrypted with a password of your choice, so only someone
who has the password can read it. The first time you open the link you type the
password. With *Remember me on this device* ticked (the default), later visits open
straight away, including after each hourly update.

How it works: the page is encrypted with AES-256-GCM using a key derived from your
password (PBKDF2-SHA256, 600,000 rounds), and your browser decrypts it. The published
page holds only the encrypted data and the unlock form. The raw `edition.json` is
never published.

- Set the password as the GitHub secret `NEWSDESK_PASSWORD` (at least 10 characters).
  If it is missing, the workflow stops instead of publishing an open page.
- Pick a long password: anyone can download the encrypted page and try passwords
  offline. Four or five random words is a good choice.
- To change the password, update the secret and run the workflow. Devices that
  remembered the old one will ask again.
- To forget a device, clear the site's data in the browser.
- Locally, `export NEWSDESK_PASSWORD=...` before `build` or `serve` to get the same
  locked page. Without it the local page is unlocked.

## WhatsApp setup

Pick one provider and set `notification.provider` in `config.yaml` (default: `greenapi`).

**Green API (free; recommended).** Links your own WhatsApp, like WhatsApp Web, and sends
the news, with the top story's photo, to your *Message yourself* chat.
1. Sign up at <https://green-api.com> and create an instance on the free **Developer** plan.
2. In the instance, scan the QR code from your phone: WhatsApp → Settings → Linked devices →
   Link a device.
3. Copy `idInstance`, `apiTokenInstance` and `apiUrl` from the console. Save them as the
   secrets `GREENAPI_ID_INSTANCE`, `GREENAPI_API_TOKEN` and `GREENAPI_API_URL`.
4. Save your number as `WHATSAPP_PHONE`, e.g. `+5491122334455`.

Green API is not an official WhatsApp product, so treat it as "use at your own risk".
The risk is low for one message a day to yourself. If you unlink the device in WhatsApp,
the messages stop until you scan the QR code again. On the free plan the instance can
pause if you don't log into the Green API console for a while. If messages stop, check
the console.

**CallMeBot (free; sends only to your own number).**
1. Follow the WhatsApp steps on <https://www.callmebot.com/blog/free-api-whatsapp-messages/>:
   add their number to your contacts and send them the activation message.
2. They reply with an API key. Save it as the secret `CALLMEBOT_APIKEY`.
3. Save your number as `WHATSAPP_PHONE` in international format, e.g. `+5491122334455`.

**Twilio (more reliable; also sends the photo of the top story).**
Set `provider: twilio` and add the secrets `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_WHATSAPP_FROM` and `WHATSAPP_PHONE`. With the free *sandbox*, WhatsApp asks you
to message the sandbox again every 72 hours. A registered WhatsApp sender avoids that,
but messages that start a conversation then need an approved template.

## Run it for free on GitHub (recommended)

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Settings → Secrets and variables → Actions**: add `NEWSDESK_PASSWORD`,
   `WHATSAPP_PHONE`, your provider's secrets and, optionally, `NEWSDESK_PROFILE`.
4. **Actions → Newsdesk → Run workflow** (tick *Also send the WhatsApp message* to test).
   The site will be at `https://<user>.github.io/<repo>/`.

The workflow (`.github/workflows/newsdesk.yml`) rebuilds the site every hour and sends
the WhatsApp once a day. **The send time is set by the cron line in that workflow, in
UTC.** It is currently `45 10 * * *`, i.e. 07:45 in Argentina. Change both that line and
`NOTIFY_CRON` to pick your time. Notes:
- GitHub can start scheduled runs 5–15 minutes late, so the time is approximate.
- GitHub pauses scheduled workflows after 60 days with no commits. Push any small change
  every so often, or re-enable the workflow from the Actions tab.
- Anyone can reach the Pages URL, but without the password they only see the unlock
  form. On a free GitHub account the repo must be public to use Pages, so keep
  personal details in the `NEWSDESK_PROFILE` secret, not in `config.yaml`.

## Or run it on your own machine / server

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m newsdesk check-feeds        # which sources respond right now
python -m newsdesk build              # writes site/index.html
python -m newsdesk notify --provider console   # preview the WhatsApp text
python -m newsdesk serve --port 8000  # refresh every hour, WhatsApp at notification.time, serve the site
```

In `serve` mode the send time comes from `notification.time` and
`notification.timezone`, and it is exact. Put your secrets in the environment
(`export WHATSAPP_PHONE=...`).

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests run offline against sample feeds in `tests/fixtures/`.

## Adding or removing sources

Edit `sources.yaml`. Keep `outlet` the same for feeds from the same newsroom, use
`region: global` for international feeds or a country code for national ones, then run
`python -m newsdesk check-feeds`. Feed URLs change now and then. A broken feed is skipped
and doesn't stop the edition.
