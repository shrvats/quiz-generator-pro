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

# Configuration
MAX_PROCESSING_TIME = 119  # seconds

def clean_text(text: str) -> str:
    """Clean text by removing copyright notices, page numbers, etc."""
    # Remove page numbers
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    # Remove copyright statements
    text = re.sub(r'©\s*\d{4}.*?\n', '\n', text, flags=re.DOTALL)
    text = re.sub(r'Copyright\s*©.*?\n', '\n', text, flags=re.DOTALL)
    # Remove standalone numbers (likely page numbers)
    text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
    return text

def extract_questions_from_pdf(doc, page_range=None):
    """Extract questions and options from PDF"""
    if page_range:
        start_page, end_page = page_range
        # Adjust page range to be within document bounds
        start_page = max(0, start_page)
        end_page = min(len(doc) - 1, end_page)
        pages = range(start_page, end_page + 1)
    else:
        pages = range(len(doc))
    
    questions = []
    for page_num in pages:
        page = doc[page_num]
        text = page.get_text("text")
        text = clean_text(text)
        
        # Find question patterns: Q.XXXX or Question X
        question_matches = list(re.finditer(r'(?:Q\.?|Question)\s*(\d+)(?:\(Q\.(\d+)\))?|\n(\d+)[\.\)]', text))
        
        for i, match in enumerate(question_matches):
            # Extract question ID from regex groups
            q_id = next((g for g in match.groups() if g), "")
            
            # Determine question text boundaries
            start_pos = match.start()
            if i < len(question_matches) - 1:
                end_pos = question_matches[i+1].start()
            else:
                end_pos = len(text)
            
            question_full_text = text[start_pos:end_pos].strip()
            
            # Process this question
            question_data = process_question(question_full_text, q_id, page, doc)
            if question_data:
                questions.append(question_data)
    
    # Sort questions by ID
    questions.sort(key=lambda q: q["id"])
    return questions

def process_question(text, q_id, page, doc):
    """Process a single question text to extract all components"""
    try:
        # Extract the actual question text (removing correct answer info)
        question_text = extract_question_text(text)
        
        # Extract options A, B, C, D
        options = extract_options(text)
        
        # Extract correct answer
        correct_answer = extract_correct_answer(text)
        
        # Extract explanation
        explanation = extract_explanation(text)
        
        # Extract things to remember
        things_to_remember = extract_things_to_remember(text)
        
        # Extract tables
        tables = extract_tables_from_page(page)
        
        return {
            "id": int(q_id),
            "question": question_text,
            "options": options,
            "correct": correct_answer,
            "explanation": explanation,
            "things_to_remember": things_to_remember,
            "has_table": bool(tables),
            "table_html": tables[0] if tables else None
        }
    except Exception as e:
        print(f"Error processing question {q_id}: {str(e)}")
        traceback.print_exc()
        return None

def extract_question_text(text):
    """Extract only the question text, removing answers and explanations"""
    # Remove option sections first
    cleaned_text = text
    
    # Remove correct answer statements
    answer_patterns = [
        r'(?:The correct answer is|Correct answer[:\s]+)[A-F]\.?.*?(?=\n|$)',
        r'The answer is [A-F]\.?.*?(?=\n|$)',
        r'Answer:.*?(?=\n|$)'
    ]
    
    for pattern in answer_patterns:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE | re.DOTALL)
    
    # Find where options begin
    option_match = re.search(r'\n\s*[A-F][\.\)]\s+', cleaned_text)
    if option_match:
        # Cut off at first option
        cleaned_text = cleaned_text[:option_match.start()]
    
    # Also cut at explanation markers
    explanation_markers = ['explanation:', 'things to remember:', 'note:']
    for marker in explanation_markers:
        marker_pos = cleaned_text.lower().find(marker)
        if marker_pos > 0:
            cleaned_text = cleaned_text[:marker_pos]
    
    # Clean up and normalize whitespace
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    # Remove any question ID prefix if it's still there
    cleaned_text = re.sub(r'^(?:Q\.?|Question)\s*\d+(?:\(Q\.\d+\))?\s*', '', cleaned_text)
    
    return cleaned_text

