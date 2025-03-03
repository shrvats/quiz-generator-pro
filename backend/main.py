from fastapi import FastAPI, UploadFile, HTTPException, Request, File, Form
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
import asyncio
import traceback
import time
import json
from typing import List, Dict, Union, Optional, Tuple

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
MAX_PROCESSING_TIME = 119  # seconds, to stay under Vercel's 60s limit

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

def check_time_limit(start_time: float) -> bool:
    """Check if we're approaching the processing time limit"""
    return time.time() - start_time > MAX_PROCESSING_TIME

def extract_blocks_with_positions(doc, page_range=None) -> List[Dict]:
    """Extract text blocks with their positions and page information"""
    all_blocks = []
    
    # If page_range is provided, use it to limit extraction
    if page_range:
        start_page, end_page = page_range
        # Adjust page range to be within document bounds
        start_page = max(0, start_page)
        end_page = min(len(doc) - 1, end_page)
        page_iterator = range(start_page, end_page + 1)
    else:
        page_iterator = range(len(doc))
    
    for page_num in page_iterator:
        page = doc[page_num]
        # Get blocks with positions
        blocks = page.get_text("dict")["blocks"]
        
        for block in blocks:
            if "lines" not in block:
                continue
                
            for line in block["lines"]:
                if "spans" not in line:
                    continue
                    
                for span in line["spans"]:
                    # Skip empty spans
                    if not span.get("text", "").strip():
                        continue
                        
                    all_blocks.append({
                        "page": page_num,
                        "text": span.get("text", ""),
                        "bbox": span.get("bbox", [0, 0, 0, 0]),
                        "font": span.get("font", ""),
                        "size": span.get("size", 0),
                        "flags": span.get("flags", 0),
                        "color": span.get("color", 0)
                    })
    
    return all_blocks

def is_option_marker(text: str) -> bool:
    """Check if text is an option marker (A, B, C, D with various formats)"""
    return bool(re.match(r'^[A-D][\.\)]|^[A-D]$', text.strip()))

def categorize_blocks(blocks: List[Dict]) -> Dict[str, List[Dict]]:
    """Categorize blocks into questions, options, explanations, etc."""
    categorized = {
        "questions": [],
        "options": [],
        "explanations": [],
        "things_to_remember": [],
        "other": []
    }
    
    # First pass to identify question numbers
    question_starts = []
    
    for i, block in enumerate(blocks):
        text = block["text"].strip()
        
        # Check for question identifiers
        if (re.match(r'^Q\.?\s*\d+', text) or 
            re.match(r'^Question\s+\d+', text) or
            re.match(r'^\d+\.\s+', text)):
            question_starts.append(i)
    
    # If no question starts found, try alternative approach
    if not question_starts:
        for i, block in enumerate(blocks):
            if i > 0 and is_option_marker(blocks[i]["text"]):
                # If we find an option marker, the previous block might be a question
                question_starts.append(i-1)
    
    # Second pass to categorize blocks
    current_category = "other"
    
    for i, block in enumerate(blocks):
        text = block["text"].strip()
        
        # Start of a new question
        if i in question_starts:
            current_category = "questions"
            categorized[current_category].append(block)
            continue
            
        # Check if this is an option
        if is_option_marker(text):
            current_category = "options"
            categorized[current_category].append(block)
            continue
            
        # Check for explanation/answer markers
        if (re.search(r'correct answer|explanation|answer:|thus,|therefore', text, re.IGNORECASE) or
            text.startswith("The answer is")):
            current_category = "explanations"
            categorized[current_category].append(block)
            continue
            
        # Check for "things to remember" markers
        if (re.search(r'remember|note:|important|tips|key points', text, re.IGNORECASE) or
            text.startswith("Note:") or
            text.startswith("Remember:")):
            current_category = "things_to_remember"
            categorized[current_category].append(block)
            continue
            
        # Otherwise, continue with current category
        categorized[current_category].append(block)
    
    return categorized

def extract_options(blocks: List[Dict]) -> Dict[str, str]:
    """Extract options A, B, C, D from blocks"""
    options = {}
    current_option = None
    option_text = ""
    
    for block in blocks:
        text = block["text"].strip()
        
        # Check if this is a new option marker
        option_match = re.match(r'^([A-D])[\.\)]?\s*(.*)', text)
        
        if option_match:
            # Save previous option if any
            if current_option:
                options[current_option] = option_text.strip()
            
            # Start new option
            current_option = option_match.group(1)
            option_text = option_match.group(2) if option_match.group(2) else ""
        elif current_option:
            # Continue current option
            option_text += " " + text
    
    # Save the last option
    if current_option:
        options[current_option] = option_text.strip()
    
    return options

