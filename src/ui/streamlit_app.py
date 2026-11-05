"""Streamlit WhatsApp-Style Web Interface for the Empório da Música AI Agent."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from src.agent.engine import EmporioAgent
from src.config import AgentConfig

st.set_page_config(
    page_title="Empório da Música — AI Customer Support",
    page_icon="🎸",
    layout="wide",
)


@st.cache_resource
def get_agent() -> EmporioAgent:
    """Initialize and cache the Empório da Música Agent instance."""
    return EmporioAgent(config=AgentConfig())


def main() -> None:
    agent = get_agent()

    # Sidebar Controls & Inspector
    with st.sidebar:
        st.title("🎸 Empório da Música")
        st.caption("*Sua música começa aqui.* — Campo Grande/MS")
        st.divider()

        st.subheader("⚙️ Agent Settings")
        provider_choice = st.selectbox(
            "LLM Provider Mode",
            options=["auto", "groq", "ollama", "openai", "gemini", "offline"],
            index=0,
            help="Select 'auto' to use Groq/Ollama when configured or seamlessly fall back to the built-in Deterministic ReAct Engine.",
        )
        agent.config.llm_provider = provider_choice

        session_id = st.text_input("Session ID", value="whatsapp-web-session")
        if st.button("🗑️ Reset Conversation History", use_container_width=True):
            agent.memory.clear_session(session_id)
            st.session_state["messages"] = []
            st.rerun()

        st.divider()
        st.subheader("⚡ Quick Test Prompts")
        quick_prompts = [
            "Quais opções de violões disponíveis custando até R$1000?",
            "Qual o endereço e horário de funcionamento da loja?",
            "Quanto custa o Takamine GD20?",
            "Me arrependi da minha compra, posso devolver meu pedido? (Pedido #8)",
            "Quais produtos estão em promoção hoje?",
            "Vocês vendem cordas avulsas, palhetas e amplificador?",
        ]
        selected_quick = None
        for qp in quick_prompts:
            if st.button(qp, use_container_width=True):
                selected_quick = qp

        st.divider()
        with st.expander("📊 Data Quality & ETL Audit Report"):
            for item in agent.db.data_quality_report:
                st.markdown(f"- {item}")

    # Main Chat Area
    st.markdown(
        """
        ### 💬 Atendimento Virtual via WhatsApp — Empório da Música
        📍 **Rua 14 de Maio, 3200 — Centro, Campo Grande/MS** | 📞 **(67) 3341-4444** | 📱 **WhatsApp: (67) 3321-4500**
        """
    )

    if "messages" not in st.session_state:
        history = agent.memory.get_history(session_id)
        if history:
            st.session_state["messages"] = history
        else:
            welcome = (
                "Olá! Seja muito bem-vindo(a) à **Empório da Música** — *Sua música começa aqui!* 🎸🎶\n\n"
                "Como posso ajudar você hoje? Posso consultar nosso estoque e preços de instrumentos, "
                "verificar promoções ativas, rastrear seu pedido ou tirar dúvidas sobre trocas, frete e parcelamento!"
            )
            st.session_state["messages"] = [{"role": "assistant", "content": welcome}]

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"], avatar="🎸" if msg["role"] == "assistant" else "👤"):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                with st.expander("🔧 Ver Consulta ao Sistema (Tool Calls)"):
                    st.json(msg["tool_calls"])

    user_prompt = st.chat_input("Digite sua mensagem para a Empório da Música...")
    active_prompt = selected_quick or user_prompt

    if active_prompt:
        st.session_state["messages"].append({"role": "user", "content": active_prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(active_prompt)

        with st.chat_message("assistant", avatar="🎸"):
            with st.spinner("Consultando sistema e políticas da Empório da Música..."):
                response = agent.chat(active_prompt, session_id=session_id)
            st.markdown(response.reply)
            traces_serialized = [
                {
                    "tool_name": t.tool_name,
                    "arguments": t.arguments,
                    "result_preview": t.result,
                }
                for t in response.tool_traces
            ]
            if traces_serialized:
                with st.expander(
                    f"🔧 Tool Calls Executadas ({len(traces_serialized)}) — Provider: {response.provider_used}"
                ):
                    st.json(traces_serialized)

        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": response.reply,
                "tool_calls": traces_serialized,
            }
        )
        if selected_quick:
            st.rerun()


if __name__ == "__main__":
    main()
