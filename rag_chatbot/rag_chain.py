"""
rag_chain.py

Connects to the Pinecone index and exposes a conversational RAG chain, built with
plain LCEL runnables (langchain.chains' old create_retrieval_chain /
create_history_aware_retriever helpers were removed in langchain 1.x, so this wires
the same logic together by hand).

Flow per question:
    1. retrieve relevant chunks by embedding the raw question (no LLM call first --
       see the note in _build_rag_step for why)
    2. answer using the retrieved context + full conversation history

Chat history is kept in memory per session_id (not persisted to disk -- restarting
the server clears it). That's fine for a personal/demo project; swap `_session_store`
for a Redis- or DB-backed history if this ever needs to survive restarts or scale to
multiple processes.
"""

import os

from dotenv import load_dotenv
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()

# Gemini's hosted embeddings. Note: gemini-embedding-001 defaults to 3072
# dimensions -- the Pinecone index must be created with dimension=3072 to match.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.5-flash-lite")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ask-your-docs")
TOP_K = int(os.getenv("TOP_K", 4))

QA_SYSTEM_PROMPT = """You are a helpful assistant that answers questions using ONLY \
the provided context, which comes from the user's own documents.

Rules:
- If the answer isn't in the context, say you don't know based on the provided documents.
- Be concise and direct.
- When useful, mention which source file(s) the answer came from.

Context:
{context}
"""

_embed_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)


@_embed_retry
def _retrieve_with_retry(retriever, query: str):
    return retriever.invoke(query)


# In-memory chat history store: session_id -> ChatMessageHistory
_session_store: dict[str, BaseChatMessageHistory] = {}


def _get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in _session_store:
        _session_store[session_id] = ChatMessageHistory()
    return _session_store[session_id]


def reset_session(session_id: str) -> None:
    _session_store.pop(session_id, None)


def _load_vectorstore():
    """
    Builds a fresh Pinecone/Gemini-embeddings client every call -- NOT cached as a
    module global. Caching this client across requests caused a real, reproducible
    bug: FastAPI's sync endpoints run in a threadpool, so a request can land on a
    different thread than the one that created the client. The underlying gRPC
    connection is bound to its creating thread/event loop, so reusing it from a
    different thread fails with an opaque 500 error -- which is exactly the "works
    on the first question, fails on the second" pattern this project hit. Rebuilding
    per-request costs a small amount of setup time but is correct under threading.
    """
    if not os.getenv("PINECONE_API_KEY"):
        raise RuntimeError("PINECONE_API_KEY not set. Add it to .env.")

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)
    embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)
    return PineconeVectorStore(index=index, embedding=embeddings)


def invalidate_vectorstore_cache() -> None:
    """No-op now that nothing is cached -- kept so main.py's existing calls to this
    (after /upload, /reindex) don't need to change."""
    pass


def _get_llm():
    """Fresh chat client per call, same reasoning as _load_vectorstore above."""
    return ChatGoogleGenerativeAI(model=CHAT_MODEL, temperature=0.2)


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

        # Retrieve using the raw question, embedded FIRST -- before any chat
        # completion call happens in this request. Retrieval used to run after a
        # separate "contextualize" chat call that rewrote follow-up questions
        # (e.g. "which university?" -> "Which university did Shahmeer attend?").
        # That extra chat call immediately before the embed call reproducibly
        # triggered a 500 from Gemini's embedding endpoint on every 2nd+ turn in a
        # conversation. Retrieval now always runs first and uses the raw question;
        # the final answer generation below still receives the full chat_history,
        # so multi-turn coherence in the ANSWER is preserved even though retrieval
        # itself is no longer history-aware. Trade-off: a very pronoun-heavy
        # follow-up ("what about that?") may retrieve slightly less precisely than
        # a rewritten version would -- acceptable given the alternative was a
        # broken 2nd question.
        docs = _retrieve_with_retry(retriever, question)
        context = _format_docs(docs)

        answer = qa_chain.invoke(
            {"input": question, "chat_history": chat_history, "context": context}
        )
        return {"answer": answer, "context": docs}

    return RunnableLambda(_run)


def _build_conversational_chain():
    """Built fresh per call -- see _load_vectorstore for why nothing here is cached."""
    rag_step = _build_rag_step()

    return RunnableWithMessageHistory(
        rag_step,
        _get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
        output_messages_key="answer",
    )


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
