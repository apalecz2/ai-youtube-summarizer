### Setup Instructions

1. Environment and Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Create .env
    - Fill in fields based on .env.example
    
3. To run locally:
```bash
uvicorn app.main:app --reload
```

4. Visit:
```bash
http://127.0.0.1:8000/health
```