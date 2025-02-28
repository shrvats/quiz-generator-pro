from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import camelot
import re
import tempfile
import os
from typing import List, Dict

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

def process_pdf(file_path: str) -> List[Dict]:
    doc = fitz.open(file_path)
    questions = []
    current_q = None
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        text = re.sub(r'Page \d+|©.*', '', text)
        
        for line in text.split('\n'):
            line = line.strip()
            
            if re.match(r'^Q\d*[.:]', line):
                if current_q: questions.append(current_q)
                current_q = {
                    'question': re.sub(r'^Q\d*[.:]\s*', '', line),
                    'options': {},
                    'correct': '',
                    'explanation': '',
                    'tables': [],
                    'math': []
                }
            elif match := re.match(r'^([A-D])[.)]\s*(.+)', line):
                current_q['options'][match.group(1)] = match.group(2)
            elif 'correct answer:' in line.lower():
                current_q['correct'] = line.split(':')[-1].strip()
            elif 'things to remember:' in line.lower():
                current_q['explanation'] = line.split(':')[-1].strip()
            
            math = re.findall(r'\$(.*?)\$', line)
            if math: current_q['math'].extend(math)
        
        tables = camelot.read_pdf(file_path, pages=str(page_num+1), flavor='stream')
        if tables: current_q['tables'] = [t.df.to_markdown() for t in tables]
    
    if current_q: questions.append(current_q)
    return questions

@app.post("/process")
async def handle_pdf(file: UploadFile):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
        
        result = process_pdf(tmp.name)
        os.unlink(tmp.name)
        return result
        
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/")
def read_root():
    return {"message": "PDF Quiz Generator API"}
