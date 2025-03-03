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

def extract_content(doc, page_range=None):
    """Extract structured content from PDF pages"""
    if page_range:
        start_page, end_page = page_range
        start_page = max(0, start_page)
        end_page = min(len(doc) - 1, end_page)
        pages = range(start_page, end_page + 1)
    else:
        pages = range(len(doc))
    
    # Extract all blocks from PDF
    all_blocks = []
    for page_num in pages:
        page = doc[page_num]
        page_dict = page.get_text("dict")
        
        # Add page blocks with page number
        for block in page_dict["blocks"]:
            if "lines" in block:
                block_text = ""
                for line in block["lines"]:
                    if "spans" in line:
                        for span in line["spans"]:
                            block_text += span.get("text", "") + " "
                
                # Skip empty blocks
                if not block_text.strip():
                    continue
                
                # Add block with metadata
                all_blocks.append({
                    "page": page_num,
                    "text": block_text.strip(),
                    "bbox": block["bbox"],
                    "type": "unknown",  # Will classify later
                    "block_obj": block  # Keep original for structure
                })
    
    return all_blocks

def classify_blocks(blocks):
    """Classify blocks by content type"""
    classified_blocks = []
    
    # First pass: basic classification
    for block in blocks:
        text = block["text"]
        
        # Skip copyright and page numbers
        if (re.search(r'©\s*\d{4}|Copyright', text, re.IGNORECASE) or
            re.match(r'^\s*\d+\s*$', text)):
            block["type"] = "skip"
            continue
        
        # Question ID blocks
        if re.match(r'(?:Question\s+\d+|Q\.\s*\d+)', text):
            block["type"] = "question_id"
        
        # Option blocks
        elif re.match(r'^[A-F][\.\)]\s+', text):
            block["type"] = "option"
            # Extract option letter
            match = re.match(r'^([A-F])[\.\)]', text)
            if match:
                block["option_letter"] = match.group(1)
        
        # Explanation blocks
        elif (re.search(r'correct answer|explanation|the answer is', text, re.IGNORECASE) or
              re.search(r'is correct', text, re.IGNORECASE)):
            block["type"] = "explanation"
        
        # Things to remember blocks
        elif re.search(r'things to remember|note:|remember:', text, re.IGNORECASE):
            block["type"] = "remember"
        
        # Treat all other blocks as potential question content for now
        else:
            block["type"] = "content"
        
        classified_blocks.append(block)
    
    # Find question boundaries
    question_starts = [i for i, block in enumerate(classified_blocks) if block["type"] == "question_id"]
    
    # Group blocks by question
    questions = []
    for i in range(len(question_starts)):
        start_idx = question_starts[i]
        end_idx = question_starts[i+1] if i+1 < len(question_starts) else len(classified_blocks)
        
        question_blocks = classified_blocks[start_idx:end_idx]
        if question_blocks:
            # Extract question ID
            q_id_block = question_blocks[0]
            q_id_match = re.search(r'(?:Question\s+(\d+)|Q\.\s*(\d+))', q_id_block["text"])
            q_id = next((g for g in q_id_match.groups() if g), "0") if q_id_match else "0"
            
            questions.append({
                "id": int(q_id),
                "blocks": question_blocks
            })
    
    return questions

def process_question(question_data):
    """Process a question's blocks into structured data"""
    blocks = question_data["blocks"]
    q_id = question_data["id"]
    
    # Initialize question components
    question_text = ""
    options = {}
    explanation = ""
    things_to_remember = ""
    correct_answer = None
    
    # First, separate blocks by type
    option_blocks = [b for b in blocks if b["type"] == "option"]
    explanation_blocks = [b for b in blocks if b["type"] == "explanation"]
    remember_blocks = [b for b in blocks if b["type"] == "remember"]
    
    # Question blocks - all non-option/explanation/remember blocks after the question_id
    question_id_index = next((i for i, b in enumerate(blocks) if b["type"] == "question_id"), 0)
    content_blocks = []
    for i, block in enumerate(blocks):
        if (i > question_id_index and 
            block["type"] not in ["option", "explanation", "remember", "skip"] and
            i < min([blocks.index(b) for b in option_blocks] or [len(blocks)])):
            content_blocks.append(block)
    
    # Extract question text
    for block in content_blocks:
        # Clean text of any copyright notices or page numbers
        text = clean_text(block["text"])
        if text:
            question_text += text + " "
    
    # Extract options
    for block in option_blocks:
        if "option_letter" in block:
            option_letter = block["option_letter"]
            # Remove option letter (A., B., etc) from beginning
            option_text = re.sub(r'^[A-F][\.\)]\s+', '', block["text"])
            options[option_letter] = clean_text(option_text)
    
    # Extract explanation
    for block in explanation_blocks:
        text = clean_text(block["text"])
        
        # Check for correct answer
        answer_match = re.search(r'(?:correct answer is|answer is|correct:)\s*([A-F])\.?', text, re.IGNORECASE)
        if answer_match:
            correct_answer = answer_match.group(1)
        
        explanation += text + " "
    
    # Extract things to remember
    for block in remember_blocks:
        things_to_remember += clean_text(block["text"]) + " "
    
    # Clean and finalize 
    question_text = clean_text(question_text.strip())
    explanation = clean_text(explanation.strip())
    things_to_remember = clean_text(things_to_remember.strip())
    
    # Final cleaning: Remove question ID from question text
    question_text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.\s*\d+(?:\(Q\.\d+\))?)\s*', '', question_text)
    
    # Final check for empty options
    options = {k: v for k, v in options.items() if v.strip()}
    
    return {
        "id": q_id,
        "question": question_text,
        "options": options,
        "correct": correct_answer,
        "explanation": explanation,
        "things_to_remember": things_to_remember,
        "has_options": len(options) > 0
    }

def clean_text(text):
    """Clean text by removing copyright notices, page numbers, etc."""
    # Remove copyright statements
    text = re.sub(r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
    
    # Remove page numbers
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    text = re.sub(r'^[ \t]*\d+[ \t]*$', '', text, flags=re.MULTILINE)
    
    # Remove any isolated numbers that might be page numbers
    text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
    
    return text.strip()

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict:
    """Process PDF to extract quiz questions using block structure"""
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        
        # Extract blocks with classified type
        blocks = extract_content(doc, page_range)
        
        # Group blocks into questions
        question_groups = classify_blocks(blocks)
        
        # Process each question group
        questions = []
        for question_group in question_groups:
            question_data = process_question(question_group)
            if question_data and question_data["question"]:
                questions.append(question_data)
        
        return {
            "questions": questions,
            "total_questions": len(questions),
            "total_pages": total_pages
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
