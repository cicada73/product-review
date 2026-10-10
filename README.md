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