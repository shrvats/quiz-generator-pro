from fastapi import FastAPI, UploadFile, HTTPException, Request, File, Form
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
import asyncio
import traceback
import time
from typing import List, Dict, Optional, Tuple

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

def extract_questions_from_pdf(doc, page_range=None):
    """Extract questions and options from PDF"""
    if page_range:
        start_page, end_page = page_range
        start_page = max(0, start_page)
        end_page = min(len(doc) - 1, end_page)
        pages = range(start_page, end_page + 1)
    else:
        pages = range(len(doc))
    
    questions = []
    for page_num in pages:
        page = doc[page_num]
        text = page.get_text("text")
        
        # Extract question numbers and their start positions
        question_matches = list(re.finditer(r'(?:Question|Q\.?)\s*(\d+)(?:\(Q\.(\d+)\))?|\n\s*(\d+)[\.\)]', text))
        
        for i, match in enumerate(question_matches):
            # Get question ID from any matching group
            q_id = next((g for g in match.groups() if g), "")
            
            # Get question text boundaries
            start_pos = match.start()
            if i < len(question_matches) - 1:
                end_pos = question_matches[i+1].start()
            else:
                end_pos = len(text)
            
            # Extract full text for this question
            question_text_block = text[start_pos:end_pos].strip()
            
            # Process question components
            question_data = extract_question_components(question_text_block, q_id, page)
            if question_data:
                questions.append(question_data)
    
    # Sort questions by ID
    questions.sort(key=lambda q: q["id"])
    return questions

