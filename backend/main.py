#!/usr/bin/env python3
"""
PDF Quiz Parser - Production-level implementation
A robust PDF parsing system to extract quiz questions from various PDF formats with 
enhanced math formula and table support.
"""

import re
import os
import sys
import time
import json
import uuid
import hashlib
import logging
import tempfile
import traceback
from enum import Enum, auto
from typing import List, Dict, Tuple, Optional, Any, Union, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter
import asyncio
from concurrent.futures import ThreadPoolExecutor

import fitz  # PyMuPDF
import pandas as pd
import numpy as np
from fastapi import FastAPI, UploadFile, HTTPException, Request, File, Form, BackgroundTasks, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

# Optional OCR support
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("quiz_parser.log")]
)
logger = logging.getLogger("quiz-pdf-parser")

# Constants
MAX_PROCESSING_TIME = 120  # seconds
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 55  # seconds
MIN_QUESTION_LENGTH = 10
MAX_PDF_SIZE_MB = 100
CACHE_EXPIRY = 3600
MATH_PATTERN = r'(?:\$.*?\$)|(?:\\begin\{equation\}.*?\\end\{equation\})|(?:[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞|\b[A-Za-z]\s*=)'

###############################
# Data Models and Structures  #
###############################

class QuestionType(Enum):
    MULTIPLE_CHOICE = auto()
    TRUE_FALSE = auto()
    FILL_IN_BLANK = auto()
    MATCHING = auto()
    CALCULATION = auto()
    ESSAY = auto()
    UNKNOWN = auto()

class ParsingMethod(Enum):
    TEXT_BASED = auto()
    BLOCK_BASED = auto()
    HYBRID = auto()
    OCR = auto()

@dataclass
class Option:
    """Represents an answer option for a question"""
    letter: str
    text: str
    is_correct: bool = False
    explanation: str = ""

@dataclass
class Question:
    """Flexible question model that handles diverse content types"""
    id: str
    text: str = ""
    options: Dict[str, str] = field(default_factory=dict)
    correct_answer: Optional[str] = None
    explanation: str = ""
    option_explanations: Dict[str, str] = field(default_factory=dict)
    things_to_remember: str = ""
    table_html: str = ""
    has_table: bool = False
    contains_math: bool = False
    math_expressions: List[str] = field(default_factory=list)
    validation_issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert question to dictionary for API response"""
        result = {
            "id": self.id,
            "question": self.text,
            "options": self.options,
            "correct": self.correct_answer,
            "explanation": self.explanation,
            "option_explanations": self.option_explanations,
            "things_to_remember": self.things_to_remember
        }
        
        if self.has_table:
            result["has_table"] = True
            result["table_html"] = self.table_html
            
        if self.contains_math:
            result["contains_math"] = True
            result["math_expressions"] = self.math_expressions
            
        if self.validation_issues:
            result["validation_issues"] = self.validation_issues
            
        return result

class ProcessingStats:
    """Stats about the PDF processing job"""
    def __init__(self):
        self.start_time = time.time()
        self.total_pages = 0
        self.processed_pages = 0
        self.questions_found = 0
        self.tables_found = 0
        self.math_found = 0
        self.images_found = 0
        self.errors = []
        self.warnings = []
        self.ocr_used = False
        
    def elapsed_time(self) -> float:
        return time.time() - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "elapsed_time": self.elapsed_time(),
            "total_pages": self.total_pages,
            "processed_pages": self.processed_pages,
            "questions_found": self.questions_found,
            "tables_found": self.tables_found,
            "math_found": self.math_found,
            "errors": self.errors,
            "warnings": self.warnings,
            "ocr_used": self.ocr_used
        }

class ProcessingResult:
    """Contains the result of processing a PDF"""
    def __init__(self, questions=None, total_pages=0, error=None):
        self.questions = questions or []
        self.total_pages = total_pages
        self.error = error
        self.stats = ProcessingStats()
        
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "questions": [q.to_dict() for q in self.questions],
            "total_questions": len(self.questions),
            "total_pages": self.total_pages,
            "stats": self.stats.to_dict()
        }
        if self.error:
            result["error"] = str(self.error)
        return result

class PDFInfoResponse(BaseModel):
    total_pages: int
    file_size_mb: float
    metadata: Dict[str, str]
    estimated_questions: int = 0
    has_toc: bool = False

class ProcessingStatus(BaseModel):
    request_id: str
    status: str
    progress: float
    message: str
    timestamp: float = Field(default_factory=time.time)

###################################
#     PDF Processing Core         #
###################################

class MathExtractor:
    """Extract and format mathematical expressions"""
    
    @staticmethod
    def extract_math(text: str) -> List[str]:
        """Extract math expressions from text"""
        expressions = []
        
        # Extract LaTeX-style math expressions
        latex_patterns = [
            r'\$\$.+?\$\$',  # Display math
            r'\$.+?\$',  # Inline math
            r'\\begin\{equation\}.+?\\end\{equation\}',  # Equation environment
            r'\\begin\{align\}.+?\\end\{align\}'  # Align environment
        ]
        
        for pattern in latex_patterns:
            matches = re.finditer(pattern, text, re.DOTALL)
            for match in matches:
                expressions.append(match.group(0))
        
        # Look for other math expressions
        math_symbols = r'[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞'
        var_assign = r'\b[A-Za-z]\s*='
        
        # Find sequences with multiple math symbols
        text_without_latex = text
        for expr in expressions:
            text_without_latex = text_without_latex.replace(expr, " ")
        
        words = text_without_latex.split()
        for word in words:
            if (len(re.findall(math_symbols, word)) > 1 or
                re.search(var_assign, word)):
                if word not in expressions:
                    expressions.append(word)
        
        return expressions

class OCRProcessor:
    """Process PDF content with OCR when needed"""
    
    @staticmethod
    def is_available() -> bool:
        return OCR_AVAILABLE
    
    @staticmethod
    def process_page(page) -> str:
        """Process a page with OCR"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            return pytesseract.image_to_string(img, lang='eng')
        except Exception as e:
            logger.error(f"OCR error: {str(e)}")
            return ""

