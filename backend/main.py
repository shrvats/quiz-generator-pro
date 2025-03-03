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

After submission, the answer should pop like this:
------------------------------------------------
The correct answer is C.
Issuing preferred shares that automatically convert to common shares upon a takeover attempt dilutes the voting power and ownership percentage of the acquirer, directly impacting the feasibility and attractiveness of the takeover. This is a classic example of a poison pill tactic.
A is incorrect. While granting a bonus to executives if the company remains independent might seem like a deterrent, it primarily serves as a retention tool rather than a structural mechanism that complicates or deters a hostile takeover directly. It does not affect the company's ownership structure or operational control during a takeover.
B is incorrect. A staggered board system, where only a fraction of directors are elected in any single year, can indeed make hostile takeovers more difficult by prolonging the process required to gain control of the board. However, this is generally considered a separate governance mechanism rather than a classic poison pill, which typically involves changes to share distribution or ownership rights.
D is incorrect. Creating a subsidiary to hold critical assets like intellectual property might make the main company less attractive to take over, but it does not directly interfere with the mechanics of a takeover or change the conditions during a takeover attempt. This strategy is more about asset protection and less about the immediate defensive reaction characteristic of poison pills.

Things to Remember
A poison pill, or shareholder rights plan, is a defensive strategy used by corporations to deter hostile takeovers by diluting the shares held by potential acquirers, making a takeover less attractive or more costly.
Examples include issuing new shares to existing shareholders at a discount, allowing shareholders (except the acquirer) to buy more shares at a discount, or creating new classes of shares that increase voting rights for existing shareholders upon a trigger event.
In 2012, Netflix adopted a poison pill after activist investor Carl Icahn acquired a significant stake. This plan was designed to be triggered if an individual or group acquired 10% (or 20% for institutional investors) of Netflix's shares, effectively preventing a hostile takeover without board approval.
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
from pydantic import BaseModel, Field, validator

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
        if self.validation_issues:
            result["validation_issues"] = self.validation_issues
        return result

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
            "warnings": self.warnings
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

###################################
#     PDF Processing Core       #
###################################

class PDFTextCleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        text = re.sub(r'(?:©|Copyright\s*©?)\s*\d{4}(?:-\d{4})?\s*[A-Za-z0-9]+(?:Prep)?\.?.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
        text = re.sub(r'^[ \t]*\d+[ \t]*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n\s*\d+\s*$', '\n', text, flags=re.MULTILINE)
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
        if self.method == ParsingMethod.TEXT_BASED:
            return self._extract_text_based(doc, page_iterator)
        elif self.method == ParsingMethod.BLOCK_BASED:
            return self._extract_block_based(doc, page_iterator)
        else:
            try:
                questions = self._extract_block_based(doc, page_iterator)
                if questions:
                    return questions
            except Exception as e:
                logger.warning(f"Block-based extraction failed: {str(e)}, falling back to text-based")
            return self._extract_text_based(doc, page_iterator)
    
    def _extract_text_based(self, doc, page_iterator) -> List[QuestionData]:
        all_text = ""
        for page_num in page_iterator:
            page = doc[page_num]
            page_text = page.get_text("text")
            all_text += page_text + "\n"
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
                question_data = self._process_question_text(question_text, int(q_id))
                if question_data and question_data.text:
                    questions.append(question_data)
            except Exception as e:
                logger.error(f"Error processing question {i+1}: {str(e)}")
                self.stats.errors.append(f"Error processing question {i+1}: {str(e)}")
        return questions
    
    def _extract_block_based(self, doc, page_iterator) -> List[QuestionData]:
        blocks = self._extract_blocks(doc, page_iterator)
        self.stats.total_blocks = len(blocks)
        classified_blocks = self._classify_blocks(blocks)
        question_blocks = self._group_blocks_by_question(classified_blocks)
        self.stats.questions_found = len(question_blocks)
        questions = []
        for i, q_blocks in enumerate(question_blocks):
            try:
                q_id = q_blocks[0].metadata.get("question_id") if q_blocks else i + 1
                question_data = self._process_question_blocks(q_blocks, q_id)
                if question_data and question_data.text:
                    questions.append(question_data)
            except Exception as e:
                logger.error(f"Error processing question from blocks {i+1}: {str(e)}")
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
                self.stats.math_expressions_found += 1
        return blocks
    
    def _group_blocks_by_question(self, blocks: List[TextBlock]) -> List[List[TextBlock]]:
        question_starts = []
        for i, block in enumerate(blocks):
            if block.block_type == BlockType.QUESTION_ID:
                question_starts.append(i)
        if not question_starts:
            logger.warning("No question boundaries found")
            return []
        question_blocks = []
        for i, start_idx in enumerate(question_starts):
            end_idx = question_starts[i+1] if i+1 < len(question_starts) else len(blocks)
            question_blocks.append(blocks[start_idx:end_idx])
        return question_blocks
    
    def _process_question_text(self, text: str, q_id: int) -> Optional[QuestionData]:
        options = self._extract_options_from_text(text)
        self.stats.options_found += len(options)
        text, correct_answer = self.cleaner.remove_answer_from_text(text)
        text = re.sub(r'^(?:Question\s+\d+(?:\(Q\.\d+\))?|Q\.?\s*\d+(?:\(Q\.\d+\))?)\s*', '', text)
        # APPENDED CHANGE: Extract "Things to Remember" section (if present) and remove it from the question text
        text, things_to_remember = self._extract_things_to_remember(text)
        text, explanation = self._extract_explanation(text)
        bidder_data = self._extract_bidder_data(text)
        if bidder_data:
            self.stats.bidder_data_found += 1
        contains_math = self._check_for_math(text)
        if contains_math:
            self.stats.math_expressions_found += 1
        question_text = self.cleaner.clean_text(text)
        if len(question_text) < MIN_QUESTION_LENGTH:
            return None
        question = QuestionData(
            id=q_id,
            text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            things_to_remember=things_to_remember,
            bidder_data=bidder_data,
            has_bidder_data=bool(bidder_data),
            contains_math=contains_math
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
        question = QuestionData(
            id=q_id,
            text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            things_to_remember=things_to_remember,
            bidder_data=bidder_data,
            has_bidder_data=bool(bidder_data),
            table_html=table_html,
            has_table=has_table,
            contains_math=contains_math,
            source_blocks=blocks
        )
        validation_issues = self._validate_question(question)
        if validation_issues:
            question.validation_issues = validation_issues
            self.stats.questions_with_issues += 1
        return question
    
    def _extract_options_from_text(self, text: str) -> Dict[str, str]:
        options = {}
        option_pattern = r'\n\s*([A-F])[\.\)]\s+(.*?)(?=\n\s*[A-F][\.\)]|\Z)'
        option_matches = list(re.finditer(option_pattern, text, re.DOTALL))
        for match in option_matches:
            letter = match.group(1)
            option_text = match.group(2).strip()
            option_text = self.cleaner.clean_option_text(option_text)
            if option_text:
                options[letter] = option_text
        if not options:
            alt_pattern = r'([A-F])[\.\)]\s*(.*?)(?=\s*[A-F][\.\)]|\Z)'
            alt_matches = list(re.finditer(alt_pattern, text, re.DOTALL))
            for match in alt_matches:
                letter = match.group(1)
                option_text = match.group(2).strip()
                option_text = self.cleaner.clean_option_text(option_text)
                if option_text:
                    options[letter] = option_text
        return options
    
    def _extract_things_to_remember(self, text: str) -> Tuple[str, str]:
        """Extract 'Things to Remember' section from text.
           APPENDED CHANGE: Capture header with optional colon and all text until the end.
        """
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
        math_patterns = [
            r'[=\+\-\*\/\^\(\)]',
            r'\d+\.\d+',
            r'[αβγδεζηθικλμνξοπρστυφχψω]',
            r'[ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ]',
            r'√|∑|∫|∂|∇|∞',
            r'\b[A-Za-z]\s*=',
            r'log|exp|sin|cos|tan',
            r'var|std|avg|mean',
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
        html = "<table border='1'>\n"
        if rows:
            html += "<tr>\n"
            for cell in rows[0]:
                html += f"  <th>{cell}</th>\n"
            html += "</tr>\n"
            for row in rows[1:]:
                html += "<tr>\n"
                for cell in row:
                    css_class = ""
                    if re.match(r'^[\d\.\$]+$', cell):
                        css_class = " align='right'"
                    html += f"  <td{css_class}>{cell}</td>\n"
                html += "</tr>\n"
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
    version="1.0.0"
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

@app.post("/batch-process")
async def batch_process_pdfs(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    batch_id = str(uuid.uuid4())
    file_ids = []
    for file in files:
        request_id = str(uuid.uuid4())
        file_ids.append(request_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        update_processing_status(request_id, "queued", 0.0, f"PDF processing queued for {file.filename}")
        background_tasks.add_task(process_pdf_task, tmp_path, request_id, None)
    processing_status[batch_id] = {
        "request_id": batch_id,
        "status": "batch_processing",
        "file_ids": file_ids,
        "total_files": len(files),
        "timestamp": time.time()
    }
    return {
        "batch_id": batch_id,
        "file_ids": file_ids,
        "total_files": len(files),
        "status_endpoint": f"/batch-status/{batch_id}"
    }

@app.get("/batch-status/{batch_id}")
async def get_batch_status(batch_id: str):
    batch_info = processing_status.get(batch_id)
    if not batch_info or batch_info.get("status") != "batch_processing":
        raise HTTPException(status_code=404, detail=f"No batch found with ID {batch_id}")
    file_ids = batch_info.get("file_ids", [])
    file_statuses = []
    for file_id in file_ids:
        status = processing_status.get(file_id, {
            "request_id": file_id,
            "status": "unknown",
            "progress": 0.0,
            "message": "Status not found"
        })
        file_statuses.append(status)
    completed = sum(1 for s in file_statuses if s.get("status") == "completed")
    error_count = sum(1 for s in file_statuses if s.get("status") == "error")
    overall_progress = sum(s.get("progress", 0) for s in file_statuses) / len(file_statuses) if file_statuses else 0
    return {
        "batch_id": batch_id,
        "total_files": len(file_ids),
        "completed": completed,
        "errors": error_count,
        "overall_progress": overall_progress,
        "file_statuses": file_statuses
    }

@app.get("/health")
async def health_check():
    import psutil
    process = psutil.Process()
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime": time.time() - process.create_time(),
        "memory_usage_mb": process.memory_info().rss / (1024 * 1024)
    }

@app.get("/")
def read_root():
    return {
        "message": "PDF Quiz Parser API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_check": "/health"
    }

@app.options("/{path:path}")
async def options_route(request: Request, path: str):
    return {}

###############################
#      Test Cases             #
###############################

def test_option_extraction():
    extractor = PDFQuestionExtractor()
    test_cases = [
        """
        A. Option text one
        B. Option text two
        C. Option text three
        D. Option text four
        """,
        """
        A.Option text one
        B.Option text two
        C.Option text three
        D.Option text four
        """,
        """
        A) Option text one
        B) Option text two
        C) Option text three
        D) Option text four
        """,
        """
        A. Option text one
        B) Option text two
        C.Option text three
        D. Option text four
        """,
        """
        A. Option text one
        B. Option text two (correct answer)
        C. Option text three
        D. Option text four
        """,
        """
        A. Option text one
        B. Option text two
        C. Option text three
        D. 
        """,
        """
        A. 100,000 at $25
        B. 200,000 at $30
        C. 300,000 at $35
        D. 400,000 at $40
        """
    ]
    results = []
    for i, test_case in enumerate(test_cases):
        options = extractor._extract_options_from_text(test_case)
        results.append({
            "case": i + 1,
            "options_found": len(options),
            "options": options
        })
    return results

def test_answer_extraction():
    cleaner = PDFTextCleaner()
    test_cases = [
        "The correct answer is A. This is the explanation.",
        "Correct answer: B. The explanation follows.",
        "The answer is C.",
        "Answer: D. With explanation.",
        "The answer is E. This is why.",
        "The correct choice is F.",
        "No answer here."
    ]
    results = []
    for i, test_case in enumerate(test_cases):
        cleaned_text, answer = cleaner.remove_answer_from_text(test_case)
        results.append({
            "case": i + 1,
            "original": test_case,
            "cleaned": cleaned_text,
            "answer": answer
        })
    return results

def test_real_pdf(file_path):
    processor = PDFProcessor(file_path)
    result = processor.process()
    questions = result.get("questions", [])
    stats = result.get("stats", {})
    analysis = {
        "total_questions": len(questions),
        "questions_with_options": sum(1 for q in questions if q.get("options")),
        "questions_with_correct_answer": sum(1 for q in questions if q.get("correct")),
        "questions_with_explanation": sum(1 for q in questions if q.get("explanation")),
        "questions_with_issues": sum(1 for q in questions if q.get("validation_issues")),
        "questions_with_bidder_data": sum(1 for q in questions if q.get("has_bidder_data", False)),
        "questions_with_tables": sum(1 for q in questions if q.get("has_table", False)),
        "questions_with_math": sum(1 for q in questions if q.get("contains_math", False)),
        "stats": stats
    }
    return analysis

def test_edge_cases():
    extractor = PDFQuestionExtractor()
    edge_cases = [
        {
            "text": "Question 1. What is 2+2? The correct answer is C. Four.",
            "expected_answer": "C"
        },
        {
            "text": "Question 2. Choose:\nA. Option A\nB. Option B\nC. Option C",
            "expected_options": ["B", "C"]
        },
        {
            "text": "A 200,000 $40.50 B 150,000 $39.50 C 400,000 $41.00",
            "expected_bidders": 3
        },
        {
            "text": "Question 4. Choose:\nA. Option A\nB. Option B\nThe correct answer is C.",
            "expected_issues": ["Correct answer 'C' not in options"]
        },
        {
            "text": "Question 5. Choose:\nA. OK\nB. No\nC. Yes\nD. Maybe",
            "expected_issues": ["Option A is very short", "Option B is very short", "Option C is very short"]
        }
    ]
    results = []
    for i, case in enumerate(edge_cases):
        question = extractor._process_question_text(case["text"], i + 1)
        result = {
            "case": i + 1,
            "passed": False,
            "details": {}
        }
        if "expected_answer" in case:
            result["details"]["expected_answer"] = case["expected_answer"]
            result["details"]["actual_answer"] = question.correct_answer
            result["passed"] = question.correct_answer == case["expected_answer"]
        if "expected_options" in case:
            result["details"]["expected_options"] = case["expected_options"]
            result["details"]["actual_options"] = list(question.options.keys())
            result["passed"] = all(opt in question.options for opt in case["expected_options"])
       
