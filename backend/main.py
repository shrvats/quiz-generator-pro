from fastapi import FastAPI, UploadFile, HTTPException, Request, File
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
import asyncio
import traceback
import time
import concurrent.futures
from typing import List, Dict, Union, Optional

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

# Patterns to identify and remove unwanted content
COPYRIGHT_PATTERNS = [
    r'©\s*\d{4}(-\d{4})?\s*[A-Za-z]+',
    r'Copyright\s*\d{4}',
    r'All rights reserved',
]

PAGE_NUMBER_PATTERNS = [
    r'^\s*\d+\s*$',  # Stand-alone number like "30"
    r'Page\s*\d+\s*of\s*\d+',
]

TABLE_OF_CONTENTS_PATTERNS = [
    r'Table of Contents',
    r'Contents',
]

def is_unwanted_content(line: str) -> bool:
    """Check if a line is page number, copyright, etc."""
    # Check page number patterns
    for pattern in PAGE_NUMBER_PATTERNS:
        if re.search(pattern, line.strip()):
            return True
            
    # Check copyright patterns
    for pattern in COPYRIGHT_PATTERNS:
        if re.search(pattern, line):
            return True
            
    return False

def is_table_of_contents(text: str) -> bool:
    """Check if a block of text appears to be a table of contents"""
    for pattern in TABLE_OF_CONTENTS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    # Also check for characteristic TOC patterns (chapter numbers followed by page numbers)
    toc_pattern = r'\n\s*\d+\s+.*?\s+\d+\s*\n'
    if re.search(toc_pattern, text):
        return True
        
    return False

def extract_sections(text: str) -> Dict[str, Dict]:
    """Extract different readings/sections from the text"""
    sections = {}
    
    # Look for patterns like "Reading XX: Title" or "Chapter XX"
    section_pattern = re.compile(r'(Reading|Chapter)\s+(\d+)[:\s]+(.*?)(?=(?:Reading|Chapter)\s+\d+|\Z)', 
                               re.DOTALL | re.IGNORECASE)
    
    matches = section_pattern.finditer(text)
    for match in matches:
        section_num = match.group(2)
        section_title = match.group(3).strip()
        section_content = match.group(0)
        
        section_id = f"{match.group(1)} {section_num}"
        sections[section_id] = {
            'title': section_title,
            'content': section_content,
            'questions': []
        }
    
    return sections

def clean_text(text: str) -> str:
    """Remove unwanted elements like page numbers, copyright notices"""
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        if not is_unwanted_content(line):
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)

def extract_table_from_text(text: str) -> Optional[str]:
    """Extract and format tabular data from text"""
    lines = text.split('\n')
    
    # Look for table-like structures
    table_lines = []
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        
        # Table indicators: aligned columns or | characters
        if (re.search(r'\s{3,}', stripped) or '\t' in stripped or
            '|' in stripped or re.search(r'\d+\s+\d+\.\d+\s+\d+\.\d+', stripped)):
            
            if not in_table:
                in_table = True
            table_lines.append(stripped)
        elif in_table and stripped:
            table_lines.append(stripped)
        elif in_table and not stripped:
            # Process the table if we have enough lines
            if len(table_lines) >= 2:
                return convert_to_html_table(table_lines)
            in_table = False
            table_lines = []
    
    # Check for unprocessed table at the end
    if in_table and len(table_lines) >= 2:
        return convert_to_html_table(table_lines)
    
    return None

def convert_to_html_table(table_lines: List[str]) -> str:
    """Convert text lines to HTML table format"""
    html = "<table border='1'>\n"
    
    # Try to determine column structure
    if any('|' in line for line in table_lines):
        # Handle pipe-delimited tables
        for line in table_lines:
            if re.match(r'\|[\s\-\+]*\|', line):  # Skip separator lines
                continue
                
            cells = [cell.strip() for cell in line.split('|') if cell.strip()]
            
            if cells:
                html += "<tr>\n"
                for cell in cells:
                    html += f"  <td>{cell}</td>\n"
                html += "</tr>\n"
    else:
        # Handle space-aligned tables (more common in financial data)
        # First try to detect headers
        headers = []
        data_rows = []
        header_pattern = re.compile(r'\s{2,}|\t+')
        
        # Identify potential header row
        if len(table_lines) > 0:
            first_line = table_lines[0]
            headers = [h.strip() for h in header_pattern.split(first_line) if h.strip()]
            data_rows = table_lines[1:]
            
            # Add header row
            if headers:
                html += "<tr>\n"
                for header in headers:
                    html += f"  <th>{header}</th>\n"
                html += "</tr>\n"
        
        # Process data rows
        for line in data_rows:
            cells = [cell.strip() for cell in header_pattern.split(line) if cell.strip()]
            
            if cells:
                html += "<tr>\n"
                for cell in cells:
                    html += f"  <td>{cell}</td>\n"
                html += "</tr>\n"
    
    html += "</table>"
    return html

def extract_options_advanced(question_text: str) -> Dict[str, str]:
    """Extract options from question text, carefully separating from explanations and answers"""
    options = {}
    
    # First, try to detect where the options section ends
    explanation_patterns = [
        r'The correct answer is [A-D]',
        r'Correct answer: [A-D]',
        r'ANSWER\s*:',
        r'Things to Remember',
        r'Explanation:'
    ]
    
    # Find the earliest occurrence of an explanation pattern
    earliest_explanation_pos = len(question_text)
    for pattern in explanation_patterns:
        match = re.search(pattern, question_text, re.IGNORECASE)
        if match and match.start() < earliest_explanation_pos:
            earliest_explanation_pos = match.start()
    
    # Extract only the part before explanations for option parsing
    options_text = question_text[:earliest_explanation_pos]
    
    # Now extract options from the limited text
    pattern1 = re.compile(r'([A-D])[\.\)]\s+(.*?)(?=(?:[A-D][\.\)])|$)', re.DOTALL)
    matches1 = list(pattern1.finditer(options_text))
    
    if matches1:
        for match in matches1:
            option_letter = match.group(1)
            option_text = match.group(2).strip()
            
            # Double-check no answer text is included
            for pattern in explanation_patterns:
                explanation_match = re.search(pattern, option_text, re.IGNORECASE)
                if explanation_match:
                    option_text = option_text[:explanation_match.start()].strip()
            
            options[option_letter] = option_text
    else:
        # Alternative approach: line by line
        lines = options_text.split('\n')
        current_option = None
        current_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if this line starts a new option
            option_match = re.match(r'\s*([A-D])[\.)\s]\s*(.*)', line)
            
            if option_match:
                # Save previous option if any
                if current_option and current_text:
                    options[current_option] = ' '.join(current_text).strip()
                    current_text = []
                
                # Start new option
                current_option = option_match.group(1)
                current_text.append(option_match.group(2))
            elif current_option and current_text:
                # Check if this line contains answer text
                contains_explanation = any(re.search(pattern, line, re.IGNORECASE) for pattern in explanation_patterns)
                if not contains_explanation:
                    current_text.append(line)
                else:
                    # Stop collecting option text once we hit explanation
                    break
        
        # Save last option
        if current_option and current_text:
            options[current_option] = ' '.join(current_text).strip()
    
    return options

