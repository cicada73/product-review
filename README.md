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