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

def detect_question_numbering_format(page_text: str) -> str:
    """Detect the question numbering format in the document"""
    formats = [
        (r'Q\.?\s*\d+', 'Q.NUMBER'),
        (r'Question\s+\d+', 'Question NUMBER'),
        (r'\n\d+\.\s+', 'NUMBER.'),
    ]
    
    for pattern, format_name in formats:
        if re.search(pattern, page_text):
            return format_name
    
    return 'unknown'

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

def is_likely_option(block: Dict, option_font_sizes: List[float]) -> bool:
    """Determine if a block is likely to be an option based on content and formatting"""
    text = block["text"].strip()
    
    # Check pattern (A., B., C., D., etc.)
    if re.match(r'^[A-D][\.\)]', text):
        return True
        
    # Check size (options tend to have consistent font size)
    if block["size"] in option_font_sizes:
        # Single letter option (A, B, C, D)
        if re.match(r'^[A-D]$', text):
            return True
            
    return False

def categorize_blocks(blocks: List[Dict]) -> Dict[str, List[Dict]]:
    """Categorize blocks into questions, options, explanations, etc."""
    categorized = {
        "questions": [],
        "options": [],
        "explanations": [],
        "other": []
    }
    
    # Detect option font sizes (since options often share the same font)
    option_font_sizes = []
    for block in blocks:
        text = block["text"].strip()
        if re.match(r'^[A-D][\.\)]', text):
            option_font_sizes.append(block["size"])
    
    option_font_sizes = list(set(option_font_sizes))  # Remove duplicates
    
    # First pass to identify question numbers
    question_starts = []
    
    for i, block in enumerate(blocks):
        text = block["text"].strip()
        
        # Check for question identifiers
        if (re.match(r'^Q\.?\s*\d+', text) or 
            re.match(r'^Question\s+\d+', text) or
            re.match(r'^\d+\.\s+', text)):
            question_starts.append(i)
    
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
        if is_likely_option(block, option_font_sizes):
            current_category = "options"
            categorized[current_category].append(block)
            continue
            
        # Check for explanation markers
        if (re.search(r'correct answer|explanation|thus,|therefore', text, re.IGNORECASE) or
            text.startswith("The answer is") or
            text.startswith("Answer:")):
            current_category = "explanations"
            categorized[current_category].append(block)
            continue
            
        # Otherwise, continue with current category
        categorized[current_category].append(block)
    
    return categorized

def identify_questions_from_blocks(blocks: List[Dict]) -> List[Dict]:
    """Identify individual questions and their components from categorized blocks"""
    questions = []
    current_question = None
    option_pattern = re.compile(r'^([A-D])[\.\)]?\s*(.*)', re.DOTALL)
    
    for block in blocks:
        text = block["text"].strip()
        
        # Check if this block is the start of a new question
        question_match = re.search(r'Q\.?\s*(\d+)|Question\s+(\d+)|\n(\d+)\.\s+', text)
        
        if question_match:
            # Save previous question if any
            if current_question:
                questions.append(current_question)
                
            # Extract question number
            q_num = next((g for g in question_match.groups() if g), "")
            
            # Initialize new question
            current_question = {
                "id": int(q_num) if q_num.isdigit() else len(questions) + 1,
                "text": text,
                "options": {},
                "correct_answer": None,
                "explanation": "",
                "blocks": [block]
            }
        elif current_question:
            # Not a new question, so add to the current one
            current_question["blocks"].append(block)
            
            # Try to categorize this block
            option_match = option_pattern.match(text)
            
            if option_match:
                # This is an option
                option_letter, option_text = option_match.groups()
                current_question["options"][option_letter] = option_text.strip()
            elif "correct answer" in text.lower() or "the answer is" in text.lower():
                # This might contain the correct answer
                answer_match = re.search(r'([A-D])\s+is\s+(?:the\s+)?correct|correct\s+answer\s+is\s+([A-D])|answer\s+is\s+([A-D])', text, re.IGNORECASE)
                if answer_match:
                    correct = next((g for g in answer_match.groups() if g), "")
                    current_question["correct_answer"] = correct
                    
                # Add to explanation
                if current_question["explanation"]:
                    current_question["explanation"] += " " + text
                else:
                    current_question["explanation"] = text
            elif re.search(r'explanation|thus,|therefore', text, re.IGNORECASE):
                # This is part of the explanation
                if current_question["explanation"]:
                    current_question["explanation"] += " " + text
                else:
                    current_question["explanation"] = text
            elif not option_match and not current_question["options"]:
                # If we haven't seen options yet, this is part of the question text
                current_question["text"] += " " + text
    
    # Add the last question
    if current_question:
        questions.append(current_question)
    
    return questions

