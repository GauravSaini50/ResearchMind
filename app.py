from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings

from src.LoadandText import extract_text_from_pdf, extract_pdf_sections
from src.DetectandSplitsections import refine_sections, split_sections_with_content
from src.getsummary import generate_detailed_summary
from src.create_vectordb import create_vector_db

from dotenv import load_dotenv
import os
import uuid

load_dotenv()

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

groq_api_key = os.getenv("GROQ_API_KEY")
llm_model = os.getenv("LLM_MODEL")
embedding_model = os.getenv("EMBEDDING_MODEL")

llm = ChatGroq(
    groq_api_key=groq_api_key,
    model_name=llm_model,
    max_tokens=8192
)

embedder = HuggingFaceEmbeddings(
    model_name=embedding_model
)

# Store multiple research papers
papers = {}

# Combined FAISS database
vector_db = None


def get_response_text(response):
    if isinstance(response, str):
        return response.strip()

    if hasattr(response, "content"):
        return response.content.strip()

    return str(response)


@app.route("/")
def index():
    return render_template("index.html")


# -----------------------------------
# MULTIPLE PDF UPLOAD
# -----------------------------------

@app.route("/upload", methods=["POST"])
def upload_pdf():

    global vector_db

    files = request.files.getlist("files")

    # Backward compatibility with old frontend
    if not files or not any(f.filename for f in files):
        files = request.files.getlist("file")

    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    uploaded = []
    errors = []

    for file in files:

        if not file.filename:
            continue

        if not file.filename.lower().endswith(".pdf"):
            errors.append(f"{file.filename}: Only PDF files are supported")
            continue

        paper_id = str(uuid.uuid4())[:8]

        filename = secure_filename(file.filename)

        saved_name = f"{paper_id}_{filename}"

        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            saved_name
        )

        try:
            file.save(filepath)

            # Extract complete text
            extracted_text = extract_text_from_pdf(filepath)

            if not extracted_text or not extracted_text.strip():
                raise ValueError("No readable text extracted from PDF")

            # Extract research sections
            extracted_sections = extract_pdf_sections(
                full_text=extracted_text
            )

            refined_sections = refine_sections(
                extracted_sections,
                llm
            )

            section_with_content = split_sections_with_content(
                extracted_text,
                refined_sections
            )

            # Store individual paper
            papers[paper_id] = {
                "id": paper_id,
                "filename": filename,
                "text": extracted_text,
                "topics": section_with_content
            }

            uploaded.append({
                "id": paper_id,
                "filename": filename,
                "topics": list(section_with_content.keys())
            })

        except Exception as e:
            errors.append(f"{filename}: {str(e)}")

    if not uploaded:
        return jsonify({
            "error": "No papers could be processed",
            "details": errors
        }), 400

    try:
        # Rebuild combined database using all uploaded papers
        vector_db = create_vector_db(
            embedder=embedder,
            papers=list(papers.values())
        )

    except Exception as e:
        return jsonify({
            "error": "Vector database creation failed",
            "details": str(e)
        }), 500

    return jsonify({
        "message": "Papers uploaded successfully",
        "papers": uploaded,
        "errors": errors
    })


# -----------------------------------
# LIST UPLOADED PAPERS
# -----------------------------------

@app.route("/papers", methods=["GET"])
def get_papers():

    result = []

    for paper in papers.values():

        result.append({
            "id": paper["id"],
            "filename": paper["filename"],
            "topics": list(paper["topics"].keys())
        })

    return jsonify({"papers": result})


# -----------------------------------
# INDIVIDUAL PAPER SUMMARY
# -----------------------------------

@app.route("/summary", methods=["POST"])
def get_summary():

    data = request.get_json() or {}

    paper_id = data.get("paper_id")
    topic = data.get("topic")

    paper = papers.get(paper_id)

    if not paper:
        return jsonify({"error": "Research paper not found"}), 404

    topic_content = paper["topics"].get(topic)

    if topic_content is None:
        return jsonify({"error": "Topic not found"}), 404

    try:
        summary = generate_detailed_summary(
            topic_content,
            llm
        )

        return jsonify({"summary": summary})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------------
# MULTIPLE RESEARCH PAPER COMPARISON
# -----------------------------------

