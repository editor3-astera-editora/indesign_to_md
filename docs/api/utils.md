# API — Utilitários

Helpers compartilhados em `idml_to_md.utils`.

---

## `idml_to_md.utils.slugify`

```python
def slugify(value: str) -> str: ...
```

Converte texto livre em slug seguro para paths e âncoras Markdown.

```python
slugify("81_Matemática Financeira")   # → "81-matematica-financeira"
slugify("Seção 1.1 — Conceitos")      # → "secao-1-1-conceitos"
```

**Algoritmo.**

1. NFKD-decompose (`unicodedata.normalize("NFKD", value)`).
2. Encode em ASCII com `errors="ignore"` (remove acentos e Unicode não-ASCII).
3. Lowercase.
4. Substitui qualquer sequência de `[^a-z0-9]+` por `-`.
5. Colapsa hífens consecutivos (`-{2,}` → `-`).
6. Remove hífens de borda.

Usado por `idml_to_md.pipeline.convert_idml` (slug do livro), `idml_to_md.toc_builder.build_toc` (slugs de heading), e `idml_to_md.translation.pipeline.translate_idml` (slug da pasta de output).

## `idml_to_md.utils.subprocess_safe`

Wrapper seguro para chamadas a binários externos (Inkscape, Ghostscript, Saxon, etc.).

```python
@dataclass(slots=True, frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class BinaryNotFoundError(FileNotFoundError):
    """Binário externo não disponível no PATH."""


def which(binary: str) -> Path | None: ...


def run(
    cmd: list[str],
    *,
    timeout: float = 60.0,
    cwd: Path | None = None,
) -> CommandResult: ...
```

**`which`** é um wrapper sobre `shutil.which` que retorna `Path | None`.

**`run`** executa `subprocess.run` com:
- `capture_output=True`, `text=True` (decodifica saída).
- `check=False` (não levanta em erro de processo — quem chama decide).
- `timeout` configurável (default 60s).
- `cwd` opcional.

Levanta:
- `BinaryNotFoundError` se `cmd[0]` não estiver no PATH.
- `subprocess.TimeoutExpired` se o timeout estourar (não é capturado aqui).

Retorna `CommandResult(returncode, stdout, stderr)` sempre que o processo termina.

**Uso típico.**

```python
from idml_to_md.utils.subprocess_safe import BinaryNotFoundError, run

try:
    result = run(["inkscape", str(src), "--export-type=svg", f"--export-filename={dst}"], timeout=60.0)
except BinaryNotFoundError:
    # cai em fallback (Ghostscript)
    ...
else:
    if result.returncode == 0 and dst.exists():
        ...
```

## `idml_to_md.utils.xml`

Mapping de namespaces IDML para uso com `lxml` XPath.

```python
IDML_NAMESPACES: dict[str, str] = {
    "idPkg": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging",
    "aid":   "http://ns.adobe.com/AdobeInDesign/4.0/",
    "aid5":  "http://ns.adobe.com/AdobeInDesign/5.0/",
}
```

Os prefixos são os declarados pelo InDesign nos arquivos IDML. Use com `etree.xpath` ou `etree.find`:

```python
from lxml import etree
from idml_to_md.utils.xml import IDML_NAMESPACES

root.xpath("//idPkg:Story", namespaces=IDML_NAMESPACES)
```

## Próximo

[translation.md](translation.md) — subpacote completo de tradução.
