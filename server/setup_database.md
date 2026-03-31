# Database Setup Guide

## Option 1: Use Docker (Recommended)

### Step 1: Start Docker Desktop
Make sure Docker Desktop is running on your Windows machine.

### Step 2: Start PostgreSQL
```bash
# From the project root directory
cd c:\Documents\GithubProjects\MedicalTranscriptionApp
docker-compose up -d db
```

### Step 3: Verify Database is Running
```bash
docker-compose ps
```

You should see the `db` service running on port 5432.

### Step 4: Create .env File
```bash
cd server
cp .env.example .env
```

The default DATABASE_URL in .env should be:
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/medscribe
```

### Step 5: Create Initial Migration
```bash
cd server
alembic revision --autogenerate -m "Initial schema"
```

### Step 6: Apply Migration
```bash
alembic upgrade head
```

---

## Option 2: Use Local PostgreSQL Installation

If you have PostgreSQL installed locally:

### Step 1: Start PostgreSQL Service
```bash
# On Windows (if PostgreSQL is installed as a service)
net start postgresql-x64-15  # Or your PostgreSQL service name
```

### Step 2: Create Database
```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE medscribe;

# Exit
\q
```

### Step 3: Update .env
```bash
cd server
cp .env.example .env
```

Edit `.env` and set:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/medscribe
```

### Step 4: Create and Apply Migration
```bash
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

---

## Option 3: Use SQLite (Quick Testing Only)

For quick testing without PostgreSQL:

### Step 1: Update DATABASE_URL in .env
```
DATABASE_URL=sqlite:///./medscribe.db
```

### Step 2: Create and Apply Migration
```bash
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

**Note:** SQLite is not recommended for production. Some features may not work correctly.

---

## Troubleshooting

### Docker Connection Refused
- Make sure Docker Desktop is running
- Check if port 5432 is already in use: `netstat -ano | findstr :5432`
- Restart Docker Desktop

### PostgreSQL Connection Refused
- Verify PostgreSQL is running: `pg_isready -h localhost -p 5432`
- Check PostgreSQL logs
- Ensure firewall isn't blocking port 5432

### Alembic Import Errors
- Make sure all dependencies are installed: `pip install -r requirements.txt`
- Verify Python path includes the server directory

---

## Verification

After setup, verify the database connection:

```python
# From server directory
python -c "from app.database.session import check_db_connection; print('✅ Connected!' if check_db_connection() else '❌ Failed')"
```

---

## Next Steps

Once the database is set up:

1. ✅ Database is running
2. ✅ Migration is created and applied
3. ✅ Tables are created

You're ready to proceed with **MVP Week 2** implementation:
- Complete LangGraph stub nodes
- Implement workflow engine
- Build patient service
- Create clinical suggestions engine
