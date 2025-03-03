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
import logging
import uuid
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple, Any, Union, Set
from enum import Enum, auto
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("quiz-pdf-parser")

class BlockType(Enum):
    """Enum for block types to ensure consistent classification"""
    UNKNOWN = auto()
    QUESTION_ID = auto()
    QUESTION_TEXT = auto()
    OPTION = auto()
    EXPLANATION = auto()
    CORRECT_ANSWER = auto()
    REMEMBER = auto()
    TABLE_HEADER = auto()
    TABLE_ROW = auto()
    COPYRIGHT = auto()
    PAGE_NUMBER = auto()
    SKIP = auto()
    BIDDER_DATA = auto()

@dataclass
class TextSpan:
    """Represents a span of text with position and style information"""
    text: str
    bbox: Tuple[float, float, float, float]
    font: str = ""
    size: float = 0
    color: int = 0

@dataclass
class TextBlock:
    """Represents a block of text"""
    spans: List[TextSpan] = field(default_factory=list)
    block_type: BlockType = BlockType.UNKNOWN
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    page_num: int = 0
    
    @property
    def text(self) -> str:
        """Get concatenated text of all spans"""
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
    """Structured data for bidder information"""
    bidder: str
    shares: int
    price: float

@dataclass
class QuestionData:
    """Full question data structure"""
    id: int
    text: str = ""
    options: Dict[str, str] = field(default_factory=dict)
    correct_answer: Optional[str] = None
    explanation: str = ""
    things_to_remember: str = ""
    bidder_data: List[BidderData] = field(default_factory=list)
    table_html: str = ""
    has_table: bool = False
    has_bidder_data: bool = False
    source_blocks: List[TextBlock] = field(default_factory=list)
    
    @property
    def has_options(self) -> bool:
        return len(self.options) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        result = {
            "id": self.id,
            "question": self.text,
            "options": self.options,
            "correct": self.correct_answer,
            "explanation": self.explanation,
            "things_to_remember": self.things_to_remember,
            "has_options": self.has_options,
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
            
        return result

class PDFParser:
    """Production-level PDF parser with robust error handling"""
    
    def __init__(self, file_path: str, page_range: Optional[Tuple[int, int]] = None):
        self.file_path = file_path
        self.page_range = page_range
        self.doc = None
        self.blocks: List[TextBlock] = []
        self.questions: List[QuestionData] = []
        self.parser_id = str(uuid.uuid4())[:8]
        self.stats = {
            "total_pages": 0,
            "processed_pages": 0,
            "total_blocks": 0,
            "questions_found": 0,
            "processing_time": 0
        }
        
        # Regex patterns for better maintainability
        self.patterns = {
            "question_id": r'(?:Question\s+(\d+)(?:\(Q\.(\d+)\))?|Q\.?\s*(\d+)(?:\(Q\.(\d+)\))?)',
            "option": r'^([A-F])[\.\)]\s+(.*?)$',
            "correct_answer": r'(?:The correct answer is|Correct answer[:\s]+|The answer is|Answer:\s*)([A-F])\.?',
            "copyright": r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?',
            "page_number": r'^\s*\d+\s*$',
            "bidder_data": r'([A-G])\s+([\d,\s]+)\s+\$([\d\.]+)',
            "remember": r'(?:Things to Remember|Remember:|Note:)',
            "explanation": r'(?:Explanation:|Therefore:|Thus,)',
            "choice_incorrect": r'Choice\s+([A-F])\s+is\s+incorrect\.',
            "choice_correct": r'Choice\s+([A-F])\s+is\s+correct\.'
        }
        
    def __enter__(self):
        """Context manager entry"""
        self.doc = fitz.open(self.file_path)
        self.stats["total_pages"] = len(self.doc)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.doc:
            self.doc.close()
    
    def process(self) -> Dict[str, Any]:
        """Main processing method"""
        start_time = time.time()
        
        try:
            # Extract blocks from PDF
            self.extract_blocks()
            
            # Classify blocks
            self.classify_blocks()
            
            # Group blocks into questions
            self.group_questions()
            
            # Process each question
            self.process_questions()
            
            # Track processing time
            self.stats["processing_time"] = time.time() - start_time
            
            # Return results
            return {
                "questions": [q.to_dict() for q in self.questions],
                "total_questions": len(self.questions),
                "total_pages": self.stats["total_pages"],
                "stats": self.stats
            }
            
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "error": f"Failed to process PDF: {str(e)}",
                "questions": [],
                "total_pages": self.stats.get("total_pages", 0)
            }
    
    def extract_blocks(self):
        """Extract blocks from PDF with position and style information"""
        # Determine page range
        if self.page_range:
            start_page, end_page = self.page_range
            start_page = max(0, start_page)
            end_page = min(len(self.doc) - 1, end_page)
            pages = range(start_page, end_page + 1)
        else:
            pages = range(len(self.doc))
        
        self.stats["processed_pages"] = len(pages)
        
        # Extract blocks from each page
        for page_num in pages:
            page = self.doc[page_num]
            page_dict = page.get_text("dict")
            
            for block in page_dict["blocks"]:
                if "lines" not in block:
                    continue
                
                text_block = TextBlock(
                    spans=[],
                    bbox=block["bbox"],
                    page_num=page_num
                )
                
                # Extract spans
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
                
                # Only add blocks with content
                if text_block.spans:
                    self.blocks.append(text_block)
        
        self.stats["total_blocks"] = len(self.blocks)
        logger.info(f"Extracted {len(self.blocks)} blocks from {len(pages)} pages")
    
    def classify_blocks(self):
        """Classify blocks by content type"""
        for block in self.blocks:
            text = block.text
            
            # Check for copyright notices or page numbers
            if re.search(self.patterns["copyright"], text, re.IGNORECASE):
                block.block_type = BlockType.COPYRIGHT
                continue
            
            if re.match(self.patterns["page_number"], text):
                block.block_type = BlockType.PAGE_NUMBER
                continue
            
            # Check for question IDs
            if re.match(self.patterns["question_id"], text):
                block.block_type = BlockType.QUESTION_ID
                # Extract question ID
                q_id_match = re.match(self.patterns["question_id"], text)
                if q_id_match:
                    # Get first non-None group
                    q_id = next((g for g in q_id_match.groups() if g), "0")
                    block.metadata["question_id"] = int(q_id)
                continue
            
            # Check for options (A. B. C. etc.)
            option_match = re.match(self.patterns["option"], text, re.DOTALL)
            if option_match:
                block.block_type = BlockType.OPTION
                block.metadata["option_letter"] = option_match.group(1)
                block.metadata["option_text"] = option_match.group(2).strip()
                continue
            
            # Check for correct answer indicators
            if re.search(self.patterns["correct_answer"], text, re.IGNORECASE):
                block.block_type = BlockType.CORRECT_ANSWER
                answer_match = re.search(self.patterns["correct_answer"], text, re.IGNORECASE)
                if answer_match:
                    block.metadata["answer"] = answer_match.group(1)
                continue
            
            # Check for "things to remember" blocks
            if re.search(self.patterns["remember"], text, re.IGNORECASE):
                block.block_type = BlockType.REMEMBER
                continue
            
            # Check for explanation blocks
            if re.search(self.patterns["explanation"], text, re.IGNORECASE):
                block.block_type = BlockType.EXPLANATION
                continue
            
            # Check for "Choice X is correct/incorrect" blocks
            choice_incorrect = re.search(self.patterns["choice_incorrect"], text, re.IGNORECASE)
            choice_correct = re.search(self.patterns["choice_correct"], text, re.IGNORECASE)
            if choice_incorrect or choice_correct:
                block.block_type = BlockType.EXPLANATION
                if choice_correct:
                    block.metadata["correct_option"] = choice_correct.group(1)
                continue
            
            # Check for bidder data
            bidder_matches = list(re.finditer(self.patterns["bidder_data"], text))
            if len(bidder_matches) >= 2:  # At least 2 bidders
                block.block_type = BlockType.BIDDER_DATA
                bidders = []
                for match in bidder_matches:
                    bidder = match.group(1)
                    shares = int(match.group(2).replace(",", "").replace(" ", ""))
                    price = float(match.group(3))
                    bidders.append(BidderData(bidder, shares, price))
                block.metadata["bidders"] = bidders
                continue
            
            # If no special type detected, keep as UNKNOWN
            # Will be assigned later during question grouping
    
    def group_questions(self):
        """Group blocks into questions based on question IDs"""
        # First, find all question ID blocks
        question_starts = []
        for i, block in enumerate(self.blocks):
            if block.block_type == BlockType.QUESTION_ID:
                question_starts.append(i)
        
        if not question_starts:
            logger.warning("No question ID blocks found")
            return
        
        # Group blocks by question
        for i, start_idx in enumerate(question_starts):
            end_idx = question_starts[i+1] if i+1 < len(question_starts) else len(self.blocks)
            
            # Get blocks for this question
            question_blocks = self.blocks[start_idx:end_idx]
            
            # Skip if no blocks (should never happen)
            if not question_blocks:
                continue
            
            # Get question ID
            q_id_block = question_blocks[0]
            q_id = q_id_block.metadata.get("question_id", i+1)
            
            # Create question data
            question = QuestionData(
                id=q_id,
                source_blocks=question_blocks
            )
            
            # Add to questions list
            self.questions.append(question)
        
        self.stats["questions_found"] = len(self.questions)
        logger.info(f"Found {len(self.questions)} questions")
    
    def process_questions(self):
        """Process each question to extract text, options, etc."""
        for question in self.questions:
            try:
                # Process this question
                self._process_question(question)
            except Exception as e:
                logger.error(f"Error processing question {question.id}: {str(e)}")
                logger.error(traceback.format_exc())
                
                # Try fallback processing to save what we can
                self._process_question_fallback(question)
    
    def _process_question(self, question: QuestionData):
        """Process a single question with sophisticated analysis"""
        blocks = question.source_blocks
        
        # Extract question text
        question_text_blocks = []
        for i, block in enumerate(blocks):
            # Take blocks after question ID until first option or explanation
            if i == 0 and block.block_type == BlockType.QUESTION_ID:
                continue
            
            if block.block_type in [BlockType.OPTION, BlockType.EXPLANATION, 
                                   BlockType.CORRECT_ANSWER, BlockType.REMEMBER]:
                break
            
            if block.block_type not in [BlockType.COPYRIGHT, BlockType.PAGE_NUMBER]:
                question_text_blocks.append(block)
        
        # Extract question text
        question.text = self._clean_text(" ".join(block.text for block in question_text_blocks))
        
        # Check for bidder data in question text
        bidder_data = self._extract_bidder_data_from_text(question.text)
        if bidder_data:
            question.bidder_data = bidder_data
            question.has_bidder_data = True
            
            # Remove bidder data from question text
            for bidder in bidder_data:
                pattern = f"{bidder.bidder}\\s+{bidder.shares:,}\\s+\\${bidder.price}"
                question.text = re.sub(pattern, "", question.text, flags=re.IGNORECASE)
                
            # Also try to remove the whole bidder table
            bidder_section = re.search(r'Bidder.*?(?=\n|$)', question.text, re.IGNORECASE | re.DOTALL)
            if bidder_section:
                question.text = question.text[:bidder_section.start()].strip()
        
        # Extract options
        options = {}
        for block in blocks:
            if block.block_type == BlockType.OPTION:
                option_letter = block.metadata.get("option_letter")
                option_text = block.metadata.get("option_text")
                if option_letter and option_text:
                    options[option_letter] = self._clean_text(option_text)
        
        # If no options were found, try alternative extraction
        if not options:
            options = self._extract_options_alternative(blocks, question.text)
        
        question.options = options
        
        # Extract correct answer
        correct_answer = None
        for block in blocks:
            if block.block_type == BlockType.CORRECT_ANSWER:
                correct_answer = block.metadata.get("answer")
                break
            
            # Also check explanation blocks for answer
            if block.block_type == BlockType.EXPLANATION:
                answer_match = re.search(self.patterns["correct_answer"], block.text, re.IGNORECASE)
                if answer_match:
                    correct_answer = answer_match.group(1)
                    break
        
        question.correct_answer = correct_answer
        
        # Extract explanation
        explanation_blocks = [b for b in blocks if b.block_type == BlockType.EXPLANATION]
        explanation_text = " ".join(b.text for b in explanation_blocks)
        question.explanation = self._clean_text(explanation_text)
        
        # Extract "things to remember"
        remember_blocks = [b for b in blocks if b.block_type == BlockType.REMEMBER]
        if remember_blocks:
            remember_text = " ".join(b.text for b in remember_blocks)
            question.things_to_remember = self._clean_text(remember_text)
        else:
            # Try to extract from explanation text
            remember_match = re.search(r'(?:Things to Remember|Note:)(.*?)(?=\n|$)', 
                                      explanation_text, re.IGNORECASE | re.DOTALL)
            if remember_match:
                question.things_to_remember = self._clean_text(remember_match.group(1))
        
        # Check for tables
        table_blocks = [b for b in blocks if b.block_type == BlockType.TABLE_HEADER 
                       or b.block_type == BlockType.TABLE_ROW]
        if table_blocks:
            question.has_table = True
            question.table_html = self._generate_table_html(table_blocks)
    
    def _process_question_fallback(self, question: QuestionData):
        """Fallback processing for questions that failed normal processing"""
        # Basic extraction of question ID and text
        if not question.text:
            # Just take all text after question ID
            full_text = " ".join(b.text for b in question.source_blocks)
            q_id_match = re.match(self.patterns["question_id"], full_text)
            if q_id_match:
                question.text = full_text[q_id_match.end():].strip()
                question.text = self._clean_text(question.text)
        
        # Try to extract options if none found
        if not question.options:
            # Look for A., B., C., etc. in full text
            full_text = " ".join(b.text for b in question.source_blocks)
            options = {}
            option_matches = re.finditer(r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\Z)', 
                                        full_text, re.DOTALL)
            
            for match in option_matches:
                letter = match.group(1)
                text = match.group(2).strip()
                if text:
                    options[letter] = self._clean_text(text)
            
            question.options = options
    
    def _extract_options_alternative(self, blocks: List[TextBlock], question_text: str) -> Dict[str, str]:
        """Alternative option extraction for complex layouts"""
        options = {}
        
        # Try to find options in the full text
        full_text = " ".join(b.text for b in blocks)
        
        # Remove question text to avoid confusion
        if question_text:
            full_text = full_text.replace(question_text, "")
        
        # Look for option patterns
        option_matches = list(re.finditer(r'([A-F])[\.\)]\s+(.*?)(?=\s+[A-F][\.\)]|\Z)', 
                                      full_text, re.DOTALL))
        
        for match in option_matches:
            letter = match.group(1)
            text = match.group(2).strip()
            if text:
                options[letter] = self._clean_text(text)
        
        return options
    
    def _extract_bidder_data_from_text(self, text: str) -> List[BidderData]:
        """Extract bidder data from text"""
        bidder_data = []
        
        # Look for patterns like "A 1,500 $40.50"
        bidder_matches = re.finditer(self.patterns["bidder_data"], text)
        
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
    
    def _generate_table_html(self, table_blocks: List[TextBlock]) -> str:
        """Generate HTML for a table"""
        if not table_blocks:
            return ""
        
        # Sort blocks by vertical position
        sorted_blocks = sorted(table_blocks, key=lambda b: (b.page_num, b.y0))
        
        # Build HTML table
        html = "<table border='1'>\n"
        
        # First block is header
        header_block = sorted_blocks[0]
        cells = self._extract_table_cells(header_block)
        html += "<tr>\n"
        for cell in cells:
            html += f"  <th>{cell}</th>\n"
        html += "</tr>\n"
        
        # Rest are data rows
        for block in sorted_blocks[1:]:
            cells = self._extract_table_cells(block)
            if not cells:
                continue
                
            html += "<tr>\n"
            for cell in cells:
                css_class = ""
                if re.match(r'^[\d\.\$]+$', cell):
                    css_class = " align='right'"
                html += f"  <td{css_class}>{cell}</td>\n"
            html += "</tr>\n"
        
        html += "</table>"
        return html
    
    def _extract_table_cells(self, block: TextBlock) -> List[str]:
        """Extract cells from a table block"""
        # Simple approach - just use spans as cells
        return [span.text for span in block.spans]
    
    def _clean_text(self, text: str) -> str:
        """Clean text by removing copyright notices, page numbers, etc."""
        # Remove copyright statements
        text = re.sub(self.patterns["copyright"], '', text, flags=re.IGNORECASE)
        
        # Remove page numbers
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
        text = re.sub(r'^[ \t]*\d+[ \t]*$', '', text, flags=re.MULTILINE)
        
        # Remove any isolated numbers that might be page numbers
        text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
        
        # Clean up any duplicate spaces and newlines
        text = re.sub(r'\s+', ' ', text)
        
        # Remove any "Choice X is incorrect/correct" statements
        text = re.sub(r'Choice\s+[A-F]\s+is\s+(?:in)?correct\..*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        
        return text.strip()

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

@app.post("/process")
async def handle_pdf(
    file: UploadFile = File(...),
    start_page: Optional[int] = Form(None),
    end_page: Optional[int] = Form(None)
):
    """Process a PDF file to extract quiz questions"""
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"Request {request_id}: Processing file {file.filename}")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"Request {request_id}: Saved to {tmp_path}")
        
        # Set page range if provided
        page_range = None
        if start_page is not None and end_page is not None:
            page_range = (int(start_page), int(end_page))
            logger.info(f"Request {request_id}: Using page range {page_range}")
        
        try:
            # Process with timeout
            result = await asyncio.wait_for(
                asyncio.to_thread(process_pdf, tmp_path, page_range, request_id),
                timeout=55.0  # Just under Vercel's 60s limit
            )
        except asyncio.TimeoutError:
            logger.error(f"Request {request_id}: Processing timed out")
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=408, 
                detail="PDF processing timed out. Please try a smaller PDF file or fewer pages."
            )
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        # Check for errors
        if "error" in result and not result.get("questions", []):
            logger.error(f"Request {request_id}: Processing error: {result['error']}")
            raise HTTPException(status_code=500, detail=result["error"])
        
        logger.info(f"Request {request_id}: Successfully processed {len(result.get('questions', []))} questions")
        return result
        
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing PDF: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

def process_pdf(file_path: str, page_range: Optional[Tuple[int, int]] = None, request_id: str = "unknown") -> Dict[str, Any]:
    """Process a PDF file using PDFParser"""
    try:
        logger.info(f"Request {request_id}: Starting PDF processing")
        
        with PDFParser(file_path, page_range) as parser:
            result = parser.process()
        
        logger.info(f"Request {request_id}: PDF processing completed")
        return result
    
    except Exception as e:
        logger.error(f"Request {request_id}: Error in process_pdf: {str(e)}")
        logger.error(traceback.format_exc())
        return {"error": f"Failed to process PDF: {str(e)}", "questions": [], "total_pages": 0}

@app.post("/pdf-info")
async def get_pdf_info(file: UploadFile = File(...)):
    """Get basic PDF information without processing content"""
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
        
        # Extract TOC (table of contents) if available
        toc = doc.get_toc()
        
        # Get document metadata
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", "")
        }
        
        # Calculate document hash for caching/tracking
        md5hash = hashlib.md5()
        md5hash.update(content)
        doc_hash = md5hash.hexdigest()
        
        # Get page sizes to detect inconsistent page sizes
        page_sizes = []
        for i in range(min(total_pages, 10)):  # Check first 10 pages
            page = doc[i]
            page_sizes.append((page.rect.width, page.rect.height))
        
        has_consistent_page_size = len(set(page_sizes)) <= 2  # Allow up to 2 different page sizes
        
        doc.close()
        os.unlink(tmp_path)
        
        return {
            "total_pages": total_pages,
            "file_size_mb": round(file_size, 2),
            "metadata": metadata,
            "has_toc": len(toc) > 0,
            "toc_entries": len(toc),
            "hash": doc_hash,
            "has_consistent_page_size": has_consistent_page_size
        }
    
    except Exception as e:
        logger.error(f"Request {request_id}: Error getting PDF info: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to get PDF info: {str(e)}")

@app.get("/health")
def health_check():
    return {
        "status": "ok", 
        "message": "Quiz PDF Parser API is running",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/")
def read_root():
    return {
        "message": "PDF Quiz Generator API", 
        "docs": "/docs",
        "status": "/health"
    }

@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}

# Test functions to help with debugging
def test_parser(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """Test the parser with a local file"""
    with PDFParser(file_path, page_range) as parser:
        return parser.process()

def analyze_block_types(file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict[str, int]:
    """Analyze block types in a PDF file"""
    with PDFParser(file_path, page_range) as parser:
        parser.extract_blocks()
        parser.classify_blocks()
        
        type_counts = Counter(block.block_type for block in parser.blocks)
        return {str(block_type): count for block_type, count in type_counts.items()}

def dump_blocks(file_path: str, output_path: str, page_range: Optional[Tuple[int, int]] = None) -> None:
    """Dump blocks to a file for inspection"""
    with PDFParser(file_path, page_range) as parser:
        parser.extract_blocks()
        parser.classify_blocks()
        
        with open(output_path, "w") as f:
            for i, block in enumerate(parser.blocks):
                f.write(f"Block {i}:\n")
                f.write(f"  Type: {block.block_type}\n")
                f.write(f"  Page: {block.page_num}\n")
                f.write(f"  BBox: {block.bbox}\n")
                f.write(f"  Text: {block.text[:100]}{'...' if len(block.text) > 100 else ''}\n")
                f.write(f"  Metadata: {block.metadata}\n")
                f.write("\n")
