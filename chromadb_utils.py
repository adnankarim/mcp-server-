#!/usr/bin/env python3
"""
ChromaDB Utilities - Simple and reliable database management

This module provides a simple, reliable way to reset ChromaDB by
deleting the entire directory, which is the safest approach.
"""

import os
import shutil
import chromadb
from chromadb.config import Settings
from typing import Optional
import time


def safe_reset_chromadb(chroma_path: str = "./chroma_db") -> bool:
    """Safely reset ChromaDB by deleting the entire directory.
    
    This is the most reliable way to reset ChromaDB and avoid corruption issues.
    
    Args:
        chroma_path: Path to the ChromaDB directory
        
    Returns:
        True if reset was successful, False otherwise
    """
    try:
        if os.path.exists(chroma_path):
            # Add a small delay to ensure any file handles are released
            time.sleep(0.1)
            shutil.rmtree(chroma_path)
            print(f"Successfully deleted ChromaDB directory: {chroma_path}")
        else:
            print(f"ChromaDB directory does not exist: {chroma_path}")
        
        return True
        
    except Exception as e:
        print(f"Error deleting ChromaDB directory: {e}")
        return False

