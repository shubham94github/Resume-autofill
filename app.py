# Project: resume-autofill (Phase 1 + HTML templates)
# File: app.py

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import sqlite3
import re
from werkzeug.utils import secure_filename

# --------- Configuration ---------
# Use the current working directory instead of __file__ to support environments
# where __file__ may not be defined (interactive shells / some sandboxes).
BASE_DIR = os.getcwd()
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_PATH = os.path.join(BASE_DIR, 'extracted_data.db')
ALLOWED_EXTENSIONS = {'pdf'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'dev-secret-change-this'

# --------- Database helpers (SQLite) ---------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS resume (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            linkedin TEXT,
            address TEXT,
            summary TEXT,
            skills TEXT,
            experience TEXT,
            education TEXT,
            raw_text TEXT,
            pdf_path TEXT
        )
    ''')
    conn.commit()
    conn.close()


def save_resume_to_db(parsed):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id FROM resume LIMIT 1')
    row = c.fetchone()
    if row:
        c.execute('''UPDATE resume SET
            name=?, email=?, phone=?, linkedin=?, address=?, summary=?, skills=?, experience=?, education=?, raw_text=?, pdf_path=? WHERE id=?''',
            (parsed.get('name'), parsed.get('email'), parsed.get('phone'), parsed.get('linkedin'), parsed.get('address'), parsed.get('summary'), parsed.get('skills'), parsed.get('experience'), parsed.get('education'), parsed.get('raw_text'), parsed.get('pdf_path'), row[0]))
    else:
        c.execute('''INSERT INTO resume (name,email,phone,linkedin,address,summary,skills,experience,education,raw_text,pdf_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (parsed.get('name'), parsed.get('email'), parsed.get('phone'), parsed.get('linkedin'), parsed.get('address'), parsed.get('summary'), parsed.get('skills'), parsed.get('experience'), parsed.get('education'), parsed.get('raw_text'), parsed.get('pdf_path')))
    conn.commit()
    conn.close()


def get_saved_resume():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM resume LIMIT 1')
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    keys = ['id','name','email','phone','linkedin','address','summary','skills','experience','education','raw_text','pdf_path']
    return dict(zip(keys,row))

# --------- PDF text extraction helpers (robust, avoids failing import)
# The sandbox may not have "pdfplumber" installed. We'll attempt multiple libraries
# in order: pdfplumber, PyPDF2, fitz (PyMuPDF). If none available, we return an
# empty string and a helpful message so the app still runs without crashing.

def extract_text_from_pdf(path):
    """Try several methods to extract text from PDF. Return the concatenated text.
    If none of the PDF libraries are available, return an empty string and
    print a helpful message to the console.
    """
    text = ''

    # Attempt 1: pdfplumber (preferred for accuracy)
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
        if text.strip():
            return text
    except Exception:
        # Ignore and try next method
        pass

    # Attempt 2: PyPDF2 (commonly available)
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        for page in reader.pages:
            try:
                page_text = page.extract_text()
            except Exception:
                page_text = ''
            if page_text:
                text += page_text + '\n'
        if text.strip():
            return text
    except Exception:
        pass

    # Attempt 3: fitz (PyMuPDF)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text += page_text + '\n'
        if text.strip():
            return text
    except Exception:
        pass

    # Fallback: no PDF extractor available in environment
    print('\n[WARNING] No PDF text extraction libraries available (pdfplumber, PyPDF2, or PyMuPDF).')
    print('Please install one of them (e.g., pip install pdfplumber or pip install PyPDF2) to enable full PDF parsing.')
    print('The application will continue to run, but resume extraction will be empty.')
    return ''

# --------- Simple heuristics for parsing text ---------

def find_email(text):
    m = re.search(r'[\w\.-]+@[\w\.-]+', text)
    return m.group(0).strip() if m else ''


def find_phone(text):
    m = re.search(r'(\+?\d[\d\s\-\(\)]{7,}\d)', text)
    return m.group(0).strip() if m else ''


def find_linkedin(text):
    m = re.search(r'(https?://)?(www\.)?linkedin\.com/[\w\-\./]+', text)
    return m.group(0).strip() if m else ''


def guess_name(text):
    for line in text.splitlines():
        line = line.strip()
        if line and len(line.split()) <= 4 and not re.search(r'@|phone|email|www|linkedin|skill|experience|education', line, re.I):
            return line
    return ''