def extract_text_between_options(doc, question: Dict) -> Dict:
    """Extract text that appears between options, which can help with option text disambiguation"""
    result = question.copy()
    
    # We need the original page content to analyze option positions
    option_blocks = {}
    other_blocks = []
    
    # Filter blocks by page and identify option and non-option blocks
    for block in question["blocks"]:
        text = block["text"].strip()
        option_match = re.match(r'^([A-D])[\.\)]', text)
        
        if option_match:
            option_letter = option_match.group(1)
            option_blocks[option_letter] = block
        else:
            other_blocks.append(block)
    
    # If we found option blocks, analyze what's between them
    if len(option_blocks) >= 2:
        # Sort options by vertical position
        sorted_options = sorted(option_blocks.items(), key=lambda x: x[1]["bbox"][1])
        
        for i in range(len(sorted_options) - 1):
            current_option, current_block = sorted_options[i]
            next_option, next_block = sorted_options[i + 1]
            
            # Find blocks between these two options
            between_blocks = []
            for block in other_blocks:
                # Check if block is between these options vertically
                if (block["page"] == current_block["page"] and 
                    block["bbox"][1] > current_block["bbox"][3] and
                    block["bbox"][3] < next_block["bbox"][1] and
                    # Skip blocks that are far to the right (likely not part of the option)
                    block["bbox"][0] < current_block["bbox"][0] + 100):
                    between_blocks.append(block)
            
            # If we found blocks between options, add their text to the current option
            if between_blocks:
                between_text = " ".join(b["text"] for b in between_blocks)
                # Make sure not to add the next option's heading
                between_text = re.sub(r'[A-D][\.\)].*$', '', between_text)
                
                # Update the option text
                if current_option in result["options"]:
                    result["options"][current_option] += " " + between_text.strip()
    
    return result

def extract_tables_from_page(page) -> List[str]:
    """Extract tables from a page and convert to HTML"""
    tables = []
    
    # Get page dimensions
    page_width, page_height = page.rect.width, page.rect.height
    
    # Try to find tables using layout analysis
    blocks = page.get_text("dict")["blocks"]
    
    # Group blocks by position to identify potential tables
    potential_tables = []
    
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
                
                # Convert to HTML
                if any(row for row in table_data):
                    html = "<table border='1'>\n"
                    
                    # First row as header
                    html += "<tr>\n"
                    for cell in table_data[0]:
                        html += f"  <th>{cell}</th>\n"
                    html += "</tr>\n"
                    
                    # Rest of rows as data
                    for row in table_data[1:]:
                        html += "<tr>\n"
                        for cell in row:
                            cell_class = ""
                            # Right-align numeric cells
                            if re.match(r'^[\d\.\$]+$', cell):
                                cell_class = " align='right'"
                            html += f"  <td{cell_class}>{cell}</td>\n"
                        html += "</tr>\n"
                    
                    html += "</table>"
                    tables.append(html)
    
    return tables

def extract_mathematical_content(text: str) -> Tuple[str, bool]:
    """Enhance and identify mathematical content in text"""
    # Patterns that indicate mathematical content
    math_patterns = [
        r'[=\+\-\*\/\^\(\)]',  # Basic operators
        r'\d+\.\d+',            # Decimal numbers
        r'[αβγδεζηθικλμνξοπρστυφχψω]',  # Greek lowercase
        r'[ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ]',  # Greek uppercase
        r'√|∑|∫|∂|∇|∞',        # Math symbols
        r'\b[A-Za-z]\s*=',      # Variable assignments
        r'log|exp|sin|cos|tan', # Functions
        r'var|std|avg|mean',    # Statistical terms
    ]
    
    contains_math = any(re.search(pattern, text) for pattern in math_patterns)
    
    # If contains math, try to improve readability
    if contains_math:
        # Format common mathematical symbols for better display
        replacements = [
            (r'(\d+)\/(\d+)', r'\1÷\2'),  # Improve fractions
            (r'(\w+)\^(\w+)', r'\1^{\2}'),  # Format powers
            (r'sqrt\(([^)]+)\)', r'√(\1)'),  # Format square roots
            (r'alpha', 'α'), (r'beta', 'β'), (r'gamma', 'γ'),  # Greek letters
            (r'delta', 'δ'), (r'sigma', 'σ'), (r'theta', 'θ'),
            (r'mu', 'μ'), (r'pi', 'π'), (r'lambda', 'λ')
        ]
        
        for old, new in replacements:
            text = re.sub(old, new, text)
    
    return text, contains_math