class PDFTextCleaner:
    """Clean text extracted from PDFs"""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Remove common PDF artifacts from text"""
        # Remove copyright notices
        text = re.sub(r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        
        # Remove page numbers
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
        text = re.sub(r'^[ \t]*\d+[ \t]*$', '', text, flags=re.MULTILINE)
        
        # Clean up whitespace
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n+', '\n', text)
        
        return text.strip()
    
    @staticmethod
    def extract_options(text: str) -> Dict[str, str]:
        """Extract answer options from text"""
        options = {}
        
        # Try pattern with newlines between options
        option_pattern = r'\n\s*([A-F])[\.\)]\s+(.*?)(?=\n\s*[A-F][\.\)]|\Z)'
        option_matches = list(re.finditer(option_pattern, text, re.DOTALL))
        
        for match in option_matches:
            letter = match.group(1)
            option_text = match.group(2).strip()
            # Clean up option text
            option_text = re.sub(r'(?:is correct|correct answer|is incorrect).*', '', option_text, flags=re.IGNORECASE)
            options[letter] = option_text.strip()
        
        # If no options found, try alternative pattern
        if not options:
            alt_pattern = r'([A-F])[\.\)]\s*(.*?)(?=\s*[A-F][\.\)]|\Z)'
            alt_matches = list(re.finditer(alt_pattern, text, re.DOTALL))
            
            for match in alt_matches:
                letter = match.group(1)
                option_text = match.group(2).strip()
                option_text = re.sub(r'(?:is correct|correct answer|is incorrect).*', '', option_text, flags=re.IGNORECASE)
                options[letter] = option_text.strip()
        
        return options
    
    @staticmethod
    def extract_correct_answer(text: str) -> Tuple[str, Optional[str]]:
        """Extract correct answer from text"""
        correct_answer = None
        patterns = [
            r'The correct answer is\s*([A-F])\..*?(?=\n|$)',
            r'Correct answer[:\s]+([A-F])\.?.*?(?=\n|$)',
            r'The answer is\s*([A-F])\.?.*?(?=\n|$)',
            r'Answer[:\s]+([A-F])\.?.*?(?=\n|$)',
            r'The correct choice is\s*([A-F])\.?.*?(?=\n|$)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                correct_answer = match.group(1)
                text = text[:match.start()] + text[match.end():]
                break
                
        return text, correct_answer
    
    @staticmethod
    def extract_option_explanations(text: str) -> Dict[str, str]:
        """Extract explanations for individual options"""
        explanations = {}
        
        patterns = [
            r'([A-F])\s+is\s+(?:correct|incorrect)[\.:]?\s+(.*?)(?=(?:[A-F]\s+is\s+(?:correct|incorrect))|$)',
            r'Option\s+([A-F])[:\.\)]\s+(.*?)(?=(?:Option\s+[A-F])|$)',
            r'([A-F])\s+is\s+(?:the\s+)?(?:correct|incorrect)\s+(?:choice|option|answer)[\.:]?\s+(.*?)(?=(?:[A-F]\s+is)|$)'
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                letter = match.group(1).upper()
                explanation = match.group(2).strip()
                if explanation:
                    explanations[letter] = explanation
        
        return explanations
    
    @staticmethod
    def extract_things_to_remember(text: str) -> Tuple[str, str]:
        """Extract 'Things to Remember' section"""
        things_to_remember = ""
        
        patterns = [
            r'Things to Remember[:\s]*\n(.+)$',
            r'Things to Remember[:\s]+(.*?)(?=\n\n|\Z)',
            r'Remember[:\s]+(.*?)(?=\n\n|\Z)',
            r'Note[:\s]+(.*?)(?=\n\n|\Z)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                things_to_remember = match.group(1).strip()
                text = text[:match.start()] + text[match.end():]
                break
                
        return text, things_to_remember
    
    @staticmethod
    def extract_explanation(text: str) -> Tuple[str, str]:
        """Extract explanation section"""
        explanation = ""
        
        patterns = [
            r'Explanation[:\s]+(.*?)(?=\n\n|\Z)',
            r'Therefore[:\s]+(.*?)(?=\n\n|\Z)',
            r'Thus[:\s]+(.*?)(?=\n\n|\Z)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                explanation = match.group(1).strip()
                text = text[:match.start()] + text[match.end():]
                break
                
        return text, explanation

class TableExtractor:
    """Extract tables from PDF content"""
    
    @staticmethod
    def extract_table_html(blocks) -> str:
        """Generate HTML table from text blocks"""
        if not blocks:
            return ""
        
        rows = []
        for block in blocks:
            if 'spans' not in block:
                continue
                
            spans_by_y = defaultdict(list)
            for span in block.get('spans', []):
                y_key = round(span.get('bbox', [0, 0, 0, 0])[1])  # y0 coordinate
                spans_by_y[y_key].append(span)
                
            sorted_y = sorted(spans_by_y.keys())
            for y in sorted_y:
                row = [span.get('text', '').strip() for span in 
                       sorted(spans_by_y[y], key=lambda s: s.get('bbox', [0, 0, 0, 0])[0])]
                if row:
                    rows.append(row)
        
        if not rows:
            return ""
            
        # Generate HTML table
        html = ["<table class='quiz-table' border='1'>"]
        
        # If first row might be header
        if rows and any(cell.isupper() for cell in rows[0]):
            html.append("<thead>")
            html.append("<tr>")
            for cell in rows[0]:
                html.append(f"<th>{cell}</th>")
            html.append("</tr>")
            html.append("</thead>")
            rows = rows[1:]
        
        # Table body
        html.append("<tbody>")
        for row in rows:
            html.append("<tr>")
            for cell in row:
                align = " align='right'" if re.match(r'^[\d\.\$]+$', cell) else ""
                html.append(f"<td{align}>{cell}</td>")
            html.append("</tr>")
        html.append("</tbody>")
        html.append("</table>")
        
        return "\n".join(html)

class QuizGenerator:
    """Extract quiz questions from PDFs"""
    
    def __init__(self, method: ParsingMethod = ParsingMethod.HYBRID):
        self.method = method
        self.cleaner = PDFTextCleaner()
        self.math_extractor = MathExtractor()
        self.table_extractor = TableExtractor()
        self.stats = ProcessingStats()
    
    def extract_questions(self, doc, page_range=None) -> List[Question]:
        """Main method to extract questions from PDF"""
        self.stats = ProcessingStats()
        self.stats.total_pages = len(doc)
        
        # Determine page range
        if page_range:
            start_page, end_page = page_range
            start_page = max(0, start_page)
            end_page = min(len(doc) - 1, end_page)
            page_iterator = range(start_page, end_page + 1)
        else:
            page_iterator = range(len(doc))
            
        self.stats.processed_pages = len(page_iterator)
        
        # Check if OCR might be needed
        needs_ocr = self._check_if_ocr_needed(doc, page_iterator)
        
        # Extract text
        all_text = self._extract_text(doc, page_iterator, use_ocr=needs_ocr)
        
        # Find question boundaries
        question_blocks = self._split_into_questions(all_text)
        self.stats.questions_found = len(question_blocks)
        
        # Process each question
        questions = []
        for i, question_text in enumerate(question_blocks):
            try:
                q_id = self._extract_question_id(question_text) or str(i + 1)
                question = self._process_question(question_text, q_id)
                if question:
                    questions.append(question)
            except Exception as e:
                logger.error(f"Error processing question {i+1}: {str(e)}")
                logger.error(traceback.format_exc())
                self.stats.errors.append(f"Error processing question {i+1}: {str(e)}")
        
        return questions
    
    def _check_if_ocr_needed(self, doc, page_iterator) -> bool:
        """Check if OCR might be needed by sampling text extraction"""
        for i in range(min(3, len(page_iterator))):
            page_idx = page_iterator[i]
            page = doc[page_idx]
            text = page.get_text("text")
            if len(text.strip()) < 50:  # Not enough text
                if OCRProcessor.is_available():
                    self.stats.ocr_used = True
                    return True
        return False
    
    def _extract_text(self, doc, page_iterator, use_ocr=False) -> str:
        """Extract text from PDF pages"""
        all_text = ""
        for page_num in page_iterator:
            page = doc[page_num]
            page_text = page.get_text("text")
            
            # Use OCR if needed and available
            if use_ocr and len(page_text.strip()) < 50:
                page_text = OCRProcessor.process_page(page)
            
            all_text += page_text + "\n"
        
        return all_text
    
    def _split_into_questions(self, text: str) -> List[str]:
        """Split text into individual questions"""
        # Try to find question markers
        question_pattern = r'(?:Question\s+(\d+)(?:\(Q\.\d+\))?|Q\.?\s*(\d+)(?:\(Q\.\d+\))?)'
        question_matches = list(re.finditer(question_pattern, text))
        
        if not question_matches:
            # Try alternative pattern
            alternate_pattern = r'\n\s*(\d+)[\.\)]\s+'
            question_matches = list(re.finditer(alternate_pattern, text))
            
            if not question_matches:
                return self._split_by_options(text)
        
        # Split text at question markers
        questions = []
        for i, match in enumerate(question_matches):
            start_pos = match.start()
            if i < len(question_matches) - 1:
                end_pos = question_matches[i+1].start()
            else:
                end_pos = len(text)
            
            question_text = text[start_pos:end_pos]
            questions.append(question_text)
        
        return questions
    
    def _split_by_options(self, text: str) -> List[str]:
        """Alternative method to split text when no clear question markers"""
        # Look for option patterns (A. B. C. D. sequence)
        option_pattern = r'\n\s*A[\.\)]\s+.*?\n\s*B[\.\)]\s+'
        option_matches = list(re.finditer(option_pattern, text, re.DOTALL))
        
        if not option_matches:
            # If no clear splitting is possible, return the whole text as one question
            self.stats.warnings.append("Could not identify question boundaries")
            return [text]
        
        questions = []
        prev_end = 0
        
        for i, match in enumerate(option_matches):
            # Look backward for start of this question
            start_pos = text.rfind('\n', 0, match.start())
            if start_pos == -1:
                start_pos = 0
            else:
                start_pos += 1  # Skip the newline
            
            # Adjust if too close to previous question
            if start_pos < prev_end:
                start_pos = prev_end
            
            # Find next option block or end of text
            if i < len(option_matches) - 1:
                next_match = option_matches[i+1]
                end_pos = next_match.start()
            else:
                end_pos = len(text)
            
            question_text = text[start_pos:end_pos].strip()
            if question_text:
                questions.append(question_text)
            prev_end = end_pos
        
        return questions
    
    def _extract_question_id(self, text: str) -> Optional[str]:
        """Extract question ID from text"""
        patterns = [
            r'Question\s+(\d+)',
            r'Q\.?\s*(\d+)',
            r'^(\d+)[\.\)]'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _process_question(self, text: str, q_id: str) -> Optional[Question]:
        """Process question text into structured Question object"""
        # Clean the text
        text = self.cleaner.clean_text(text)
        
        # Remove question prefix
        text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.?\s*\d+(?:\(Q\.\d+\))?)\s*', '', text)
        
        # Extract correct answer
        text, correct_answer = self.cleaner.extract_correct_answer(text)
        
        # Extract "Things to Remember"
        text, things_to_remember = self.cleaner.extract_things_to_remember(text)
        
        # Extract explanation
        text, explanation = self.cleaner.extract_explanation(text)
        
        # Extract options
        options_dict = self.cleaner.extract_options(text)
        
        # Extract option-specific explanations
        option_explanations = {}
        if explanation:
            option_explanations = self.cleaner.extract_option_explanations(explanation)
        
        # Extract mathematical expressions
        math_expressions = []
        contains_math = bool(re.search(MATH_PATTERN, text))
        if contains_math:
            math_expressions = self.math_extractor.extract_math(text)
            self.stats.math_found += len(math_expressions)
        
        # The remaining text is the question statement
        question_text = text.strip()
        if len(question_text) < MIN_QUESTION_LENGTH:
            return None
        
        # Create Question object
        question = Question(
            id=q_id,
            text=question_text,
            options=options_dict,
            correct_answer=correct_answer,
            explanation=explanation,
            option_explanations=option_explanations,
            things_to_remember=things_to_remember,
            contains_math=contains_math,
            math_expressions=math_expressions
        )
        
        # Check for validation issues
        validation_issues = self._validate_question(question)
        if validation_issues:
            question.validation_issues = validation_issues
        
        return question
    
    def _validate_question(self, question: Question) -> List[str]:
        """Validate a question for potential issues"""
        issues = []
        
        if not question.text.strip():
            issues.append("Question text is empty")
        
        if question.options and len(question.options) < 2:
            issues.append(f"Question has only {len(question.options)} options")
        
        if question.correct_answer and question.options:
            if question.correct_answer not in question.options:
                issues.append(f"Correct answer '{question.correct_answer}' not in options")
        
        for letter, text in question.options.items():
            if len(text) < 5:
                issues.append(f"Option {letter} is too short: '{text}'")
        
        return issues

class PDFProcessor:
    """Main class for processing PDF files"""
    
    def __init__(self, file_path: str, page_range: Optional[Tuple[int, int]] = None):
        self.file_path = file_path
        self.page_range = page_range
        self.doc = None
        self.extractor = QuizGenerator()
        self.result = ProcessingResult()
        self.process_id = str(uuid.uuid4())[:8]
    
    def process(self) -> Dict[str, Any]:
        """Process PDF file and extract questions"""
        logger.info(f"Processing PDF {self.file_path} (ID: {self.process_id})")
        
        try:
            self.doc = fitz.open(self.file_path)
            self.result.total_pages = len(self.doc)
            
            questions = self.extractor.extract_questions(self.doc, self.page_range)
            self.result.questions = questions
            self.result.stats = self.extractor.stats
            
            logger.info(f"Processed PDF {self.file_path}: Found {len(questions)} questions")
            return self.result.to_dict()
        
        except Exception as e:
            logger.error(f"Error processing PDF {self.file_path}: {str(e)}")
            logger.error(traceback.format_exc())
            self.result.error = str(e)
            return self.result.to_dict()
        
        finally:
            if self.doc:
                self.doc.close()

###############################
#     API Implementation      #
###############################

app = FastAPI(
    title="PDF Quiz Parser API",
    description="API for extracting quiz questions from PDF documents",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store processing status
processing_status = {}

def update_processing_status(request_id: str, status: str, progress: float, message: str):
    """Update the processing status for a request"""
    processing_status[request_id] = {
        "request_id": request_id,
        "status": status,
        "progress": progress,
        "message": message,
        "timestamp": time.time()
    }
    
    # Clean up old entries
    current_time = time.time()
    keys_to_remove = [k for k, v in processing_status.items() 
                     if current_time - v["timestamp"] > CACHE_EXPIRY]
    for key in keys_to_remove:
        processing_status.pop(key, None)

async def process_pdf_task(file_path: str, request_id: str, page_range=None):
    """Background task for PDF processing"""
    try:
        update_processing_status(request_id, "processing", 0.1, "Starting PDF processing")
        processor = PDFProcessor(file_path, page_range)
        
        with ThreadPoolExecutor() as executor:
            result = await asyncio.get_event_loop().run_in_executor(executor, processor.process)
            
        update_processing_status(
            request_id, 
            "completed", 
            1.0, 
            f"Completed processing. Found {result.get('total_questions', 0)} questions"
        )
        return result
    
    except Exception as e:
        update_processing_status(request_id, "error", 0, f"Error: {str(e)}")
        logger.error(f"Error in background processing: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": str(e), "questions": [], "total_pages": 0}
    
    finally:
        # Clean up temp file
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.error(f"Error cleaning up temp file: {str(e)}")

@app.post("/process")
async def handle_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    start_page: Optional[int] = Form(None),
    end_page: Optional[int] = Form(None),
    async_process: bool = Form(False)
):
    """Process a PDF file to extract quiz questions"""
    request_id = str(uuid.uuid4())
    logger.info(f"Request {request_id}: Processing file {file.filename}")
    
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")
        
        # Save the uploaded file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            file_size_mb = len(content) / (1024 * 1024)
            
            if file_size_mb > MAX_PDF_SIZE_MB:
                raise HTTPException(
                    status_code=400, 
                    detail=f"File too large ({file_size_mb:.1f}MB). Maximum size is {MAX_PDF_SIZE_MB}MB"
                )
            
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"Request {request_id}: Saved to {tmp_path}")
        
        # Set page range if provided
        page_range = None
        if start_page is not None and end_page is not None:
            page_range = (int(start_page), int(end_page))
            logger.info(f"Request {request_id}: Using page range {page_range}")
        
        # Process asynchronously if requested
        if async_process:
            update_processing_status(request_id, "queued", 0.0, "PDF processing queued")
            background_tasks.add_task(process_pdf_task, tmp_path, request_id, page_range)
            return {
                "request_id": request_id,
                "status": "queued",
                "message": "PDF processing has been queued",
                "status_endpoint": f"/status/{request_id}"
            }
        
        # Process synchronously
        try:
            result = await asyncio.wait_for(
                process_pdf_task(tmp_path, request_id, page_range),
                timeout=DEFAULT_TIMEOUT
            )
            
            if "error" in result and not result.get("questions", []):
                logger.error(f"Request {request_id}: Processing error: {result['error']}")
                raise HTTPException(status_code=500, detail=result["error"])
            
            logger.info(f"Request {request_id}: Successfully processed {len(result.get('questions', []))} questions")
            result["request_id"] = request_id
            return result
        
        except asyncio.TimeoutError:
            logger.error(f"Request {request_id}: Processing timed out")
            update_processing_status(request_id, "timeout", 0.0, "PDF processing timed out")
            raise HTTPException(
                status_code=408, 
                detail="PDF processing timed out. Try using async_process=True for large files."
            )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing PDF: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.get("/status/{request_id}")
async def get_processing_status(request_id: str):
    """Get the status of an async processing job"""
    status = processing_status.get(request_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No status found for request ID {request_id}")
    return status

@app.post("/pdf-info")
async def get_pdf_info(file: UploadFile = File(...)):
    """Get basic information about a PDF file"""
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"Request {request_id}: Getting info for file {file.filename}")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        doc = fitz.open(tmp_path)
        total_pages = len(doc)
        file_size = os.path.getsize(tmp_path) / (1024 * 1024)
        toc = doc.get_toc()
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", "")
        }
        
        # Estimate question count
        question_pattern = re.compile(r'(?:Question\s+\d+|Q\.\s*\d+)')
        question_count = 0
        for i in range(min(10, total_pages)):
            page_text = doc[i].get_text("text")
            matches = question_pattern.findall(page_text)
            question_count += len(matches)
        
        estimated_questions = round(question_count * (total_pages / min(10, total_pages)))
        
        doc.close()
        os.unlink(tmp_path)
        
        return {
            "total_pages": total_pages,
            "file_size_mb": round(file_size, 2),
            "metadata": metadata,
            "has_toc": len(toc) > 0,
            "estimated_questions": estimated_questions
        }
    
    except Exception as e:
        logger.error(f"Request {request_id}: Error getting PDF info: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get PDF info: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    import psutil
    process = psutil.Process()
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime": time.time() - process.create_time(),
        "memory_usage_mb": process.memory_info().rss / (1024 * 1024)
    }

@app.get("/")
def read_root():
    return {
        "message": "PDF Quiz Parser API",
        "version": "2.0.0",
        "docs_url": "/docs",
        "health_check": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
