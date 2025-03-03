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
    current_question = None
    option_letters = ["A", "B", "C", "D", "E", "F"]
    
    for page_num in pages:
        page = doc[page_num]
        text = page.get_text("text")
        
        # Remove page numbers and copyright notices
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
        text = re.sub(r'©.*?\n', '', text, flags=re.DOTALL)
        text = re.sub(r'Copyright.*?\n', '', text, flags=re.DOTALL)
        
        # Look for question patterns: Q.1234 or Question 1 or just 1. at beginning of line
        question_matches = list(re.finditer(r'(?:Q\.?|Question)\s*(\d+)|\n(\d+)[\.\)]', text))
        
        for i, match in enumerate(question_matches):
            question_number = match.group(1) or match.group(2)
            start_pos = match.start()
            
            # Determine end position (next question or end of text)
            if i < len(question_matches) - 1:
                end_pos = question_matches[i+1].start()
            else:
                end_pos = len(text)
            
            question_text = text[start_pos:end_pos].strip()
            
            # Extract options
            options = {}
            for letter in option_letters:
                option_pattern = rf'(?:\n|^)({letter})[\.\)]\s*(.*?)(?=\n(?:[A-F][\.\)]|\s*(?:Correct|Answer|The answer))|\Z)'
                option_match = re.search(option_pattern, question_text, re.DOTALL)
                if option_match:
                    option_key = option_match.group(1)
                    option_value = option_match.group(2).strip()
                    options[option_key] = option_value
            
            # Extract correct answer if present
            correct_answer = None
            answer_match = re.search(r'(?:Correct answer|Answer|The answer).*?([A-F])', question_text, re.IGNORECASE)
            if answer_match:
                correct_answer = answer_match.group(1)
            
            # Extract things to remember
            things_to_remember = ""
            remember_match = re.search(r'(?:Remember:|Things to remember:|Note:)(.*?)(?=\n\s*[A-F][\.\)]|\Z)', 
                                      question_text, re.DOTALL | re.IGNORECASE)
            if remember_match:
                things_to_remember = remember_match.group(1).strip()
            
            # Extract tables for this question
            tables = extract_table_from_page(page)
            table_html = tables[0] if tables else None
            
            question = {
                "id": int(question_number),
                "question": extract_main_question(question_text),
                "options": options,
                "correct": correct_answer,
                "explanation": extract_explanation(question_text),
                "things_to_remember": things_to_remember,
                "has_table": bool(tables),
                "table_html": table_html
            }
            
            questions.append(question)
    
    # Sort questions by ID
    questions.sort(key=lambda q: q["id"])
    return questions

def extract_main_question(text):
    """Extract the main question text from the full text"""
    # Remove option sections
    for letter in ["A", "B", "C", "D", "E", "F"]:
        text = re.sub(rf'\n{letter}[\.\)][^\n]+(\n[^\n{letter}][^\n]*)*', '', text)
    
    # Remove answer/explanation sections
    text = re.sub(r'\n(?:Correct answer|Answer|The answer).*', '', text, re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\nRemember:.*', '', text, re.DOTALL | re.IGNORECASE)
    
    # Clean up and return
    return text.strip()

def extract_explanation(text):
    """Extract explanation from text"""
    explanation = ""
    explanation_match = re.search(r'(?:Correct answer|Answer|The answer)[^:]*:?\s*(.*?)(?=\n\s*Remember:|Things to remember:|\Z)', 
                                 text, re.DOTALL | re.IGNORECASE)
    if explanation_match:
        explanation = explanation_match.group(1).strip()
    return explanation

def extract_table_from_page(page):
    """Extract tables from a page"""
    tables = []
    page_dict = page.get_text("dict")
    
    # Simple approach to detect tables
    row_counts = {}
    max_cols = 0
    
    # Collect potential table rows
    for block in page_dict["blocks"]:
        if "lines" in block:
            for line in block["lines"]:
                if "spans" in line:
                    spans = line["spans"]
                    if len(spans) > 1:  # Potential table row
                        y_pos = line["bbox"][1]  # vertical position
                        row_counts[y_pos] = len(spans)
                        max_cols = max(max_cols, len(spans))
    
    # If we have enough rows with multiple columns, we might have a table
    if len(row_counts) >= 3 and max_cols >= 2:
        # Sort rows by vertical position
        sorted_rows = sorted(row_counts.keys())
        
        # Build HTML table
        table_data = []
        for y_pos in sorted_rows:
            row_data = []
            for block in page_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        if "spans" in line and abs(line["bbox"][1] - y_pos) < 2:
                            row_data = [span["text"] for span in line["spans"]]
                            break
            if row_data:
                table_data.append(row_data)
        
        # Generate HTML
        if table_data:
            html = "<table border='1'>\n"
            # Assume first row is header
            html += "<tr>\n"
            for cell in table_data[0]:
                html += f"  <th>{cell}</th>\n"
            html += "</tr>\n"
            
            # Rest are data rows
            for row in table_data[1:]:
                html += "<tr>\n"
                for cell in row:
                    html += f"  <td>{cell}</td>\n"
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
