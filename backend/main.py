from fastapi import FastAPI, UploadFile, HTTPException, Request, File
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import camelot
import re
import tempfile
import os
from typing import List, Dict
import asyncio
import traceback

app = FastAPI()

# Constants
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

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

def extract_tables_from_page(file_path, page_num):
    """Extract tables from a specific page"""
    try:
        tables = camelot.read_pdf(
            file_path, 
            pages=str(page_num+1), 
            flavor='lattice',
            suppress_stdout=True
        )
        
        if len(tables) == 0:
            # Try stream as fallback
            tables = camelot.read_pdf(
                file_path, 
                pages=str(page_num+1), 
                flavor='stream',
                suppress_stdout=True
            )
        
        return [t.df.to_html() for t in tables] if tables else []
    except Exception as e:
        print(f"Table extraction error on page {page_num+1}: {str(e)}")
        return []

def process_pdf(file_path: str) -> List[Dict]:
    try:
        doc = fitz.open(file_path)
        questions = []
        current_q = None
        
        # Process each page
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            
            # Clean up page text
            text = re.sub(r'Page \d+|©.*', '', text)
            
            # Extract questions
            # Look for patterns like Q1, Q2, Question 1, etc.
            question_matches = re.finditer(r'(?:^|\n)(?:Q|Question)\s*(\d+)[.:]?\s*([^\n]+)', text, re.IGNORECASE)
            
            for match in question_matches:
                q_num = match.group(1)
                q_text = match.group(2).strip()
                
                # If we have a current question, add it to our list
                if current_q:
                    questions.append(current_q)
                
                # Create new question dict
                current_q = {
                    'id': int(q_num),
                    'question': q_text,
                    'options': {},
                    'correct': '',
                    'explanation': '',
                    'tables': [],
                    'math': []
                }
                
                # Extract tables for this page
                if page_num < len(doc):
                    tables = extract_tables_from_page(file_path, page_num)
                    if tables and current_q:
                        current_q['tables'] = tables
            
            # Now process the text line by line for options, answers, etc.
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Only process if we have a current question
                if current_q:
                    # Check for options (A, B, C, D)
                    if match := re.match(r'^([A-D])[.)]\s*(.+)', line):
                        option_letter = match.group(1)
                        option_text = match.group(2).strip()
                        current_q['options'][option_letter] = option_text
                    
                    # Check for correct answer
                    elif 'correct answer:' in line.lower() or 'answer:' in line.lower():
                        answer_text = re.sub(r'^(?:correct\s+)?answer:\s*', '', line, flags=re.IGNORECASE)
                        current_q['correct'] = answer_text.strip()
                    
                    # Check for explanation/things to remember
                    elif 'things to remember:' in line.lower() or 'explanation:' in line.lower():
                        explanation_text = re.sub(r'^(?:things\s+to\s+remember|explanation):\s*', '', line, flags=re.IGNORECASE)
                        current_q['explanation'] = explanation_text.strip()
                    
                    # Extract math content
                    math_matches = re.findall(r'\$(.*?)\$', line)
                    if math_matches:
                        current_q['math'].extend(math_matches)
        
        # Add the last question if it exists
        if current_q:
            questions.append(current_q)
        
        # Sort questions by ID
        questions.sort(key=lambda q: q.get('id', 0))
        
        # For each question, check if we have any math formulas and mark them
        for q in questions:
            q['has_math'] = len(q.get('math', [])) > 0
            
            # Check options for math formulas
            for option_key, option_text in q.get('options', {}).items():
                math_in_option = re.findall(r'\$(.*?)\$', option_text)
                if math_in_option:
                    if 'math' not in q:
                        q['math'] = []
                    q['math'].extend(math_in_option)
                    q['has_math'] = True
        
        return questions
    except Exception as e:
        print(f"PDF processing error: {str(e)}")
        traceback.print_exc()
        raise Exception(f"Failed to process PDF: {str(e)}")

@app.post("/process")
async def handle_pdf(file: UploadFile = File(...)):
    try:
        print(f"Received file: {file.filename}")
        
        # Check file size first - read in chunks to avoid memory issues
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        
        # Reset file pointer to beginning
        await file.seek(0)
        
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File size exceeds the {MAX_FILE_SIZE/1024/1024}MB limit"
                )
        
        # Reset file pointer to beginning
        await file.seek(0)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        
        # Process the PDF
        result = await asyncio.to_thread(process_pdf, tmp_path)
        
        # Clean up
        os.unlink(tmp_path)
        
        # Output the number of questions found
        print(f"Returning {len(result)} questions to client")
        
        return result
        
    except HTTPException as e:
        # Pass through HTTP exceptions
        raise e
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

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
