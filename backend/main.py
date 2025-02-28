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
    try:
        doc = fitz.open(file_path)
        questions = []
        current_q = None
        
        # Start from page 0 instead of 2 to handle all PDFs
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
                if math and current_q: current_q['math'].extend(math)
            
            # Only try to extract tables if we have a current question
            # This reduces unnecessary processing
            if current_q:
                try:
                    # Use lattice flavor first as it's faster for structured tables
                    tables = camelot.read_pdf(
                        file_path, 
                        pages=str(page_num+1), 
                        flavor='lattice',
                        suppress_stdout=True
                    )
                    
                    # If no tables found with lattice, try stream as fallback but with a timeout
                    if len(tables) == 0:
                        tables = camelot.read_pdf(
                            file_path, 
                            pages=str(page_num+1), 
                            flavor='stream',
                            suppress_stdout=True
                        )
                    
                    if tables and len(tables) > 0:
                        current_q['tables'] = [t.df.to_markdown() for t in tables]
                except Exception as e:
                    print(f"Table extraction error on page {page_num+1}: {str(e)}")
        
        if current_q: questions.append(current_q)
        return questions
    except Exception as e:
        print(f"PDF processing error: {str(e)}")
        raise Exception(f"Failed to process PDF: {str(e)}")

@app.post("/process")
async def handle_pdf(file: UploadFile):
    try:
        print(f"Received file: {file.filename}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        result = process_pdf(tmp_path)
        os.unlink(tmp_path)
        print(f"Processed {len(result)} questions")
        return result
        
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        raise HTTPException(500, f"Processing failed: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "API is running"}

@app.get("/")
def read_root():
    return {"message": "PDF Quiz Generator API"}

# Handle OPTIONS requests
@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}