def parse_resume(path):
    raw = extract_text_from_pdf(path)
    parsed = {
        'name': guess_name(raw),
        'email': find_email(raw),
        'phone': find_phone(raw),
        'linkedin': find_linkedin(raw),
        'address': '',
        'summary': '',
        'skills': '',
        'experience': '',
        'education': '',
        'raw_text': raw,
        'pdf_path': path
    }

    # Heuristic section extraction (best-effort)
    if raw:
        skills_match = re.search(r'(skills|technical skills)[\s:\n]*(.*?)(\n\n|\n[A-Z]|$)', raw, re.I | re.S)
        if skills_match:
            parsed['skills'] = skills_match.group(2).strip().replace('\n', ', ')

        summary_match = re.search(r'(summary|professional summary)[\s:\n]*(.*?)(\n\n|\n[A-Z]|$)', raw, re.I | re.S)
        if summary_match:
            parsed['summary'] = summary_match.group(2).strip()

        exp_match = re.search(r'(experience)(.*?)(education|certifications|$)', raw, re.I | re.S)
        if exp_match:
            parsed['experience'] = exp_match.group(2).strip()

        edu_match = re.search(r'(education)(.*?)(certifications|languages|$)', raw, re.I | re.S)
        if edu_match:
            parsed['education'] = edu_match.group(2).strip()

    return parsed

# --------- Routes ---------

@app.route('/')
def index():
    resume = get_saved_resume()
    return render_template('index.html', resume=resume)


@app.route('/upload', methods=['POST'])
def upload():
    if 'resume' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))
    file = request.files['resume']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        parsed = parse_resume(save_path)
        save_resume_to_db(parsed)
        flash('Resume uploaded and parsed successfully')
        return redirect(url_for('index'))
    else:
        flash('Invalid file type. Please upload a PDF.')
        return redirect(url_for('index'))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/edit', methods=['GET', 'POST'])
def edit():
    if request.method == 'POST':
        data = request.form.to_dict()
        parsed = get_saved_resume() or {}
        parsed.update(data)
        save_resume_to_db(parsed)
        flash('Saved changes successfully')
        return redirect(url_for('index'))
    resume = get_saved_resume()
    return render_template('edit.html', resume=resume)


@app.route('/api/resume')
def api_resume():
    resume = get_saved_resume()
    if not resume:
        return jsonify({'error': 'No resume found'}), 404
    return jsonify({k: v for k, v in resume.items() if k not in ['raw_text', 'id']})


if __name__ == '__main__':
    init_db()
    app.run(debug=True)


# ---------- Templates (unchanged) ----------

# templates/index.html
'''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Resume Autofill Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f8f9fa; }
    .container { max-width: 800px; margin-top: 40px; }
    .card { box-shadow:0 2px 8px rgba(0,0,0,0.1); border-radius:10px; }
  </style>
</head>
<body>
<div class="container">
  <div class="card p-4">
    <h2 class="mb-3 text-center">Resume Autofill Assistant</h2>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-info">{{ messages[0] }}</div>
      {% endif %}
    {% endwith %}

    <form method="POST" action="/upload" enctype="multipart/form-data" class="mb-4">
      <label class="form-label">Upload your Resume (PDF):</label>
      <div class="input-group">
        <input class="form-control" type="file" name="resume" required>
        <button class="btn btn-primary">Upload</button>
      </div>
    </form>

    {% if resume %}
    <h5>Extracted Information</h5>
    <ul class="list-group mb-3">
      <li class="list-group-item"><strong>Name:</strong> {{ resume.name }}</li>
      <li class="list-group-item"><strong>Email:</strong> {{ resume.email }}</li>
      <li class="list-group-item"><strong>Phone:</strong> {{ resume.phone }}</li>
      <li class="list-group-item"><strong>LinkedIn:</strong> {{ resume.linkedin }}</li>
      <li class="list-group-item"><strong>Skills:</strong> {{ resume.skills[:200] }}...</li>
    </ul>
    <a href="/edit" class="btn btn-outline-secondary">Edit Details</a>
    {% else %}
    <p>No resume uploaded yet.</p>
    {% endif %}
  </div>
</div>
</body>
</html>
'''

# templates/edit.html
'''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Edit Resume Data</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f8f9fa; }
    .container { max-width:800px; margin-top:40px; }
    textarea { min-height: 100px; }
  </style>
</head>
<body>
<div class="container">
  <div class="card p-4">
    <h3 class="mb-3">Edit Extracted Resume Data</h3>
    <form method="POST" action="/edit">
      {% for field,label in [('name','Name'),('email','Email'),('phone','Phone'),('linkedin','LinkedIn'),('address','Address'),('summary','Summary'),('skills','Skills'),('experience','Experience'),('education','Education')] %}
      <div class="mb-3">
        <label class="form-label">{{ label }}</label>
        {% if field in ['summary','skills','experience','education'] %}
        <textarea name="{{field}}" class="form-control">{{ resume[field] if resume else '' }}</textarea>
        {% else %}
        <input name="{{field}}" class="form-control" value="{{ resume[field] if resume else '' }}">
        {% endif %}
      </div>
      {% endfor %}
      <button class="btn btn-success">Save Changes</button>
      <a href="/" class="btn btn-outline-secondary">Back</a>
    </form>
  </div>
</div>
</body>
</html>
'''
