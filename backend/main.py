from fastapi import FastAPI, UploadFile, HTTPException, Request, File
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
import asyncio
import traceback
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

def parse_html_table(table_html: str) -> List[List[str]]:
    """Parse HTML table into a 2D array of text"""
    rows = []
    current_row = []
    in_row = False
    in_cell = False
    cell_content = ""
    
    for line in table_html.split('\n'):
        if '<tr>' in line:
            in_row = True
            current_row = []
        elif '</tr>' in line:
            in_row = False
            if current_row:
                rows.append(current_row)
        elif '<td>' in line or '<th>' in line:
            in_cell = True
            cell_content = line.replace('<td>', '').replace('<th>', '').replace('</td>', '').replace('</th>', '').strip()
            if '</td>' in line or '</th>' in line:
                in_cell = False
                current_row.append(cell_content)
        elif '</td>' in line or '</th>' in line:
            in_cell = False
            current_row.append(cell_content)
            cell_content = ""
        elif in_cell:
            cell_content += " " + line.strip()
    
    return rows

def extract_table_from_text(text: str) -> Optional[str]:
    """Try to extract a table from text by looking for patterns of whitespace alignment"""
    lines = text.split('\n')
    
    # Look for lines with multiple consecutive spaces or tab characters
    table_lines = []
    in_table = False
    
    for line in lines:
        # Check if line has multiple spaces or tabs that might indicate a table column
        if re.search(r'\s{3,}', line) or '\t' in line:
            if not in_table:
                in_table = True
            table_lines.append(line)
        elif in_table and line.strip():
            # Still in table if line is not empty
            table_lines.append(line)
        elif in_table:
            # End of table if we were in a table and hit an empty line
            in_table = False
    
    if not table_lines:
        return None
        
    # Convert detected table to HTML
    html = "<table border='1'>\n"
    
    for line in table_lines:
        # Split by multiple spaces or tabs
        cells = re.split(r'\s{2,}|\t+', line.strip())
        cells = [cell.strip() for cell in cells if cell.strip()]
        
        if cells:
            html += "<tr>\n"
            for cell in cells:
                html += f"  <td>{cell}</td>\n"
            html += "</tr>\n"
    
    html += "</table>"
    return html

def process_pdf(file_path: str) -> List[Dict]:
    try:
        doc = fitz.open(file_path)
        questions = []
        
        # Extract full text
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            full_text += text + "\n\n"
        
        # Split text into question blocks
        # Looking for pattern Q.XXXX or Q XXXX at the start of a line
        question_pattern = re.compile(r'Q\.?\s*\d+\s+', re.IGNORECASE)
        
        # Find all matches
        matches = list(question_pattern.finditer(full_text))
        
        # Extract the text for each question
        for i, match in enumerate(matches):
            start_pos = match.start()
            
            # Determine end position (start of next question or end of text)
            if i < len(matches) - 1:
                end_pos = matches[i+1].start()
            else:
                end_pos = len(full_text)
            
            # Extract question text
            question_text = full_text[start_pos:end_pos]
            
            # Extract question ID
            q_id_match = re.match(r'Q\.?\s*(\d+)', question_text)
            q_id = q_id_match.group(1) if q_id_match else f"{i+1}"
            
            print(f"Processing Question {q_id}")
            
            # Try to extract the main question text (everything before options)
            lines = question_text.split('\n')
            main_question = ""
            options = {}
            correct_answer = ""
            explanation = ""
            things_to_remember = []
            
            # Check for tables in the question
            table_html = extract_table_from_text(question_text)
            
            # Process line by line
            in_options = False
            option_lines = []
            current_section = "question"
            
            for j, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                
                # Skip the question ID line if it's alone
                if j == 0 and re.match(r'Q\.?\s*\d+\s*$', line):
                    continue
                
                # Check for option lines (A., B., C., D.)
                if re.match(r'^[A-D]\.\s+', line):
                    in_options = True
                    option_letter = line[0]
                    option_text = line[3:].strip()
                    options[option_letter] = option_text
                    option_lines.append(j)
                    current_section = "options"
                
                # Check for "The correct answer is X" line
                elif "correct answer is" in line.lower():
                    # Extract the letter
                    answer_match = re.search(r'correct answer is ([A-D])', line, re.IGNORECASE)
                    if answer_match:
                        correct_answer = answer_match.group(1)
                    current_section = "answer"
                
                # Check for "Things to Remember" section
                elif "things to remember" in line.lower():
                    current_section = "things_to_remember"
                    # Extract text after "Things to Remember"
                    remember_text = re.sub(r'^.*?things to remember\s*:?\s*', '', line, re.IGNORECASE)
                    if remember_text:
                        things_to_remember.append(remember_text)
                
                # Process line based on current section
                elif current_section == "question" and not in_options:
                    # Before we hit options, this is part of the main question
                    if main_question:
                        main_question += " " + line
                    else:
                        main_question = line
                elif current_section == "things_to_remember":
                    # In the "Things to Remember" section
                    if line.startswith("•"):
                        # Bullet point
                        things_to_remember.append(line[1:].strip())
                    else:
                        # Regular text - append to last item or start new
                        if things_to_remember:
                            things_to_remember[-1] += " " + line
                        else:
                            things_to_remember.append(line)
                elif current_section == "answer" and not line.startswith("The correct answer is"):
                    # After the answer line but before Things to Remember
                    if explanation:
                        explanation += " " + line
                    else:
                        explanation = line
            
            # If we didn't find a main question, use the first non-empty line
            if not main_question:
                for line in lines:
                    if line.strip() and not line.startswith("Q."):
                        main_question = line.strip()
                        break
            
            # Create question object
            question_obj = {
                'id': int(q_id) if q_id.isdigit() else i + 1,
                'question': main_question,
                'options': options,
                'correct': correct_answer,
                'explanation': explanation,
                'things_to_remember': things_to_remember,
                'has_table': bool(table_html),
                'table_html': table_html if table_html else None
            }
            
            questions.append(question_obj)
        
        # Sort questions by ID
        questions.sort(key=lambda q: q.get('id', 0))
        
        # Print summary
        print(f"Extracted {len(questions)} questions")
        for i, q in enumerate(questions[:3]):  # Show first 3
            print(f"Question {i+1}: {q['question'][:50]}...")
            print(f"Options: {list(q['options'].keys())}")
            print(f"Correct: {q['correct']}")
        
        return questions
    except Exception as e:
        print(f"PDF processing error: {str(e)}")
        traceback.print_exc()
        raise Exception(f"Failed to process PDF: {str(e)}")

@app.post("/process")
async def handle_pdf(file: UploadFile = File(...)):
    try:
        print(f"Received file: {file.filename}")
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"Processing file at: {tmp_path}")
        
        # Process the PDF
        result = await asyncio.to_thread(process_pdf, tmp_path)
        
        # Clean up
        os.unlink(tmp_path)
        
        # Output the number of questions found
        print(f"Returning {len(result)} questions to client")
        
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
