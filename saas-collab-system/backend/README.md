# Backend

Django REST Framework backend for the SaaS collaboration system.

## Development

```bash
python -m venv .venv
pip install -r requirements.txt
python manage.py check
```

Configuration is read from environment variables. Use the project-level `.env.example` as a reference and do not commit a real `.env` file.
