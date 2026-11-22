from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate


def get_qa_chain(vectordb, llm):

    retriever = vectordb.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 8}
    )

    prompt_template = """
You are Research Mind, an intelligent academic research assistant.

Answer the user's question using ONLY the provided research context.

Instructions:

1. Understand information from all relevant research papers.
2. Combine findings when the question requires comparison.
3. Identify similarities and differences.
4. Never mix findings from different papers.
5. Mention the paper name when presenting important findings.
6. If papers disagree, explain the disagreement.
7. If information is partially available, explain what is available.
8. Do not invent research findings or references.

Context:
{context}

Question:
{question}

Provide a structured and detailed answer.
"""

    PROMPT = PromptTemplate(
        template=prompt_template,
        input_variables=["context", "question"]
    )

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={
            "prompt": PROMPT
        }
    )

    return chain
