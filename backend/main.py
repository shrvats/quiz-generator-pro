#!/usr/bin/env python3
"""
PDF Quiz Parser - Production-level implementation
Robust PDF parsing system optimized for financial and exam content.
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
from fastapi import FastAPI, UploadFile, HTTPException, Request, File, Form, BackgroundTasks, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

# Optional OCR support
try:
    import pytesseract
    import cv2
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Optional tabula support
try:
    import tabula
    TABULA_AVAILABLE = True
except ImportError:
    TABULA_AVAILABLE = False

# Setup logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
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
ENABLE_VECTOR_DB = os.environ.get("ENABLE_VECTOR_DB", "true").lower() == "true"

###############################
# Data Models and Structures  #
###############################

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
    
    # Add explicit properties to avoid attribute errors
    @property
    def y0(self) -> float:
        return self.bbox[1] if self.bbox else 0
    
    @property
    def x0(self) -> float:
        return self.bbox[0] if self.bbox else 0

@dataclass
class QuestionData:
    id: int
    text: str = ""
    options: Dict[str, str] = field(default_factory=dict)
    correct_answer: Optional[str] = None
    explanation: str = ""
    option_explanations: Dict[str, str] = field(default_factory=dict)
    things_to_remember: str = ""
    table_html: str = ""
    has_table: bool = False
    has_math: bool = False
    is_skipped: bool = False
    math_expressions: List[str] = field(default_factory=list)
    validation_issues: List[str] = field(default_factory=list)
    
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
            "type": "MULTIPLE_CHOICE" if self.has_options else "UNKNOWN",
            "is_skipped": self.is_skipped
        }
        
        if self.has_table:
            result["has_table"] = True
            result["table_html"] = self.table_html
            
        if self.has_math:
            result["contains_math"] = True
            result["math_expressions"] = self.math_expressions
            
        if self.option_explanations:
            result["option_explanations"] = self.option_explanations
            
        if self.validation_issues:
            result["validation_issues"] = self.validation_issues
            
        # Generate answer HTML
        result["answer_html"] = self._generate_answer_html()
        return result
    
    def _generate_answer_html(self) -> str:
        """Generate the answer explanation HTML"""
        if not self.correct_answer:
            return ""
        
        lines = []
        
        # First line is always "The correct answer is X."
        lines.append(f"The correct answer is {self.correct_answer}.")
        
        # Main explanation for the correct answer
        if self.explanation:
            lines.append(self.explanation)
        
        # Add explanations for each incorrect option
        for letter in sorted(self.options.keys()):
            if letter == self.correct_answer:
                continue
                
            explanation = self.option_explanations.get(letter, "")
            if explanation:
                lines.append(f"{letter} is incorrect. {explanation}")
        
        # Add "Things to Remember" section if present
        if self.things_to_remember:
            lines.append("Things to Remember:")
            lines.append(self.things_to_remember)
            
        return "\n".join(lines)

class ProcessingStats:
    def __init__(self):
        self.start_time = time.time()
        self.total_pages = 0
        self.processed_pages = 0
        self.questions_found = 0
        self.tables_found = 0
        self.math_found = 0
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
            "questions_found": self.questions_found,
            "tables_found": self.tables_found,
            "math_found": self.math_found,
            "errors": self.errors,
            "warnings": self.warnings,
            "ocr_used": self.ocr_used
        }

class ProcessingResult:
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

# API Models
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

class QuizSubmission(BaseModel):
    question_id: int
    selected_answer: str

class SimilarQuestionResponse(BaseModel):
    questions: List[Dict[str, Any]]
    total: int
    query: str

###################################
#     PDF Processing Core         #
###################################

class MathExtractor:
    """Extracts mathematical expressions from text"""
    
    @staticmethod
    def extract_math(text: str) -> List[str]:
        """Extract mathematical expressions from text"""
        expressions = []
        
        # LaTeX math patterns
        latex_patterns = [
            r'\$\$.+?\$\$',  # Display math
            r'\$.+?\$',      # Inline math
            r'\\begin\{equation\}.+?\\end\{equation\}',  # Equation environment
            r'\\begin\{align\}.+?\\end\{align\}'         # Align environment
        ]
        
        for pattern in latex_patterns:
            matches = re.finditer(pattern, text, re.DOTALL)
            for match in matches:
                expressions.append(match.group(0))
        
        # Extract other mathematical expressions
        math_symbols = r'[=\+\-\*\/\^\(\)]|√|∑|∫|∂|∇|∞|α|β|γ|δ|ε|θ|λ|μ|π|σ|φ|ω'
        var_assign = r'\b[A-Za-z]\s*='
        
        # Clean text by removing already found expressions
        text_cleaned = text
        for expr in expressions:
            text_cleaned = text_cleaned.replace(expr, " ")
        
        # Find other expressions with math symbols
        words = text_cleaned.split()
        for word in words:
            if (len(re.findall(math_symbols, word)) > 1 or 
                re.search(var_assign, word)):
                if word not in expressions:
                    expressions.append(word)
        
        return expressions

class EnhancedOCRProcessor:
    """Enhanced OCR processing with image preprocessing"""
    
    def __init__(self):
        self.tesseract_config = r'--oem 3 --psm 6 -l eng+equ --dpi 300'
        self.is_available = OCR_AVAILABLE
    
    def preprocess_image(self, img):
        """Apply preprocessing to improve OCR results"""
        if not OCR_AVAILABLE:
            return img
            
        # Convert to grayscale
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        
        # Apply thresholding to remove noise
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # Deskew if needed
        coords = np.column_stack(np.where(thresh > 0))
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
            
        # Rotate the image to deskew
        if abs(angle) > 0.5:
            (h, w) = thresh.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(thresh, M, (w, h), flags=cv2.INTER_CUBIC, 
                                     borderMode=cv2.BORDER_REPLICATE)
            return Image.fromarray(rotated)
            
        return Image.fromarray(thresh)
    
    def process_page(self, page, dpi=300):
        """Process a page with enhanced OCR"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            # Convert page to image with higher resolution
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Preprocess the image
            preprocessed = self.preprocess_image(img)
            
            # Run OCR with advanced configuration
            text = pytesseract.image_to_string(preprocessed, config=self.tesseract_config)
            
            # Post-process the text (remove stray marks, fix common OCR errors)
            text = self._post_process_text(text)
            return text
        except Exception as e:
            logger.error(f"Enhanced OCR processing error: {str(e)}")
            return ""
    
    def _post_process_text(self, text):
        """Clean up OCR results"""
        # Replace common OCR errors
        replacements = {
            'l\n': '1\n',
            '0\n': 'O\n',
            'S\n': '5\n',
            'l.': '1.',
            '0.': 'O.',
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
            
        # Remove stray marks and non-text elements
        text = re.sub(r'[^\x00-\x7F]+', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text

class OCRProcessor:
    """Processes images to extract text using OCR"""
    
    @staticmethod
    def is_available() -> bool:
        return OCR_AVAILABLE
    
    @staticmethod
    def process_page(page) -> str:
        """Process a page with OCR"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            # Use enhanced OCR processor if available
            enhanced_processor = EnhancedOCRProcessor()
            return enhanced_processor.process_page(page)
        except Exception as e:
            logger.error(f"OCR processing error: {str(e)}")
            
            # Fallback to basic OCR if enhanced fails
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Use custom OCR configuration for better results
                custom_config = r'--oem 3 --psm 6'
                text = pytesseract.image_to_string(img, lang='eng', config=custom_config)
                return text
            except Exception as e2:
                logger.error(f"Basic OCR processing error: {str(e2)}")
                return ""
    
    @staticmethod
    def process_region(page, bbox) -> str:
        """Process a specific region of a page with OCR"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            mat = fitz.Matrix(2, 2)
            clip = fitz.Rect(bbox)
            pix = page.get_pixmap(matrix=mat, clip=clip)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Try enhanced OCR first
            enhanced_processor = EnhancedOCRProcessor()
            preprocessed = enhanced_processor.preprocess_image(img)
            text = pytesseract.image_to_string(preprocessed, config=enhanced_processor.tesseract_config)
            
            return text
        except Exception as e:
            logger.error(f"OCR region processing error: {str(e)}")
            return ""

class PDFTextCleaner:
    """Cleans and processes PDF text"""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean general text from PDFs"""
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
        """Extract options from text"""
        options = {}
        
        # Multiple option patterns for different formats
        option_patterns = [
            r'\n\s*([A-F])[\.\)]\s+(.*?)(?=\n\s*[A-F][\.\)]|\Z)',  # Standard with newlines
            r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\Z)',         # Compact without newlines
            r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\n\s*[A-F][\.\)]|\Z)'  # Mixed format
        ]
        
        # Try each pattern
        for pattern in option_patterns:
            matches = list(re.finditer(pattern, text, re.DOTALL))
            
            for match in matches:
                letter = match.group(1).upper()  # Ensure uppercase
                option_text = match.group(2).strip()
                
                # Clean option text
                option_text = re.sub(r'(?:is correct|correct answer|is incorrect).*', '', option_text, flags=re.IGNORECASE)
                
                if option_text:
                    options[letter] = option_text.strip()
            
            # If found some options, stop trying patterns
            if len(options) >= 2:
                break
        
        return options
    
    @staticmethod
    def extract_correct_answer(text: str) -> Tuple[str, Optional[str]]:
        """Extract the correct answer from text"""
        correct_answer = None
        
        # Multiple patterns to identify the correct answer
        patterns = [
            r'The correct answer is\s*([A-F])\..*?(?=\n|$)',
            r'Correct answer[:\s]+([A-F])\.?.*?(?=\n|$)',
            r'The answer is\s*([A-F])\.?.*?(?=\n|$)',
            r'Answer[:\s]+([A-F])\.?.*?(?=\n|$)',
            r'The correct choice is\s*([A-F])\.?.*?(?=\n|$)',
            r'([A-F])\s+is\s+(?:the\s+)?correct\s+(?:answer|option|choice)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                correct_answer = match.group(1).upper()
                text = text[:match.start()] + text[match.end():]
                break
        
        return text, correct_answer
    
    @staticmethod
    def extract_option_explanations(text: str) -> Dict[str, str]:
        """Extract explanations for individual options"""
        explanations = {}
        
        # Patterns to extract option-specific explanations
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
            r'Note[:\s]+(.*?)(?=\n\n|\Z)',
            r'Important[:\s]+(.*?)(?=\n\n|\Z)'
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

class EnhancedTableExtractor:
    """Enhanced table extraction using tabula-py and heuristics"""
    
    def __init__(self):
        self.tabula_available = TABULA_AVAILABLE
    
    def detect_tables(self, doc, page_idx):
        """Detect tables using multiple methods"""
        page = doc[page_idx]
        table_regions = []
        
        # Method 1: Use PyMuPDF built-in detection
        try:
            tables = page.find_tables()
            if tables and tables.tables:
                for table in tables.tables:
                    table_regions.append(table.rect)
        except Exception as e:
            logger.debug(f"PyMuPDF table detection error: {str(e)}")
        
        # Method 2: Look for grid patterns in text blocks (backup method)
        if not table_regions:
            try:
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block and len(block.get("lines", [])) >= 3:
                        spans_by_line = []
                        for line in block["lines"]:
                            if "spans" in line:
                                spans_by_line.append(len(line["spans"]))
                        
                        # If multiple lines with multiple spans, might be a table
                        if len(spans_by_line) >= 3 and sum(spans_by_line) >= 6:
                            table_regions.append(block["bbox"])
            except Exception as e:
                logger.debug(f"Text-based table detection error: {str(e)}")
        
        return table_regions
    
    def extract_table(self, doc, page_idx, table_rect):
        """Extract table using tabula or fallback to manual extraction"""
        if self.tabula_available:
            try:
                # Save page to a temporary PDF
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp_path = tmp.name
                
                # Extract just the page with the table
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                new_doc.save(tmp_path)
                new_doc.close()
                
                # Calculate relative coordinates (tabula uses top-left origin)
                page = doc[page_idx]
                page_height = page.rect.height
                
                # Convert from PyMuPDF to tabula coordinates (relative to page)
                area = [
                    table_rect[1] / page_height * 100,            # top
                    table_rect[0] / page.rect.width * 100,        # left
                    table_rect[3] / page_height * 100,            # bottom
                    table_rect[2] / page.rect.width * 100         # right
                ]
                
                # Use tabula to extract the table
                tables = tabula.read_pdf(
                    tmp_path, 
                    pages=1,  # Just the extracted page
                    area=area,
                    multiple_tables=False,
                    pandas_options={'header': None}
                )
                
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                
                if tables and len(tables) > 0:
                    df = tables[0]
                    # Convert to HTML
                    html = df.to_html(index=False, classes='quiz-table', na_rep='')
                    return html
            
            except Exception as e:
                logger.error(f"Tabula extraction error: {str(e)}")
        
        # Fallback to manual extraction
        return self._extract_table_manually(doc, page_idx, table_rect)
    
    def _extract_table_manually(self, doc, page_idx, bbox):
        """Manual table extraction as fallback"""
        try:
            page = doc[page_idx]
            table_text = page.get_text("dict", clip=bbox)
            
            # Extract rows based on vertical position
            rows_by_y = defaultdict(list)
            
            if "blocks" in table_text:
                for block in table_text["blocks"]:
                    if "lines" not in block:
                        continue
                    
                    for line in block["lines"]:
                        if "spans" not in line:
                            continue
                        
                        y_pos = round(line["bbox"][1])  # y0 coordinate
                        
                        # Group spans by x-position to form cells
                        spans_by_x = {}
                        for span in line["spans"]:
                            if "text" in span and span["text"].strip():
                                # Round x position to group nearby values
                                x_pos = round(span["bbox"][0] / 10) * 10
                                if x_pos not in spans_by_x:
                                    spans_by_x[x_pos] = []
                                spans_by_x[x_pos].append(span["text"])
                        
                        # Sort by x position and add to row
                        x_positions = sorted(spans_by_x.keys())
                        row_cells = []
                        for x_pos in x_positions:
                            cell_text = " ".join(spans_by_x[x_pos])
                            row_cells.append(cell_text)
                        
                        if row_cells:
                            rows_by_y[y_pos] = row_cells
            
            # Sort rows by vertical position
            sorted_y = sorted(rows_by_y.keys())
            rows = [rows_by_y[y] for y in sorted_y]
            
            # Generate HTML table
            if not rows:
                return ""
            
            # Determine table structure by analyzing column counts
            col_counts = [len(row) for row in rows]
            if not col_counts:
                return ""
                
            # Use the most common column count as our standard
            target_cols = max(set(col_counts), key=col_counts.count)
            
            # Check if first row might be headers
            headers = []
            data_rows = rows
            if len(rows) > 1:
                # Heuristic: First row is often header if it's bold or has different formatting
                if len(rows[0]) <= target_cols:
                    headers = rows[0]
                    data_rows = rows[1:]
            
            # Generate HTML
            html = ["<table class='quiz-table' border='1'>"]
            
            # Add headers if found
            if headers:
                html.append("<thead>")
                html.append("<tr>")
                for header in headers:
                    html.append(f"<th>{header}</th>")
                html.append("</tr>")
                html.append("</thead>")
            
            # Add data rows
            html.append("<tbody>")
            for row in data_rows:
                html.append("<tr>")
                # Normalize row to target column count
                if len(row) < target_cols:
                    row = row + [""] * (target_cols - len(row))
                elif len(row) > target_cols:
                    row = row[:target_cols]
                    
                for cell in row:
                    # Check if cell might be numeric for alignment
                    align = " class='numeric'" if re.match(r'^[\d\.\$]+$', cell) else ""
                    html.append(f"<td{align}>{cell}</td>")
                html.append("</tr>")
            html.append("</tbody>")
            html.append("</table>")
            
            return "\n".join(html)
        
        except Exception as e:
            logger.error(f"Manual table extraction error: {str(e)}")
            return ""

class TableExtractor:
    """Extracts and formats tables from PDFs"""
    
    @staticmethod
    def detect_tables(doc, page_idx) -> List[Tuple[float, float, float, float]]:
        """Detect potential table regions on a page"""
        try:
            # Use enhanced table extractor
            enhanced_extractor = EnhancedTableExtractor()
            return enhanced_extractor.detect_tables(doc, page_idx)
        except Exception as e:
            logger.error(f"Enhanced table detection error: {str(e)}")
            
            # Fallback to basic detection
            try:
                page = doc[page_idx]
                
                # Look for patterns that could indicate tables:
                # 1. Multiple horizontal lines close together
                # 2. Text arranged in grid-like patterns
                
                # Get the text blocks
                blocks = page.get_text("dict")["blocks"]
                
                table_regions = []
                for i, block in enumerate(blocks):
                    # Check if the block might be a table
                    if "lines" in block and len(block.get("lines", [])) >= 3:
                        # Check for grid-like pattern of text
                        spans_by_line = []
                        for line in block["lines"]:
                            if "spans" in line:
                                spans_by_line.append(len(line["spans"]))
                        
                        # If there are multiple lines with multiple spans, might be a table
                        if len(spans_by_line) >= 3 and sum(spans_by_line) >= 6:
                            table_regions.append(block["bbox"])
                
                return table_regions
            except Exception as e:
                logger.error(f"Table detection error: {str(e)}")
                return []
    
    @staticmethod
    def extract_table(doc, page_idx, bbox) -> str:
        """Extract table content as HTML"""
        try:
            # Use enhanced table extractor
            enhanced_extractor = EnhancedTableExtractor()
            return enhanced_extractor.extract_table(doc, page_idx, bbox)
        except Exception as e:
            logger.error(f"Enhanced table extraction error: {str(e)}")
            
            # Fallback to basic extraction
            try:
                page = doc[page_idx]
                
                # Get text from the table region
                table_text = page.get_text("dict", clip=bbox)
                
                # Extract rows based on vertical position
                rows_by_y = defaultdict(list)
                
                if "blocks" in table_text:
                    for block in table_text["blocks"]:
                        if "lines" not in block:
                            continue
                        
                        for line in block["lines"]:
                            if "spans" not in line:
                                continue
                            
                            y_pos = round(line["bbox"][1])  # y0 coordinate
                            spans = []
                            for span in line["spans"]:
                                if "text" in span and span["text"].strip():
                                    spans.append(span["text"])
                            
                            # Add text to the corresponding row
                            if spans:
                                rows_by_y[y_pos].extend(spans)
                
                # Sort rows by vertical position
                sorted_y = sorted(rows_by_y.keys())
                rows = [rows_by_y[y] for y in sorted_y]
                
                # Generate HTML table
                if not rows:
                    return ""
                
                # Check if first row might be headers
                headers = []
                if rows:
                    first_row = rows[0]
                    if len(first_row) >= 2:
                        # First row could be headers if it differs from others
                        headers = first_row
                        rows = rows[1:]
                
                html = ["<table class='quiz-table' border='1'>"]
                
                # Add headers if found
                if headers:
                    html.append("<thead>")
                    html.append("<tr>")
                    for header in headers:
                        html.append(f"<th>{header}</th>")
                    html.append("</tr>")
                    html.append("</thead>")
                
                # Add data rows
                html.append("<tbody>")
                for row in rows:
                    html.append("<tr>")
                    for cell in row:
                        # Check if cell might be numeric for alignment
                        align = " class='numeric'" if re.match(r'^[\d\.\$]+$', cell) else ""
                        html.append(f"<td{align}>{cell}</td>")
                    html.append("</tr>")
                html.append("</tbody>")
                html.append("</table>")
                
                return "\n".join(html)
            
            except Exception as e:
                logger.error(f"Table extraction error: {str(e)}")
                return ""

class PDFQuestionExtractor:
    """Extracts quiz questions from PDF documents"""
    
    def __init__(self, method: ParsingMethod = ParsingMethod.TEXT_BASED):
        self.method = method
        self.cleaner = PDFTextCleaner()
        self.stats = ProcessingStats()
    
    def extract_from_document(self, doc, page_range=None) -> List[QuestionData]:
        """Main method to extract questions from a PDF document"""
        self.stats = ProcessingStats()
        self.stats.total_pages = len(doc)
        
        # Set page range
        if page_range:
            start_page, end_page = page_range
            start_page = max(0, start_page)
            end_page = min(len(doc) - 1, end_page)
            page_iterator = range(start_page, end_page + 1)
        else:
            page_iterator = range(len(doc))
        
        self.stats.processed_pages = len(page_iterator)
        
        # Check if OCR is needed
        needs_ocr = self._check_if_ocr_needed(doc, page_iterator)
        
        # Default to text-based extraction
        return self._extract_text_based(doc, page_iterator, use_ocr=needs_ocr)
    
    def _check_if_ocr_needed(self, doc, page_iterator) -> bool:
        """Determine if OCR should be used"""
        if not OCRProcessor.is_available():
            return False
        
        for i in range(min(3, len(page_iterator))):
            page_idx = page_iterator[i]
            page = doc[page_idx]
            text = page.get_text("text")
            
            # If page has very little text, try OCR
            if len(text.strip()) < 50:
                self.stats.ocr_used = True
                return True
        
        return False
    
    def _extract_text_based(self, doc, page_iterator, use_ocr=False) -> List[QuestionData]:
        """Extract questions using text-based approach"""
        # Get text from all relevant pages
        all_text = ""
        for page_num in page_iterator:
            page = doc[page_num]
            page_text = page.get_text("text")
            
            # Use OCR if needed
            if use_ocr and len(page_text.strip()) < 50:
                page_text = OCRProcessor.process_page(page)
            
            all_text += page_text + "\n"
        
        # Find math expressions
        math_expressions = MathExtractor.extract_math(all_text)
        self.stats.math_found += len(math_expressions)
        
        # Find question boundaries
        questions_text = self._split_into_questions(all_text)
        self.stats.questions_found = len(questions_text)
        
        # Process each question
        questions = []
        for i, q_text in enumerate(questions_text):
            try:
                # Extract ID and process question
                q_id, q_number = self._extract_question_id(q_text, i)
                
                # Process the question
                question = self._process_question_text(q_text, q_id)
                
                # Add math expressions if present
                question_math = [expr for expr in math_expressions if expr in q_text]
                if question_math:
                    question.has_math = True
                    question.math_expressions = question_math
                
                # Check for tables
                if self._text_might_have_table(q_text):
                    # Find the page this question is on
                    for page_num in page_iterator:
                        page = doc[page_num]
                        if q_text in page.get_text("text"):
                            table_regions = TableExtractor.detect_tables(doc, page_num)
                            if table_regions:
                                html = TableExtractor.extract_table(doc, page_num, table_regions[0])
                                if html:
                                    question.has_table = True
                                    question.table_html = html
                                    self.stats.tables_found += 1
                                    break
                
                # Add the question if valid
                if question and question.text:
                    questions.append(question)
            except Exception as e:
                logger.error(f"Error processing question {i+1}: {str(e)}")
                logger.error(traceback.format_exc())
                self.stats.errors.append(f"Error processing question {i+1}: {str(e)}")
        
        return questions
    
    def _split_into_questions(self, text: str) -> List[str]:
        """Split text into individual questions"""
        # Try different patterns to find question boundaries
        
        # Pattern 1: Standard question numbering (Question X or Q.X)
        question_pattern = r'(?:Question\s+(\d+)(?:\(Q\.\d+\))?|Q\.?\s*(\d+)(?:\(Q\.\d+\))?)'
        question_matches = list(re.finditer(question_pattern, text))
        
        if question_matches:
            return self._split_by_matches(text, question_matches)
        
        # Pattern 2: Simple numbered items
        alternate_pattern = r'\n\s*(\d+)[\.\)]\s+'
        alternate_matches = list(re.finditer(alternate_pattern, text))
        
        if alternate_matches:
            self.stats.warnings.append("Used alternate question numbering pattern")
            return self._split_by_matches(text, alternate_matches)
        
        # Pattern 3: Option-based splitting (look for A. B. C. pattern)
        option_pattern = r'\n\s*A[\.\)]\s+.*?\n\s*B[\.\)]\s+'
        option_matches = list(re.finditer(option_pattern, text))
        
        if option_matches:
            self.stats.warnings.append("Used option-based question splitting")
            return self._split_by_options(text, option_matches)
        
        # If no clear boundaries, treat as one question
        self.stats.warnings.append("No clear question boundaries found")
        return [text]
    
    def _split_by_matches(self, text: str, matches: List[re.Match]) -> List[str]:
        """Split text at the matched positions"""
        questions = []
        
        for i, match in enumerate(matches):
            start_pos = match.start()
            
            if i < len(matches) - 1:
                end_pos = matches[i+1].start()
            else:
                end_pos = len(text)
                
            question_text = text[start_pos:end_pos]
            if question_text.strip():
                questions.append(question_text)
                
        return questions
    
    def _split_by_options(self, text: str, option_matches: List[re.Match]) -> List[str]:
        """Split text based on option patterns"""
        questions = []
        prev_end = 0
        
        for i, match in enumerate(option_matches):
            # Look for the start of this question (before options)
            start_pos = text.rfind('\n', 0, match.start())
            if start_pos == -1:
                start_pos = 0
            else:
                start_pos += 1  # Skip the newline
                
            # If too close to previous question end, adjust
            if start_pos < prev_end:
                start_pos = prev_end
                
            # Find the end (next option pattern or end of text)
            if i < len(option_matches) - 1:
                end_pos = option_matches[i+1].start()
            else:
                end_pos = len(text)
                
            question_text = text[start_pos:end_pos].strip()
            if question_text:
                questions.append(question_text)
                prev_end = end_pos
                
        return questions
    
    def _extract_question_id(self, text: str, default_index: int) -> Tuple[int, Optional[str]]:
        """Extract question ID and Q number from text"""
        # Look for question numbering patterns
        q_id = None
        q_number = None
        
        # Pattern 1: Question X(Q.YYYY)
        pattern1 = r'Question\s+(\d+)\s*(?:\(Q\.(\d+)\))?'
        match1 = re.search(pattern1, text)
        if match1:
            q_id = int(match1.group(1))
            q_number = match1.group(2) if match1.group(2) else str(q_id)
            return q_id, q_number
            
        # Pattern 2: Q.YYYY
        pattern2 = r'Q\.?\s*(\d+)'
        match2 = re.search(pattern2, text)
        if match2:
            q_id = int(match2.group(1))
            q_number = str(q_id)
            return q_id, q_number
            
        # Pattern 3: Number at start of text
        pattern3 = r'^(\d+)[\.\)]'
        match3 = re.search(pattern3, text)
        if match3:
            q_id = int(match3.group(1))
            q_number = str(q_id)
            return q_id, q_number
            
        # No pattern matched, use default index
        return default_index + 1, str(default_index + 1)
    
    def _process_question_text(self, text: str, q_id: int) -> QuestionData:
        """Process a question's text into a structured QuestionData object"""
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
        options = self.cleaner.extract_options(text)
        
        # Extract option-specific explanations
        option_explanations = self.cleaner.extract_option_explanations(explanation)
        
        # Determine if the question should be skipped
        is_skipped = "skipped" in text.lower() or not options
        
        # The remaining text is the question statement
        question_text = text.strip()
        
        return QuestionData(
            id=q_id,
            text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            option_explanations=option_explanations,
            things_to_remember=things_to_remember,
            is_skipped=is_skipped
        )
    
    def _text_might_have_table(self, text: str) -> bool:
        """Check if text might contain a table"""
        # Look for indications of a table
        table_indicators = [
            text.count("|") > 4,  # Multiple pipe characters
            text.count("\t") > 4,  # Multiple tabs
            text.lower().count("table") > 0,  # Explicit mention
            re.search(r'\n\s*-{3,}', text),  # Table separators
            re.search(r'[A-Za-z]+\s+\|\s+[A-Za-z]+', text)  # Column headings
        ]
        
        return any(table_indicators)

class VectorDatabase:
    """Vector database for quiz questions with similarity search"""
    
    def __init__(self, connection_string=None):
        self.connection_string = connection_string or os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/quizdb"
        )
        self.embedding_model = None
        self.conn = None
        self.initialized = False
    
    async def initialize(self):
        """Initialize the database connection and embeddings model"""
        if self.initialized:
            return
            
        try:
            # Initialize embedding model
            from sentence_transformers import SentenceTransformer
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Initialize postgres connection with pgvector
            import psycopg
            import pgvector.psycopg
            
            self.conn = await psycopg.AsyncConnection.connect(
                self.connection_string, autocommit=True
            )
            
            # Create tables if they don't exist
            await self._create_tables()
            self.initialized = True
            logger.info("Vector database initialized successfully")
        except ImportError as e:
            logger.error(f"Missing dependencies for vector database: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to initialize vector database: {str(e)}")
    
    async def _create_tables(self):
        """Create necessary tables and extensions"""
        async with self.conn.cursor() as cur:
            # Create pgvector extension if not exists
            await cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Create questions table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id SERIAL PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    options JSONB,
                    correct_answer TEXT,
                    explanation TEXT,
                    embedding vector(384),
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index on embedding for similarity search
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS questions_embedding_idx 
                ON questions USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
            
            # Create files table to track processed files
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id SERIAL PRIMARY KEY,
                    file_hash TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    total_pages INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    def compute_embedding(self, text):
        """Generate embeddings for text"""
        if not self.embedding_model:
            return None
        
        # Clean the text first
        clean_text = ' '.join(text.split())
        return self.embedding_model.encode(clean_text).tolist()
    
    async def store_questions(self, questions, file_hash, filename, metadata=None):
        """Store questions in vector database"""
        if not self.initialized:
            await self.initialize()
            
        if not self.initialized:
            logger.error("Vector database not initialized, cannot store questions")
            return False
            
        try:
            # First store file record
            async with self.conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO files (file_hash, filename, total_pages, total_questions, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (file_hash) DO UPDATE
                    SET total_questions = %s, metadata = %s
                    RETURNING id
                    """,
                    (
                        file_hash, 
                        filename, 
                        metadata.get('total_pages', 0) if metadata else 0,
                        len(questions),
                        json.dumps(metadata) if metadata else '{}',
                        len(questions),
                        json.dumps(metadata) if metadata else '{}'
                    )
                )
                
                file_id = await cur.fetchone()
                
                # Then store each question with its embedding
                for question in questions:
                    # Generate embedding for the question text
                    q_text = question.text
                    embedding = self.compute_embedding(q_text)
                    
                    # Store in database
                    await cur.execute(
                        """
                        INSERT INTO questions 
                        (question_id, file_hash, text, options, correct_answer, explanation, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(question.id),
                            file_hash,
                            q_text,
                            json.dumps(question.options),
                            question.correct_answer,
                            question.explanation,
                            embedding,
                            json.dumps({
                                'has_math': question.has_math,
                                'has_table': question.has_table,
                                'math_expressions': question.math_expressions
                            })
                        )
                    )
                
            logger.info(f"Stored {len(questions)} questions in vector database for file {filename}")
            return True
        
        except Exception as e:
            logger.error(f"Error storing questions in vector database: {str(e)}")
            return False
    
    async def find_similar_questions(self, query_text, limit=5):
        """Find similar questions to the given query"""
        if not self.initialized:
            await self.initialize()
            
        if not self.initialized:
            logger.error("Vector database not initialized, cannot search questions")
            return []
            
        try:
            # Generate embedding for query
            query_embedding = self.compute_embedding(query_text)
            
            # Search for similar questions
            async with self.conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT 
                        id, 
                        question_id, 
                        text, 
                        options, 
                        correct_answer, 
                        explanation,
                        1 - (embedding <=> %s) as similarity
                    FROM questions
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (query_embedding, query_embedding, limit)
                )
                
                results = await cur.fetchall()
                
                # Format results
                similar_questions = []
                for row in results:
                    similar_questions.append({
                        'id': row[0],
                        'question_id': row[1],
                        'text': row[2],
                        'options': json.loads(row[3]),
                        'correct_answer': row[4],
                        'explanation': row[5],
                        'similarity': row[6]
                    })
                
                return similar_questions
        
        except Exception as e:
            logger.error(f"Error searching for similar questions: {str(e)}")
            return []
    
    async def close(self):
        """Close database connection"""
        if self.conn:
            await self.conn.close()
            self.conn = None
            self.initialized = False

