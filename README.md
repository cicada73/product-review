# Product Review Application

A Django and MySQL application for discovering products, sharing reviews,
and managing community moderation.

The application includes account security, review approval workflows,
report handling, and account suspension with audit history. It is built
as a portfolio project and runs locally.

## Features

### Product discovery

- Search active products by name, brand, or description.
- Filter by category and paginate results without losing filters.
- View product descriptions, images, and approved customer reviews.
- Display average ratings calculated from approved reviews only.

### Accounts and reviews

- Register with a unique email address and validated password.
- Log in, log out, edit profile details, and change or reset passwords.
- Submit one review per user per product.
- Edit owned reviews and track their status through My reviews.
- Return edited reviews to pending approval before public display.

### Moderation

- Approve or reject reviews with a mandatory reason.
- Report other users’ approved reviews.
- Resolve or dismiss reports with a recorded outcome.
- Suspend and restore eligible accounts.
- Record moderation state changes and audit entries atomically.
- Reject stale decisions when the underlying record has changed.
- Prevent moderators from deciding their own reviews or reports.

### Interface

- Shared navigation and responsive page layouts.
- Text-based status badges and visible keyboard focus.
- Consistent forms, validation messages, and empty states.
- Product image placeholders for items without uploaded images.

## Technology

| Area | Technology |
| --- | --- |
| Backend | Python, Django 5.2 |
| Database | MySQL 8.4 |
| Frontend | Django templates, HTML, CSS |
| Authentication | Django authentication and database-backed sessions |
| Login protection | Django Axes |
| Image processing | Pillow |
| Static assets | WhiteNoise |
| Browser testing | Playwright with Chromium |
| Automated checks | Django test framework, GitHub Actions |
| Local database | Docker Compose |

Dependency versions are pinned in `requirements.txt` and
`requirements-dev.txt`.

## Architecture

The application renders HTML on the server using Django templates.
Views handle requests and forms validate input. Moderation service
functions enforce action permissions and coordinate database updates
with audit records.

| Django app | Responsibility |
| --- | --- |
| `core` | Homepage and database health endpoint |
| `accounts` | Custom user model, authentication, profiles, session security |
| `catalog` | Categories, products, search, filtering, public ratings |
| `reviews` | Review submission, editing, ownership, private dashboard |
| `moderation` | Review decisions, reports, account actions, audit history |

Database constraints enforce rules such as one review per author and
product, valid ratings, and valid moderation-record states.

Moderation services use transactions and row locking. State changes
and their audit records succeed or roll back together.

## Important workflow rules

- New reviews start as Pending.
- Only Approved reviews appear publicly or contribute to ratings.
- Editing a review returns it to Pending.
- Reporting a review does not automatically hide it.
- Closing a report does not change the review’s approval status.
- Suspending an account blocks login and invalidates existing sessions.
- Restoring an account requires a fresh login; old sessions stay invalid.
- Approved reviews remain public after account suspension unless
  separately rejected.
- Staff, superusers, and the acting account manager’s own account are
  excluded from account suspension actions.

## Local setup — Windows

### Prerequisites

- Python 3.12, matching the GitHub Actions environment.
- Docker Desktop with Docker Compose.
- Git.

The commands below use Windows Command Prompt from the project folder.
Virtual-environment activation is optional because commands explicitly
use its Python executable.

### 1. Get the source

Clone this repository using its GitHub clone URL, then enter the
`product-review` directory.

### 2. Install dependencies

```bat
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 3. Configure the environment

For a new checkout, copy the example configuration:

```bat
copy .env.example .env
```

Generate a secret key:

```bat
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set `DJANGO_SECRET_KEY` in `.env` to the generated value. Replace the
application and root database password placeholders with your own values.

Use these local connection settings:

```dotenv
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

MYSQL_DATABASE=product_reviews
MYSQL_USER=review_app
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
```

Keep `.env` private. Commit only `.env.example` with placeholder secrets.

### 4. Start MySQL

Start Docker Desktop, then run:

```bat
docker compose up -d db
docker compose ps
```

Wait until the database service is healthy.

MySQL is exposed on `127.0.0.1:3307`. Inside the container it listens
on port `3306`.

### 5. Initialize the application

```bat
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py setup_roles
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

`seed_demo` creates sample categories and products and can be run
repeatedly without replacing existing records.

`setup_roles` creates or updates the configured moderation groups.

### 6. Run Django

```bat
.\.venv\Scripts\python.exe manage.py runserver
```

| Page | Local URL |
| --- | --- |
| Homepage | http://127.0.0.1:8000/ |
| Product catalog | http://127.0.0.1:8000/products/ |
| My reviews | http://127.0.0.1:8000/reviews/ |
| Review moderation | http://127.0.0.1:8000/moderation/ |
| Report queue | http://127.0.0.1:8000/moderation/reports/ |
| Account management | http://127.0.0.1:8000/moderation/accounts/ |
| Django admin | http://127.0.0.1:8000/admin/ |
| Database health | http://127.0.0.1:8000/health/ |

Authenticated and moderation pages require the appropriate access.

## Demonstrating roles

Create separate regular accounts through signup. Sign in to Django admin
with the superuser and assign the relevant groups:

| Group | Access |
| --- | --- |
| Review Moderators | Review approval/rejection and report handling |
| Account Managers | Account suspension and restoration |

Group membership does not automatically grant staff or superuser status.
These roles use the application’s moderation pages.

Use separate browser profiles or private windows to demonstrate an
author, moderator, and account manager independently.

## Tests

The latest verified suite contains **228 tests**, including **10 Chromium
browser tests**.

Coverage includes database constraints, authentication, permissions,
CSRF protection, review visibility, stale moderation decisions, audit
rollback, and session invalidation.

Browser tests exercise complete workflows, keyboard search, and public
page layouts at 320px and 390px widths.

### Test database access

The local application database user needs permission to create and use
Django’s separate test database.

Open MySQL:

```bat
docker compose exec db mysql -u root -p
```

Enter the root password from `.env`, then run:

```sql
GRANT ALL PRIVILEGES ON `test_product_reviews`.*
TO 'review_app'@'%';

exit;
```

These names assume the example database and username above.

### Run checks and the complete suite

```bat
.\.venv\Scripts\python.exe manage.py check --database default
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py test --keepdb --verbosity 2
```

Collect static files before testing so the static-file manifest is
available when pages render with debug disabled.

Run only browser tests:

```bat
.\.venv\Scripts\python.exe manage.py test --tag=browser --keepdb --verbosity 2
```

Run application tests without browser execution:

```bat
.\.venv\Scripts\python.exe manage.py test --exclude-tag=browser --keepdb --verbosity 2
```

For a fresh test-database run, replace `--keepdb` with `--noinput`.
The test database is separate from the development database.

Manual usability checks are recorded in
[the usability checklist](docs/part-7-manual-checks.md).
These checks are not a full accessibility audit.

## Continuous integration

GitHub Actions runs on pushes and pull requests. It uses Python 3.12
and a MySQL 8.4 service to:

- Check Django configuration and migration consistency.
- Apply migrations and collect static files.
- Install Chromium and its browser dependencies.
- Run application and browser tests.

CI uses MySQL port `3306`; local development uses `3307`.

## Local authentication notes

Five failed login attempts for the same username and IP address trigger
a 15-minute lockout. Additional failed attempts may extend the waiting
period.

To clear a development lockout:

```bat
.\.venv\Scripts\python.exe manage.py axes_reset_username YOUR_USERNAME
```

Password-reset emails use Django’s console email backend and appear in
the server terminal. They are not delivered to an inbox.

Sessions have a one-hour lifetime. Password-reset links expire after
one hour.

## Deployment status

This project is intended for local demonstration and is not currently
deployed.

Deployment preparation includes WhiteNoise, collected static assets,
and a separate `config.settings_production` module with HTTPS enforcement
and debug disabled.

Hosting, trusted proxy configuration, production email delivery,
persistent uploaded-image storage, backups, and live HTTPS verification
remain future work. HSTS is intentionally disabled until HTTPS is verified.

## Stopping the application

Stop Django with `Ctrl + C`, then stop MySQL:

```bat
docker compose down
```

Database records remain in the Docker volume. Avoid `docker compose down -v`
unless you intend to delete that database volume.

MySQL initialization variables apply when the volume is first created.
Changing a password in `.env` does not change an existing MySQL account’s
password.