# Job Radar

Every morning (about 9:00 IST) this program finds Java backend jobs in India that match your resume for 1 to 3 years of experience,
checks the links, and sends you up to 50 of them by email and into a Google Sheet.

It runs free on GitHub Actions. You never have to open it.

## One-time setup (about 30 minutes)

1. **Create a PRIVATE GitHub repo** called `job-radar` and push this folder to it.
2. **Adzuna keys (required).** Sign up free at https://developer.adzuna.com, create an app, copy the *app id* and *app key*.
3. **Jooble key (optional).** Request one at https://jooble.org/api/about. Skip it if it does not arrive quickly.
4. **Gmail app password.** Google Account > Security > turn on 2-Step Verification > App passwords > create one named "job-radar".
5. **Google Sheet.** Open your tracker sheet (or a new one) > Extensions > Apps Script > paste `apps_script/Code.gs`,
   change `SECRET` to a long random string > Deploy > New deployment > Web app > Execute as *Me*, access *Anyone* > Deploy.
   Copy the Web app URL. Jobs land on a tab called "Daily Jobs".
6. **GitHub secrets.** Repo > Settings > Secrets and variables > Actions > New repository secret. Add:

| Secret | Value |
| ------ | ----- |
| ADZUNA_APP_ID / ADZUNA_APP_KEY | from step 2 |
| JOOBLE_KEY | from step 3 (optional) |
| GMAIL_ADDRESS | your Gmail address |
| GMAIL_APP_PASSWORD | from step 4 |
| EMAIL_TO | where to receive the list (optional, defaults to GMAIL_ADDRESS) |
| SHEET_WEBHOOK_URL | Web app URL from step 5 |
| SHEET_TOKEN | the same string you put in `SECRET` |

7. **Test it.** Repo > Actions > "Daily job digest" > Run workflow. Open the run log to see what each source returned.

## Tuning

- `config.yaml`: number of jobs, search terms, how old a posting can be, experience limit, minimum match score.
- `companies.yaml`: add company career boards (Greenhouse, Lever, Ashby). Wrong slugs are skipped safely.
- Change the time in `.github/workflows/daily.yml` (cron is in UTC; IST = UTC + 5:30).

## Test on your laptop

```
pip install -r requirements.txt
python -m unittest discover -s tests
python -m jobradar --dry-run --sample tests/sample_jobs.json --no-verify
```

## What to expect

- It cannot promise exactly 50 fresh, relevant, live jobs every day. It sends the best it finds and states the real count.
- LinkedIn, Naukri and Indeed cannot be read legally by a program, so keep their saved-search alerts as well.
- "could not check" next to a link means that site blocks automated checks. The link is usually fine.
- Jobs already sent are remembered in `data/sent.json`, so you do not get repeats.

## Tailored resumes (new)

For every job in the daily list the program writes a one-page PDF resume tailored to that job description.
It uses only the facts in `master_resume.json` (edit that file to change what the resumes can say).

- The resumes are saved in a Google Drive folder called **Job Radar Resumes** and linked in the **Tailored resume**
  column of the Daily Jobs tab. They are not attached to the email.
- The sheet also shows an AI **Resume fit** score out of 100 and **Gaps to consider**: keywords the job wants that your
  facts do not support. Add a gap to your resume only if it is true.
- Safety checks in code: numbers must come from the bullet being rewritten, skills must come from your list, unlisted
  technologies, the company name, em dashes and en dashes are rejected. A bullet that fails a check falls back to your
  original master bullet.
- Needs a secret named `ANTHROPIC_API_KEY` (console.anthropic.com, add a small credit balance). Without it the resumes are
  generic (untailored). The model is set in `config.yaml` (`resumes.model`).
- After copying the new `apps_script/Code.gs` into your Sheet's Apps Script: Deploy > Manage deployments > pencil icon >
  Version: New version > Deploy, then approve the extra Google Drive permission when asked.