@app.route("/compare", methods=["POST"])
def compare_papers():

    data = request.get_json() or {}

    paper_ids = list(dict.fromkeys(data.get("paper_ids", [])))

    if len(paper_ids) < 2:
        return jsonify({
            "error": "Select at least two research papers"
        }), 400

    if len(paper_ids) > 5:
        return jsonify({
            "error": "Compare a maximum of five papers at a time"
        }), 400

    selected_papers = []

    for paper_id in paper_ids:

        paper = papers.get(paper_id)

        if not paper:
            return jsonify({
                "error": f"Paper not found: {paper_id}"
            }), 404

        selected_papers.append(paper)

    paper_context = ""

    for index, paper in enumerate(selected_papers, start=1):

        paper_context += f"""

        PAPER {index}
        Paper Name: {paper['filename']}

        Research Content:
        {paper['text'][:8000]}

        --------------------------------
        """

    prompt = f"""
You are an expert academic research analyst.

Compare the following research papers carefully.

{paper_context}

Prepare a detailed comparative analysis using these headings:

1. Research Objectives
2. Research Problems
3. Methodologies Used
4. Datasets and Study Materials
5. Important Findings
6. Similarities Between Papers
7. Differences Between Papers
8. Limitations of Each Paper
9. Common Research Gaps
10. Contradictory Findings
11. Future Research Directions

IMPORTANT INSTRUCTIONS:

- Compare each paper separately.
- Mention the actual paper filename.
- Do not invent information.
- If information is unavailable, mention it.
- Identify research gaps based on the supplied papers.
- Clearly distinguish reported findings from your own analysis.

Write a detailed, structured academic comparison.
"""

    try:

        response = llm.invoke(prompt)

        return jsonify({
            "comparison": get_response_text(response),
            "compared_papers": [
                p["filename"] for p in selected_papers
            ]
        })

    except Exception as e:

        return jsonify({"error": str(e)}), 500


# -----------------------------------
# MULTI-PAPER GROUP CHAT
# -----------------------------------

@app.route("/chat", methods=["POST"])
def chat():

    global vector_db

    data = request.get_json() or {}

    user_message = data.get("message", "").strip()

    selected_ids = data.get("paper_ids") or list(papers.keys())

    if not user_message:
        return jsonify({
            "error": "Please enter a question"
        }), 400

    if not papers:
        return jsonify({
            "error": "Please upload research papers first"
        }), 400

    if not vector_db:
        return jsonify({
            "error": "Vector database is not ready"
        }), 500

    if not selected_ids:
        return jsonify({
            "error": "No research papers selected"
        }), 400

    if any(pid not in papers for pid in selected_ids):
        return jsonify({
            "error": "Invalid paper selection"
        }), 400

    try:

        # Retrieve chunks only from selected papers
        metadata_filter = {
            "paper_id": {
                "$in": selected_ids
            }
        }

        retrieved_docs = vector_db.similarity_search(
            user_message,
            k=8,
            filter=metadata_filter
        )

        if not retrieved_docs:
            return jsonify({
                "error": "No relevant information found in selected papers"
            }), 404

        context = ""

        source_names = set()

        for doc in retrieved_docs:

            source = doc.metadata.get(
                "source",
                "Unknown paper"
            )

            source_names.add(source)

            context += f"""

            Source Paper: {source}

            Research Content:
            {doc.page_content}

            ------------------------
            """

        prompt = f"""
You are Research Mind, an advanced multi-paper research assistant.

The user has asked a question about selected research papers.

Use ONLY the supplied research context to answer.

Instructions:

1. Answer clearly and in detail.
2. Combine information from multiple papers when appropriate.
3. Identify which paper supports each important finding.
4. Compare papers when necessary.
5. Mention similarities and differences.
6. Explain conflicting findings.
7. Never invent citations or research findings.
8. If context is insufficient, explain what is missing.
9. Distinguish evidence from your own interpretation.

RESEARCH CONTEXT:

{context}

USER QUESTION:

{user_message}

Provide a structured academic answer.
"""

        response = llm.invoke(prompt)

        return jsonify({
            "response": get_response_text(response),
            "sources": list(source_names)
        })

    except Exception as e:

        print("GROUP CHAT ERROR:", str(e))

        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )
