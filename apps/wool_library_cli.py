"""Manual reference review commands; not available as automatic agent approval."""
import json

import typer

from src.wool.danbooru import fetch_candidates
from src.wool.reference_library import WoolReferenceLibrary, wool_asset_root

app = typer.Typer(help="AI鸡蛋候选图库、人工入选与参考图选择")


def emit(action):
    try:
        typer.echo(json.dumps(action(), ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("list")
def list_library():
    emit(lambda: WoolReferenceLibrary(wool_asset_root()).snapshot())


@app.command("fetch")
def fetch_library(count: int = typer.Option(10, min=1, max=30), style: str = "mixed"):
    emit(lambda: fetch_candidates(wool_asset_root(), count=count, style=style))


@app.command("review")
def review_library(identity: str, decision: str = typer.Option("reject"), adult_confirmed: bool = False,
                   rights_confirmed: bool = False, non_explicit_confirmed: bool = False, note: str = ""):
    emit(lambda: WoolReferenceLibrary(wool_asset_root()).review(
        identity, decision=decision, adult_confirmed=adult_confirmed, rights_confirmed=rights_confirmed,
        non_explicit_confirmed=non_explicit_confirmed, note=note))


@app.command("select")
def select_library(identity: str = typer.Argument("")):
    emit(lambda: WoolReferenceLibrary(wool_asset_root()).set_selection(identity))
