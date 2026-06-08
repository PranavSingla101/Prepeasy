# Local Setup

## Prerequisites
- Python 3.10+
- pip

## Install dependencies
```bash
pip install -r requirements.txt
```

## Environment variables
Copy `.env.example` to `.env` and fill in the required values.

## Sample resume
The `data/resume_samples/` folder is git-ignored. Before running the app, add at least one resume file there:
```
data/
└── resume_samples/
    └── your_resume.pdf   # or .docx
```

## Run
```bash
cd backend
python parse_resume.py
```