def extract_correct_answer(text: str) -> Optional[str]:
    """Find the correct answer in the question text"""
    patterns = [
        r'(?:The|THE)\s+correct\s+answer\s+is\s+([A-D])',
        r'([A-D])\s+is\s+the\s+correct\s+answer',
        r'ANSWER\s*:\s*([A-D])',
        r'Correct answer\s*:\s*([A-D])',
        r'correct answer:\s*([A-D])',
        r'answer\s+is\s+([A-D])'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_things_to_remember(text: str) -> List[str]:
    """Extract 'Things to Remember' section from question text"""
    things_to_remember = []
    
    # Find the 'Things to Remember' section
    patterns = [
        r'Things to Remember:(.*?)(?=$|(?:The correct answer))',
        r'Things to Remember:(.*)',
        r'Things to remember:(.*)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            # Process the content
            content = match.group(1).strip()
            
            # Split into bullet points if present
            if '•' in content:
                bullet_points = content.split('•')
                for point in bullet_points:
                    if point.strip():
                        things_to_remember.append(point.strip())
            else:
                # Otherwise add as a single item or split by newlines
                lines = content.split('\n')
                if len(lines) > 1:
                    for line in lines:
                        if line.strip():
                            things_to_remember.append(line.strip())
                else:
                    things_to_remember.append(content)
            
            break
    
    return things_to_remember

def process_question(question_text: str, q_id: str, idx: int) -> Dict:
    """Process a single question block with improved separation of content"""
    # Clean the text of unwanted elements
    cleaned_text = clean_text(question_text)
    
    # Initialize question components
    main_question = ""
    explanation = ""
    
    # Check for tables in the question
    table_html = extract_table_from_text(cleaned_text)
    
    # Extract options with enhanced separation from explanations
    options = extract_options_advanced(cleaned_text)
    
    # Extract correct answer
    correct_answer = extract_correct_answer(cleaned_text)
    
    # Extract things to remember section
    things_to_remember = extract_things_to_remember(cleaned_text)
    
    # Extract main question - get everything before the first option
    first_option_pos = float('inf')
    for letter in "ABCD":
        patterns = [f"{letter}.", f"{letter})"]
        for pattern in patterns:
            pos = cleaned_text.find(pattern)
            if 0 <= pos < first_option_pos:
                first_option_pos = pos
    
    if first_option_pos < float('inf'):
        main_question = cleaned_text[:first_option_pos].strip()
    else:
        # Fallback: try to extract question by looking for a question mark
        question_parts = cleaned_text.split('?')
        if len(question_parts) > 1:
            main_question = question_parts[0].strip() + '?'
        else:
            # Second fallback: use first non-empty line
            lines = cleaned_text.split('\n')
            for line in lines:
                if line.strip() and not re.match(r'Q\.?\s*\d+\s*$', line):
                    main_question = line.strip()
                    break
    
    # Look for explanations that aren't in "Things to Remember"
    explanation_patterns = [
        r'The correct answer is [A-D].*?(?=Things to Remember:|$)',
        r'Explanation:(.*?)(?=Things to Remember:|$)'
    ]
    
    for pattern in explanation_patterns:
        match = re.search(pattern, cleaned_text, re.DOTALL | re.IGNORECASE)
        if match:
            explanation_text = match.group(0).strip()
            # Remove the "The correct answer is X" part
            explanation_text = re.sub(r'The correct answer is [A-D]\.?\s*', '', explanation_text, flags=re.IGNORECASE)
            explanation = explanation_text.strip()
            break
    
    # Check if question contains mathematical content
    contains_math = (
        re.search(r'[=\+\-\*\/\^\(\)]', main_question) is not None or
        any(re.search(r'[=\+\-\*\/\^\(\)]', opt) for opt in options.values()) or
        re.search(r'\d+\.\d+', main_question) is not None  # Decimal numbers
    )
    
    # Create the question object
    question_obj = {
        'id': int(q_id) if q_id.isdigit() else idx + 1,
        'question': main_question,
        'options': options,
        'correct': correct_answer,
        'explanation': explanation,
        'things_to_remember': things_to_remember,
        'has_table': bool(table_html),
        'table_html': table_html,
        'contains_math': contains_math
    }
    
    return question_obj

def process_pdf(file_path: str) -> Dict:
    """Process PDF with optimizations for performance and accuracy"""
    start_time = time.time()
    
    try:
        doc = fitz.open(file_path)
        
        # Extract text from each page with optimizations
        full_text = ""
        sections = {}
        
        # First pass: extract text and identify sections
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            
            # Clean the text
            cleaned_text = clean_text(text)
            
            # Skip table of contents pages
            if is_table_of_contents(cleaned_text):
                continue
            
            # Add to full text
            full_text += cleaned_text + "\n\n"
        
        # Extract sections/readings
        extracted_sections = extract_sections(full_text)
        if extracted_sections:
            sections = extracted_sections
        
        # Second pass: extract questions
        question_pattern = re.compile(r'Q\.?\s*\d+\s+', re.IGNORECASE)
        matches = list(question_pattern.finditer(full_text))
        questions = []
        
        # Process questions in parallel for better performance
        question_blocks = []
        for i, match in enumerate(matches):
            start_pos = match.start()
            
            # Determine end position (start of next question or end of text)
            if i < len(matches) - 1:
                end_pos = matches[i+1].start()
            else:
                end_pos = len(full_text)
            
            question_text = full_text[start_pos:end_pos]
            q_id_match = re.match(r'Q\.?\s*(\d+)', question_text)
            q_id = q_id_match.group(1) if q_id_match else f"{i+1}"
            
            question_blocks.append((question_text, q_id, i))
        
        # Use a small thread pool to process questions (Vercel has limited resources)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_question, text, q_id, idx) 
                      for text, q_id, idx in question_blocks]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    question = future.result()
                    questions.append(question)
                    
                    # Assign to section if applicable
                    for section_id, section_data in sections.items():
                        if question['question'] in section_data['content']:
                            section_data['questions'].append(question)
                except Exception as e:
                    print(f"Error processing question: {str(e)}")
        
        # Sort questions by ID
        questions.sort(key=lambda q: q.get('id', 0))
        
        # Return questions and sections
        return {
            'questions': questions,
            'sections': [{"name": name, "title": section_data.get('title', ''), "questions": section_data['questions']} 
                         for name, section_data in sections.items()],
            'processing_time': time.time() - start_time,
            'total_questions': len(questions)
        }
        
    except Exception as e:
        print(f"PDF processing error: {str(e)}")
        traceback.print_exc()
        raise Exception(f"Failed to process PDF: {str(e)}")

@app.post("/process")
async def handle_pdf(file: UploadFile = File(...)):
    try:
        print(f"Received file: {file.filename}")
        start_time = time.time()
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        
        # Process the PDF with timeout protection
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(process_pdf, tmp_path),
                timeout=55.0  # Allow 55 seconds max (within Vercel's 60s limit)
            )
        except asyncio.TimeoutError:
            # Clean up
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=408, 
                detail="PDF processing timed out. Please try a smaller PDF file."
            )
        
        # Clean up
        os.unlink(tmp_path)
        
        print(f"Returning {result['total_questions']} questions. Process time: {time.time() - start_time:.2f}s")
        return result
        
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

@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}
