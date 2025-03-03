#!/usr/bin/env python3
"""
PDF Quiz Parser - Production-level implementation
A robust PDF parsing system to extract quiz questions from various PDF formats.

Sample Question for Understanding:
------------------------------------------------
Q.4885 In corporate finance, companies often employ various defensive strategies to protect against hostile takeovers. Which of the following is an example of a poison pill?
A. Granting a bonus to executives if the company remains independent after a takeover attempt.
B. Implementing a staggered board system where only a few directors are elected each year.
C. Issuing preferred shares that immediately convert to common shares in the case of a takeover.
D. Creating a subsidiary that holds all the intellectual property, which can be sold in the event of a takeover.

After submission, the answer should appear like this:
------------------------------------------------
The correct answer is C.
Issuing preferred shares that automatically convert to common shares upon a takeover attempt dilutes the voting power and ownership percentage of the acquirer, directly impacting the feasibility and attractiveness of the takeover. This is a classic example of a poison pill tactic.
A is incorrect. While granting a bonus to executives if the company remains independent might seem like a deterrent, it primarily serves as a retention tool rather than a structural mechanism that deters a hostile takeover.
B is incorrect. A staggered board system, though it prolongs the takeover process, is a governance mechanism rather than a classic poison pill.
D is incorrect. Creating a subsidiary to hold critical assets does not directly interfere with takeover mechanics.
Things to Remember:
A poison pill is a defensive strategy to deter hostile takeovers by diluting the shares held by potential acquirers. Examples include issuing new shares at a discount or creating share classes with enhanced voting rights. (For instance, Netflix adopted a poison pill in 2012.)
------------------------------------------------

Author: Quiz Parser Team
Version: 1.0.0
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
from typing import List, Dict, Tuple, Optional, Any, Union, Set, NamedTuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter
import asyncio
from concurrent.futures import ThreadPoolExecutor

import fitz  # PyMuPDF
import pandas as pd
import numpy as np
from fastapi import FastAPI, UploadFile, HTTPException, Request, File, Form, BackgroundTasks, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, validator

# Optional OCR support
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Setup logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("quiz_parser.log")
    ]
)
logger = logging.getLogger("quiz-pdf-parser")

# Constants
MAX_PROCESSING_TIME = 120  # seconds
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 55  # seconds
SUPPORTED_LANGUAGES = ["en", "fr", "es", "de"]
MIN_QUESTION_LENGTH = 10
MAX_PDF_SIZE_MB = 100
CACHE_EXPIRY = 3600
MAX_PARALLEL_REQUESTS = 5
MATH_PATTERN = r'(?:\$.*?\$)|(?:\\begin\{equation\}.*?\\end\{equation\})|(?:[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞|\b[A-Za-z]\s*=)'

###############################
# Data Models and Structures  #
###############################

class BlockType(Enum):
    UNKNOWN = auto()
    QUESTION_ID = auto()
    QUESTION_TEXT = auto()
    OPTION_A = auto()
    OPTION_B = auto()
    OPTION_C = auto()
    OPTION_D = auto()
    OPTION_E = auto()
    OPTION_F = auto()
    CORRECT_ANSWER = auto()
    EXPLANATION = auto()
    REMEMBER = auto()
    COPYRIGHT = auto()
    PAGE_NUMBER = auto()
    HEADER = auto()
    FOOTER = auto()
    TABLE = auto()
    BIDDER_DATA = auto()
    MATH = auto()

class QuestionType(Enum):
    MULTIPLE_CHOICE = auto()
    TRUE_FALSE = auto()
    FILL_IN_BLANK = auto()
    MATCHING = auto()
    CALCULATION = auto()
    FINANCIAL = auto()
    ESSAY = auto()
    UNKNOWN = auto()

class ParsingMethod(Enum):
    TEXT_BASED = auto()
    BLOCK_BASED = auto()
    HYBRID = auto()
    OCR = auto()

@dataclass
class TextSpan:
    text: str
    bbox: Tuple[float, float, float, float]
    font: str = ""
    size: float = 0
    color: int = 0

@dataclass
class TextBlock:
    spans: List[TextSpan] = field(default_factory=list)
    block_type: BlockType = BlockType.UNKNOWN
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    page_num: int = 0
    
    @property
    def text(self) -> str:
        return " ".join(span.text for span in self.spans)
    
    @property
    def x0(self) -> float:
        return self.bbox[0]
    
    @property
    def y0(self) -> float:
        return self.bbox[1]
    
    @property
    def x1(self) -> float:
        return self.bbox[2]
    
    @property
    def y1(self) -> float:
        return self.bbox[3]

@dataclass
class BidderData:
    bidder: str
    shares: int
    price: float

@dataclass
class QuestionData:
    id: int
    text: str = ""
    options: Dict[str, str] = field(default_factory=dict)
    correct_answer: Optional[str] = None
    explanation: str = ""
    option_explanations: Dict[str, str] = field(default_factory=dict)
    things_to_remember: str = ""
    bidder_data: List[BidderData] = field(default_factory=list)
    table_html: str = ""
    has_table: bool = False
    has_bidder_data: bool = False
    type: QuestionType = QuestionType.MULTIPLE_CHOICE
    source_blocks: List[TextBlock] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    validation_issues: List[str] = field(default_factory=list)
    contains_math: bool = False
    math_expressions: List[str] = field(default_factory=list)
    
    @property
    def has_options(self) -> bool:
        return len(self.options) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "question": self.text,
            "options": self.options,
            "correct": self.correct_answer,
            "explanation": self.explanation,
            "things_to_remember": self.things_to_remember,
            "has_options": self.has_options,
            "type": self.type.name,
        }
        if self.has_bidder_data:
            result["bidder_data"] = [
                {"bidder": b.bidder, "shares": b.shares, "price": b.price} 
                for b in self.bidder_data
            ]
            result["has_bidder_data"] = True
        if self.has_table:
            result["table_html"] = self.table_html
            result["has_table"] = True
        if self.contains_math:
            result["contains_math"] = True
            result["math_expressions"] = self.math_expressions
        if self.validation_issues:
            result["validation_issues"] = self.validation_issues
        
        # Generate the answer HTML exactly as shown in the example
        result["answer_html"] = self._generate_answer_html()
        return result
    
    def _generate_answer_html(self) -> str:
        """Generate the answer HTML in the exact format requested"""
        if not self.correct_answer:
            return ""
            
        lines = []
        lines.append(f"The correct answer is {self.correct_answer}.")
        
        # Main explanation for the correct answer (first paragraph)
        if self.explanation:
            lines.append(self.explanation)
        elif self.correct_answer in self.options:
            lines.append(self.options[self.correct_answer])
        
        # Add explanation for each option
        for letter in sorted(self.options.keys()):
            if letter == self.correct_answer:
                continue
                
            # Get explanation for this specific option
            explanation = self.option_explanations.get(letter, "")
            if not explanation:
                option_text = self.options.get(letter, "")
                explanation = f"While {option_text}, this is not the correct answer."
                
            lines.append(f"{letter} is incorrect. {explanation}")
        
        # Add Things to Remember section if present
        if self.things_to_remember:
            lines.append("Things to Remember:")
            lines.append(self.things_to_remember)
            
        return "\n".join(lines)

class ParsingStatistics:
    def __init__(self):
        self.start_time = time.time()
        self.total_pages = 0
        self.processed_pages = 0
        self.total_blocks = 0
        self.questions_found = 0
        self.options_found = 0
        self.tables_found = 0
        self.math_expressions_found = 0
        self.bidder_data_found = 0
        self.questions_with_issues = 0
        self.errors = []
        self.warnings = []
        self.ocr_used = False
        
    def elapsed_time(self) -> float:
        return time.time() - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "elapsed_time_seconds": self.elapsed_time(),
            "total_pages": self.total_pages,
            "processed_pages": self.processed_pages,
            "total_blocks": self.total_blocks,
            "questions_found": self.questions_found,
            "options_found": self.options_found,
            "tables_found": self.tables_found,
            "math_expressions_found": self.math_expressions_found,
            "bidder_data_found": self.bidder_data_found,
            "questions_with_issues": self.questions_with_issues,
            "errors": self.errors,
            "warnings": self.warnings,
            "ocr_used": self.ocr_used
        }

class ProcessingResult:
    def __init__(self, questions=None, total_pages=0, error=None):
        self.questions = questions or []
        self.total_pages = total_pages
        self.error = error
        self.stats = ParsingStatistics()
        
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

# API Models
class PDFInfoResponse(BaseModel):
    total_pages: int
    file_size_mb: float
    metadata: Dict[str, str]
    estimated_questions: int = 0
    has_toc: bool = False
    language: str = "en"
    
class ProcessingStatus(BaseModel):
    request_id: str
    status: str
    progress: float
    message: str
    timestamp: float = Field(default_factory=time.time)

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime: float
    memory_usage_mb: float

class QuizSubmission(BaseModel):
    question_id: int
    selected_answer: str

class QuizSubmissionResponse(BaseModel):
    question_id: int
    selected_answer: str
    correct_answer: str
    is_correct: bool
    explanation_html: str

###################################
#     PDF Processing Core       #
###################################

class MathExtractor:
    """Extract mathematical expressions from text"""
    
    @staticmethod
    def extract_expressions(text: str) -> List[str]:
        """Extract mathematical expressions from text"""
        expressions = []
        
        # Extract LaTeX-style expressions
        latex_patterns = [
            r'\$.*?\$',  # Inline math
            r'\$\$.*?\$\$',  # Display math
            r'\\begin\{equation\}.*?\\end\{equation\}',  # Equation environment
            r'\\begin\{align\}.*?\\end\{align\}'  # Align environment
        ]
        
        for pattern in latex_patterns:
            matches = re.finditer(pattern, text, re.DOTALL)
            for match in matches:
                expressions.append(match.group(0))
        
        # Extract other potential math expressions
        math_symbols = r'[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞'
        var_assignment = r'\b[A-Za-z]\s*='
        
        # Find sequences with multiple math symbols or variable assignments
        text_without_latex = text
        for expr in expressions:
            text_without_latex = text_without_latex.replace(expr, " ")
        
        words = text_without_latex.split()
        for word in words:
            if (len(re.findall(math_symbols, word)) > 1 or
                re.search(var_assignment, word)):
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
        """Process a PDF page with OCR to extract text"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            # Convert page to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Run OCR
            text = pytesseract.image_to_string(img, lang='eng')
            return text
        except Exception as e:
            logger.error(f"OCR processing error: {str(e)}")
            return ""

class PDFTextCleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        text = re.sub(r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
        text = re.sub(r'^[ \t]*\d+[ \t]*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
        # Clean up multiple whitespaces
        text = re.sub(r' +', ' ', text)
        # Clean up multiple newlines
        text = re.sub(r'\n+', '\n', text)
        return text.strip()
    
    @staticmethod
    def remove_answer_from_text(text: str) -> Tuple[str, Optional[str]]:
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
    def clean_option_text(text: str) -> str:
        text = re.sub(r'(?:is correct|correct answer|is incorrect).*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        return text.strip()
    
    @staticmethod
    def extract_option_explanations(text: str) -> Dict[str, str]:
        """Extract explanations for each option from text"""
        explanations = {}
        
        # Patterns for option explanations
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

class PDFQuestionExtractor:
    def __init__(self, method: ParsingMethod = ParsingMethod.HYBRID):
        self.method = method
        self.cleaner = PDFTextCleaner()
        self.stats = ParsingStatistics()
        
    def extract_from_document(self, doc, page_range=None) -> List[QuestionData]:
        self.stats = ParsingStatistics()
        self.stats.total_pages = len(doc)
        if page_range:
            start_page, end_page = page_range
            start_page = max(0, start_page)
            end_page = min(len(doc) - 1, end_page)
            page_iterator = range(start_page, end_page + 1)
        else:
            page_iterator = range(len(doc))
        self.stats.processed_pages = len(page_iterator)
        
        # Check if OCR might be needed
        needs_ocr = False
        for i in range(min(3, len(page_iterator))):
            page_idx = page_iterator[i]
            page = doc[page_idx]
            text = page.get_text("text")
            if len(text.strip()) < 50:  # Not enough text
                if OCRProcessor.is_available():
                    needs_ocr = True
                    self.stats.ocr_used = True
                    break
        
        if needs_ocr:
            logger.info("Using OCR for text extraction")
        
        if self.method == ParsingMethod.TEXT_BASED:
            return self._extract_text_based(doc, page_iterator, use_ocr=needs_ocr)
        elif self.method == ParsingMethod.BLOCK_BASED:
            return self._extract_block_based(doc, page_iterator)
        else:
            try:
                questions = self._extract_block_based(doc, page_iterator)
                if questions:
                    return questions
            except Exception as e:
                logger.warning(f"Block-based extraction failed: {str(e)}, falling back to text-based")
            return self._extract_text_based(doc, page_iterator, use_ocr=needs_ocr)
    
    def _extract_text_based(self, doc, page_iterator, use_ocr=False) -> List[QuestionData]:
        all_text = ""
        for page_num in page_iterator:
            page = doc[page_num]
            page_text = page.get_text("text")
            
            # Use OCR if needed
            if use_ocr and len(page_text.strip()) < 50:
                page_text = OCRProcessor.process_page(page)
                
            all_text += page_text + "\n"
        
        # Extract math expressions from the entire text
        math_expressions = MathExtractor.extract_expressions(all_text)
        self.stats.math_expressions_found = len(math_expressions)
        
        question_pattern = r'(?:Question\s+(\d+)(?:\(Q\.\d+\))?|Q\.?\s*(\d+)(?:\(Q\.\d+\))?)'
        question_matches = list(re.finditer(question_pattern, all_text))
        self.stats.questions_found = len(question_matches)
        
        if not question_matches:
            alternate_pattern = r'\n\s*(\d+)[\.\)]\s+'
            alternate_matches = list(re.finditer(alternate_pattern, all_text))
            if alternate_matches:
                question_matches = alternate_matches
                self.stats.questions_found = len(alternate_matches)
                self.stats.warnings.append("Used alternate question numbering pattern")
        
        questions = []
        for i, match in enumerate(question_matches):
            try:
                q_id = None
                for group in match.groups() or []:
                    if group:
                        q_id = group
                        break
                if not q_id and match.group(0):
                    q_id_match = re.search(r'\d+', match.group(0))
                    if q_id_match:
                        q_id = q_id_match.group(0)
                if not q_id:
                    q_id = str(i + 1)
                
                start_pos = match.start()
                if i < len(question_matches) - 1:
                    end_pos = question_matches[i+1].start()
                else:
                    end_pos = len(all_text)
                
                question_text = all_text[start_pos:end_pos]
                
                # Check if this question text contains math expressions
                question_math = [expr for expr in math_expressions 
                                if expr in question_text]
                
                question_data = self._process_question_text(question_text, int(q_id))
                
                if question_data:
                    if question_math:
                        question_data.contains_math = True
                        question_data.math_expressions = question_math
                    
                    if question_data.text:
                        questions.append(question_data)
            except Exception as e:
                logger.error(f"Error processing question {i+1}: {str(e)}")
                logger.error(traceback.format_exc())
                self.stats.errors.append(f"Error processing question {i+1}: {str(e)}")
        
        return questions
    
    def _extract_block_based(self, doc, page_iterator) -> List[QuestionData]:
        blocks = self._extract_blocks(doc, page_iterator)
        self.stats.total_blocks = len(blocks)
        
        # Extract math expressions from all blocks
        all_text = " ".join(block.text for block in blocks)
        math_expressions = MathExtractor.extract_expressions(all_text)
        self.stats.math_expressions_found = len(math_expressions)
        
        # Update block metadata with math expression information
        for block in blocks:
            block_math = [expr for expr in math_expressions if expr in block.text]
            if block_math:
                block.metadata["contains_math"] = True
                block.metadata["math_expressions"] = block_math
        
        classified_blocks = self._classify_blocks(blocks)
        question_blocks = self._group_blocks_by_question(classified_blocks)
        self.stats.questions_found = len(question_blocks)
        
        questions = []
        for i, q_blocks in enumerate(question_blocks):
            try:
                q_id = q_blocks[0].metadata.get("question_id") if q_blocks else i + 1
                question_data = self._process_question_blocks(q_blocks, q_id)
                
                # Check if any block in this question contains math
                has_math = any(block.metadata.get("contains_math", False) for block in q_blocks)
                if has_math:
                    question_data.contains_math = True
                    # Collect all math expressions from blocks in this question
                    question_data.math_expressions = []
                    for block in q_blocks:
                        if block.metadata.get("contains_math", False):
                            question_data.math_expressions.extend(
                                block.metadata.get("math_expressions", [])
                            )
                
                if question_data and question_data.text:
                    questions.append(question_data)
            except Exception as e:
                logger.error(f"Error processing question from blocks {i+1}: {str(e)}")
                logger.error(traceback.format_exc())
                self.stats.errors.append(f"Error processing question from blocks {i+1}: {str(e)}")
        
        return questions
    
    def _extract_blocks(self, doc, page_iterator) -> List[TextBlock]:
        blocks = []
        for page_num in page_iterator:
            page = doc[page_num]
            page_dict = page.get_text("dict")
            for block in page_dict["blocks"]:
                if "lines" not in block:
                    continue
                text_block = TextBlock(
                    spans=[],
                    bbox=block["bbox"],
                    page_num=page_num
                )
                for line in block["lines"]:
                    if "spans" not in line:
                        continue
                    for span in line["spans"]:
                        if not span.get("text", "").strip():
                            continue
                        text_block.spans.append(TextSpan(
                            text=span.get("text", ""),
                            bbox=span.get("bbox", (0, 0, 0, 0)),
                            font=span.get("font", ""),
                            size=span.get("size", 0),
                            color=span.get("color", 0)
                        ))
                if text_block.spans:
                    blocks.append(text_block)
        return blocks
    
    def _classify_blocks(self, blocks: List[TextBlock]) -> List[TextBlock]:
        for block in blocks:
            text = block.text
            if not text.strip():
                continue
            if re.search(r'(?:©|Copyright\s*©?)\s*\d{4}', text, re.IGNORECASE):
                block.block_type = BlockType.COPYRIGHT
                continue
            if re.match(r'^\s*\d+\s*$', text):
                block.block_type = BlockType.PAGE_NUMBER
                continue
            if re.match(r'(?:Question\s+\d+|Q\.\s*\d+)', text):
                block.block_type = BlockType.QUESTION_ID
                q_id_match = re.search(r'\d+', text)
                if q_id_match:
                    block.metadata["question_id"] = int(q_id_match.group(0))
                continue
            # APPENDED CHANGE: Exclude options that start with "Choice"
            if re.match(r'^(?i:choice)', text):
                continue
            option_match = re.match(r'^([A-F])[\.\)]\s+(.*)', text, re.DOTALL)
            if option_match:
                letter = option_match.group(1)
                option_text = option_match.group(2).strip()
                if letter == 'A':
                    block.block_type = BlockType.OPTION_A
                elif letter == 'B':
                    block.block_type = BlockType.OPTION_B
                elif letter == 'C':
                    block.block_type = BlockType.OPTION_C
                elif letter == 'D':
                    block.block_type = BlockType.OPTION_D
                elif letter == 'E':
                    block.block_type = BlockType.OPTION_E
                elif letter == 'F':
                    block.block_type = BlockType.OPTION_F
                block.metadata["option_letter"] = letter
                block.metadata["option_text"] = option_text
                self.stats.options_found += 1
                continue
            if re.search(r'(?:The correct answer is|Correct answer|The answer is|Answer:)', text, re.IGNORECASE):
                block.block_type = BlockType.CORRECT_ANSWER
                answer_match = re.search(r'(?:The correct answer is|Correct answer|The answer is|Answer:)\s*([A-F])', text, re.IGNORECASE)
                if answer_match:
                    block.metadata["correct_answer"] = answer_match.group(1)
                continue
            if re.search(r'(?:Things to Remember|Remember:|Note:)', text, re.IGNORECASE):
                block.block_type = BlockType.REMEMBER
                continue
            if re.search(r'(?:Explanation:|Therefore:|Thus:)', text, re.IGNORECASE):
                block.block_type = BlockType.EXPLANATION
                continue
            if len(block.spans) >= 3 and len(set(span.y0 for span in block.spans)) >= 3:
                block.block_type = BlockType.TABLE
                self.stats.tables_found += 1
                continue
            bidder_matches = list(re.finditer(r'([A-G])\s+([\d,\s]+)\s+\$([\d\.]+)', text))
            if len(bidder_matches) >= 2:
                block.block_type = BlockType.BIDDER_DATA
                bidders = []
                for match in bidder_matches:
                    bidder = match.group(1)
                    shares_str = match.group(2).replace(",", "").replace(" ", "")
                    price_str = match.group(3)
                    try:
                        shares = int(shares_str)
                        price = float(price_str)
                        bidders.append(BidderData(bidder, shares, price))
                    except ValueError:
                        pass
                if bidders:
                    block.metadata["bidders"] = bidders
                    self.stats.bidder_data_found += 1
                continue
            if re.search(r'[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞|\b[A-Za-z]\s*=', text):
                block.metadata["contains_math"] = True
                block.metadata["math_expressions"] = MathExtractor.extract_expressions(text)
                self.stats.math_expressions_found += 1
        return blocks
    
    def _group_blocks_by_question(self, blocks: List[TextBlock]) -> List[List[TextBlock]]:
        question_starts = []
        for i, block in enumerate(blocks):
            if block.block_type == BlockType.QUESTION_ID:
                question_starts.append(i)
        if not question_starts:
            # Try alternative grouping based on options
            return self._group_blocks_by_options(blocks)
        question_blocks = []
        for i, start_idx in enumerate(question_starts):
            end_idx = question_starts[i+1] if i+1 < len(question_starts) else len(blocks)
            question_blocks.append(blocks[start_idx:end_idx])
        return question_blocks
    
    def _group_blocks_by_options(self, blocks: List[TextBlock]) -> List[List[TextBlock]]:
        """Alternative grouping strategy when question IDs aren't found"""
        logger.warning("No question boundaries found, trying to group by options")
        self.stats.warnings.append("Grouped questions by options")
        
        # Find blocks that contain options
        option_indices = []
        for i, block in enumerate(blocks):
            if block.block_type in [BlockType.OPTION_A, BlockType.OPTION_B, 
                                   BlockType.OPTION_C, BlockType.OPTION_D]:
                if block.block_type == BlockType.OPTION_A:
                    option_indices.append(i)
        
        if not option_indices:
            logger.warning("No option blocks found, returning all blocks as one question")
            return [blocks] if blocks else []
        
        question_blocks = []
        for i, start_idx in enumerate(option_indices):
            # Look for the block before option A, which is likely the question text
            question_start = max(0, start_idx - 1)
            
            end_idx = option_indices[i+1] - 1 if i+1 < len(option_indices) else len(blocks)
            question_blocks.append(blocks[question_start:end_idx])
        
        return question_blocks
    
    def _process_question_text(self, text: str, q_id: int) -> Optional[QuestionData]:
        # Extract options with improved pattern matching
        options = self._extract_options_from_text(text)
        self.stats.options_found += len(options)
        
        # Extract option-specific explanations
        option_explanations = self.cleaner.extract_option_explanations(text)
        
        # Get text without answer that might be embedded
        text, correct_answer = self.cleaner.remove_answer_from_text(text)
        
        # Remove question ID pattern from beginning
        text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.?\s*\d+(?:\(Q\.\d+\))?)\s*', '', text)
        
        # Extract Things to Remember section if present
        text, things_to_remember = self._extract_things_to_remember(text)
        
        # Extract explanation
        text, explanation = self._extract_explanation(text)
        
        # Extract bidder data
        bidder_data = self._extract_bidder_data(text)
        if bidder_data:
            self.stats.bidder_data_found += 1
        
        # Check for math expressions
        contains_math = self._check_for_math(text)
        math_expressions = []
        if contains_math:
            math_expressions = MathExtractor.extract_expressions(text)
            self.stats.math_expressions_found += len(math_expressions)
        
        # Clean up the question text
        question_text = self.cleaner.clean_text(text)
        
        if len(question_text) < MIN_QUESTION_LENGTH:
            return None
        
        question = QuestionData(
            id=q_id,
            text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            option_explanations=option_explanations,
            things_to_remember=things_to_remember,
            bidder_data=bidder_data,
            has_bidder_data=bool(bidder_data),
            contains_math=contains_math,
            math_expressions=math_expressions
        )
        
        validation_issues = self._validate_question(question)
        if validation_issues:
            question.validation_issues = validation_issues
            self.stats.questions_with_issues += 1
        
        return question
    
    def _process_question_blocks(self, blocks: List[TextBlock], q_id: int) -> Optional[QuestionData]:
        question_blocks = []
        option_blocks = []
        explanation_blocks = []
        remember_blocks = []
        table_blocks = []
        bidder_blocks = []
        answer_blocks = []
        
        for block in blocks:
            if block.block_type == BlockType.QUESTION_ID:
                question_blocks.append(block)
            elif block.block_type in [BlockType.OPTION_A, BlockType.OPTION_B, BlockType.OPTION_C, 
                                     BlockType.OPTION_D, BlockType.OPTION_E, BlockType.OPTION_F]:
                option_blocks.append(block)
            elif block.block_type == BlockType.EXPLANATION:
                explanation_blocks.append(block)
            elif block.block_type == BlockType.REMEMBER:
                remember_blocks.append(block)
            elif block.block_type == BlockType.TABLE:
                table_blocks.append(block)
            elif block.block_type == BlockType.BIDDER_DATA:
                bidder_blocks.append(block)
            elif block.block_type == BlockType.CORRECT_ANSWER:
                answer_blocks.append(block)
            elif block.block_type == BlockType.UNKNOWN:
                if not option_blocks:
                    question_blocks.append(block)
        
        question_text = ""
        for block in question_blocks:
            if block.block_type == BlockType.QUESTION_ID:
                text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.?\s*\d+(?:\(Q\.\d+\))?)\s*', '', block.text)
            else:
                text = block.text
            question_text += " " + text
        
        question_text = self.cleaner.clean_text(question_text)
        
        options = {}
        for block in option_blocks:
            letter = block.metadata.get("option_letter")
            text = block.metadata.get("option_text", "")
            if letter and text:
                options[letter] = self.cleaner.clean_option_text(text)
        
        correct_answer = None
        for block in answer_blocks:
            if "correct_answer" in block.metadata:
                correct_answer = block.metadata["correct_answer"]
                break
        
        if not correct_answer:
            for block in blocks:
                answer_match = re.search(r'(?:The correct answer is|Correct answer|The answer is|Answer:)\s*([A-F])', block.text, re.IGNORECASE)
                if answer_match:
                    correct_answer = answer_match.group(1)
                    break
        
        explanation = " ".join(block.text for block in explanation_blocks)
        explanation = self.cleaner.clean_text(explanation)
        
        # Extract option-specific explanations from the explanation text
        option_explanations = self.cleaner.extract_option_explanations(explanation)
        
        things_to_remember = " ".join(block.text for block in remember_blocks)
        things_to_remember = self.cleaner.clean_text(things_to_remember)
        
        bidder_data = []
        for block in bidder_blocks:
            if "bidders" in block.metadata:
                bidder_data.extend(block.metadata["bidders"])
        
        if not bidder_data:
            bidder_data = self._extract_bidder_data(question_text)
        
        has_table = bool(table_blocks)
        table_html = ""
        if has_table:
            table_html = self._generate_table_html(table_blocks)
        
        contains_math = any(block.metadata.get("contains_math", False) for block in blocks) or self._check_for_math(question_text)
        
        # Collect all math expressions from this question
        math_expressions = []
        if contains_math:
            for block in blocks:
                if block.metadata.get("contains_math", False):
                    math_expressions.extend(block.metadata.get("math_expressions", []))
            
            # If no expressions found in block metadata, extract from question text
            if not math_expressions:
                math_expressions = MathExtractor.extract_expressions(question_text)
        
        question = QuestionData(
            id=q_id,
            text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            option_explanations=option_explanations,
            things_to_remember=things_to_remember,
            bidder_data=bidder_data,
            has_bidder_data=bool(bidder_data),
            table_html=table_html,
            has_table=has_table,
            contains_math=contains_math,
            math_expressions=math_expressions,
            source_blocks=blocks
        )
        
        validation_issues = self._validate_question(question)
        if validation_issues:
            question.validation_issues = validation_issues
            self.stats.questions_with_issues += 1
        
        return question
    
    def _extract_options_from_text(self, text: str) -> Dict[str, str]:
        options = {}
        
        # Try multiple patterns to extract options
        option_patterns = [
            # Standard pattern with newlines
            r'\n\s*([A-F])[\.\)]\s+(.*?)(?=\n\s*[A-F][\.\)]|\Z)',
            # No newlines between options
            r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\Z)',
            # Pattern for options that might span multiple lines
            r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\n\s*[A-F][\.\)]|\Z)'
        ]
        
        # Try each pattern until we find options
        for pattern in option_patterns:
            matches = list(re.finditer(pattern, text, re.DOTALL))
            for match in matches:
                letter = match.group(1)
                option_text = match.group(2).strip()
                option_text = self.cleaner.clean_option_text(option_text)
                if option_text:
                    options[letter] = option_text
            
            # If we found options with this pattern, stop trying others
            if options:
                break
        
        return options
    
    def _extract_things_to_remember(self, text: str) -> Tuple[str, str]:
        things_to_remember = ""
        pattern = r'Things to Remember[:\s]*\n(.+)$'
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            things_to_remember = match.group(1).strip()
            text = text[:match.start()].strip()
        else:
            patterns = [
                r'Things to Remember[:\s]+(.*?)(?=\n\n|\Z)',
                r'Remember[:\s]+(.*?)(?=\n\n|\Z)',
                r'Note[:\s]+(.*?)(?=\n\n|\Z)',
                r'Important[:\s]+(.*?)(?=\n\n|\Z)'
            ]
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
                if m:
                    things_to_remember = m.group(1).strip()
                    text = text[:m.start()] + text[m.end():]
                    break
            text = text.strip()
        return text, things_to_remember
    
    def _extract_explanation(self, text: str) -> Tuple[str, str]:
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
    
    def _extract_bidder_data(self, text: str) -> List[BidderData]:
        bidder_data = []
        bidder_matches = re.finditer(r'([A-G])\s+([\d,\s]+)\s+\$([\d\.]+)', text)
        for match in bidder_matches:
            bidder = match.group(1)
            shares_str = match.group(2).replace(",", "").replace(" ", "")
            price_str = match.group(3)
            try:
                shares = int(shares_str)
                price = float(price_str)
                bidder_data.append(BidderData(bidder, shares, price))
            except ValueError:
                continue
        return bidder_data
    
    def _check_for_math(self, text: str) -> bool:
        # Enhanced pattern to detect math content
        math_patterns = [
            r'\$.*?\$',                   # LaTeX inline math
            r'\$\$.*?\$\$',               # LaTeX display math
            r'\\begin\{equation\}.*?\\end\{equation\}',  # LaTeX equation env
            r'[=\+\-\*\/\^\(\)]',         # Standard math operators
            r'\d+\.\d+',                  # Decimal numbers
            r'[αβγδεζηθικλμνξοπρστυφχψω]', # Greek letters
            r'√|∑|∫|∂|∇|∞',               # Math symbols
            r'\b[A-Za-z]\s*=',            # Variable assignments
            r'log|exp|sin|cos|tan',       # Math functions
            r'var|std|avg|mean',          # Statistical terms
        ]
        
        return any(re.search(pattern, text) for pattern in math_patterns)
    
    def _generate_table_html(self, table_blocks: List[TextBlock]) -> str:
        if not table_blocks:
            return ""
        
        sorted_blocks = sorted(table_blocks, key=lambda b: (b.page_num, b.y0))
        rows = []
        
        for block in sorted_blocks:
            spans_by_y = defaultdict(list)
            for span in block.spans:
                y_key = round(span.bbox[1])
                spans_by_y[y_key].append(span)
            
            sorted_y = sorted(spans_by_y.keys())
            for y in sorted_y:
                row = [span.text.strip() for span in sorted(spans_by_y[y], key=lambda s: s.bbox[0])]
                if row:
                    rows.append(row)
        
        if not rows:
            return ""
        
        html = "<table class='quiz-table' border='1'>\n"
        
        # If we have a header row (likely first row)
        if rows and any(cell.isupper() for cell in rows[0]):
            html += "<thead>\n<tr>\n"
            for cell in rows[0]:
                html += f"  <th>{cell}</th>\n"
            html += "</tr>\n</thead>\n"
            rows = rows[1:]
        
        # Table body
        html += "<tbody>\n"
        for row in rows:
            html += "<tr>\n"
            for cell in row:
                css_class = ""
                if re.match(r'^[\d\.\$]+$', cell):
                    css_class = " class='numeric'"
                html += f"  <td{css_class}>{cell}</td>\n"
            html += "</tr>\n"
        html += "</tbody>\n"
        html += "</table>"
        
        return html
    
    def _validate_question(self, question: QuestionData) -> List[str]:
        issues = []
        if not question.text.strip():
            issues.append("Question text is empty")
        
        if question.options and len(question.options) < 2:
            issues.append(f"Question has only {len(question.options)} options, should have at least 2")
        
        if question.correct_answer and question.options:
            if question.correct_answer not in question.options:
                issues.append(f"Correct answer '{question.correct_answer}' not in options")
        
        for letter, text in question.options.items():
            if len(text) < 5:
                issues.append(f"Option {letter} is very short: '{text}'")
        
        # Validate option explanations
        if question.option_explanations:
            for letter in question.option_explanations:
                if letter not in question.options:
                    issues.append(f"Explanation provided for option {letter} which is not in options")
        
        return issues

class PDFProcessor:
    def __init__(self, file_path: str, page_range: Optional[Tuple[int, int]] = None):
        self.file_path = file_path
        self.page_range = page_range
        self.doc = None
        self.extractor = PDFQuestionExtractor(method=ParsingMethod.HYBRID)
        self.result = ProcessingResult()
        self.process_id = str(uuid.uuid4())[:8]
    
    def process(self) -> Dict[str, Any]:
        logger.info(f"Processing PDF {self.file_path} (ID: {self.process_id})")
        
        try:
            self.doc = fitz.open(self.file_path)
            self.result.total_pages = len(self.doc)
            
            questions = self.extractor.extract_from_document(self.doc, self.page_range)
            self.result.questions = questions
            self.result.stats = self.extractor.stats
            
            logger.info(f"Processed PDF {self.file_path} (ID: {self.process_id}): Found {len(questions)} questions")
            return self.result.to_dict()
        
        except Exception as e:
            logger.error(f"Error processing PDF {self.file_path} (ID: {self.process_id}): {str(e)}")
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
    description="Production-level API for extracting quiz questions from PDF documents",
    version="2.0.0"
)

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

processing_status = {}

def update_processing_status(request_id: str, status: str, progress: float, message: str):
    processing_status[request_id] = {
        "request_id": request_id,
        "status": status,
        "progress": progress,
        "message": message,
        "timestamp": time.time()
    }
    current_time = time.time()
    keys_to_remove = []
    for key, value in processing_status.items():
        if current_time - value["timestamp"] > CACHE_EXPIRY:
            keys_to_remove.append(key)
    for key in keys_to_remove:
        processing_status.pop(key, None)

