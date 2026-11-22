#!/usr/bin/env python3
"""
RAG MCP Server - Simplified Demo Version

This server provides tools for:
1. Ingesting files into a local vector database (ChromaDB)
2. Retrieving relevant information based on queries
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any

# FastMCP imports
from fastmcp import FastMCP

# ChromaDB imports
import chromadb
from chromadb.config import Settings

# LlamaParse and LlamaIndex imports
from llama_parse import LlamaParse
from llama_index.core import SimpleDirectoryReader
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = "rag_documents"
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

# Initialize FastMCP server
mcp = FastMCP("RAG Server")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag_server")

def get_chroma_client() -> chromadb.PersistentClient:
    """Get the ChromaDB client instance."""
    
    persist_directory = get_database_directory()
    
    return chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
    
def get_database_directory():
    """Get the ChromaDB persistent directory path."""
    env_db_dir = os.getenv('LLAMA_RAG_DB_DIR')
    db_path = Path(env_db_dir).expanduser().resolve() if env_db_dir else Path('./chroma')
    db_path.mkdir(parents=True, exist_ok=True)
    logger.info("Database directory: %s (env set: %s)", str(db_path), bool(env_db_dir))
    return db_path

def get_data_directory():
    """Get the data directory path."""
    env_data_dir = os.getenv('LLAMA_RAG_DATA_DIR')
    data_path = Path(env_data_dir).expanduser().resolve() if env_data_dir else Path('./data')
    data_path.mkdir(parents=True, exist_ok=True)
    logger.info("Data directory: %s (env set: %s)", str(data_path), bool(env_data_dir))
    return data_path

def chunk_text(text: str, max_chars: int = 5000):
    if not text:
        return []
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

def initialize_chromadb():
    """Initialize ChromaDB client and collection."""
    try:
        logger.info("Initializing ChromaDB")
        
        chroma_client = get_chroma_client()
        logger.info("ChromaDB client created")
        
        chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Collection for RAG document storage"}
        )
        
        logger.info("Collection ready: %s", COLLECTION_NAME)
        logger.info("Initialization complete")
    except Exception:
        logger.exception("Failed to initialize ChromaDB")
        raise

 

# Initialize ChromaDB on startup
initialize_chromadb()

@mcp.tool
def query_documents(query: str, n_results: int = 5) -> str:
    """
    Query the vector database to retrieve relevant documents.
    
    Args:
        query: The search query
        n_results: Number of results to return (default: 5)
    
    Returns:
        Formatted string with relevant documents
    """
    chroma_client = get_chroma_client()
    collection = chroma_client.get_collection(name=COLLECTION_NAME)
    
    logger.info("Query: %s (n_results=%d)", query, n_results)
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )
    
    if not results["documents"] or not results["documents"][0]:
        logger.info("No results for query")
        return "No relevant documents found for your query."
    
    # Format results
    formatted_results = []
    documents = results["documents"][0]
    metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
    distances = results["distances"][0] if results["distances"] else [0] * len(documents)
    
    for i, (doc, metadata, distance) in enumerate(zip(documents, metadatas, distances)):
        result_text = f"\n--- Result {i+1} ---\n"
        result_text += f"Content: {doc}\n"
        result_text += f"Source: {metadata.get('file_name', 'Unknown')}\n"
        result_text += f"Similarity Score: {1 - distance:.3f}\n"
        formatted_results.append(result_text)
    
    response = f"Found {len(documents)} relevant documents for query: '{query}'\n"
    response += "\n".join(formatted_results)
    
    logger.info("Returned %d results", len(documents))
    return response

@mcp.tool
def list_ingested_files() -> str:
    """
    List all files that have been ingested into the vector database.
    
    Returns:
        Formatted string with information about ingested files
    """
    chroma_client = get_chroma_client()
    collection = chroma_client.get_collection(name=COLLECTION_NAME)
    
    all_docs = collection.get(include=["metadatas"])
    
    if not all_docs["metadatas"]:
        logger.info("No ingested files")
        return "No files have been ingested yet."
    
    # Get unique file names
    file_names = set()
    for metadata in all_docs["metadatas"]:
        if metadata and "file_name" in metadata:
            file_names.add(metadata["file_name"])
    
    if not file_names:
        return "No files have been ingested yet."
    
    response = f"Ingested Files ({len(file_names)} total):\n\n"
    for i, file_name in enumerate(sorted(file_names), 1):
        response += f"{i}. {file_name}\n"
    
    total_chunks = len(all_docs["metadatas"])
    response += f"\nTotal chunks in database: {total_chunks}"
    logger.info("Listed %d files, %d chunks", len(file_names), total_chunks)
    
    return response

@mcp.tool
def server_status() -> str:
    data_path = get_data_directory()
    db_path = get_database_directory()
    chroma_client = get_chroma_client()
    llama_index_api_key = os.getenv('LLAMA_CLOUD_API_KEY')
    collection = chroma_client.get_collection(name=COLLECTION_NAME)
    all_docs = collection.get(include=["metadatas"])
    file_names = set()
    for metadata in all_docs["metadatas"]:
        if metadata and "file_name" in metadata:
            file_names.add(metadata["file_name"])
    count_files = len(file_names)
    logger.info("Status: data=%s db=%s files=%d", str(data_path), str(db_path), count_files)
    return f"Data directory: {str(data_path)}\nDatabase directory: {str(db_path)}\nIngested files: {count_files}\nLLAMA_CLOUD_API_KEY: ****{llama_index_api_key[-4:]}"

@mcp.tool
def ingest_data_directory() -> str:
    """
    Ingest (or reingest) all files from the data directory into the vector database.
    If other files are already ingested, they will be overwritten.
    
    Returns:
        Status message indicating success
    """
    
    logger.info("Ingesting data directory")
    chroma_client = get_chroma_client()
    try:
        chroma_client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        logger.info("Collection %s did not exist or could not be deleted; continuing", COLLECTION_NAME)
    collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Collection for RAG document storage"}
    )
    
    try:
        parser = LlamaParse(api_key=LLAMA_CLOUD_API_KEY, result_type="text")
        file_extractor = {
            ".pdf": parser,
            ".docx": parser,
            ".pptx": parser,
            ".doc": parser,
            ".ppt": parser
        }
        data_path = get_data_directory()
        documents = SimpleDirectoryReader(
            input_dir=str(data_path),
            file_extractor=file_extractor,
            recursive=True
        ).load_data()
        
        logger.info("Documents loaded: %d", len(documents) if documents else 0)
        
        for doc in documents:
            chunks = chunk_text(doc.text, 8000)
            for idx, chunk in enumerate(chunks):
                collection.add(
                    documents=[chunk],
                    metadatas=[doc.metadata.copy() if doc.metadata else {}],
                    ids=[f"{doc.id_}_chunk_{idx}"]
                )
            logger.info("Chunks ingested: %d", len(chunks))
            
    except Exception:
        logger.exception("Reingest failed")
        raise
    
    final_count = collection.count()
    logger.info("Ingest complete. Document count: %d", final_count)
    return f"Successfully ingested data directory. Database now contains {final_count} documents."

if __name__ == "__main__":
    # Run the MCP server
    mcp.run("stdio")