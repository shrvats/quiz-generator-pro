from fastapi import FastAPI, UploadFile, HTTPException, Request, File
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import re
import tempfile
import os
from typing import List, Dict
import asyncio
import traceback

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

def process_pdf(file_path: str) -> List[Dict]:
    try:
        doc = fitz.open(file_path)
        questions = []
        current_q = None
        
        # First, extract all text from the PDF for debugging
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text("text")
            full_text += page_text
            
            # Print first 500 chars of each page for debugging
            print(f"===== PAGE {page_num+1} SAMPLE TEXT =====")
            print(page_text[:500])
            print(f"====================================")
        
        # Print total text length for debugging
        print(f"Total text length: {len(full_text)} characters")
        
        # Look for questions in the entire document
        # Try multiple pattern matching approaches
        
        # Approach 1: Q1, Q2, etc. pattern
        print("Trying Q1/Q2 pattern matching...")
        q_pattern1 = re.compile(r'Q\s*(\d+)[.:]?\s*([^\n]+)', re.MULTILINE)
        matches1 = list(q_pattern1.finditer(full_text))
        print(f"Found {len(matches1)} potential questions with pattern 1")
        
        if matches1:
            for match in matches1:
                q_num = match.group(1)
                q_text = match.group(2).strip()
                print(f"Found Q{q_num}: {q_text[:50]}...")
                
                # Extract the text that follows this question until the next question
                start_pos = match.end()
                next_match = None
                for next_q in matches1:
                    if next_q.start() > start_pos:
                        next_match = next_q
                        break
                
                if next_match:
                    q_content = full_text[start_pos:next_match.start()]
                else:
                    q_content = full_text[start_pos:]
                
                # Now parse the content for options and answers
                options = {}
                correct = ""
                explanation = ""
                
                # Extract options (A, B, C, D)
                opt_pattern = re.compile(r'([A-D])[.)]?\s*([^\n]+)')
                for opt_match in opt_pattern.finditer(q_content):
                    opt_letter = opt_match.group(1)
                    opt_text = opt_match.group(2).strip()
                    options[opt_letter] = opt_text
                
                # Extract correct answer
                if "correct answer:" in q_content.lower():
                    correct_match = re.search(r'correct answer:\s*([^\n]+)', q_content, re.IGNORECASE)
                    if correct_match:
                        correct = correct_match.group(1).strip()
                
                # Extract explanation
                if "things to remember:" in q_content.lower():
                    expl_match = re.search(r'things to remember:\s*([^\n]+)', q_content, re.IGNORECASE)
                    if expl_match:
                        explanation = expl_match.group(1).strip()
                
                # Create question dict
                question = {
                    'id': int(q_num),
                    'question': q_text,
                    'options': options,
                    'correct': correct,
                    'explanation': explanation,
                    'math': [],
                    'tables': []
                }
                
                # Add to questions list
                questions.append(question)
        
        # If no questions found with first approach, try more patterns
        if not questions:
            print("Trying alternative Question/Answer pattern...")
            # Look for "Question 1", "Question 2", etc.
            q_pattern2 = re.compile(r'(?:Question|QUESTION)\s*(\d+)[.:]?\s*([^\n]+)', re.MULTILINE)
            matches2 = list(q_pattern2.finditer(full_text))
            print(f"Found {len(matches2)} potential questions with pattern 2")
            
            # Process similar to above...
            # (pattern 2 processing would be similar to pattern 1)
        
        # If still no questions, try a more general approach
        if not questions:
            print("Using line-by-line approach for question detection...")
            lines = full_text.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                
                # Check if line looks like a question start
                if re.match(r'^(?:Q|Question)\s*\d+', line, re.IGNORECASE):
                    print(f"Potential question found: {line[:50]}...")
                    # Process this question...
                    # (remainder of processing would go here)
        
        # If we still have no questions, try a very broad approach
        if not questions:
            print("WARNING: No questions found with standard patterns, using fallback method")
            # Just try to extract any text that might be a question...
            # This is a last resort approach
            
            # Try with very simple Q1, Q2 pattern
            q_pattern_simple = re.compile(r'Q(\d+)[:\.]?\s*(.*?)(?=Q\d+|$)', re.DOTALL)
            matches_simple = list(q_pattern_simple.finditer(full_text))
            print(f"Simple pattern found {len(matches_simple)} potential questions")
            
            for match in matches_simple:
                q_num = match.group(1)
                q_content = match.group(2).strip()
                
                # Split this into lines
                content_lines = q_content.split('\n')
                if not content_lines:
                    continue
                
                # First line is the question
                q_text = content_lines[0].strip()
                options = {}
                correct = ""
                explanation = ""
                
                # Process remaining lines for options, correct answer, etc.
                for line in content_lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Check for options
                    if opt_match := re.match(r'^([A-D])[.)]?\s*(.*)', line):
                        opt_letter = opt_match.group(1)
                        opt_text = opt_match.group(2).strip()
                        options[opt_letter] = opt_text
                    
                    # Check for correct answer
                    elif "correct answer:" in line.lower():
                        correct = line.split(":", 1)[1].strip()
                    
                    # Check for explanation
                    elif "things to remember:" in line.lower():
                        explanation = line.split(":", 1)[1].strip()
                
                # Create question dict
                question = {
                    'id': int(q_num),
                    'question': q_text,
                    'options': options,
                    'correct': correct,
                    'explanation': explanation,
                    'math': [],
                    'tables': []
                }
                
                # Add to questions list
                questions.append(question)
        
        # Print final question count and sample
        print(f"Final question count: {len(questions)}")
        for i, q in enumerate(questions[:3]):  # Print first 3 questions as sample
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
