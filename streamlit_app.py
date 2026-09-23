import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="RAG 客服機器人", page_icon="🤖", layout="centered")
st.title("🤖 RAG 客服機器人")

if "messages" not in st.session_state:
    st.session_state.messages = []


def api_chat(message: str) -> dict:
    try:
        response = requests.post(f"{API_BASE}/api/chat/", json={"message": message}, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"answer": "無法連線到後端伺服器，請確認 FastAPI 是否已啟動。", "sources": [], "confidence": "no_context"}
    except Exception as e:
        return {"answer": f"發生錯誤：{e}", "sources": [], "confidence": "no_context"}


def api_upload(file) -> dict:
    try:
        response = requests.post(
            f"{API_BASE}/api/documents/upload",
            files={"file": (file.name, file.getvalue(), file.type or "application/octet-stream")},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def api_list_documents() -> list[str]:
    try:
        response = requests.get(f"{API_BASE}/api/documents/", timeout=10)
        response.raise_for_status()
        return response.json().get("documents", [])
    except Exception:
        return []


def api_delete_document(filename: str) -> bool:
    try:
        response = requests.delete(f"{API_BASE}/api/documents/{filename}", timeout=10)
        return response.ok
    except Exception:
        return False


def confidence_badge(confidence: str) -> str:
    return {
        "high": "🟢 高信心",
        "low": "🟡 低信心（建議人工確認）",
        "no_context": "🔴 知識庫無相關資料",
    }.get(confidence, "")


tab_chat, tab_docs = st.tabs(["💬 聊天", "📁 知識庫管理"])

# ── Tab 1：聊天 ──────────────────────────────────────────────
with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant" and msg.get("sources"):
                st.caption(f"來源：{'、'.join(msg['sources'])}　{confidence_badge(msg.get('confidence', ''))}")

    if prompt := st.chat_input("請輸入問題..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("查詢知識庫中..."):
                result = api_chat(prompt)
            st.write(result["answer"])
            if result.get("sources"):
                st.caption(f"來源：{'、'.join(result['sources'])}　{confidence_badge(result.get('confidence', ''))}")

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["answer"],
            "sources": result.get("sources", []),
            "confidence": result.get("confidence", ""),
        })

# ── Tab 2：知識庫管理 ─────────────────────────────────────────
with tab_docs:
    st.subheader("上傳文件")
    uploaded = st.file_uploader("選擇檔案（PDF、TXT、MD）", type=["pdf", "txt", "md"])
    if uploaded:
        if st.button("上傳至知識庫"):
            with st.spinner("上傳並建立索引中..."):
                result = api_upload(uploaded)
            if "error" in result:
                st.error(f"上傳失敗：{result['error']}")
            else:
                st.success(f"成功上傳 **{result['filename']}**，共切成 {result['chunks']} 個段落")
                st.rerun()

    st.divider()
    st.subheader("已上傳的文件")

    docs = api_list_documents()
    if not docs:
        st.info("知識庫目前是空的，請先上傳文件。")
    else:
        for doc in docs:
            col1, col2 = st.columns([5, 1])
            col1.write(f"📄 {doc}")
            if col2.button("刪除", key=f"del_{doc}"):
                if api_delete_document(doc):
                    st.success(f"{doc} 已刪除")
                    st.rerun()
                else:
                    st.error("刪除失敗")
