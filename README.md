# Product Review Application

A product review application built incrementally with Django, HTML,
CSS, and MySQL.

## Part 1: Project Foundation

Implemented:

- Django project configuration.
- Environment-based secret and database settings.
- MySQL development service through Docker Compose.
- Custom user model and Django admin registration.
- Responsive landing page.
- Database health endpoint.
- Four automated foundation tests.
- GitHub Actions workflow.

Product listings, public registration, reviews, and moderation workflows
will be added in later milestones.

## Requirements

- Python 3.12
- Docker Desktop with Docker Compose
- Git

## Local Setup

Create a virtual environment and install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy the configuration template:

```powershell
Copy-Item .env.example .env
```

Replace every placeholder in `.env` with your own generated values.

Start MySQL and apply migrations:

```powershell
docker compose up -d db
.\.venv\Scripts\python.exe manage.py migrate
```

Create an administrator and start Django:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

## Local URLs

- Homepage: http://127.0.0.1:8000/
- Database health: http://127.0.0.1:8000/health/
- Admin: http://127.0.0.1:8000/admin/

## Tests

For local testing, grant access to the separate test database.

Open MySQL:

```powershell
docker compose exec db mysql -u root -p
```

Run this SQL, then exit:

```sql
GRANT ALL PRIVILEGES ON `test_product_reviews`.*
TO 'review_app'@'%';
exit;
```

Run the checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test core --keepdb
```

Tests use a separate database named `test_product_reviews`.

## Stopping MySQL

```powershell
docker compose down
```

Database data remains in the Docker volume.

## Configuration Notes

Keep `.env` out of Git. Commit only `.env.example`.

MySQL initialization settings apply when its data volume is first created.
Changing a password in `.env` does not update an existing MySQL account.

This setup is for local development. Production deployment comes later.



## Part 2: Database Foundation

Implemented:

- Category and Product models with unique slugs.
- Optional product image uploads.
- Product archival through the active flag.
- Review model with pending, approved, and rejected statuses.
- One review per author per product.
- Database constraints for ratings and review statuses.
- Protected deletion of referenced categories, products, and authors.
- Catalog and review administration.
- Model constraint tests and demo-data command tests.

Create sample categories and products:

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
```

The command preserves existing records and can be run repeatedly.

The complete test suite currently contains 18 tests.

## Part 3 — User accounts and authentication

Implemented:

- Signup with unique email addresses and password validation.
- Username/password login and POST-only logout.
- Profile editing for first and last names.
- Password changes that preserve the current session and invalidate
  other sessions.
- Password reset links with a one-hour expiry.
- Database-backed sessions with a one-hour lifetime.
- HttpOnly session cookies and SameSite=Lax cookies.
- HTTPS-only session and CSRF cookies when DEBUG is disabled.
- Login protection using Django Axes.

### Login protection

Five failed attempts for the same username and IP address trigger a
15-minute lockout. Successful login before lockout resets the failure
counter. Further failed attempts may extend the waiting period.

During local development, client IP detection uses REMOTE_ADDR.
Proxy settings must be reviewed before production deployment.

To clear a development lockout, replace YOUR_USERNAME below:

```bat
.\.venv\Scripts\python.exe manage.py axes_reset_username YOUR_USERNAME
```

### Local password reset emails

Development uses Django's console email backend. Password reset emails
appear in the runserver terminal; they are not delivered to an inbox.

Production email delivery will be configured during deployment.

### Local database

MySQL is available on localhost port 3307.
The database container uses port 3306 internally.

### Verification

The full suite currently contains 61 tests covering the foundation,
catalog, reviews, account flows, CSRF protection, password reset,
session invalidation, and login lockouts.

```bat
.\.venv\Scripts\python.exe manage.py test --keepdb --verbosity 2
```

## Part 4 — Public product catalog

Implemented:

- Public listing of active products, with 12 products per page.
- Search by product name, brand, or description.
- Category filtering that works alongside search.
- Pagination links that preserve search and category selections.
- Product detail pages with full descriptions and optional images.
- Approved review counts and average ratings on listings and details.
- Approved reviews displayed newest first, with 10 reviews per page.
- Rating summaries calculated across all approved reviews.
- Inactive products and unknown product/category URLs return 404.
- Product and review text is HTML-escaped.
- Homepage link to the catalog.

Pending and rejected reviews are excluded from public review lists,
counts, and average ratings.

### Routes

- `/products/` — product listing
- `/products/?q=SEARCH&category=CATEGORY_SLUG` — filtered listing
- `/products/PRODUCT_SLUG/` — product details and approved reviews

### Verification

The full test suite currently contains 82 tests.

Run against a fresh test database:

```bat
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 2
```

## Part 5 — Review submission and management

Implemented:

- Authenticated review submission for active products.
- Ratings from 1 to 5.
- Review titles between 5 and 200 characters.
- Review bodies between 20 and 5,000 characters.
- One review per user per product, enforced by the database.
- New reviews saved as Pending.
- Authors can edit their own reviews.
- Valid edits return reviews to Pending for approval again.
- Invalid edits leave existing content and approval status unchanged.
- Author, product, and approval status cannot be chosen through form data.
- CSRF protection for submission and editing.
- Private My reviews dashboard with all approval statuses.
- Dashboard pagination with 10 reviews per page.
- Reviews of inactive products remain visible to their author,
  but editing is disabled.

Pending and rejected reviews are excluded from public reviews and
rating calculations.

### Routes

- `/reviews/` — My reviews dashboard
- `/reviews/products/PRODUCT_SLUG/new/` — submit a review
- `/reviews/REVIEW_ID/edit/` — edit your own review

### Verification

The full suite currently contains 119 tests, including form validation,
submission, ownership checks, reapproval, CSRF protection, dashboard
privacy, and pagination.

```bat
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 2
```

## Part 6 — Moderation, reporting, and account management

Implemented:

- Review Moderators role for review decisions and report handling.
- Account Managers role for suspension and restoration.
- Permission checks in both views and service functions.
- Review approval/rejection with mandatory reasons.
- Moderators cannot decide their own reviews.
- Reporting of other users' approved reviews on active products.
- One report per user per review, including after closure.
- Report resolution/dismissal with moderator, timestamp, and note.
- Moderators cannot decide their own reports or reports about their reviews.
- Stale review, report, and account decisions are rejected.
- State changes and audit entries share atomic transactions.
- Account suspension/restoration with mandatory reasons.
- Session versioning prevents restoration from reviving old sessions.
- Staff, superusers, and the acting manager's own account are protected.
- Review, report, and audit records are read-only in Django admin.
- Account activation and session version are read-only in user admin.
- CSRF protection on action forms.

Reporting and closing reports do not change review approval status.
Existing approved reviews remain public when an account is suspended
unless separately rejected.

### Role setup

After applying migrations, run:

```bat
.\.venv\Scripts\python.exe manage.py setup_roles
```

This repeatable command sets each role's permissions to its configured
list. Assign users to groups through Django admin.

Role membership does not automatically grant staff or superuser status.

### Routes

- `/moderation/` — review moderation queue
- `/moderation/reviews/REVIEW_ID/` — approve/reject a review
- `/moderation/reviews/REVIEW_ID/report/` — report a public review
- `/moderation/reports/` — report queue
- `/moderation/reports/REPORT_ID/` — resolve/dismiss a report
- `/moderation/accounts/` — account management
- `/moderation/accounts/USER_ID/` — suspend/restore an account

### Verification

The full suite currently contains 218 tests. Moderation coverage includes
permissions, database constraints, conflict checks, stale decisions,
audit rollback, CSRF protection, session invalidation, and admin controls.

```bat
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 2
```

# Part 7 — Manual usability checks

Mark each item complete only after checking it.

- [ ] Main user flows work using only the keyboard.
- [ ] Focus is visible on links, buttons, inputs, and selects.
- [ ] No keyboard traps were found.
- [ ] Pages remain usable at 320px and 390px widths.
- [ ] Moderation pages remain usable on narrow screens.
- [ ] Pages remain usable at 200% browser zoom.
- [ ] Form fields have understandable visible labels.
- [ ] Validation errors are clear and preserve entered values.
- [ ] Review and report statuses are communicated using text.

Issues found and fixes:
- no issues
These checks are a basic usability review, not a full accessibility audit.

## Part 7 — Browser testing and quality assurance

Implemented Chromium browser tests covering:

- Homepage-to-product navigation.
- Search, category filters, and pagination.
- Signup, profile editing, login, and logout.
- Review submission, moderator approval, and editing back to Pending.
- Reporting and report resolution through separate browser sessions.
- Account suspension/restoration and old-session invalidation.
- Keyboard operation of the search form.
- Public-page overflow checks at 320px and 390px widths.

Browser tests use Django's temporary live server and test database.
GitHub Actions installs Chromium and its Linux dependencies.

Manual keyboard, mobile, zoom, and form checks are recorded in
`docs/part-7-manual-checks.md`. These are basic usability checks,
not a full accessibility audit.

### Development setup

```bat
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

### Run tests

All 228 tests:

```bat
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 2
```

Only the 10 browser tests:

```bat
.\.venv\Scripts\python.exe manage.py test --tag=browser --keepdb --verbosity 2
```

Application tests without browser execution:

```bat
.\.venv\Scripts\python.exe manage.py test --exclude-tag=browser --keepdb --verbosity 2
```