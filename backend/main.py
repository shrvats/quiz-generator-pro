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
    """Extract and format tabular data from text, enhanced for mathematical and financial tables"""
    lines = text.split('\n')
    
    # Look for table-like structures - now with stronger patterns for financial tables
    table_lines = []
    in_table = False
    
    # Detect patterns common in financial tables
    financial_patterns = [
        r'\d+\s+\d+\.\d+\s+\d+\.\d+',  # Numbers and decimals in columns
        r'Age\s+\d+',                   # Age columns
        r'Probability\s+of\s+death',    # Probability tables  
        r'Year\s+\d+',                  # Year columns
        r'Rate\s+\d+',                  # Rate tables
        r'\$\s*\d+',                    # Dollar amounts
        r'[Vv]alue\s+[Aa]t',            # Value at... (common in financial tables)
        r'[Ss]urvival probability',     # Survival tables
        r'[Ll]ife expectancy',          # Life expectancy tables
    ]
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            if in_table:
                # Don't break the table for a single empty line if next line looks like a table
                if i+1 < len(lines) and (
                    re.search(r'\s{3,}', lines[i+1].strip()) or
                    '\t' in lines[i+1] or
                    any(re.search(pattern, lines[i+1]) for pattern in financial_patterns)
                ):
                    continue
                else:
                    # Process the table if we have enough data
                    if len(table_lines) >= 2:
                        return convert_to_html_table(table_lines)
                    in_table = False
                    table_lines = []
            continue
        
        # Table indicators: aligned columns, tabs, or specific financial patterns
        if (re.search(r'\s{3,}', stripped) or 
            '\t' in stripped or 
            '|' in stripped or 
            re.search(r'\d+\s+\d+\.\d+', stripped) or
            any(re.search(pattern, stripped) for pattern in financial_patterns)):
            
            if not in_table:
                in_table = True
            table_lines.append(stripped)
        elif in_table:
            # Continue including lines that appear to be part of the table
            table_lines.append(stripped)
    
    # Check for unprocessed table at the end
    if in_table and len(table_lines) >= 2:
        return convert_to_html_table(table_lines)
    
    return None

