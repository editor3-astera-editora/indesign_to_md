"""Fila de tradução em lote: processa uma pasta de livros IDML PT→ES.

Camada fina sobre :func:`idml_to_md.translation.pipeline.translate_idml` que
descobre livros, traduz cada um e empacota a saída no formato de entrega
pronto para reabrir no InDesign.

Estrutura de pastas::

    Input/<Livro>/   →  {<Livro>.idml, <Livro>.indd, Links/, Document fonts/}
    Output/<Livro>/  →  {Document fonts/, Links/, <Livro>_es.idml, out/<artefatos>}
    FEITOS/<Livro>/  →  subpasta de Input movida intacta após SUCESSO
    FALHAS/<Livro>/  →  subpasta de Input movida após FALHA (output parcial fica em Output/)

Cada livro é isolado: uma exceção ou reprovação no gate de completude move o
livro para ``FALHAS/`` e a fila segue para o próximo. Os artefatos internos do
pipeline (``segments.json``, ``translations.json``, ``_translation_report.json``,
``xml_original/``, ``xml_traduzido/``, ``_completeness.json``) ficam em
``Output/<Livro>/out/``.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from loguru import logger

from idml_to_md.translation.completeness_checker import check_completeness
from idml_to_md.translation.models import CompletenessReport
from idml_to_md.translation.pipeline import (
    TranslationConfig,
    TranslationResult,
    translate_idml,
)

# Pastas de assets copiadas de Input para a entrega (Output). O ``.indd``/``.pdf``
# permanecem só no original arquivado em FEITOS.
_ASSET_DIRS: tuple[str, ...] = ("Links", "Document fonts")

# Funções injetáveis (default = produção; sobrescritas nos testes para evitar
# OpenAI e leitura/escrita pesada), no mesmo espírito do ``translator_client``
# injetável em ``translate_idml``.
TranslateFn = Callable[..., TranslationResult]
VerifyFn = Callable[[Path, Path], CompletenessReport]


class BookStatus(StrEnum):
    """Resultado do processamento de um livro na fila."""

    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class BookJob:
    """Um livro pendente na fila."""

    name: str
    folder: Path
    idml_path: Path


@dataclass(slots=True)
class BookOutcome:
    """Desfecho do processamento de um livro."""

    name: str
    status: BookStatus
    delivery_dir: Path | None = None
    target_idml: Path | None = None
    completeness_ok: bool | None = None
    error: str | None = None


@dataclass(slots=True)
class QueueResult:
    """Agregado dos desfechos de toda a fila."""

    outcomes: list[BookOutcome] = field(default_factory=list)

    @property
    def done(self) -> list[BookOutcome]:
        return [o for o in self.outcomes if o.status is BookStatus.DONE]

    @property
    def failed(self) -> list[BookOutcome]:
        return [o for o in self.outcomes if o.status is BookStatus.FAILED]

    @property
    def skipped(self) -> list[BookOutcome]:
        return [o for o in self.outcomes if o.status is BookStatus.SKIPPED]


def discover_books(input_dir: Path, only: Sequence[str] | None = None) -> list[BookJob]:
    """Lista os livros pendentes em ``input_dir`` (uma subpasta por livro).

    Cada subpasta imediata deve conter exatamente um ``.idml``. Subpastas sem
    ``.idml`` são puladas (com aviso); com mais de um, usa o primeiro em ordem.

    Se ``only`` for informado, mantém apenas os livros cujo nome de subpasta
    esteja na lista (comparação sem diferenciar maiúsculas/minúsculas); nomes
    pedidos que não casarem com nenhum livro geram aviso.
    """
    input_dir = Path(input_dir)
    jobs: list[BookJob] = []
    for sub in sorted(p for p in input_dir.iterdir() if p.is_dir()):
        idmls = sorted(sub.glob("*.idml"))
        if not idmls:
            logger.warning("Pulando '{}': nenhum .idml encontrado", sub.name)
            continue
        if len(idmls) > 1:
            logger.warning(
                "'{}': {} arquivos .idml; usando '{}'",
                sub.name,
                len(idmls),
                idmls[0].name,
            )
        jobs.append(BookJob(name=sub.name, folder=sub, idml_path=idmls[0]))

    if only:
        jobs = _filter_only(jobs, only)
    return jobs


def _filter_only(jobs: list[BookJob], only: Sequence[str]) -> list[BookJob]:
    """Mantém só os ``jobs`` nomeados em ``only`` (case-insensitive); avisa faltantes."""
    wanted = {name.casefold() for name in only}
    selected = [job for job in jobs if job.name.casefold() in wanted]
    found = {job.name.casefold() for job in selected}
    for name in only:
        if name.casefold() not in found:
            logger.warning("--only '{}': nenhum livro com esse nome em Input", name)
    return selected


def process_book(
    job: BookJob,
    output_root: Path,
    done_root: Path,
    failed_root: Path,
    *,
    config: TranslationConfig,
    styles_overlay: Path | None = None,
    dry_run: bool = False,
    translate_fn: TranslateFn = translate_idml,
    verify_fn: VerifyFn = check_completeness,
) -> BookOutcome:
    """Traduz um livro e empacota a saída; move o input para FEITOS/FALHAS.

    Em ``dry_run`` apenas extrai segmentos (sem OpenAI, sem ``.idml``, sem mover
    o input nem rodar o gate de completude).
    """
    delivery_dir = output_root / job.name
    internal_out = delivery_dir / "out"
    try:
        if delivery_dir.exists():
            # Saída é regenerável; limpa restos de execução anterior.
            shutil.rmtree(delivery_dir)
        internal_out.mkdir(parents=True, exist_ok=True)

        result = translate_fn(
            idml_path=job.idml_path,
            output_dir=internal_out,
            config=config,
            styles_overlay=styles_overlay,
            dry_run=dry_run,
        )

        # ``translate_idml`` escreve em ``internal_out/<slug>/``; achatamos para
        # ``internal_out/`` (e, fora do dry-run, sobe o .idml para a entrega).
        if dry_run:
            _flatten_slug_dir(result.output_dir, internal_out)
            logger.info("[dry-run] {} → {}", job.name, internal_out)
            return BookOutcome(
                name=job.name,
                status=BookStatus.SKIPPED,
                delivery_dir=delivery_dir,
            )

        final_idml = delivery_dir / f"{job.idml_path.stem}_{config.target_lang}.idml"
        shutil.move(str(result.target_idml), str(final_idml))
        _flatten_slug_dir(result.output_dir, internal_out)

        _copy_assets(job.folder, delivery_dir)

        comp = verify_fn(job.idml_path, final_idml)
        (internal_out / "_completeness.json").write_text(
            comp.model_dump_json(indent=2), encoding="utf-8"
        )

        if not comp.ok:
            logger.error("Completude reprovada em '{}': {}", job.name, comp.summary)
            _move_folder(job.folder, failed_root / job.name)
            return BookOutcome(
                name=job.name,
                status=BookStatus.FAILED,
                delivery_dir=delivery_dir,
                target_idml=final_idml,
                completeness_ok=False,
                error=comp.summary,
            )

        _move_folder(job.folder, done_root / job.name)
        logger.success("'{}' OK → {}", job.name, final_idml.name)
        return BookOutcome(
            name=job.name,
            status=BookStatus.DONE,
            delivery_dir=delivery_dir,
            target_idml=final_idml,
            completeness_ok=True,
        )

    except Exception as exc:  # isolamento por livro: uma falha não derruba a fila
        logger.exception("Falha ao processar '{}'", job.name)
        _move_folder(job.folder, failed_root / job.name)
        return BookOutcome(
            name=job.name,
            status=BookStatus.FAILED,
            delivery_dir=delivery_dir,
            error=str(exc),
        )


def run_queue(
    input_dir: Path,
    output_root: Path,
    done_root: Path,
    failed_root: Path,
    *,
    config: TranslationConfig,
    styles_overlay: Path | None = None,
    dry_run: bool = False,
    only: Sequence[str] | None = None,
    translate_fn: TranslateFn = translate_idml,
    verify_fn: VerifyFn = check_completeness,
) -> QueueResult:
    """Processa os livros de ``input_dir`` sequencialmente (todos, ou só ``only``)."""
    input_dir = Path(input_dir).resolve()
    output_root = Path(output_root).resolve()
    done_root = Path(done_root).resolve()
    failed_root = Path(failed_root).resolve()
    for root in (output_root, done_root, failed_root):
        root.mkdir(parents=True, exist_ok=True)

    jobs = discover_books(input_dir, only=only)
    result = QueueResult()
    logger.info("Fila: {} livro(s) em {}", len(jobs), input_dir)

    for idx, job in enumerate(jobs, start=1):
        logger.info("[{}/{}] {}", idx, len(jobs), job.name)
        outcome = process_book(
            job,
            output_root,
            done_root,
            failed_root,
            config=config,
            styles_overlay=styles_overlay,
            dry_run=dry_run,
            translate_fn=translate_fn,
            verify_fn=verify_fn,
        )
        result.outcomes.append(outcome)

    logger.info(
        "Fila concluída: {} feitos, {} falhas, {} pulados",
        len(result.done),
        len(result.failed),
        len(result.skipped),
    )
    return result


def _flatten_slug_dir(slug_dir: Path, dest: Path) -> None:
    """Move o conteúdo de ``slug_dir`` para ``dest`` e remove ``slug_dir``.

    ``translate_idml`` cria um subdiretório ``<slug>/`` sob ``dest``; aqui o
    achatamos para que os artefatos fiquem direto em ``dest`` (a pasta ``out/``).
    """
    if slug_dir == dest or not slug_dir.exists():
        return
    for item in slug_dir.iterdir():
        target = dest / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
    slug_dir.rmdir()


def _copy_assets(src_folder: Path, delivery_dir: Path) -> None:
    """Copia ``Links/`` e ``Document fonts/`` do input para a entrega."""
    for name in _ASSET_DIRS:
        src = src_folder / name
        if src.is_dir():
            shutil.copytree(src, delivery_dir / name, dirs_exist_ok=True)
        else:
            logger.warning("'{}' sem pasta '{}' — não copiada", src_folder.name, name)


def _move_folder(src: Path, dst: Path) -> Path:
    """Move ``src`` para ``dst``; se ``dst`` existir, anexa sufixo de timestamp.

    Garante que re-execuções (mesmo livro caindo de novo em FEITOS/FALHAS) não
    sobrescrevam um arquivamento anterior.
    """
    if dst.exists():
        dst = dst.with_name(f"{dst.name}__{int(time.time())}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst
