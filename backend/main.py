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

def clean_text(text):
    """Clean text by removing copyright notices, page numbers, etc."""
    # Remove copyright statements and year ranges (© 2014-2025 AnalystPrep)
    text = re.sub(r'(?:©|Copyright\s*©?)\s*\d+(?:-\d+)?\s*[A-Za-z]+(?:Prep)?\.?', '', text, flags=re.IGNORECASE)
    
    # Remove page numbers
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    
    # Remove standalone numbers that might be page numbers
    text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
    
    return text

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict:
    """Process PDF to extract quiz questions and answers"""
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        
        # Adjust page range if provided
        if page_range:
            start_page, end_page = page_range
            start_page = max(0, start_page)
            end_page = min(len(doc) - 1, end_page)
            page_iterator = range(start_page, end_page + 1)
        else:
            page_iterator = range(len(doc))
        
        # Extract all text from PDF first
        all_text = ""
        for page_num in page_iterator:
            page = doc[page_num]
            all_text += page.get_text("text") + "\n"
        
        # Clean all copyright notices and page numbers
        all_text = clean_text(all_text)
        
        # Find all questions in the text
        questions = []
        
        # Match Q.XXXX or Question X patterns
        question_pattern = r'(?:Question\s+(\d+)(?:\(Q\.(\d+)\))?|Q\.?\s*(\d+)(?:\(Q\.(\d+)\))?)'
        
        # Find all question matches
        question_matches = list(re.finditer(question_pattern, all_text))
        
        for i, match in enumerate(question_matches):
            # Get question ID
            q_num = None
            for group in match.groups():
                if group:
                    q_num = group
                    break
            
            if not q_num:
                continue
                
            # Calculate text boundaries for this question
            start_pos = match.start()
            if i < len(question_matches) - 1:
                end_pos = question_matches[i+1].start()
            else:
                end_pos = len(all_text)
            
            question_text_block = all_text[start_pos:end_pos].strip()
            
            # Process this question
            question_data = extract_question_data(question_text_block, q_num)
            if question_data:
                questions.append(question_data)
        
        # Sort questions by ID
        questions.sort(key=lambda q: q["id"])
        
        return {
            "questions": questions,
            "total_questions": len(questions),
            "total_pages": total_pages
        }
    
    except Exception as e:
        print(f"Error in PDF processing: {str(e)}")
        traceback.print_exc()
        return {"error": f"Failed to process PDF: {str(e)}", "questions": [], "total_pages": 0}

def extract_question_data(text, q_id):
    """Extract all components of a question"""
    try:
        # Get the main question text
        main_question = extract_question_text(text)
        
        # Get the options
        options = extract_clean_options(text)
        
        # Get the correct answer
        correct_answer = extract_correct_answer(text)
        
        # Get any numeric values in the question (for financial calculations)
        numeric_value = extract_numeric_value(text)
        
        # Get explanation (to be shown after answering)
        explanation = extract_explanation(text)
        
        # Get "Things to Remember" section
        things_to_remember = extract_things_to_remember(text)
        
        # Create question object
        question = {
            "id": int(q_id) if q_id.isdigit() else 0,
            "question": main_question,
            "options": options,
            "correct": correct_answer,
            "explanation": explanation,
            "things_to_remember": things_to_remember,
            "numeric_value": numeric_value,
            "has_options": len(options) > 0
        }
        
        return question
    except Exception as e:
        print(f"Error extracting question data: {str(e)}")
        return None

def extract_question_text(text):
    """Extract only the main question text"""
    # Remove the question ID/number
    text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.?\s*\d+(?:\(Q\.\d+\))?)\s*', '', text)
    
    # Find where the options start
    option_match = re.search(r'\n\s*[A-F][\.\)]\s+', text)
    if option_match:
        # Cut off at first option
        text = text[:option_match.start()]
    
    # Also cut off at any "Choice X is..." text which might be in tables
    choice_match = re.search(r'\n\s*Choice\s+[A-F]\s+is\s+', text, re.IGNORECASE)
    if choice_match:
        text = text[:choice_match.start()]
    
    # Remove any "The correct answer is..." text
    text = re.sub(r'The correct answer is [A-F]\..*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:Correct answer|Answer)[:\s]+[A-F]\.?.*', '', text, flags=re.IGNORECASE)
    
    return text.strip()

