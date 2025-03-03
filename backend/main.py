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

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict:
    """Simplified PDF processing function to extract quiz data"""
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
        
        # Find all questions in the text
        questions = []
        
        # Match Q.XXXX or Question X patterns
        question_pattern = r'(?:Q\.?\s*(\d+)(?:\(Q\.(\d+)\))?|Question\s+(\d+)(?:\(Q\.(\d+)\))?)'
        
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
            
            question_text = all_text[start_pos:end_pos].strip()
            
            # Extract options for this question
            options = {}
            
            # Look for A., B., C., D. options
            option_pattern = r'(?:^|\n)\s*([A-F])[\.\)]\s*(.*?)(?=\n\s*[A-F][\.\)]|\n\s*$|$)'
            option_matches = list(re.finditer(option_pattern, question_text, re.DOTALL))
            
            for opt_match in option_matches:
                letter = opt_match.group(1)
                option_text = opt_match.group(2).strip()
                
                # Clean the option text (remove any "correct" markers)
                option_text = re.sub(r'(?:is correct|correct answer|is incorrect)', '', option_text, flags=re.IGNORECASE)
                
                options[letter] = option_text
            
            # Extract correct answer if present
            correct_answer = None
            answer_patterns = [
                r'(?:The correct answer is|Correct answer[:\s]+)([A-F])\.?',
                r'The answer is ([A-F])\.?',
                r'Answer:\s*([A-F])\.?'
            ]
            
            for pattern in answer_patterns:
                answer_match = re.search(pattern, question_text, re.IGNORECASE)
                if answer_match:
                    correct_answer = answer_match.group(1)
                    break
            
            # Extract ONLY the actual question text (not options or answers)
            actual_question = extract_question_only(question_text)
            
            # For questions with numbers in them, extract those separately
            numeric_value = extract_numeric_value(question_text)
            
            # Create the question object
            q_obj = {
                "id": int(q_num),
                "question": actual_question,
                "options": options,
                "numeric_value": numeric_value,
                "correct": correct_answer,
                "explanation": extract_explanation(question_text),
                "has_options": len(options) > 0
            }
            
            questions.append(q_obj)
        
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

def extract_question_only(text):
    """Extract only the question text without options or answers"""
    # Remove any "The correct answer is..." text
    text = re.sub(r'The correct answer is [A-F]\..*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:Correct answer|Answer)[:\s]+[A-F]\.?.*', '', text, flags=re.IGNORECASE)
    
    # Cut off at first option
    option_match = re.search(r'\n\s*[A-F][\.\)]', text)
    if option_match:
        text = text[:option_match.start()]
    
    # Remove the question ID
    text = re.sub(r'^(?:Q\.?\s*\d+(?:\(Q\.\d+\))?|Question\s+\d+(?:\(Q\.\d+\))?)\s*', '', text)
    
    return text.strip()

def extract_numeric_value(text):
    """Extract any numeric values from question like 37.00 or 39.00 F 50,000"""
    # Look for patterns like "37.00" or "39.00 F 50,000"
    patterns = [
        r'(\d+\.\d+)\s+([A-Z])\s+([\d,]+)',  # For patterns like "39.00 F 50,000"
        r'(\d+\.\d+)\s*([A-Z])?\s*([\d,]*)',  # More general pattern
        r'(\d+\.\d+)'  # Just a number
    ]
    
    for pattern in patterns:
        num_match = re.search(pattern, text)
        if num_match:
            return num_match.group(0).strip()
    
    return None

def extract_explanation(text):
    """Extract explanation text"""
    explanation = ""
    
    # Look for explanation after correct answer
    exp_match = re.search(r'(?:The correct answer is|Correct answer[:\s]+)[A-F]\.?\s*(.*?)(?=$)', 
                         text, re.DOTALL | re.IGNORECASE)
    if exp_match:
        explanation = exp_match.group(1).strip()
    
    return explanation

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