def convert_to_html_table(table_lines: List[str]) -> str:
    """Convert text lines to HTML table format, improved for mathematical and financial data"""
    html = "<table border='1' class='financial-table'>\n"
    
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
                    if re.match(r'^[\d\.]+$', cell) or re.match(r'^\$\s*[\d\.]+$', cell):
                        # Numeric cell - right align
                        html += f"  <td align='right'>{cell}</td>\n"
                    else:
                        html += f"  <td>{cell}</td>\n"
                html += "</tr>\n"
    else:
        # Try to determine if this is a header row + data or all data
        all_data_rows = True
        for line in table_lines[:2]:  # Check first two rows
            # If it doesn't contain numbers or common financial terms, it might be a header
            if not re.search(r'\d+\.\d+|\d{2,}|[%$]', line) and not all_data_rows:
                all_data_rows = False
        
        if not all_data_rows and len(table_lines) > 1:
            # Process with a header row
            header_line = table_lines[0]
            
            # Detect column boundaries in the header
            # We'll look for multiple spaces as column separators
            header_pattern = re.compile(r'\s{2,}|\t+')
            headers = [h.strip() for h in header_pattern.split(header_line) if h.strip()]
            
            # Add header row
            if headers:
                html += "<tr>\n"
                for header in headers:
                    html += f"  <th>{header}</th>\n"
                html += "</tr>\n"
            
            # Process data rows
            for line in table_lines[1:]:
                # Try to align columns with headers
                if headers and len(headers) > 1:
                    cells = []
                    remaining_text = line
                    
                    # Split using the same pattern as headers
                    cells = [cell.strip() for cell in header_pattern.split(remaining_text) if cell.strip()]
                    
                    # Ensure we have the right number of cells
                    while len(cells) < len(headers):
                        cells.append("")  # Pad with empty cells if needed
                    
                    if len(cells) > len(headers):
                        # Too many cells, combine extras into the last cell
                        cells[len(headers)-1] = " ".join(cells[len(headers)-1:])
                        cells = cells[:len(headers)]
                    
                    # Create table row
                    html += "<tr>\n"
                    for cell in cells:
                        if re.match(r'^[\d\.]+$', cell) or re.match(r'^\$\s*[\d\.]+$', cell):
                            # Numeric cell - right align
                            html += f"  <td align='right'>{cell}</td>\n"
                        else:
                            html += f"  <td>{cell}</td>\n"
                    html += "</tr>\n"
                else:
                    # Fallback: just put the whole line in a row
                    html += "<tr><td>" + line + "</td></tr>\n"
        else:
            # All data - try to split consistently
            first_line = table_lines[0]
            
            # Look for spaces that might be column separators
            possible_cols = []
            for match in re.finditer(r'\s{2,}', first_line):
                possible_cols.append((match.start(), match.end()))
            
            if possible_cols:
                # Process all lines using the same column positions
                for line in table_lines:
                    html += "<tr>\n"
                    last_end = 0
                    
                    # Extract cells based on column positions
                    for start, end in possible_cols:
                        if last_end < len(line):
                            cell = line[last_end:start].strip()
                            if cell:
                                # Check if numeric for alignment
                                if re.match(r'^[\d\.]+$', cell) or re.match(r'^\$\s*[\d\.]+$', cell):
                                    html += f"  <td align='right'>{cell}</td>\n"
                                else:
                                    html += f"  <td>{cell}</td>\n"
                            last_end = end
                    
                    # Last cell
                    if last_end < len(line):
                        cell = line[last_end:].strip()
                        if cell:
                            if re.match(r'^[\d\.]+$', cell) or re.match(r'^\$\s*[\d\.]+$', cell):
                                html += f"  <td align='right'>{cell}</td>\n"
                            else:
                                html += f"  <td>{cell}</td>\n"
                    
                    html += "</tr>\n"
            else:
                # No clear columns, use line-by-line approach
                for line in table_lines:
                    html += "<tr><td>" + line + "</td></tr>\n"
    
    html += "</table>"
    return html

def extract_options_advanced(question_text: str) -> Dict[str, str]:
    """Extract options from question text, with robust handling for mathematical and fewer options"""
    options = {}
    
    # First, try to detect where the options section ends
    explanation_patterns = [
        r'The correct answer is [A-D]',
        r'Correct answer: [A-D]',
        r'ANSWER\s*:',
        r'Things to Remember',
        r'Explanation:',
        r'Thus,',  # Common in mathematical explanations
        r'Therefore,'  # Common in mathematical explanations
    ]
    
    # Find the earliest occurrence of an explanation pattern
    earliest_explanation_pos = len(question_text)
    for pattern in explanation_patterns:
        match = re.search(pattern, question_text, re.IGNORECASE)
        if match and match.start() < earliest_explanation_pos:
            earliest_explanation_pos = match.start()
    
    # Extract only the part before explanations for option parsing
    options_text = question_text[:earliest_explanation_pos]
    
    # Try multiple pattern matching approaches for options
    
    # Approach 1: Extract options with standard patterns
    option_patterns = [
        r'([A-D])[\.\)]\s+(.*?)(?=(?:[A-D][\.\)])|\Z)',  # A. text or A) text
        r'([A-D])\s+(.*?)(?=(?:[A-D]\s+)|\Z)',           # A text
    ]
    
    options_found = False
    for pattern in option_patterns:
        matches = list(re.finditer(pattern, options_text, re.DOTALL))
        
        if matches:
            options_found = True
            for match in matches:
                option_letter = match.group(1)
                option_text = match.group(2).strip()
                
                # Double-check no explanation is included
                for exp_pattern in explanation_patterns:
                    exp_match = re.search(exp_pattern, option_text, re.IGNORECASE)
                    if exp_match:
                        option_text = option_text[:exp_match.start()].strip()
                
                options[option_letter] = option_text
            break  # Stop if we found options with this pattern
    
    # Approach 2: Line-by-line extraction if approach 1 failed
    if not options_found:
        lines = options_text.split('\n')
        current_option = None
        current_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Try different option patterns
            option_match = None
            for pattern in [
                r'\s*([A-D])[\.)\s]\s*(.*)',  # A. text, A) text, A text
                r'\s*([A-D])\s*$'              # Just the option letter on a line
            ]:
                match = re.match(pattern, line)
                if match:
                    option_match = match
                    break
            
            if option_match:
                # Save previous option if any
                if current_option and current_text:
                    options[current_option] = ' '.join(current_text).strip()
                    current_text = []
                
                # Start new option
                current_option = option_match.group(1)
                # Sometimes a line has just the option letter
                if len(option_match.groups()) > 1 and option_match.group(2):
                    current_text.append(option_match.group(2))
            elif current_option is not None:
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
    
    # Approach 3: For financial/mathematical questions with numerical options
    if not options and re.search(r'\d+\.\d+', options_text):
        # Look for lines with decimal numbers that might be options
        lines = options_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Look for option patterns in this line
            for letter in 'ABCD':
                for pattern in [f"{letter}\\.", f"{letter}\\)", f"{letter}\\s"]:
                    if re.match(f"\\s*{pattern}", line):
                        # Extract text from this line and possibly next lines
                        option_text = line.split(f"{letter}.", 1)[-1].split(f"{letter})", 1)[-1].strip()
                        if not option_text and len(line) > 2:
                            option_text = line[2:].strip()
                        
                        # Look ahead for multi-line options
                        next_idx = i + 1
                        while next_idx < len(lines) and not any(re.match(f"\\s*[A-D][\\.)\\s]", lines[next_idx]) for letter in 'ABCD'):
                            if lines[next_idx].strip():
                                option_text += " " + lines[next_idx].strip()
                            next_idx += 1
                        
                        if option_text:
                            options[letter] = option_text
    
    # If we still have no options, try a more aggressive approach
    if not options:
        # Just look for lines with A, B, C, D at the beginning
        lines = options_text.split('\n')
        
        for line in lines:
            line = line.strip()
            for letter in 'ABCD':
                if line.startswith(letter) and (len(line) == 1 or line[1] in ['.', ')', ' ']):
                    option_text = line[2:].strip() if len(line) > 2 else ""
                    options[letter] = option_text
    
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

def has_mathematical_content(text: str) -> bool:
    """Check if text contains mathematical or Greek symbols, formulas, etc."""
    # Patterns for mathematical content
    math_patterns = [
        r'[=\+\-\*\/\^\(\)]',  # Basic math operators
        r'\d+\.\d+',            # Decimal numbers
        r'[αβγδεζηθικλμνξοπρστυφχψω]',  # Greek letters lowercase
        r'[ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ]',  # Greek letters uppercase
        r'√|∑|∫|∂|∇|∞|∝|≈|≠|≤|≥',  # Math symbols
        r'\$\d+',               # Dollar amounts
        r'\d+%',                # Percentages
        r'e\^',                 # Exponential
        r'log',                 # Logarithm
        r'sin|cos|tan',         # Trigonometric functions
        r'var|std|prob',        # Statistical terms
        r'(\b[A-Z]\b.*?){2,}',  # Variables (single letters)
    ]
    
    for pattern in math_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False