def extract_options(text):
    """Extract the options A, B, C, D, etc. from text"""
    options = {}
    
    # Match each option with its text
    option_pattern = r'(?:^|\n)\s*([A-F])[\.\)]\s*(.*?)(?=\n\s*[A-F][\.\)]|\n\s*(?:The correct|Correct|Answer)|\Z)'
    option_matches = re.finditer(option_pattern, text, re.DOTALL)
    
    for match in option_matches:
        letter = match.group(1)
        option_text = match.group(2).strip()
        
        # Clean the option text (remove answer indicators)
        option_text = re.sub(r'(?:is correct|correct answer)', '', option_text, flags=re.IGNORECASE)
        options[letter] = option_text
    
    return options

def extract_correct_answer(text):
    """Extract the correct answer (A, B, C, D) from text"""
    # Common patterns for marking correct answers
    patterns = [
        r'(?:The correct answer is|Correct answer[:\s]+)([A-F])\.?',
        r'The answer is ([A-F])\.?',
        r'Answer:\s*([A-F])\.?',
        r'([A-F])\s+is correct',
        r'([A-F])\s+is the correct answer'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_explanation(text):
    """Extract explanation text"""
    # Look for explanation markers
    patterns = [
        r'(?:Explanation:|The explanation:)\s*(.*?)(?=\n\s*(?:Things to remember:|Note:)|\Z)',
        r'(?:The correct answer is|Correct answer[:\s]+)[A-F]\.?\s*(.*?)(?=\n\s*(?:Things to remember:|Note:)|\Z)',
        r'The answer is [A-F]\.?\s*(.*?)(?=\n\s*(?:Things to remember:|Note:)|\Z)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            explanation = match.group(1).strip()
            if explanation:
                return explanation
    
    return ""

def extract_things_to_remember(text):
    """Extract 'things to remember' section"""
    patterns = [
        r'(?:Things to remember:|Remember:|Note:)\s*(.*?)(?=\n\s*[A-F][\.\)]|\Z)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return ""

def extract_tables_from_page(page):
    """Extract tables from a page"""
    tables = []
    page_dict = page.get_text("dict")
    
    # Simple approach to detect tables
    rows = {}
    
    # First pass: identify potential table rows by counting spans in a line
    for block in page_dict["blocks"]:
        if "lines" not in block:
            continue
            
        for line in block["lines"]:
            if "spans" in line and len(line["spans"]) > 1:
                # Potential table row - group by vertical position
                y_pos = round(line["bbox"][1])  # round to handle slight misalignments
                if y_pos not in rows:
                    rows[y_pos] = []
                for span in line["spans"]:
                    rows[y_pos].append({
                        "text": span.get("text", "").strip(),
                        "x": span["bbox"][0],
                        "width": span["bbox"][2] - span["bbox"][0]
                    })
    
    # If we have enough rows, we likely have a table
    if len(rows) >= 3:
        # Sort rows by vertical position
        sorted_y = sorted(rows.keys())
        
        # Build HTML table
        if sorted_y:
            html = "<table border='1'>\n"
            
            # Assume first row is header
            html += "<tr>\n"
            for cell in rows[sorted_y[0]]:
                html += f"  <th>{cell['text']}</th>\n"
            html += "</tr>\n"
            
            # Rest are data rows
            for y in sorted_y[1:]:
                html += "<tr>\n"
                for cell in rows[y]:
                    cell_class = ""
                    if re.match(r'^[\d\.\$]+$', cell['text']):
                        cell_class = " align='right'"
                    html += f"  <td{cell_class}>{cell['text']}</td>\n"
                html += "</tr>\n"
            
            html += "</table>"
            tables.append(html)
    
    return tables

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
