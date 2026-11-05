"""Interactive Rich CLI for the Empório da Música Customer Support Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from src.agent.engine import EmporioAgent
from src.config import AgentConfig

# Ensure UTF-8 console output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console(legacy_windows=False)


def render_tool_traces(traces: list) -> None:
    """Display tool execution traces in a clean diagnostic table."""
    if not traces:
        return
    table = Table(
        title="🔧 Tool Execution Trace (Real-Time Grounding)",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Tool Name", style="bold green")
    table.add_column("Arguments", style="yellow")
    for idx, t in enumerate(traces, start=1):
        table.add_row(str(idx), t.tool_name, str(t.arguments))
    console.print(table)


def run_demo_scenarios(agent: EmporioAgent, show_traces: bool = True) -> None:
    """Execute standard showcase scenarios in the terminal."""
    demo_prompts = [
        "Quais opções de violões disponíveis custando até R$1000?",
        "Qual o endereço e horário de funcionamento da loja?",
        "Quanto custa o Takamine GD20 e como fica o parcelamento ou no PIX?",
        "Me arrependi da minha compra, posso devolver meu pedido? Sou a Ana Carolina Ferreira (Pedido #8).",
        "Vocês vendem encordoamento de violão, palhetas e amplificador?",
    ]
    console.print(
        Panel(
            "[bold gold1]Empório da Música — Automated Showcase Scenarios[/bold gold1]\n"
            "Running 5 representative customer support interactions...",
            border_style="gold1",
        )
    )
    for idx, prompt in enumerate(demo_prompts, start=1):
        console.print(f"\n[bold bright_blue]👤 Cliente ({idx}/5):[/bold bright_blue] {prompt}")
        resp = agent.chat(prompt, session_id="cli-demo")
        if show_traces:
            render_tool_traces(resp.tool_traces)
        console.print(
            Panel(
                Markdown(resp.reply),
                title=f"🎸 Empório da Música [{resp.provider_used} / {resp.model_used}]",
                border_style="green",
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Empório da Música — AI Customer Support Agent CLI"
    )
    parser.add_argument(
        "--session",
        default="cli-default",
        help="Session ID for persistent conversation history (default: cli-default)",
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "groq", "ollama", "openai", "gemini", "offline"],
        default=None,
        help="Override LLM_PROVIDER setting",
    )
    parser.add_argument(
        "--query",
        "-q",
        default=None,
        help="Execute a single query non-interactively and exit",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the 5 automated showcase scenarios and exit",
    )
    parser.add_argument(
        "--hide-traces",
        action="store_true",
        help="Hide tool execution trace tables",
    )
    args = parser.parse_args()

    config = AgentConfig()
    if args.provider:
        config.llm_provider = args.provider

    agent = EmporioAgent(config=config)

    if args.demo:
        run_demo_scenarios(agent, show_traces=not args.hide_traces)
        return

    if args.query:
        resp = agent.chat(args.query, session_id=args.session)
        if not args.hide_traces:
            render_tool_traces(resp.tool_traces)
        console.print(
            Panel(
                Markdown(resp.reply),
                title=f"🎸 Empório da Música [{resp.provider_used} / {resp.model_used}]",
                border_style="green",
            )
        )
        return

    # Interactive mode
    console.print(
        Panel(
            "[bold green]🎸 Empório da Música — Atendimento Virtual (WhatsApp Simulator)[/bold green]\n"
            "[italic]Sua música começa aqui! — Rua 14 de Maio, 3200, Centro, Campo Grande/MS[/italic]\n\n"
            "Commands: [bold]/reset[/bold] (clear session) | [bold]/traces[/bold] (toggle tool inspector) | [bold]/exit[/bold] (quit)",
            border_style="green",
        )
    )

    show_traces = not args.hide_traces
    while True:
        try:
            user_input = console.input("\n[bold bright_blue]👤 Você:[/bold bright_blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Encerrando atendimento. Até logo! 🎶[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit", "sair", "exit"):
            console.print("[dim]Encerrando atendimento. Até logo! 🎶[/dim]")
            break
        if user_input.lower() == "/reset":
            agent.memory.clear_session(args.session)
            console.print("[yellow]✔ Histórico da sessão limpo![/yellow]")
            continue
        if user_input.lower() == "/traces":
            show_traces = not show_traces
            console.print(f"[yellow]✔ Exibição de Tool Traces: {show_traces}[/yellow]")
            continue

        resp = agent.chat(user_input, session_id=args.session)
        if show_traces:
            render_tool_traces(resp.tool_traces)
        console.print(
            Panel(
                Markdown(resp.reply),
                title=f"🎸 Empório da Música [{resp.provider_used} / {resp.model_used}]",
                border_style="green",
            )
        )


if __name__ == "__main__":
    main()
