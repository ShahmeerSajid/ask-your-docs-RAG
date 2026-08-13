"""
rag_chain.py

Loads the persisted FAISS index and exposes a conversational RAG chain, built with
plain LCEL runnables (langchain.chains' old create_retrieval_chain /
create_history_aware_retriever helpers were removed in langchain 1.x, so this wires
the same logic together by hand -- it's a handful of Runnables, not "less" of a RAG
pipeline than the deprecated helpers gave you).

Multi-turn flow:
    1. contextualize the latest question against chat history
       (e.g. "what about his SLAM work?" -> "What has Shahmeer done with SLAM?")
    2. retrieve relevant chunks using the contextualized question
    3. answer using only the retrieved context + conversation history

Chat history is kept in memory per session_id (not persisted to disk -- restarting
the server clears it). That's fine for a personal/demo project; swap `_session_store`
for a Redis- or DB-backed history if this ever needs to survive restarts or scale to
multiple processes.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

load_dotenv()

INDEX_DIR = Path(__file__).parent / "faiss_index"

# Local embedding model -- runs on your machine, no API key or network call needed.
# Google's hosted embedding endpoint has an ongoing, intermittent server-side bug
# (confirmed by multiple developers), so embeddings run locally instead. Gemini is
# still used below for the chat/generation half, which has been reliable.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3-flash-preview")
TOP_K = int(os.getenv("TOP_K", 4))

CONTEXTUALIZE_SYSTEM_PROMPT = """Given a chat history and the latest user question, \
which might reference context in the chat history, rewrite it as a standalone \
question that can be understood without the chat history. Do NOT answer the \
question -- just rewrite it if needed, otherwise return it as-is. Return ONLY the \
rewritten question, nothing else."""

QA_SYSTEM_PROMPT = """You are a helpful assistant that answers questions using ONLY \
the provided context, which comes from the user's own documents.

Rules:
- If the answer isn't in the context, say you don't know based on the provided documents.
- Be concise and direct.
- When useful, mention which source file(s) the answer came from.

Context:
{context}
"""

_vectorstore = None
_llm = None
_conversational_chain = None

# In-memory chat history store: session_id -> ChatMessageHistory
_session_store: dict[str, BaseChatMessageHistory] = {}


def _get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in _session_store:
        _session_store[session_id] = ChatMessageHistory()
    return _session_store[session_id]


def reset_session(session_id: str) -> None:
    _session_store.pop(session_id, None)


def _load_vectorstore():
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    if not INDEX_DIR.exists() or not any(INDEX_DIR.iterdir()):
        raise RuntimeError(
            "No FAISS index found. Run `python ingest.py` first (or call /reindex) "
            "to build one from the files in ./documents."
        )

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    _vectorstore = FAISS.load_local(
        str(INDEX_DIR),
        embeddings,
        allow_dangerous_deserialization=True,  # safe: we created this index ourselves
    )
    return _vectorstore


def invalidate_vectorstore_cache() -> None:
    """Call this after the index changes on disk (e.g. after /upload or /reindex)."""
    global _vectorstore, _conversational_chain
    _vectorstore = None
    _conversational_chain = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(model=CHAT_MODEL, temperature=0.2)
    return _llm


def _format_docs(docs) -> str:
    parts = []
    for d in docs:
        source = d.metadata.get("source", "unknown")
        page = d.metadata.get("page")
        label = f"{source}" + (f" (page {page + 1})" if page is not None else "")
        parts.append(f"[{label}]\n{d.page_content}")
    return "\n\n---\n\n".join(parts)


def _build_rag_step():
    """
    Returns a RunnableLambda that takes {"input": str, "chat_history": [...]} and
    returns {"answer": str, "context": [Document, ...]}.
    """
    vectorstore = _load_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K})
    llm = _get_llm()

    contextualize_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CONTEXTUALIZE_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    contextualize_chain = contextualize_prompt | llm | StrOutputParser()

    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QA_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    qa_chain = qa_prompt | llm | StrOutputParser()

    def _run(inputs: dict) -> dict:
        question = inputs["input"]
        chat_history = inputs.get("chat_history", [])

        standalone_question = (
            contextualize_chain.invoke({"input": question, "chat_history": chat_history})
            if chat_history
            else question
        )

        docs = retriever.invoke(standalone_question)
        context = _format_docs(docs)

        answer = qa_chain.invoke(
            {"input": question, "chat_history": chat_history, "context": context}
        )
        return {"answer": answer, "context": docs}

    return RunnableLambda(_run)


def _build_conversational_chain():
    global _conversational_chain
    if _conversational_chain is not None:
        return _conversational_chain

    rag_step = _build_rag_step()

    _conversational_chain = RunnableWithMessageHistory(
        rag_step,
        _get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
        output_messages_key="answer",
    )
    return _conversational_chain


def answer_question(question: str, session_id: str) -> dict:
    """
    Returns {"answer": str, "sources": [{"source", "page", "snippet"}, ...]}.
    Automatically uses/updates the chat history for the given session_id.
    """
    chain = _build_conversational_chain()
    result = chain.invoke(
        {"input": question},
        config={"configurable": {"session_id": session_id}},
    )

    sources = [
        {
            "source": d.metadata.get("source", "unknown"),
            "page": d.metadata.get("page"),
            "snippet": d.page_content[:300],
        }
        for d in result.get("context", [])
    ]

    return {"answer": result["answer"], "sources": sources}
