from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
from typing import List, Dict
import asyncio
import concurrent.futures

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

def extract_text_from_page(doc, page_num):
    """Extract text from a specific page"""
    page = doc[page_num]
    text = page.get_text("text")
    return text

def process_pdf(file_path: str) -> List[Dict]:
    try:
        doc = fitz.open(file_path)
        questions = []
        current_q = None
        
        # Create an executor for parallel processing
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Extract text from all pages in parallel
            future_to_page = {
                executor.submit(extract_text_from_page, doc, i): i 
                for i in range(len(doc))
            }
            
            # Process each page as it completes
            for future in concurrent.futures.as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    text = future.result()
                    text = re.sub(r'Page \d+|©.*', '', text)
                    
                    for line in text.split('\n'):
                        line = line.strip()
                        
                        if re.match(r'^Q\d*[.:]', line):
                            if current_q: 
                                questions.append(current_q)
                            current_q = {
                                'question': re.sub(r'^Q\d*[.:]\s*', '', line),
                                'options': {},
                                'correct': '',
                                'explanation': '',
                                'math': []
                            }
                        elif match := re.match(r'^([A-D])[.)]\s*(.+)', line):
                            if current_q:  # Make sure we have a current question
                                current_q['options'][match.group(1)] = match.group(2)
                        elif 'correct answer:' in line.lower():
                            if current_q:
                                current_q['correct'] = line.split(':')[-1].strip()
                        elif 'things to remember:' in line.lower():
                            if current_q:
                                current_q['explanation'] = line.split(':')[-1].strip()
                        
                        math = re.findall(r'\$(.*?)\$', line)
                        if math and current_q: 
                            current_q['math'].extend(math)
                
                except Exception as e:
                    print(f"Error processing page {page_num}: {str(e)}")
        
        if current_q: 
            questions.append(current_q)
        
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
        # Handle PDF processing in a way that doesn't block
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, process_pdf, tmp_path)
        
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
