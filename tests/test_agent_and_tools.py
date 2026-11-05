"""Unit and integration test suite for Empório da Música AI Agent."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.agent.engine import EmporioAgent
from src.agent.memory import SessionMemory
from src.config import AgentConfig
from src.data.database import StoreDatabase
from src.retrieval.policy_rag import PolicyKnowledgeBase
from src.tools.store_tools import StoreToolkit


@pytest.fixture(scope="module")
def config() -> AgentConfig:
    cfg = AgentConfig()
    cfg.llm_provider = "offline"
    cfg.reference_date = date(2026, 3, 23)
    return cfg


@pytest.fixture(scope="module")
def db(config: AgentConfig) -> StoreDatabase:
    return StoreDatabase(config.data_dir)


@pytest.fixture(scope="module")
def policy_kb(config: AgentConfig) -> PolicyKnowledgeBase:
    return PolicyKnowledgeBase(config.data_dir / "políticas_da_loja.pdf")


@pytest.fixture(scope="module")
def toolkit(db: StoreDatabase, policy_kb: PolicyKnowledgeBase, config: AgentConfig) -> StoreToolkit:
    return StoreToolkit(db, policy_kb, config)


@pytest.fixture()
def agent(config: AgentConfig, db: StoreDatabase, policy_kb: PolicyKnowledgeBase) -> EmporioAgent:
    memory = SessionMemory(":memory:")
    return EmporioAgent(config=config, db=db, policy_kb=policy_kb, memory=memory)


# ==============================================================================
# 1. Data Cleaning & Relational Database Tests
# ==============================================================================

def test_database_tables_and_row_counts(db: StoreDatabase) -> None:
    """Verify all 6 CSV files are loaded into SQLite with exact row counts."""
    cur = db.conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 9
    assert cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 50
    assert cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 20
    assert cur.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 22
    assert cur.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 65
    assert cur.execute("SELECT COUNT(*) FROM promotions").fetchone()[0] == 25


def test_violoes_up_to_1000_in_stock_filtering(db: StoreDatabase) -> None:
    """Verify 'violões disponíveis custando até R$1000' returns 12 active in-stock models
    and excludes out-of-stock (#96 Giannini GF-3D) and discontinued (#113 Shelby SN-7C).
    """
    res = db.search_products(category="Violões", max_price=1000.0, only_in_stock=True)
    assert res["total_matches"] == 12
    returned_ids = {p["product_id"] for p in res["products"]}
    assert 96 not in returned_ids  # Giannini GF-3D has stock_quantity=0
    assert 113 not in returned_ids  # Shelby SN-7C is discontinued
    assert 81 in returned_ids  # Yamaha C40 (R$ 599.90)
    assert 112 in returned_ids  # Tagima TW-7 (R$ 999.00)


def test_takamine_gd20_pricing_and_expired_promotion(db: StoreDatabase) -> None:
    """Verify Takamine GD20 (#95) has list price R$ 2199.00, PIX price R$ 2089.05,
    and notes expired promotion #4 (12% OFF).
    """
    res = db.search_products(query="Takamine GD20", only_in_stock=False)
    assert len(res["products"]) == 1
    gd20 = res["products"][0]
    assert gd20["product_id"] == 95
    assert gd20["list_price_brl"] == 2199.0
    assert gd20["has_active_promotion"] is False
    assert gd20["pix_price_brl"] == 2089.05
    assert "12% OFF - EXPIRED" in gd20.get("expired_promotion_history", "")


def test_active_promotions_and_non_cumulative_pix_rule(db: StoreDatabase) -> None:
    """Verify the 4 active promotions (is_active == 1) and non-cumulative PIX rule (Section 6.2)."""
    promos = db.get_promotions(include_expired=False)
    assert promos["active_promotions_count"] == 4
    active_ids = {p["product_id"] for p in promos["active_promotions"]}
    assert active_ids == {90, 94, 121, 127}

    # Check Crafter HT-100 (#90): R$ 2399 with 18% OFF -> R$ 1967.18; PIX does not stack
    crafter_res = db.search_products(query="Crafter HT-100")
    crafter = crafter_res["products"][0]
    assert crafter["has_active_promotion"] is True
    assert crafter["effective_price_brl"] == 1967.18
    assert crafter["pix_price_brl"] == 1967.18


def test_installment_tier_rules_section_3_1(toolkit: StoreToolkit) -> None:
    """Verify credit card installment rules per Section 3.1."""
    # R$ 159.90 -> max 3x of R$ 53.30 (since 4x would be R$ 39.98 < R$ 80 min)
    res_low = toolkit.calculate_payment_and_shipping(amount_brl=159.90)
    assert "Até 3x" in res_low["payment_methods"]["credit_card"]["max_option"]
    assert res_low["payment_methods"]["combined_payment_allowed"] is False

    # R$ 459.90 -> max 5x of R$ 91.98 (since 6x would be R$ 76.65 < R$ 80 min)
    res_mid = toolkit.calculate_payment_and_shipping(amount_brl=459.90)
    assert "Até 5x" in res_mid["payment_methods"]["credit_card"]["max_option"]

    # R$ 2199.00 -> max 12x of R$ 183.25 + combined payment allowed (> R$ 2000)
    res_high = toolkit.calculate_payment_and_shipping(amount_brl=2199.00, city="Campo Grande")
    assert "Até 12x" in res_high["payment_methods"]["credit_card"]["max_option"]
    assert res_high["payment_methods"]["combined_payment_allowed"] is True
    assert res_high["shipping"]["free_shipping_applied"] is True
    assert res_high["shipping"]["shipping_cost_brl"] == 0.0


def test_order_lookup_and_return_eligibility(db: StoreDatabase) -> None:
    """Verify order lookup and automatic 7-day regret / 30-day defect eligibility."""
    # Order #8 (Ana Carolina Ferreira) -> shipped
    o8 = db.lookup_order_or_customer(order_id=8, reference_date=date(2026, 3, 23))
    assert o8["found"] is True
    assert o8["orders"][0]["status"] == "shipped"
    assert o8["orders"][0]["tracking_code"] == "BRJL5544332BR"
    assert o8["orders"][0]["return_and_warranty_eligibility"]["can_return_for_regret_7d"] is True

    # Order #7 (Letícia Gonçalves Rocha) -> delivered 2026-02-17 (34 days before 2026-03-23)
    o7 = db.lookup_order_or_customer(order_id=7, reference_date=date(2026, 3, 23))
    elig7 = o7["orders"][0]["return_and_warranty_eligibility"]
    assert elig7["can_return_for_regret_7d"] is False
    assert elig7["under_legal_warranty_90d"] is True


# ==============================================================================
# 2. Hybrid Policy RAG Tests
# ==============================================================================

def test_policy_rag_retrieves_correct_sections(policy_kb: PolicyKnowledgeBase) -> None:
    """Verify semantic + lexical RAG retrieves accurate sections from `políticas_da_loja.pdf`."""
    res_hours = policy_kb.search("Qual o horário de funcionamento aos sábados e endereço?")
    sec_ids = [s["section_id"] for s in res_hours["matched_sections"]]
    assert "1" in sec_ids or "2" in sec_ids

    res_return = policy_kb.search("Me arrependi da compra online, qual o prazo de devolução?")
    assert res_return["matched_sections"][0]["section_id"] == "4"

    res_warranty = policy_kb.search("Garantia legal 90 dias desgaste de cordas e trastes")
    assert res_warranty["matched_sections"][0]["section_id"] == "8"


# ==============================================================================
# 3. End-to-End Agent Integration & Guardrail Tests
# ==============================================================================

def test_agent_catalog_budget_scenario(agent: EmporioAgent) -> None:
    resp = agent.chat("Quais opções de violões disponíveis custando até R$1000?")
    assert any(t.tool_name == "search_products" for t in resp.tool_traces)
    assert "Yamaha C40" in resp.reply
    assert "Tagima TW-7" in resp.reply
    assert "Giannini GF-3D" in resp.reply  # Mentioned in transparency note as out-of-stock


def test_agent_store_info_scenario(agent: EmporioAgent) -> None:
    resp = agent.chat("Qual o endereço e horário de funcionamento da loja?")
    assert any(t.tool_name == "search_store_policies" for t in resp.tool_traces)
    assert "Rua 14 de Maio, 3200" in resp.reply
    assert "09:00 às 18:00" in resp.reply
    assert "09:00 às 13:00" in resp.reply


def test_agent_price_and_installment_scenario(agent: EmporioAgent) -> None:
    resp = agent.chat("Quanto custa o Takamine GD20?")
    assert any(t.tool_name == "search_products" for t in resp.tool_traces)
    assert "2,199.00" in resp.reply or "2.199,00" in resp.reply
    assert "2,089.05" in resp.reply or "2.089,05" in resp.reply


def test_agent_return_policy_and_order_scenario(agent: EmporioAgent) -> None:
    resp = agent.chat("Me arrependi da minha compra, posso devolver meu pedido #8?")
    tool_names = [t.tool_name for t in resp.tool_traces]
    assert "lookup_order_or_customer" in tool_names
    assert "search_store_policies" in tool_names
    assert "7 (sete) dias corridos" in resp.reply
    assert "BRJL5544332BR" in resp.reply


def test_agent_accessories_scope_guardrail(agent: EmporioAgent) -> None:
    resp = agent.chat("Vocês vendem cordas avulsas, palhetas, cabos e amplificador?")
    assert "exclusivamente com instrumentos musicais" in resp.reply
    assert "não comercializamos acessórios" in resp.reply


def test_agent_unrelated_out_of_scope_guardrail(agent: EmporioAgent) -> None:
    resp = agent.chat("Qual a melhor receita de bolo de cenoura com chocolate?")
    assert "instrumentos musicais" in resp.reply
    assert len(resp.tool_traces) == 0


def test_session_memory_persistence(agent: EmporioAgent) -> None:
    agent.chat("Olá, meu nome é Lucas!", session_id="test-session-1")
    history = agent.memory.get_history("test-session-1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    agent.memory.clear_session("test-session-1")
    assert len(agent.memory.get_history("test-session-1")) == 0