def process_question(question_text: str, q_id: str, idx: int) -> Dict:
    """Process a single question block with enhanced handling for mathematical and tabular content"""
    # Clean the text of unwanted elements
    cleaned_text = clean_text(question_text)
    
    # Initialize question components
    main_question = ""
    explanation = ""
    
    # Check for mathematical content early
    contains_math = has_mathematical_content(cleaned_text)
    
    # Check for tables in the question - enhanced for financial tables
    table_html = extract_table_from_text(cleaned_text)
    
    # Extract options with enhanced handling for mathematical notation
    options = extract_options_advanced(cleaned_text)
    
    # Extract correct answer
    correct_answer = extract_correct_answer(cleaned_text)
    
    # Extract things to remember section
    things_to_remember = extract_things_to_remember(cleaned_text)
    
    # Extract main question
    # For mathematical questions, we need to be more careful about where the question ends
    first_option_pos = float('inf')
    
    # Look for option indicators to find where the question ends
    for letter in "ABCD":
        for pattern in [f"{letter}.", f"{letter})", f" {letter} "]:
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
            # Second fallback: look for lines that appear to be the question
            lines = cleaned_text.split('\n')
            for i, line in enumerate(lines):
                if line.strip() and not re.match(r'Q\.?\s*\d+\s*$', line):
                    # Found first non-empty, non-question number line
                    main_question = line.strip()
                    
                    # Include additional lines if they seem to be part of the question
                    next_idx = i + 1
                    while (next_idx < len(lines) and 
                           not any(re.match(f"\\s*[A-D][\\.)\\s]", lines[next_idx]) for letter in 'ABCD') and
                           not any(re.search(pattern, lines[next_idx]) for pattern in [
                               r'The correct answer is', r'Correct answer:', r'ANSWER'
                           ])):
                        if lines[next_idx].strip():
                            main_question += " " + lines[next_idx].strip()
                        next_idx += 1
                    
                    break
    
    # Check if there's a calculation part to include in the question
    calculation_keywords = [
        r'[Cc]alculate',
        r'[Ff]ind',
        r'[Dd]etermine',
        r'[Cc]ompute',
        r'[Ee]stimate'
    ]
    
    for keyword in calculation_keywords:
        calc_match = re.search(keyword, cleaned_text, re.IGNORECASE)
        if calc_match and calc_match.start() not in [m.start() for m in re.finditer(keyword, main_question, re.IGNORECASE)]:
            # There's a calculation instruction not already in the main question
            calc_part = cleaned_text[calc_match.start():]
            # Find where this calculation part ends (at first option or explanation)
            end_pos = float('inf')
            for letter in "ABCD":
                for pattern in [f"{letter}.", f"{letter})", f" {letter} "]:
                    pos = calc_part.find(pattern)
                    if 0 <= pos < end_pos:
                        end_pos = pos
            
            for pattern in [r'The correct answer is', r'Correct answer:', r'ANSWER']:
                pos = calc_part.find(pattern)
                if 0 <= pos < end_pos:
                    end_pos = pos
            
            if end_pos < float('inf'):
                calc_part = calc_part[:end_pos].strip()
            
            main_question += " " + calc_part
    
    # Look for explanations that aren't in "Things to Remember"
    explanation_patterns = [
        r'The correct answer is [A-D].*?(?=Things to Remember:|$)',
        r'Explanation:(.*?)(?=Things to Remember:|$)',
        r'Thus,(.*?)(?=Things to Remember:|$)',
        r'Therefore,(.*?)(?=Things to Remember:|$)'
    ]
    
    for pattern in explanation_patterns:
        match = re.search(pattern, cleaned_text, re.DOTALL | re.IGNORECASE)
        if match:
            explanation_text = match.group(0).strip()
            # Remove the "The correct answer is X" part
            explanation_text = re.sub(r'The correct answer is [A-D]\.?\s*', '', explanation_text, flags=re.IGNORECASE)
            explanation = explanation_text.strip()
            break
    
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
    """Process PDF with optimizations for financial, mathematical and tabular content"""
    start_time = time.time()
    
    try:
        doc = fitz.open(file_path)
        
        # Optimize for speed: extract text all at once rather than page by page
        full_text = ""
        sections = {}
        toc_pages = set()
        
        # First quick pass: identify TOC pages and extract sections
        for page_num in range(min(len(doc), 10)):  # Check first 10 pages for TOC
            page = doc[page_num]
            text = page.get_text("text")
            
            if is_table_of_contents(text):
                toc_pages.add(page_num)
        
        # Extract all text (skipping TOC pages)
        for page_num in range(len(doc)):
            if page_num in toc_pages:
                continue
                
            page = doc[page_num]
            text = page.get_text("text")
            
            # Clean the text
            cleaned_text = clean_text(text)
            full_text += cleaned_text + "\n\n"
        
        # Extract sections/readings
        extracted_sections = extract_sections(full_text)
        if extracted_sections:
            sections = extracted_sections
        
        # Extract questions with more robust pattern matching
        question_patterns = [
            r'Q\.?\s*\d+\s+',  # Standard Q.XX format
            r'Question\s+\d+',  # "Question XX" format
            r'\n\d+\.\s+'       # Numbered list format
        ]
        
        all_matches = []
        
        for pattern in question_patterns:
            matches = list(re.finditer(pattern, full_text, re.IGNORECASE))
            if matches:
                # Store pattern used for later use
                all_matches.extend([(match, pattern) for match in matches])
        
        # Sort matches by position in text
        all_matches.sort(key=lambda x: x[0].start())
        
        # Process questions efficiently
        questions = []
        question_blocks = []
        
        if all_matches:
            for i, (match, pattern) in enumerate(all_matches):
                start_pos = match.start()
                
                # Determine end position (start of next question or end of text)
                if i < len(all_matches) - 1:
                    end_pos = all_matches[i+1][0].start()
                else:
                    end_pos = len(full_text)
                
                question_text = full_text[start_pos:end_pos]
                
                # Extract question ID based on pattern used
                q_id = ""
                if 'Q' in pattern:
                    q_id_match = re.match(r'Q\.?\s*(\d+)', question_text)
                    q_id = q_id_match.group(1) if q_id_match else f"{i+1}"
                elif 'Question' in pattern:
                    q_id_match = re.match(r'Question\s+(\d+)', question_text)
                    q_id = q_id_match.group(1) if q_id_match else f"{i+1}"
                else:
                    q_id_match = re.match(r'\n(\d+)\.', question_text)
                    q_id = q_id_match.group(1) if q_id_match else f"{i+1}"
                
                question_blocks.append((question_text, q_id, i))
        
        # Use a smaller thread pool to stay within Vercel limits
        max_workers = min(4, len(question_blocks))  # Don't create more threads than questions
        
        if max_workers > 0:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit questions for processing, but with a maximum batch size
                batch_size = 10  # Process in batches to reduce memory usage
                
                for batch_start in range(0, len(question_blocks), batch_size):
                    batch_end = min(batch_start + batch_size, len(question_blocks))
                    batch = question_blocks[batch_start:batch_end]
                    
                    futures = [executor.submit(process_question, text, q_id, idx) 
                              for text, q_id, idx in batch]
                    
                    # Wait for this batch to complete
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            question = future.result()
                            questions.append(question)
                            
                            # Check for timeout
                            if time.time() - start_time > 50:  # 50-second safety limit
                                print("Approaching time limit, stopping processing")
                                break
                        except Exception as e:
                            print(f"Error processing question: {str(e)}")
                    
                    # Check for timeout after each batch
                    if time.time() - start_time > 50:  # 50-second safety limit
                        break
        
        # Sort questions by ID to ensure correct order
        questions.sort(key=lambda q: q.get('id', 0))
        
        # Assign questions to sections if applicable
        if sections:
            for question in questions:
                for section_id, section_data in sections.items():
                    if question['question'] in section_data['content']:
                        section_data['questions'].append(question)
        
        # Validate all questions
        valid_questions = []
        for q in questions:
            # Only keep questions with a reasonable amount of content
            if len(q['question']) > 10 and (q['options'] or q['has_table']):
                valid_questions.append(q)
        
        # Return processed data
        return {
            'questions': valid_questions,
            'sections': [{"name": name, "title": section_data.get('title', ''), "questions": section_data['questions']} 
                         for name, section_data in sections.items()],
            'processing_time': time.time() - start_time,
            'total_questions': len(valid_questions)
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