def process_questions_and_options(identified_questions: List[Dict], doc) -> List[Dict]:
    """Process identified questions to extract options and correct answers"""
    processed_questions = []
    
    for question in identified_questions:
        # First, try to improve option extraction using layout information
        enhanced_question = extract_text_between_options(doc, question)
        
        # Extract options more carefully
        options = {}
        correct_answer = None
        
        # Normalize existing options
        for key, value in enhanced_question["options"].items():
            # Remove any correct answer text from options
            clean_value = re.sub(r'.*correct answer is.*', '', value, flags=re.IGNORECASE)
            options[key] = clean_value.strip()
        
        # Try to extract correct answer from explanation
        explanation = enhanced_question.get("explanation", "")
        if explanation:
            answer_match = re.search(r'correct answer is\s+([A-D])|answer\s+is\s+([A-D])', explanation, re.IGNORECASE)
            if answer_match:
                correct = next((g for g in answer_match.groups() if g), "")
                correct_answer = correct
        
        # Extract any tables in the question
        tables = []
        page_nums = set(block["page"] for block in enhanced_question["blocks"])
        
        for page_num in page_nums:
            tables.extend(extract_tables_from_page(doc[page_num]))
        
        # Process any mathematical content
        question_text, contains_math = extract_mathematical_content(enhanced_question["text"])
        
        # Process options for mathematical content
        for key, value in options.items():
            options[key], _ = extract_mathematical_content(value)
        
        # Create cleaned question object
        processed_question = {
            "id": enhanced_question["id"],
            "question": question_text,
            "options": options,
            "correct": correct_answer,
            "explanation": explanation,
            "has_table": len(tables) > 0,
            "table_html": tables[0] if tables else None,
            "contains_math": contains_math
        }
        
        processed_questions.append(processed_question)
    
    return processed_questions

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict:
    """Advanced PDF processing with layout analysis for mathematical and financial content"""
    start_time = time.time()
    
    try:
        # Open the PDF with PyMuPDF
        doc = fitz.open(file_path)
        
        # Get total page count
        total_pages = len(doc)
        
        # If page range is not specified, process the entire document
        if page_range is None:
            page_range = (0, total_pages - 1)
        
        # Strategy: Use layout analysis instead of just text patterns
        # 1. Extract blocks with position information
        # 2. Categorize blocks (questions, options, explanations)
        # 3. Group blocks into complete questions
        # 4. Extract tables and mathematical content
        
        # Extract blocks with positions for the specified page range
        blocks = extract_blocks_with_positions(doc, page_range)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during block extraction", "questions": [], "total_pages": total_pages}
        
        # Categorize blocks by purpose
        categorized = categorize_blocks(blocks)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during block categorization", "questions": [], "total_pages": total_pages}
            
        # Identify individual questions
        identified_questions = identify_questions_from_blocks(blocks)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during question identification", "questions": [], "total_pages": total_pages}
        
        # Process each question to extract components
        processed_questions = process_questions_and_options(identified_questions, doc)
        
        if check_time_limit(start_time):
            return {"error": "Processing time limit exceeded during question processing", "questions": processed_questions, "total_pages": total_pages}
        
        # Sort questions by ID
        processed_questions.sort(key=lambda q: q["id"])
        
        # Return the processed questions along with page information
        return {
            "questions": processed_questions,
            "total_questions": len(processed_questions),
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
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        print(f"Page range requested: {start_page} to {end_page}")
        
        # Determine page range
        page_range = None
        if start_page is not None and end_page is not None:
            page_range = (int(start_page), int(end_page))
        
        # Process the PDF with timeout protection
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(process_pdf, tmp_path, page_range),
                timeout=55.0  # Allow 55 seconds max (within Vercel's 60s limit)
            )
        except asyncio.TimeoutError:
            # Clean up
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=408, 
                detail="PDF processing timed out. Please try a smaller PDF file or fewer pages."
            )
        
        # Clean up
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
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        # Open PDF to get page count
        doc = fitz.open(tmp_path)
        total_pages = len(doc)
        
        # Get file size in MB
        file_size = os.path.getsize(tmp_path) / (1024 * 1024)
        
        # Extract metadata
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", "")
        }
        
        # Clean up
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
