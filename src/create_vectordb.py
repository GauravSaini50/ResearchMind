from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
import os


def create_vector_db(text=None, embedder=None, papers=None):

    if embedder is None:
        raise ValueError("Embedding model is required")

    # Support the previous single-paper implementation
    if papers is None:
        papers = [{
            "id": "paper_1",
            "filename": "Research Paper",
            "text": text or ""
        }]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " "]
    )

    all_docs = []

    # Process every research paper
    for paper in papers:

        paper_id = paper["id"]
        filename = paper["filename"]
        paper_text = paper["text"]

        chunks = splitter.split_text(paper_text)

        for index, chunk in enumerate(chunks):

            doc = Document(
                page_content=chunk,
                metadata={
                    "paper_id": paper_id,
                    "source": filename,
                    "chunk": index
                }
            )

            all_docs.append(doc)

    if not all_docs:
        raise ValueError("No text available to create vector database")

    # Create combined FAISS database
    vectordb = FAISS.from_documents(
        all_docs,
        embedding=embedder
    )

    # Save database locally
    os.makedirs("research_paper_vector_db", exist_ok=True)

    vectordb.save_local("research_paper_vector_db")

    return vectordb
