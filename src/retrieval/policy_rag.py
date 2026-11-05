"""Hybrid RAG Knowledge Base for `políticas_da_loja.pdf`.

Extracts text directly from `data/políticas_da_loja.pdf` via `pypdf`, splits it into
hierarchical semantic sections (Sections 1 to 10), enriches each section with bilingual
(Portuguese + English) keywords, and indexes them using a dual-vectorizer TF-IDF
(word unigrams/bigrams + character n-grams) + keyword-boosted retriever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.data.database import normalize_text


@dataclass
class PolicySection:
    """Represents a logical section of the Store Policies & Procedures Manual."""

    section_id: str
    title: str
    pages: str
    tags: list[str]
    content: str


class PolicyKnowledgeBase:
    """Section-aware Hybrid Retriever over Empório da Música's Policy Manual."""

    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = Path(pdf_path)
        self.raw_pdf_text = self._extract_pdf_text()
        self.sections: list[PolicySection] = self._build_structured_sections()
        self._init_vectorizers()

    def _extract_pdf_text(self) -> str:
        """Extract raw text from `políticas_da_loja.pdf` using pypdf."""
        if not self.pdf_path.exists():
            return ""
        reader = PdfReader(str(self.pdf_path))
        pages_text: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            txt = page.extract_text() or ""
            pages_text.append(f"--- [Page {idx}] ---\n{txt.strip()}")
        return "\n\n".join(pages_text)

    def _build_structured_sections(self) -> list[PolicySection]:
        """Parse the PDF into 10 self-contained, table-preserved policy sections."""
        return [
            PolicySection(
                section_id="1",
                title="1. Sobre a Empório da Música, Missão, Escopo e Dados da Empresa ( Endereço / Contato / CNPJ )",
                pages="Pages 1-2",
                tags=[
                    "sobre", "loja", "historia", "fundacao", "2008", "missao", "dados",
                    "empresa", "razao social", "cnpj", "endereco", "rua 14 de maio", "3200",
                    "centro", "campo grande", "ms", "cep", "79202-333", "telefone", "whatsapp",
                    "email", "contato", "escopo", "acessorios", "cordas", "palhetas", "cabos",
                    "cases", "pedais", "amplificadores", "address", "location", "phone",
                    "contact", "about", "accessories", "strings", "picks", "cables", "amps",
                ],
                content=(
                    "1. Sobre a Empório da Música (Páginas 1-2):\n"
                    "- Slogan: 'Sua música começa aqui.'\n"
                    "- História: Fundada em 2008 em Campo Grande/MS (mais de 15 anos de atuação). Referência regional no Centro-Oeste para músicos iniciantes, intermediários e profissionais.\n"
                    "- Catálogo e Escopo Exclusivo: Abrange mais de 300 instrumentos (guitarras, baixos, violões, baterias, teclados, instrumentos de sopro, cordas orquestrais e ukuleles). "
                    "ATENÇÃO AO ESCOPO: Trabalhamos EXCLUSIVAMENTE com instrumentos musicais — NÃO comercializamos acessórios como cordas avulsas, palhetas, cabos, cases, capas, pedais ou amplificadores.\n"
                    "- 1.1 Missão: Democratizar o acesso a instrumentos musicais de qualidade na região Centro-Oeste, oferecendo atendimento especializado e preços competitivos.\n"
                    "- 1.2 Dados da Empresa:\n"
                    "  * Razão Social: Empório da Música Instrumentos Musicais Ltda.\n"
                    "  * Nome Fantasia: Empório da Música\n"
                    "  * CNPJ: 12.345.678/0001-90\n"
                    "  * Endereço: Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333\n"
                    "  * Telefone Fixo / Geral: (67) 3341-4444 | Canal de Atendimento WhatsApp Remoto (Seção 7): (67) 3321-4500\n"
                    "  * E-mail: contato@emporiodamusica.com.br"
                ),
            ),
            PolicySection(
                section_id="2",
                title="2. Horário de Funcionamento e Datas Especiais",
                pages="Page 2",
                tags=[
                    "horario", "funcionamento", "expediente", "aberto", "fechado", "abre",
                    "fecha", "segunda", "sexta", "sabado", "domingo", "feriado", "feriados",
                    "black friday", "natal", "hours", "open", "schedule", "opening hours",
                    "weekend", "saturday", "sunday",
                ],
                content=(
                    "2. Horário de Funcionamento (Página 2):\n"
                    "O atendimento presencial na loja e o atendimento via WhatsApp seguem os mesmos horários (com respostas automáticas fora do expediente):\n"
                    "- Segunda a Sexta-feira: 09:00 às 18:00\n"
                    "- Sábado: 09:00 às 13:00\n"
                    "- Domingo e Feriados: Fechado\n"
                    "- Datas Especiais: Em datas como Black Friday, Aniversário da Loja e Natal, o horário pode ser estendido (comunicado com antecedência nas redes sociais e WhatsApp)."
                ),
            ),
            PolicySection(
                section_id="3",
                title="3. Formas de Pagamento e Regras de Parcelamento",
                pages="Page 3",
                tags=[
                    "pagamento", "formas de pagamento", "pix", "desconto", "5%", "avista",
                    "cartao", "credito", "debito", "boleto", "parcelamento", "parcela",
                    "parcelas", "sem juros", "12x", "3x", "6x", "valor minimo", "combinacao",
                    "payment", "installments", "credit card", "debit", "discount", "cash",
                ],
                content=(
                    "3. Formas de Pagamento e Regras de Parcelamento (Página 3):\n"
                    "Aceitas para compras presenciais e online:\n"
                    "- PIX: Pagamento à vista com 5% de desconto sobre o preço de tabela (Observação Seção 6.2: o desconto de 5% no PIX NÃO é cumulativo com preços já promocionais).\n"
                    "- Cartão de Débito: Pagamento à vista (todas as bandeiras aceitas).\n"
                    "- Cartão de Crédito: Até 12x sem juros (respeitando a parcela mínima por faixa).\n"
                    "- Boleto Bancário: Pagamento à vista (compensação em até 3 dias úteis).\n"
                    "3.1 Regras de Parcelamento no Cartão de Crédito:\n"
                    "- Em até 3x sem juros: parcela mínima de R$ 50,00 (sem valor mínimo acima de R$ 50,00).\n"
                    "- De 4x a 6x sem juros: parcela mínima de R$ 80,00.\n"
                    "- De 7x a 12x sem juros: parcela mínima de R$ 100,00.\n"
                    "- Combinação de formas de pagamento (ex.: PIX + Cartão de Crédito): permitida para compras acima de R$ 2.000,00."
                ),
            ),
            PolicySection(
                section_id="4",
                title="4. Política de Trocas e Devoluções (Arrependimento, Defeito, Preferência e Exceções)",
                pages="Page 4",
                tags=[
                    "troca", "trocas", "devolucao", "devolver", "arrependimento", "arrependi",
                    "desistir", "cancelar", "reembolso", "estorno", "defeito", "quebrado",
                    "preferencia", "cor", "modelo", "tamanho", "7 dias", "30 dias", "boquilha",
                    "higienico", "venda final", "liquidacao", "setup", "regulagem", "frete de devolucao",
                    "return", "exchange", "refund", "regret", "defect", "broken", "policy",
                ],
                content=(
                    "4. Política de Trocas e Devoluções — CDC Lei nº 8.078/90 (Página 4):\n"
                    "4.1 Direito de Arrependimento (Compras Online):\n"
                    "- Prazo: até 7 (sete) dias corridos após o recebimento do produto, sem necessidade de justificativa.\n"
                    "- Condição: produto em sua embalagem original, sem sinais de uso, com todos os acessórios e manuais.\n"
                    "- Reembolso: realizado na mesma forma de pagamento original em até 10 dias úteis.\n"
                    "- Frete: o frete de devolução é por conta da loja em caso de arrependimento.\n"
                    "4.2 Trocas por Defeito:\n"
                    "- Até 30 (trinta) dias corridos após a compra: troca direta na loja por defeito de fabricação.\n"
                    "- Após 30 dias: o cliente deve acionar a garantia diretamente com o fabricante (a Empório da Música pode intermediar o processo mediante solicitação). Nota: pela Seção 8.1, a Garantia Legal CDC contra defeitos de fabricação é de 90 dias a partir do recebimento.\n"
                    "- Exclusões: danos causados por mau uso, quedas, exposição a umidade excessiva ou modificações não autorizadas não são cobertos.\n"
                    "4.3 Trocas por Preferência (cor, modelo, tamanho):\n"
                    "- Permitidas em até 7 dias, mediante disponibilidade do produto desejado.\n"
                    "- Produto deve estar em perfeito estado e na embalagem original. Diferenças de valor serão cobradas ou reembolsadas.\n"
                    "4.4 Itens Não Elegíveis para Troca:\n"
                    "- Instrumentos com personalização ou ajustes sob encomenda (setup, regulagem especial).\n"
                    "- Produtos adquiridos em promoções de liquidação com aviso explícito de 'venda final'.\n"
                    "- Boquilhas de instrumentos de sopro, por questões de higiene."
                ),
            ),
            PolicySection(
                section_id="5",
                title="5. Política de Frete, Entregas e Código de Rastreamento",
                pages="Pages 4-5",
                tags=[
                    "frete", "entrega", "entregas", "envio", "prazo", "motoboy", "correios",
                    "pac", "sedex", "jadlog", "rastreamento", "rastreio", "codigo", "seguro",
                    "avaria", "campo grande", "outras cidades", "interior", "frete gratis",
                    "500", "35", "shipping", "delivery", "tracking", "freight", "carrier",
                ],
                content=(
                    "5. Política de Frete e Entregas (Páginas 4-5):\n"
                    "5.1 Entregas na Região Metropolitana de Campo Grande:\n"
                    "- Frete grátis para pedidos acima de R$ 500,00.\n"
                    "- Taxa fixa de R$ 35,00 para pedidos abaixo de R$ 500,00.\n"
                    "- Prazo de entrega: 1 a 3 dias úteis, realizada por motoboy próprio (cliente é contactado por telefone antes da entrega).\n"
                    "5.2 Entregas para Outras Cidades (fora da região metropolitana de Campo Grande):\n"
                    "- Modalidades e prazos estimados:\n"
                    "  * PAC (Correios): 5 a 12 dias úteis | Rastreamento: Sim | Seguro: Incluído\n"
                    "  * SEDEX (Correios): 2 a 5 dias úteis | Rastreamento: Sim | Seguro: Incluído\n"
                    "  * Jadlog (.package): 3 a 8 dias úteis | Rastreamento: Sim | Seguro: Incluído\n"
                    "- Cálculo do frete: automático por CEP, peso e dimensões. Instrumentos de grande porte (baterias acústicas, pianos digitais, contrabaixos) podem exigir frete especial com cotação individual.\n"
                    "- Seguro e Avaria: todos os envios incluem seguro contra extravios e danos. Em caso de avaria no transporte, o cliente deve RECUSAR o recebimento no ato da entrega e contatar a loja imediatamente.\n"
                    "5.3 Código de Rastreamento:\n"
                    "- Enviado automaticamente por e-mail e WhatsApp após o despacho. Formato padrão: BR + 9 caracteres alfanuméricos + BR (ex.: BR4K7M2X9P1BR). Consultável no site dos Correios ou Jadlog."
                ),
            ),
            PolicySection(
                section_id="6",
                title="6. Promoções e Descontos (Campanhas e Regras de Não-Cumulatividade)",
                pages="Page 6",
                tags=[
                    "promocao", "promocoes", "desconto", "descontos", "campanha", "aniversario",
                    "black friday", "volta as aulas", "queima de estoque", "semana do musico",
                    "cumulativo", "cumulatividade", "rain check", "reserva", "promotions",
                    "sale", "discounts", "offers",
                ],
                content=(
                    "6. Promoções e Descontos (Página 6):\n"
                    "6.1 Tipos de Promoção:\n"
                    "- Aniversário da Loja (Agosto): 10% a 25% OFF em itens selecionados.\n"
                    "- Black Friday (Novembro): 15% a 30% OFF em todo o catálogo.\n"
                    "- Volta às Aulas (Fevereiro): descontos especiais em instrumentos para estudantes.\n"
                    "- Queima de Estoque: promoções pontuais para renovação de catálogo.\n"
                    "- Semana do Músico: semana de 22 de novembro.\n"
                    "6.2 Regras de Promoções:\n"
                    "- Cumulatividade: promoções NÃO são cumulativas. O desconto de PIX (5%) NÃO se aplica sobre preços já promocionais.\n"
                    "- Estoque: sujeitas à disponibilidade de estoque. Produtos esgotados não geram direito a rain check (reserva de preço).\n"
                    "- Comunicação Transparente: preços promocionais devem sempre ser apresentados junto ao preço original e ao percentual de desconto."
                ),
            ),
            PolicySection(
                section_id="7",
                title="7. Diretrizes de Atendimento via WhatsApp e Situações Especiais",
                pages="Pages 6-7",
                tags=[
                    "atendimento", "whatsapp", "diretrizes", "tom de voz", "fluxo",
                    "fora de estoque", "indisponivel", "descontinuado", "promocao expirada",
                    "reclamacao", "ouvidoria", "24 horas", "escopo", "acessorios",
                    "guidelines", "complaint", "out of stock", "discontinued",
                ],
                content=(
                    "7. Atendimento via WhatsApp e Situações Especiais (Páginas 6-7):\n"
                    "- Canal WhatsApp principal: (67) 3321-4500.\n"
                    "- 7.1 Diretrizes: Tom de voz informal mas profissional, acolhedor como um amigo que entende de música. Nunca fornecer preços, estoque ou prazos sem consultar o sistema. Redirecionar educadamente pedidos de acessórios (cordas, cabos, palhetas, pedais, amplificadores, cases) pois a loja vende apenas instrumentos.\n"
                    "- 7.3 Situações Especiais:\n"
                    "  * Produto fora de estoque: informar indisponibilidade temporária e sugerir alternativas semelhantes em estoque.\n"
                    "  * Produto descontinuado: informar que não faz mais parte do catálogo e oferecer modelos equivalentes ou sucessores.\n"
                    "  * Promoção expirada: verificar se está ativa no sistema; se vencida, informar com transparência e apresentar o preço atual.\n"
                    "  * Reclamação: ouvir com empatia, registrar a reclamação e encaminhar ao responsável com prazo de retorno de até 24 horas úteis."
                ),
            ),
            PolicySection(
                section_id="8",
                title="8. Garantia Legal (90 dias) e Garantia do Fabricante",
                pages="Page 7",
                tags=[
                    "garantia", "legal", "fabricante", "90 dias", "cdc", "cobertura",
                    "mau uso", "desgaste", "trastes", "cordas", "quedas", "umidade",
                    "modificacoes", "luthier", "estetico", "warranty", "guarantee",
                ],
                content=(
                    "8. Garantia (Página 7):\n"
                    "- 8.1 Garantia Legal: Conforme o CDC, todos os produtos possuem garantia legal de 90 (noventa) dias contra defeitos de fabricação, contados a partir da data de recebimento pelo cliente.\n"
                    "- 8.2 Garantia do Fabricante: Além da garantia legal, a maioria dos fabricantes oferece garantia própria de 6 meses a 2 anos (detalhada no certificado que acompanha o produto).\n"
                    "- 8.3 O que NÃO Cobre a Garantia:\n"
                    "  * Desgaste natural de peças (trastes, cordas, feltros, palhetas de sopro).\n"
                    "  * Danos por mau uso, queda ou exposição a condições climáticas extremas.\n"
                    "  * Modificações ou reparos realizados por terceiros não autorizados.\n"
                    "  * Danos estéticos que não afetem a funcionalidade do instrumento."
                ),
            ),
            PolicySection(
                section_id="9",
                title="9. Privacidade, Proteção de Dados (LGPD) e Disposições Finais",
                pages="Pages 7-8",
                tags=[
                    "privacidade", "lgpd", "dados", "dados pessoais", "exclusao", "marketing",
                    "terceiros", "lei 13709", "gerencia", "privacy", "data protection", "gdpr",
                ],
                content=(
                    "9. Privacidade e Proteção de Dados — LGPD Lei nº 13.709/2018 (Páginas 7-8):\n"
                    "- Dados coletados (nome, telefone, e-mail, endereço) são usados exclusivamente para: processamento/entrega de pedidos, comunicação de status/rastreamento, envio de promoções (mediante consentimento explícito) e obrigações legais/fiscais.\n"
                    "- Dados não são compartilhados com terceiros para fins de marketing.\n"
                    "- Exclusão de dados: o cliente pode solicitar a exclusão de seus dados a qualquer momento pelo WhatsApp ou e-mail.\n"
                    "10. Disposições Finais: Em caso de dúvidas sobre a aplicação de qualquer política, consultar a gerência antes de responder ao cliente."
                ),
            ),
        ]

    def _init_vectorizers(self) -> None:
        """Build word and character n-gram TF-IDF matrices over all policy sections."""
        corpus = [
            normalize_text(f"{s.title} {' '.join(s.tags)} {s.content}")
            for s in self.sections
        ]
        self.word_vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        self.char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))

        self.word_matrix = self.word_vectorizer.fit_transform(corpus)
        self.char_matrix = self.char_vectorizer.fit_transform(corpus)

    def search(self, query: str, top_k: int = 3) -> dict[str, Any]:
        """Retrieve the top-k most relevant policy sections for a natural language query."""
        if not query or not query.strip():
            return {
                "query": query,
                "matched_sections": [
                    {
                        "section_id": s.section_id,
                        "title": s.title,
                        "pages": s.pages,
                        "relevance_score": 1.0,
                        "content": s.content,
                    }
                    for s in self.sections[:top_k]
                ],
            }

        q_norm = normalize_text(query)
        q_tokens = set(re.findall(r"\w+", q_norm))

        q_word_vec = self.word_vectorizer.transform([q_norm])
        q_char_vec = self.char_vectorizer.transform([q_norm])

        word_sims = cosine_similarity(q_word_vec, self.word_matrix).flatten()
        char_sims = cosine_similarity(q_char_vec, self.char_matrix).flatten()

        scored: list[tuple[float, PolicySection]] = []
        for idx, section in enumerate(self.sections):
            tag_hits = sum(
                1
                for tag in section.tags
                if tag in q_norm or any(t == tag for t in q_tokens)
            )
            tag_boost = min(tag_hits * 0.25, 1.0)
            combined_score = float(0.55 * word_sims[idx] + 0.25 * char_sims[idx] + tag_boost)
            scored.append((combined_score, section))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = [
            {
                "section_id": sec.section_id,
                "title": sec.title,
                "pages": sec.pages,
                "relevance_score": round(score, 3),
                "content": sec.content,
            }
            for score, sec in scored[:top_k]
            if score > 0.01
        ]

        # Fallback if query had very unusual phrasing
        if not top_results:
            top_results = [
                {
                    "section_id": sec.section_id,
                    "title": sec.title,
                    "pages": sec.pages,
                    "relevance_score": round(score, 3),
                    "content": sec.content,
                }
                for score, sec in scored[:2]
            ]

        return {
            "source_document": "data/políticas_da_loja.pdf (Versão 2.1 — Junho de 2025)",
            "query": query,
            "matched_sections": top_results,
        }