def extract_question_components(text, q_id, page):
    """Extract all components of a question"""
    try:
        # CRITICAL FIX: Remove any "correct answer is" statements from question text
        clean_question = re.sub(r'The correct answer is [A-F]\..*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        clean_question = re.sub(r'(?:Correct answer|Answer)[:\s]+[A-F]\.?.*?(?=\n|$)', '', clean_question, flags=re.IGNORECASE)
        
        # CRITICAL FIX: Remove explanations from question text
        for marker in ['explanation:', 'thus,', 'therefore,']:
            marker_pos = clean_question.lower().find(marker)
            if marker_pos > 0:
                clean_question = clean_question[:marker_pos]
        
        # Extract main question text (before options)
        main_question = extract_main_question_text(clean_question)
        
        # Extract options A, B, C, D
        options = extract_options(clean_question)
        
        # CRITICAL FIX: Separately extract answer information
        correct_answer = extract_correct_answer(text)
        explanation = extract_explanation(text)
        
        # CRITICAL FIX: Extract "Choice X is incorrect" type tables separately
        correct_option_data = extract_option_evaluation(text)
        
        return {
            "id": int(q_id) if q_id.isdigit() else 0,
            "question": main_question,
            "options": options,
            "correct": correct_answer,
            "explanation": explanation,
            "option_evaluations": correct_option_data,  # CRITICAL FIX: Store option evaluations separately
            "has_table": False  # We're not handling tables in this simplified version
        }
    except Exception as e:
        print(f"Error processing question {q_id}: {str(e)}")
        return None

def extract_main_question_text(text):
    """Extract only the question text, removing options and explanations"""
    # Find where options begin
    option_match = re.search(r'\n\s*[A-F][\.\)]', text)
    if option_match:
        # Cut off at first option
        return text[:option_match.start()].strip()
    return text.strip()

def extract_options(text):
    """Extract options A, B, C, D, etc. from text"""
    options = {}
    
    # Match each option with its text
    option_pattern = r'(?:^|\n)\s*([A-F])[\.\)]\s*(.*?)(?=\n\s*[A-F][\.\)]|\Z)'
    option_matches = re.finditer(option_pattern, text, re.DOTALL)
    
    for match in option_matches:
        letter = match.group(1)
        option_text = match.group(2).strip()
        
        # CRITICAL FIX: Remove any indication of correct/incorrect from options
        option_text = re.sub(r'(?:is correct|correct answer|is incorrect)', '', option_text, flags=re.IGNORECASE)
        
        options[letter] = option_text
    
    return options

def extract_correct_answer(text):
    """Extract the letter (A-F) of the correct answer"""
    patterns = [
        r'(?:The correct answer is|Correct answer[:\s]+)([A-F])\.?',
        r'The answer is ([A-F])\.?',
        r'Answer:\s*([A-F])\.?'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_explanation(text):
    """Extract explanation text that should be shown after user answers"""
    explanation = ""
    
    # Look for explanation after the correct answer statement
    exp_match = re.search(r'(?:The correct answer is|Correct answer[:\s]+)[A-F]\.?\s*(.*?)(?=\n\s*(?:Things to remember:|Note:)|\Z)', 
                         text, re.DOTALL | re.IGNORECASE)
    if exp_match:
        explanation = exp_match.group(1).strip()
    
    # If no explanation found after correct answer, look for explicit explanation section
    if not explanation:
        exp_match = re.search(r'Explanation:\s*(.*?)(?=\n\s*(?:Things to remember:|Note:)|\Z)',
                             text, re.DOTALL | re.IGNORECASE)
        if exp_match:
            explanation = exp_match.group(1).strip()
    
    return explanation

def extract_option_evaluation(text):
    """Extract 'Choice X is incorrect/correct' evaluations from text"""
    evaluations = {}
    
    # Find evaluation table rows
    eval_pattern = r'(?:Choice|Option)\s+([A-F])\s+is\s+(in)?correct\.\s*(.*?)(?=\n\s*(?:Choice|Option)|$)'
    eval_matches = re.finditer(eval_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for match in eval_matches:
        option = match.group(1)
        is_correct = match.group(2) is None  # If "in" is not present, it's correct
        explanation = match.group(3).strip()
        
        evaluations[option] = {
            "is_correct": is_correct,
            "explanation": explanation
        }
    
    return evaluations

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict:
    """Process PDF to extract quiz questions and answers"""
    start_time = time.time()
    
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        
        questions = extract_questions_from_pdf(doc, page_range)
        
        return {
            "questions": questions,
            "total_questions": len(questions),
            "total_pages": total_pages,
            "processing_time": time.time() - start_time
        }
    
    except Exception as e:
        print(f"Error in PDF processing: {str(e)}")
        traceback.print_exc()
        return {"error": f"Failed to process PDF: {str(e)}", "questions": [], "total_pages": 0}

@app.post("/process")
async def handle_pdf(
    file: UploadFile = File(...),
    start_page: Optional[int] = Form(None),
    end_page: Optional[int] = Form(None)
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        page_range = None
        if start_page is not None and end_page is not None:
            page_range = (int(start_page), int(end_page))
        
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(process_pdf, tmp_path, page_range),
                timeout=55.0
            )
        except asyncio.TimeoutError:
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=408, 
                detail="PDF processing timed out. Please try a smaller PDF file or fewer pages."
            )
        
        os.unlink(tmp_path)
        
        if "error" in result and not result.get("questions", []):
            raise HTTPException(status_code=500, detail=result["error"])
            
        return result
        
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.post("/pdf-info")
async def get_pdf_info(file: UploadFile = File(...)):
    """Get basic PDF information without processing content"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        doc = fitz.open(tmp_path)
        total_pages = len(doc)
        file_size = os.path.getsize(tmp_path) / (1024 * 1024)
        
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", "")
        }
        
        doc.close()
        os.unlink(tmp_path)
        
        return {
            "total_pages": total_pages,
            "file_size_mb": round(file_size, 2),
            "metadata": metadata
        }
    
    except Exception as e:
        print(f"Error getting PDF info: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get PDF info: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "API is running"}

@app.get("/")
def read_root():
    return {"message": "PDF Quiz Generator API"}

@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}