def extract_clean_options(text):
    """Extract options (A, B, C, D) without any explanations or copyright notices"""
    options = {}
    
    # Find all option blocks
    option_pattern = r'(?:^|\n)\s*([A-F])[\.\)]\s*(.*?)(?=\n\s*[A-F][\.\)]|\n\s*(?:Things to Remember|Choice [A-F] is)|\Z)'
    option_matches = re.finditer(option_pattern, text, re.DOTALL)
    
    for match in option_matches:
        letter = match.group(1)
        option_text = match.group(2).strip()
        
        # Clean the option text
        # Remove any copyright notices
        option_text = re.sub(r'(?:©|Copyright\s*©?)\s*\d+(?:-\d+)?\s*[A-Za-z]+(?:Prep)?\.?.*?(?=\n|$)', '', option_text, flags=re.IGNORECASE)
        
        # Remove "Things to Remember" and anything after it
        option_text = re.sub(r'Things to Remember.*', '', option_text, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove any "Choice X is..." text 
        option_text = re.sub(r'Choice\s+[A-F]\s+is\s+(?:in)?correct\..*', '', option_text, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove any "The correct answer is..." text
        option_text = re.sub(r'The correct answer is [A-F]\..*', '', option_text, flags=re.DOTALL | re.IGNORECASE)
        option_text = re.sub(r'(?:Correct answer|Answer)[:\s]+[A-F]\.?.*', '', option_text, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove page numbers
        option_text = re.sub(r'\n\s*\d+\s*\n', '\n', option_text)
        
        # Clean up and store
        options[letter] = option_text.strip()
    
    return options

def extract_correct_answer(text):
    """Extract the correct answer letter"""
    patterns = [
        r'(?:The correct answer is|Correct answer[:\s]+)([A-F])\.?',
        r'The answer is ([A-F])\.?',
        r'Answer:\s*([A-F])\.?',
        r'Choice\s+([A-F])\s+is\s+correct\.'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_numeric_value(text):
    """Extract numeric values for financial questions"""
    patterns = [
        r'(\d+\.\d+)\s+([A-Z])\s+([\d,]+)',  # For patterns like "39.00 F 50,000"
        r'(\d+\.\d+)\s*([A-Z])?\s*([\d,]*)',  # More general pattern
        r'(\d+\.\d+)'  # Just a number
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    
    return None

def extract_explanation(text):
    """Extract explanation text to be shown after answering"""
    explanation = ""
    
    # Look for explanation after correct answer
    exp_match = re.search(r'(?:The correct answer is|Correct answer[:\s]+)[A-F]\.?\s*(.*?)(?=\n\s*(?:Things to Remember:|Choice [A-F] is)|\Z)', 
                         text, re.DOTALL | re.IGNORECASE)
    if exp_match:
        explanation = exp_match.group(1).strip()
    
    # Also look for explicit explanation section
    if not explanation:
        exp_match = re.search(r'Explanation:\s*(.*?)(?=\n\s*(?:Things to Remember:|Choice [A-F] is)|\Z)',
                             text, re.DOTALL | re.IGNORECASE)
        if exp_match:
            explanation = exp_match.group(1).strip()
    
    # Clean any copyright notices from explanation
    explanation = re.sub(r'(?:©|Copyright\s*©?)\s*\d+(?:-\d+)?\s*[A-Za-z]+(?:Prep)?\.?.*?(?=\n|$)', '', explanation, flags=re.IGNORECASE)
    
    return explanation

def extract_things_to_remember(text):
    """Extract 'Things to Remember' section"""
    remember_match = re.search(r'Things to Remember\s*(.*?)(?=\n\s*(?:Choice [A-F] is)|\Z)', 
                              text, re.DOTALL | re.IGNORECASE)
    if remember_match:
        remember_text = remember_match.group(1).strip()
        
        # Clean any copyright notices
        remember_text = re.sub(r'(?:©|Copyright\s*©?)\s*\d+(?:-\d+)?\s*[A-Za-z]+(?:Prep)?\.?.*?(?=\n|$)', '', remember_text, flags=re.IGNORECASE)
        
        return remember_text
    
    return ""

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