def identify_questions(doc, blocks: List[Dict]) -> List[Dict]:
    """Identify individual questions and their components"""
    categorized = categorize_blocks(blocks)
    questions = []
    
    # First identify question boundaries
    question_blocks = []
    current_question = []
    
    for i, block in enumerate(categorized["questions"]):
        text = block["text"].strip()
        
        # Check if this block starts a new question
        is_new_question = (
            re.match(r'^Q\.?\s*\d+', text) or 
            re.match(r'^Question\s+\d+', text) or 
            re.match(r'^\d+\.\s+', text)
        )
        
        if is_new_question and current_question:
            question_blocks.append(current_question)
            current_question = [block]
        else:
            current_question.append(block)
    
    # Add the last question
    if current_question:
        question_blocks.append(current_question)
    
    # Now process each question
    for i, blocks in enumerate(question_blocks):
        # Extract question ID and text
        question_text = " ".join(block["text"] for block in blocks)
        question_id = i + 1
        
        # Try to extract ID from question text
        id_match = re.search(r'Q\.?\s*(\d+)|Question\s+(\d+)|\s*(\d+)\.\s+', question_text)
        if id_match:
            extracted_id = next((g for g in id_match.groups() if g), None)
            if extracted_id:
                question_id = int(extracted_id)
        
        # Extract options for this question
        options = extract_options(categorized["options"])
        
        # Extract correct answer
        correct_answer = None
        explanation = ""
        
        for block in categorized["explanations"]:
            text = block["text"].strip()
            explanation += " " + text
            
            # Try to find correct answer marker
            answer_match = re.search(r'([A-D])\s+is\s+(?:the\s+)?correct|correct\s+answer\s+is\s+([A-D])|answer\s+is\s+([A-D])', text, re.IGNORECASE)
            if answer_match:
                for group in answer_match.groups():
                    if group:
                        correct_answer = group
                        break
        
        # Extract things to remember
        things_to_remember = ""
        for block in categorized["things_to_remember"]:
            things_to_remember += " " + block["text"].strip()
        
        # Extract tables for this question
        tables = extract_tables_from_page(doc[blocks[0]["page"]])
        
        question = {
            "id": question_id,
            "question": clean_text(question_text),
            "options": options,
            "correct": correct_answer,
            "explanation": explanation.strip(),
            "things_to_remember": things_to_remember.strip(),
            "has_table": len(tables) > 0,
            "table_html": tables[0] if tables else None
        }
        
        questions.append(question)
    
    # Sort questions by ID
    questions.sort(key=lambda q: q["id"])
    return questions

def extract_tables_from_page(page) -> List[str]:
    """Extract tables from a page and convert to HTML"""
    tables = []
    blocks = page.get_text("dict")["blocks"]
    
    for block in blocks:
        if "lines" not in block:
            continue
            
        lines_with_spans = [line for line in block["lines"] if "spans" in line]
        
        if len(lines_with_spans) >= 3:  # At least 3 lines needed for a table
            span_counts = [len(line["spans"]) for line in lines_with_spans]
            
            if max(span_counts) >= 2 and max(span_counts) - min(span_counts) <= 1:
                table_data = []
                
                for line in lines_with_spans:
                    row = [span.get("text", "").strip() for span in line["spans"]]
                    table_data.append(row)
                
                # Only convert if at least one cell is non-empty
                if any(cell.strip() for row in table_data for cell in row):
                    html = "<table border='1'>\n"
                    html += "<tr>\n"
                    for cell in table_data[0]:
                        html += f"  <th>{cell}</th>\n"
                    html += "</tr>\n"
                    
                    for row in table_data[1:]:
                        html += "<tr>\n"
                        for cell in row:
                            cell_class = ""
                            if re.match(r'^[\d\.\$]+$', cell):
                                cell_class = " align='right'"
                            html += f"  <td{cell_class}>{cell}</td>\n"
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
        if page_range is None:
            page_range = (0, total_pages - 1)
        
        blocks = extract_blocks_with_positions(doc, page_range)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during block extraction", "questions": [], "total_pages": total_pages}
        
        questions = identify_questions(doc, blocks)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during question processing", "questions": questions, "total_pages": total_pages}
        
        return {
            "questions": questions,
            "total_questions": len(questions),
            "total_pages": total_pages,
            "page_range": page_range,
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
        print(f"Received file: {file.filename}")
        start_time = time.time()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        print(f"Page range requested: {start_page} to {end_page}")
        
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
            
        print(f"Returning {result.get('total_questions', 0)} questions. Process time: {time.time() - start_time:.2f}s")
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