class PDFProcessor:
    """Main class for processing PDF files to extract quiz questions"""
    
    def __init__(self, file_path: str, page_range: Optional[Tuple[int, int]] = None):
        self.file_path = file_path
        self.page_range = page_range
        self.doc = None
        self.extractor = PDFQuestionExtractor(method=ParsingMethod.TEXT_BASED)
        self.result = ProcessingResult()
        self.process_id = str(uuid.uuid4())[:8]
    
    def process(self) -> Dict[str, Any]:
        """Process the PDF file and extract questions"""
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

# Store processing status
processing_status = {}

# Create vector DB instance
vector_db = VectorDatabase() if ENABLE_VECTOR_DB else None

# Add dependency for vector DB access
async def get_vector_db():
    if vector_db:
        if not vector_db.initialized:
            await vector_db.initialize()
        return vector_db
    return None

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

async def process_pdf_with_storage(
    file_path, 
    request_id, 
    page_range, 
    file_hash, 
    filename, 
    store_in_db=True,
    vector_db=None
):
    """Process PDF and optionally store in vector database"""
    try:
        update_processing_status(request_id, "processing", 0.1, "Starting PDF processing")
        processor = PDFProcessor(file_path, page_range)
        
        with ThreadPoolExecutor() as executor:
            result = await asyncio.get_event_loop().run_in_executor(executor, processor.process)
        
        # Store in vector database if enabled and requested
        if store_in_db and vector_db and result.get('questions'):
            try:
                # Convert dict questions back to QuestionData objects
                questions = []
                for q_dict in result.get('questions', []):
                    question = QuestionData(
                        id=q_dict.get('id'),
                        text=q_dict.get('question', ''),
                        options=q_dict.get('options', {}),
                        correct_answer=q_dict.get('correct'),
                        explanation=q_dict.get('explanation', ''),
                        has_table=q_dict.get('has_table', False),
                        has_math=q_dict.get('contains_math', False),
                        math_expressions=q_dict.get('math_expressions', [])
                    )
                    questions.append(question)
                
                # Store in DB
                metadata = {
                    'total_pages': result.get('total_pages', 0),
                    'stats': result.get('stats', {})
                }
                
                success = await vector_db.store_questions(
                    questions, 
                    file_hash, 
                    filename, 
                    metadata
                )
                
                if success:
                    result['stored_in_db'] = True
                    logger.info(f"Stored {len(questions)} questions in vector database")
                else:
                    result['stored_in_db'] = False
                    logger.warning("Failed to store questions in vector database")
            
            except Exception as e:
                logger.error(f"Error storing in vector database: {str(e)}")
                result['stored_in_db'] = False
        
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
    async_process: bool = Form(False),
    store_in_db: bool = Form(True),
    vector_db: Optional[VectorDatabase] = Depends(get_vector_db)
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
            
            # Generate file hash for DB storage
            file_hash = hashlib.sha256(content).hexdigest()
            
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
            # Modified background task function to include vector DB storage
            background_tasks.add_task(
                process_pdf_with_storage, 
                tmp_path, 
                request_id, 
                page_range,
                file_hash,
                file.filename,
                store_in_db,
                vector_db
            )
            return {
                "request_id": request_id,
                "status": "queued",
                "message": "PDF processing has been queued",
                "status_endpoint": f"/status/{request_id}"
            }
        
        # Process synchronously
        try:
            result = await asyncio.wait_for(
                process_pdf_with_storage(
                    tmp_path, 
                    request_id, 
                    page_range,
                    file_hash,
                    file.filename,
                    store_in_db,
                    vector_db
                ),
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

@app.post("/search")
async def search_similar_questions(
    query: str = Form(...),
    limit: int = Form(5),
    vector_db: Optional[VectorDatabase] = Depends(get_vector_db)
):
    """Search for questions similar to the query"""
    if not vector_db:
        raise HTTPException(status_code=400, detail="Vector database is not enabled")
    
    try:
        similar_questions = await vector_db.find_similar_questions(query, limit)
        return {
            "questions": similar_questions,
            "total": len(similar_questions),
            "query": query
        }
    except Exception as e:
        logger.error(f"Error searching questions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@app.get("/status/{request_id}")
async def get_processing_status(request_id: str):
    """Get the status of an async processing job"""
    status = processing_status.get(request_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No status found for request ID {request_id}")
    return status
    
@app.head("/")
def head_root():
    # Return an empty response with a 200 status code
      return {}


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
        
        estimated_questions = round(question_count * (total_pages / max(1, min(10, total_pages))))
        
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
    """Handle quiz answer submission and return the formatted answer display"""
    try:
        # This endpoint would normally look up the actual question in a database
        # For now it returns a stub response
        return {
            "question_id": submission.question_id,
            "selected_answer": submission.selected_answer,
            "correct_answer": "C", # Example
            "is_correct": submission.selected_answer == "C"
        }
    except Exception as e:
        logger.error(f"Error processing quiz submission: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process submission: {str(e)}")

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
