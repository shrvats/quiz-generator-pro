from fastapi import FastAPI, UploadFile, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
import time
from typing import List, Dict, Optional, Union

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

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

def clean_text(text: str) -> str:
    """Clean text by removing unnecessary characters and formatting."""
    # Remove page numbers
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    # Remove copyright statements
    text = re.sub(r'©\s*\d{4}.*?\n', '\n', text, flags=re.DOTALL)
    text = re.sub(r'Copyright\s*©.*?\n', '\n', text, flags=re.DOTALL)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove standalone numbers (likely page numbers)
    text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
    return text.strip()

def extract_questions_from_page(page, page_num: int) -> List[Dict]:
    """Extract questions and options from a single page."""
    questions = []
    text = page.get_text()
    clean_page_text = clean_text(text)
    
    # First, look for question patterns
    question_pattern = re.compile(r'(\d+)\.\s+(.*?)(?=\n\d+\.\s+|\n?[A-D][\.\)]\s+|\Z)', re.DOTALL)
    question_matches = question_pattern.findall(clean_page_text)
    
    for q_num, q_text in question_matches:
        question = {
            "question": q_text.strip(),
            "options": {},
            "page": page_num
        }
        
        # Extract blocks for option recognition
        blocks = page.get_text("dict")["blocks"]
        
        # Find the question text in blocks to determine its position
        question_pos = None
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        for span in line["spans"]:
                            if q_text.strip() in span.get("text", ""):
                                question_pos = span.get("bbox")
                                break
                        if question_pos:
                            break
                if question_pos:
                    break
        
        # If we found the question position, look for options below it
        if question_pos:
            options = {}
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        if "spans" in line:
                            for span in line["spans"]:
                                text = span.get("text", "").strip()
                                # Check for option pattern
                                option_match = re.match(r'^([A-D])[\.\)]\s+(.*)', text)
                                if option_match:
                                    option_letter = option_match.group(1)
                                    option_text = option_match.group(2).strip()
                                    # Only consider options below the question
                                    if span.get("bbox")[1] > question_pos[1]:
                                        options[option_letter] = option_text
            
            # If options were found, add them to the question
            if options:
                question["options"] = options
        
        # If no options found via block analysis, try regex on text near the question
        if not question["options"]:
            # Look for options in the text after the question
            q_index = clean_page_text.find(q_text)
            if q_index != -1:
                after_q_text = clean_page_text[q_index + len(q_text):]
                option_pattern = re.compile(r'([A-D])[\.\)]\s+(.*?)(?=[A-D][\.\)]|\n\d+\.\s+|\Z)', re.DOTALL)
                option_matches = option_pattern.findall(after_q_text)
                for opt_letter, opt_text in option_matches:
                    question["options"][opt_letter] = opt_text.strip()
        
        # Only add questions that have extracted options
        if question["options"]:
            questions.append(question)
    
    return questions

def extract_tables_from_page(page) -> List[Dict]:
    """Extract tables from a page and convert to structured data."""
    tables = []
    
    # Get page dimensions
    page_width, page_height = page.rect.width, page.rect.height
    
    # Try to find tables using layout analysis
    blocks = page.get_text("dict")["blocks"]
    
    # Group blocks by position to identify potential tables
    for block in blocks:
        if "lines" not in block:
            continue
        
        # Check if block contains multiple lines with similar structure (potential table)
        lines_with_spans = [line for line in block["lines"] if "spans" in line]
        if len(lines_with_spans) >= 3:  # At least 3 lines needed for a table
            # Check if lines have similar number of spans (columns)
            span_counts = [len(line["spans"]) for line in lines_with_spans]
            if max(span_counts) >= 2 and max(span_counts) - min(span_counts) <= 1:
                # Potential table found
                table_data = []
                for line in lines_with_spans:
                    row = [span.get("text", "").strip() for span in line["spans"]]
                    table_data.append(row)
                
                # Only add non-empty tables
                if any(any(cell for cell in row) for row in table_data):
                    tables.append({
                        "type": "table",
                        "data": table_data
                    })
    
    return tables

@app.post("/pdf-info")
async def get_pdf_info(file: UploadFile):
    """Get basic information about the PDF file."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(await file.read())
            tmp_file_path = tmp_file.name
        
        doc = fitz.open(tmp_file_path)
        info = {
            "total_pages": len(doc),
            "file_size_mb": round(os.path.getsize(tmp_file_path) / (1024 * 1024), 2),
            "filename": file.filename
        }
        doc.close()
        os.remove(tmp_file_path)
        
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing PDF: {str(e)}")

@app.post("/process")
async def process_pdf(
    file: UploadFile,
    start_page: int = Form(0, description="Starting page (0-indexed)"),
    end_page: int = Form(-1, description="Ending page (-1 for last page)")
):
    """Process a PDF file to extract questions and options."""
    try:
        start_time = time.time()
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(await file.read())
            tmp_file_path = tmp_file.name
        
        doc = fitz.open(tmp_file_path)
        
        # Validate and adjust page range
        total_pages = len(doc)
        if end_page == -1 or end_page >= total_pages:
            end_page = total_pages - 1
        
        # Ensure valid page range
        start_page = max(0, start_page)
        end_page = min(end_page, total_pages - 1)
        
        # Extract questions from each page in the range
        all_questions = []
        sections = []
        current_section = None
        
        for page_num in range(start_page, end_page + 1):
            page = doc[page_num]
            
            # Look for section headers
            text = page.get_text()
            section_matches = re.findall(r'(?:^|\n)((?:Section|Chapter|Part)\s+\d+[:.]\s*.*?)(?=\n)', text)
            for section_match in section_matches:
                current_section = {
                    "name": section_match.strip(),
                    "questions": []
                }
                sections.append(current_section)
            
            # Extract questions
            page_questions = extract_questions_from_page(page, page_num)
            
            # Add questions to the current section if available
            if current_section:
                current_section["questions"].extend(page_questions)
            
            all_questions.extend(page_questions)
            
            # Extract tables that might contain questions
            tables = extract_tables_from_page(page)
            
            # Process tables for potential questions (if applicable)
            for table in tables:
                # Check if table data resembles question-option format
                table_data = table["data"]
                for row in table_data:
                    if len(row) >= 2:
                        # Check if first column looks like a question number
                        if re.match(r'^\d+\.?$', row[0]):
                            # The second column might be the question
                            question_text = row[1]
                            question = {
                                "question": question_text,
                                "options": {},
                                "page": page_num
                            }
                            
                            # Look for options in subsequent rows or columns
                            option_pattern = re.compile(r'^([A-D])[\.\)]?\s*(.*)')
                            for i in range(2, len(row)):
                                option_match = option_pattern.match(row[i])
                                if option_match:
                                    option_letter = option_match.group(1)
                                    option_text = option_match.group(2).strip()
                                    question["options"][option_letter] = option_text
                            
                            # Only add if options were found
                            if question["options"]:
                                all_questions.append(question)
                                if current_section:
                                    current_section["questions"].append(question)
        
        doc.close()
        os.remove(tmp_file_path)
        
        processing_time = time.time() - start_time
        
        return {
            "questions": all_questions,
            "sections": sections,
            "stats": {
                "total_questions": len(all_questions),
                "processing_time_seconds": round(processing_time, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")