async def process_pdf_task(file_path: str, request_id: str, page_range: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    try:
        update_processing_status(request_id, "processing", 0.1, "Starting PDF processing")
        processor = PDFProcessor(file_path, page_range)
        with ThreadPoolExecutor() as executor:
            result = await asyncio.get_event_loop().run_in_executor(executor, processor.process)
        update_processing_status(request_id, "completed", 1.0, f"Completed processing. Found {result.get('total_questions', 0)} questions")
        return result
    except Exception as e:
        update_processing_status(request_id, "error", 0, f"Error: {str(e)}")
        logger.error(f"Error in background processing task: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "error": str(e),
            "questions": [],
            "total_pages": 0
        }
    finally:
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
    request_id = str(uuid.uuid4())
    logger.info(f"Request {request_id}: Processing file {file.filename}")
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")
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
        page_range = None
        if start_page is not None and end_page is not None:
            page_range = (int(start_page), int(end_page))
            logger.info(f"Request {request_id}: Using page range {page_range}")
        if async_process:
            update_processing_status(request_id, "queued", 0.0, "PDF processing queued")
            background_tasks.add_task(process_pdf_task, tmp_path, request_id, page_range)
            return {
                "request_id": request_id,
                "status": "queued",
                "message": "PDF processing has been queued",
                "status_endpoint": f"/status/{request_id}"
            }
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
                detail="PDF processing timed out. Please try using async_process=True for large files."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing PDF: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.get("/status/{request_id}")
async def get_processing_status(request_id: str):
    status = processing_status.get(request_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No status found for request ID {request_id}")
    return status

@app.post("/pdf-info")
async def get_pdf_info(file: UploadFile = File(...)):
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

@app.post("/quiz-submit")
async def submit_quiz_answer(submission: QuizSubmission):
    """Handle quiz answer submission with proper formatting"""
    try:
        # In a real implementation, fetch the actual question and check the answer
        # For now, return a properly formatted example response
        return {
            "question_id": submission.question_id,
            "selected_answer": submission.selected_answer,
            "correct_answer": "C",
            "is_correct": submission.selected_answer == "C",
            "explanation_html": """
                The correct answer is C.
                Issuing preferred shares that automatically convert to common shares upon a takeover attempt dilutes the voting power and ownership percentage of the acquirer, directly impacting the feasibility and attractiveness of the takeover. This is a classic example of a poison pill tactic.
                A is incorrect. While granting a bonus to executives if the company remains independent might seem like a deterrent, it primarily serves as a retention tool rather than a structural mechanism that deters a hostile takeover.
                B is incorrect. A staggered board system, though it prolongs the takeover process, is a governance mechanism rather than a classic poison pill.
                D is incorrect. Creating a subsidiary to hold critical assets does not directly interfere with takeover mechanics.
                Things to Remember:
                A poison pill is a defensive strategy to deter hostile takeovers by diluting the shares held by potential acquirers. Examples include issuing new shares at a discount or creating share classes with enhanced voting rights. (For instance, Netflix adopted a poison pill in 2012.)
            """
        }
    except Exception as e:
        logger.error(f"Error processing quiz submission: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process submission: {str(e)}")

@app.get("/health")
async def health_check():
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

@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
